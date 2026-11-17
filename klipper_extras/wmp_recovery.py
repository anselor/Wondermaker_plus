"""Wondermaker bottom-Z reference, shared by unhomed tool changes and recovery.

Native Z rail homing only: no homing_override, LEVELING pulse, XY or return.
See docs/z-recovery-investigation.md for the machine measurements.
"""
import logging
import hashlib
import json
import math
import copy
import configparser
import io
import re
import uuid
import sys
import os
import tempfile
import fcntl
from contextlib import contextmanager


try:
    from .wmp_xy_homing import XYHoming
    from .wmp_calibration_records import ProbeSaveRecord, CalibrationSaveRecord
    from .wmp_probe_state import ProbeConfigChange, ProbeEditorReceipt
    from .wmp_probe_editor import ProbeEditorCommands
    from .wmp_calibration import CalibrationHeaterOwnership, CalibrationCommands
except ImportError:
    from wmp_xy_homing import XYHoming
    from wmp_calibration_records import ProbeSaveRecord, CalibrationSaveRecord
    from wmp_probe_state import ProbeConfigChange, ProbeEditorReceipt
    from wmp_probe_editor import ProbeEditorCommands
    from wmp_calibration import CalibrationHeaterOwnership, CalibrationCommands


class BottomZ:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        self.xy_homing = XYHoming(self.printer)
        self.valid = False
        self.active = False
        self.calibration = CalibrationCommands(self.printer, self.gcode)
        self.identification = None
        self.gcode.register_command('_WMP_IDENTIFY_HEADS', self.cmd_identify,
                                    desc='Identify physical heads and atomically save the complete mapping')
        self.printer.register_event_handler('klippy:connect', self._connect)
        self.printer.register_event_handler('klippy:ready', self._identification_ready)
        self.printer.register_event_handler('klippy:shutdown', self._invalidate)
        self.printer.register_event_handler('homing:home_rails_begin', self._home_begin)
        self.printer.register_event_handler('homing:home_rails_end', self._home_end)
        self.gcode.register_command('_WMP_HOME_Z_BOTTOM', self.cmd_home,
                                    desc='Home Z at the bottom endstop before X/Y travel')

    def _connect(self):
        enable = self.printer.lookup_object('stepper_enable').lookup_enable('stepper_z')
        enable.register_state_callback(self._motor_state)

    def _identification_ready(self):
        from .wmp_identification import IdentificationCommands
        self.identification = IdentificationCommands(self.printer, self.gcode, self.calibration)
        self.identification.check_startup()

    def _invalidate(self, *args):
        self.valid = False

    def _motor_state(self, print_time, enabled):
        if not enabled:
            self.valid = False

    @staticmethod
    def _z_rail(rails):
        return any(s.get_name() == 'stepper_z' for r in rails for s in r.get_steppers())

    def _home_begin(self, homing_state, rails):
        if self._z_rail(rails):
            self.valid = False

    def _home_end(self, homing_state, rails):
        if self._z_rail(rails):
            self.valid = True

    def get_status(self, eventtime):
        axes = self.printer.lookup_object('toolhead').get_status(eventtime)['homed_axes']
        editor = self.calibration.probe_editor
        calibration_active = self.calibration.active or editor.busy()
        active_reason = ''
        if self.calibration.active:
            active_reason = 'Calibration command is running'
        elif calibration_active:
            active_reason = 'Manual probe calibration is active: state=' + str(editor.state)[:80]
        return {'z_reference_valid': self.valid and 'z' in axes, 'homing': self.active,
                'calibration_failed': self.calibration.failure,
                'calibration_active': calibration_active,
                'calibration_active_reason': active_reason,
                'probe_editor': self.calibration.probe_editor.get_status(),
                'calibration_session': self.calibration.session,
                'calibration_checkpoint': self.calibration.checkpoint,
                'calibration_save_result': dict(self.calibration.save_result),
                'calibration_attempt_protocol': 1,
                'calibration_ticket_protocol': 1,
                'calibration_next_ticket': str(self.calibration._ticket_counter + 1),
                'calibration_attempt': dict(self.calibration.attempt_result),
                'identification': self.identification.get_status() if self.identification else
                    {'protocol': 2, 'state': 'idle', 'steps': [], 'failure': '', 'restart_required': False}}

    def cmd_identify(self, gcmd):
        if self.identification is None:
            from .wmp_identification import IdentificationCommands
            self.identification = IdentificationCommands(self.printer, self.gcode, self.calibration)
        self.identification.dispatch(gcmd)

    @contextmanager
    def _native_bottom_reference(self, native):
        # Native homing owns both seeks and the retract. Its step history uses
        # nominal times, while this vendor MCU can execute late steps later.
        # Negative overshoot is impossible for this positive-only seek: anchor
        # the successfully stopped physical endstop instead of reversing retract.
        # This references the actual halt, not a reconstructed switch-edge time;
        # physical stopping overshoot remains a qualification limit. It does not
        # repair host scheduling latency. Native slow second seek is retained.
        namespace = getattr(native.cmd_G28, '__globals__', {})
        original = namespace.get('HomingMove')
        if original is None:  # Injected/non-native command providers have no factory.
            yield
            return
        owner = self

        class BottomReferenceMove(original):
            def homing_move(move, movepos, speed, probe_pos=False,
                            triggered=True, check_triggered=True):
                result = super().homing_move(movepos, speed, probe_pos,
                                            triggered, check_triggered)
                # The native end event also runs on error; only a successful
                # return establishes this correction's authority.
                positions = move.stepper_positions
                if (owner.active and move.printer is owner.printer
                        and not probe_pos and triggered and check_triggered
                        and len(positions) == 1 and all(p.stepper_name == 'stepper_z'
                                              and p.endstop_name == 'z' for p in positions)
                        and any(p.halt_pos < p.trig_pos for p in positions)):
                    position = list(move.toolhead.get_position())
                    position[2] = movepos[2]
                    move.toolhead.set_position(position)
                    for p in positions:
                        logging.warning('WMP bottom Z: negative nominal history correction '
                                        'halt=%s trigger=%s; anchor stopped endstop at Z=%s',
                                        p.halt_pos, p.trig_pos, movepos[2])
                        # Final native rail callbacks must use the same actual
                        # stopped reference, not the invalid nominal history.
                        p.trig_pos = p.halt_pos
                return result

        namespace['HomingMove'] = BottomReferenceMove
        try:
            yield
        finally:
            namespace['HomingMove'] = original

    def cmd_home(self, gcmd):
        # A preflight refusal has performed no homing. Only a failed started
        # home invalidates physical position and must retire queued movement.
        entered = started = False
        try:
            now = self.printer.get_reactor().monotonic()
            ps = self.printer.lookup_object('print_stats').get_status(now)
            paused = self.printer.lookup_object('pause_resume').get_status(now)['is_paused']
            body = self.printer.lookup_object('gcode_macro START_PRINT').get_status(now)['print_body_ready']
            if self.active or paused or (ps['state'] == 'printing' and body):
                raise gcmd.error('Cannot home Z at the bottom: ' + ('bottom-Z command already running' if self.active else 'pause_resume.is_paused=%r' % paused if paused else 'print_stats.state=printing and START_PRINT.print_body_ready=%r' % body))
            settings = self.printer.lookup_object('configfile').get_status(now)['settings']
            z = settings['stepper_z']
            if (settings['printer']['kinematics'] != 'corexy'
                    or z['endstop_pin'] != 'PD2' or z['homing_positive_dir'] is not True):
                raise gcmd.error('Bottom-Z homing requires corexy, physical PD2 and positive Z homing')
            # Native Klipper owns the configured endstop and retract distance;
            # differing valid travel values are not a different homing method.
            minimum = z.get('position_min', 0.)
            maximum = z.get('position_max', z['position_endstop'])
            endstop, retract = z['position_endstop'], z['homing_retract_dist']
            if (any(type(value) not in (int, float) or not math.isfinite(value)
                    for value in (minimum, maximum, endstop, retract))
                    or not minimum < endstop <= maximum or not 0 < retract < maximum - minimum):
                raise gcmd.error('Bottom-Z homing requires finite native Z bounds and retract within travel')
            inactive = []
            for name in ('LEVELING', 'GANTRY'):
                pin = self.printer.lookup_object('output_pin ' + name).get_status(now)
                if pin['value'] != 1:
                    inactive.append(name)
            if inactive:
                material = self.printer.lookup_object('wm_material', None)
                if (self.calibration.active or self.calibration.probe_editor.busy()
                        or (material is not None and any(material._material_operation_active(kind)
                            for kind in ('filament_operation', 'toolhead_operation')))):
                    raise gcmd.error('Cannot reset bottom-Z trigger pins during an active calibration or material operation')
                # Stock load_cell.cfg declares 1 as both idle and shutdown.
                # Restore that level without the stock low trigger pulse.
                for name in inactive:
                    self.gcode.run_script_from_command('SET_PIN PIN=%s VALUE=1' % name)
                    self.printer.lookup_object('toolhead').wait_moves()
                    observed = self.printer.lookup_object('output_pin ' + name).get_status(
                        self.printer.get_reactor().monotonic()).get('value')
                    if observed != 1:
                        raise gcmd.error('%s idle reset was not confirmed: value=%r; expected 1' % (name, observed))
            entered = True
            self.active = True
            self.valid = False
            self.printer.lookup_object('toolhead').wait_moves()
            # Discard compensation without moving. Native home resets the Z
            # base to the retained homing offset; do not erase tool offsets.
            self.gcode.run_script_from_command('BED_MESH_CLEAR')
            self.gcode.run_script_from_command('STEPPER_DIAG_ENABLE CHIP=stepper_z')
            try:
                native = self.printer.lookup_object('homing')
                started = True
                with self._native_bottom_reference(native):
                    native.cmd_G28(self.gcode.create_gcode_command('G28', 'G28 Z', {'Z': '0'}))
                self.printer.lookup_object('toolhead').wait_moves()
            finally:
                self.gcode.run_script_from_command('STEPPER_DIAG_DISABLE CHIP=stepper_z')
            self.valid = True
            logging.info('WMP recovery: native bottom Z home complete; no XY or upward return')
            gcmd.respond_info('WM+: Z homed at the bottom. The bed remains there; X/Y did not move.')
        except Exception:
            if entered:
                self.valid = False
            if started:
                self.printer.invoke_shutdown('Bottom-Z homing failed. Klipper shut down to block further recovery movement; check the preceding error.')
            raise
        finally:
            if entered:
                self.active = False


def load_config(config):
    return BottomZ(config)
