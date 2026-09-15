"""Wondermaker bottom-Z reference, shared by unhomed tool changes and recovery.

Native Z rail homing only: no homing_override, LEVELING pulse, XY or return.
See docs/z-recovery-investigation.md for the machine measurements.
"""
import logging


class BottomZ:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        self.valid = False
        self.active = False
        self.printer.register_event_handler('klippy:connect', self._connect)
        self.printer.register_event_handler('klippy:shutdown', self._invalidate)
        self.printer.register_event_handler('homing:home_rails_begin', self._home_begin)
        self.printer.register_event_handler('homing:home_rails_end', self._home_end)
        self.gcode.register_command('_WMP_HOME_Z_BOTTOM', self.cmd_home,
                                    desc='Home native Z to the bottom before XY travel')

    def _connect(self):
        enable = self.printer.lookup_object('stepper_enable').lookup_enable('stepper_z')
        enable.register_state_callback(self._motor_state)

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
        return {'z_reference_valid': self.valid and 'z' in axes, 'homing': self.active}

    def cmd_home(self, gcmd):
        # A plain error does not cancel separately queued touchscreen requests.
        # Any failure here shuts down, so no later XY/pickup can use a guess.
        try:
            now = self.printer.get_reactor().monotonic()
            ps = self.printer.lookup_object('print_stats').get_status(now)
            paused = self.printer.lookup_object('pause_resume').get_status(now)['is_paused']
            body = self.printer.lookup_object('gcode_macro START_PRINT').get_status(now)['print_body_ready']
            if self.active or paused or (ps['state'] == 'printing' and body):
                raise gcmd.error('Bottom-Z homing cannot reset the reference of an active print')
            settings = self.printer.lookup_object('configfile').get_status(now)['settings']
            z = settings['stepper_z']
            if (settings['printer']['kinematics'] != 'corexy'
                    or z['endstop_pin'] != 'PD2' or not z['homing_positive_dir']
                    or z['position_endstop'] != 300.0 or z['homing_retract_dist'] != 2.0):
                raise gcmd.error('Bottom-Z homing requires the inspected Wondermaker Z geometry')
            for name in ('LEVELING', 'GANTRY'):
                pin = self.printer.lookup_object('output_pin ' + name).get_status(now)
                if pin['value'] != 1:
                    raise gcmd.error('%s must be inactive before bottom-Z homing' % name)
            self.active = True
            self.valid = False
            self.printer.lookup_object('toolhead').wait_moves()
            # Discard compensation without moving. Native home resets the Z
            # base to the retained homing offset; do not erase tool offsets.
            self.gcode.run_script_from_command('BED_MESH_CLEAR')
            self.gcode.run_script_from_command('STEPPER_DIAG_ENABLE CHIP=stepper_z')
            try:
                native = self.printer.lookup_object('homing')
                native.cmd_G28(self.gcode.create_gcode_command('G28', 'G28 Z', {'Z': '0'}))
                self.printer.lookup_object('toolhead').wait_moves()
            finally:
                self.gcode.run_script_from_command('STEPPER_DIAG_DISABLE CHIP=stepper_z')
            self.valid = True
            logging.info('WMP recovery: native bottom Z home complete; no XY or upward return')
            gcmd.respond_info('WMP: Z referenced at bottom; no XY or upward return')
        except Exception:
            self.valid = False
            self.printer.invoke_shutdown('Bottom-Z homing failed; subsequent recovery motion blocked')
            raise
        finally:
            self.active = False


def load_config(config):
    return BottomZ(config)
