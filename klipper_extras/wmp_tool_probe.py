# SPDX-License-Identifier: GPL-3.0-or-later
"""Repeat tool-setter touches that trigger before the nozzle has travelled.

The CELL board can report a touch from a bad load-cell read taken before the
probing move starts: a bad zero, or a bad first sample. Such a touch stops
within a few motor steps of where it began. A bad zero stays in the board
until the next zero, so the touch is discarded, the sensor is zeroed again
and the touch is repeated from the same position.

install() replaces run_probe on the vendor probe object. It does nothing if
the vendor run_probe is not the reviewed 1.1.13 source. A [wmp_tool_probe]
config section calls install() when Klipper connects.
"""
import hashlib
import inspect
import logging
import sys
import types
try:
    from .wmp_stop_points import check_operation_boundary
except ImportError:
    from wmp_stop_points import check_operation_boundary

# sha256 of inspect.getsource(PrinterProbeMultiAxis.run_probe), firmware 1.1.13
STOCK_RUN_PROBE_SHA256 = '6f41a0d50deb412830efb2fa0ad1f351f385aa0e86c34db9b78b7a9d29cd8fc0'
# A real touch travels at least sample_retract_dist; a false one a few steps.
MIN_TRAVEL = 0.1
MAX_REPEATS = 1
NO_MOVEMENT = 'Probe triggered prior to movement'
FALSE_TRIGGER_REPORT = ('WM+: load-cell false trigger after %.4f mm travel; '
                        're-zeroing and repeating the touch')


def install(printer):
    calibrate = printer.lookup_object('tools_calibrate', None)
    probe = getattr(calibrate, 'probe_multi_axis', None)
    if probe is None:
        return False
    try:
        source = inspect.getsource(type(probe).run_probe)
    except (OSError, TypeError):
        source = ''
    if hashlib.sha256(source.encode('utf-8')).hexdigest() != STOCK_RUN_PROBE_SHA256:
        logging.warning('WMP tool probe: vendor run_probe is not the reviewed '
                        'source; false-trigger handling is not installed')
        return False
    probe.run_probe = types.MethodType(run_probe, probe)
    logging.info('WMP tool probe: false-trigger handling installed')
    return True


def _touch(self, vendor, speed, axis, sense, max_distance):
    # Vendor _probe without its report, which is made only for kept touches.
    # Returns None when Klipper saw no step at all before the trigger.
    phoming = self.printer.lookup_object('homing')
    target = self._get_target_position(axis, sense, max_distance)
    try:
        epos = phoming.probing_move(self.mcu_probe[axis], target, speed)
    except self.printer.command_error as e:
        reason = str(e)
        if NO_MOVEMENT in reason:
            return None
        if 'Timeout during endstop homing' in reason:
            reason += getattr(vendor, 'HINT_TIMEOUT', '')
        raise self.printer.command_error(reason)
    return epos[:3]


def run_probe(self, direction, gcmd, speed_ratio=1.0, samples=None,
              max_distance=100.0):
    vendor = sys.modules.get(type(self).__module__)
    direction_types = vendor.direction_types
    speed = gcmd.get_float('PROBE_SPEED', self.speed, above=0.) * speed_ratio
    if direction not in direction_types:
        raise self.printer.command_error('Wrong value for DIRECTION.')
    (axis, sense) = direction_types[direction]
    lift_speed = self.get_lift_speed(gcmd)
    sample_count = gcmd.get_int('SAMPLES',
                                samples if samples else self.sample_count,
                                minval=1)
    sample_retract_dist = gcmd.get_float('SAMPLE_RETRACT_DIST',
                                         self.sample_retract_dist, above=0.)
    samples_tolerance = gcmd.get_float('SAMPLES_TOLERANCE',
                                       self.samples_tolerance, minval=0.)
    samples_retries = gcmd.get_int('SAMPLES_TOLERANCE_RETRIES',
                                   self.samples_retries, minval=0)
    samples_result = gcmd.get('SAMPLES_RESULT', self.samples_result)

    toolhead = self.printer.lookup_object('toolhead')
    endstop = self.mcu_probe[axis]
    probe_start = list(toolhead.get_position())
    retries = 0
    repeats = 0
    positions = []

    check_operation_boundary(self.printer, 'before tool-setter probing', 'tool_probe')
    endstop.multi_probe_begin()
    toolhead.dwell(0.75)
    endstop.home_zero()

    self.verify_no_crash()

    while len(positions) < sample_count:
        try:
            check_operation_boundary(self.printer, 'before tool-setter touch', 'tool_probe')
        except Exception:
            # A sample retract was queued by _move. Finish that admitted
            # clearance move before reporting cancellation/closing the probe.
            try:
                toolhead.wait_moves()
            finally:
                endstop.multi_probe_end()
            raise
        touch_start = list(toolhead.get_position())
        pos = _touch(self, vendor, speed, axis, sense, max_distance)
        travel = 0. if pos is None else abs(pos[axis] - touch_start[axis])
        if travel < MIN_TRAVEL and repeats < MAX_REPEATS:
            repeats += 1
            gcmd.respond_info(FALSE_TRIGGER_REPORT % travel)
            self._move(touch_start, lift_speed)
            toolhead.wait_moves()
            toolhead.dwell(0.75)
            endstop.home_zero()
            continue
        if pos is None:
            endstop.multi_probe_end()
            raise self.printer.command_error(NO_MOVEMENT)
        self.gcode.respond_info('Probe made contact at %.6f, %.6f, %.6f'
                                % (pos[0], pos[1], pos[2]))
        positions.append(pos)

        axis_positions = [p[axis] for p in positions]
        if max(axis_positions) - min(axis_positions) > samples_tolerance:
            if retries >= samples_retries:
                endstop.multi_probe_end()
                coll = self.printer.lookup_object('collision_detect', None)
                if coll is not None:
                    try:
                        coll.cmd_disable()
                    except Exception:
                        pass
                raise gcmd.error('Probe samples exceed samples_tolerance')
            gcmd.respond_info('Probe samples exceed tolerance. Retrying...')
            toolhead.dwell(0.75)
            endstop.home_zero()
            retries += 1
            positions = []
            self._move(probe_start, lift_speed)
            continue

        if len(positions) < sample_count:
            liftpos = list(probe_start)
            liftpos[axis] = pos[axis] - sense * sample_retract_dist
            self._move(liftpos, lift_speed)

    endstop.multi_probe_end()

    if samples_result == 'median':
        return self._calc_median(positions, axis)
    return self._calc_mean(positions)


def load_config(config):
    printer = config.get_printer()
    printer.register_event_handler('klippy:connect', lambda: install(printer))
    return types.SimpleNamespace(get_status=lambda eventtime: {})
