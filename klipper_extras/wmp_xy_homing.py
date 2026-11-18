# SPDX-License-Identifier: GPL-3.0-or-later
"""Establish Y at a repeatable X position, without moving Z or changing tools."""
import logging


class XYHoming:
    CORNER_DISTANCE = 10.
    BACKOFF = 5.
    REPEAT_TOLERANCE = .25

    def __init__(self, printer):
        self.printer = printer
        self.gcode = printer.lookup_object('gcode')
        self.gcode.register_command('_WMP_HOME_XY', self.cmd_home,
                                    desc='Home Y, then X, then verify Y at a fixed X position')

    def cmd_home(self, gcmd):
        try:
            from .homing import Homing, HomingMove
        except ImportError:
            from homing import Homing, HomingMove
        return self._home(gcmd, Homing, HomingMove)

    def _home(self, gcmd, Homing, HomingMove):
        printer = self.printer
        toolhead = printer.lookup_object('toolhead')
        kin = toolhead.get_kinematics()
        xrail, yrail = kin.rails[:2]
        xhi, yhi = xrail.get_homing_info(), yrail.get_homing_info()
        if (xrail.get_name() != 'stepper_x' or yrail.get_name() != 'stepper_y'
                or not xhi.positive_dir or yhi.positive_dir):
            raise gcmd.error('Fixed-corner homing requires the WM X-positive/Y-negative configuration')
        material = printer.lookup_object('wm_material', None)
        generation = getattr(material, '_command_generation', None)

        def guard():
            if (printer.is_shutdown() or getattr(printer, 'quick_stop_flag', False)
                    or getattr(material, '_command_generation', None) != generation):
                raise gcmd.error('XY homing interrupted')

        def native_home(axis):
            guard()
            command = self.gcode.create_gcode_command('G28', 'G28 ' + axis, {axis: ''})
            # Call the native homing implementation, not the macro override:
            # this routine owns XY only and must never trigger Z or tool pickup.
            printer.lookup_object('homing').cmd_G28(command)
            toolhead.wait_moves()
            guard()

        def move_to(**axes):
            guard()
            pos = list(toolhead.get_position())
            for axis, value in axes.items():
                pos['xyz'.index(axis)] = value
            toolhead.move(pos, yhi.retract_speed)
            toolhead.wait_moves()
            guard()

        try:
            # Only establishes front clearance for X homing. Its Y result is
            # replaced below; no dock travel may consume it as the final datum.
            gcmd.respond_info('XY homing: preliminary Y home, then X home')
            native_home('Y')
            native_home('X')
            reference_x = xhi.position_endstop - self.CORNER_DISTANCE
            if not xrail.get_range()[0] <= reference_x <= xrail.get_range()[1]:
                raise gcmd.error('Fixed X homing reference is outside travel limits')
            move_to(x=reference_x)
            state = Homing(printer)
            state.set_axes([1])
            endstops = yrail.get_endstops()
            printer.send_event('homing:home_rails_begin', state, [yrail])
            travels = []
            # The first contact replaces the preliminary Y datum; its travel
            # must NOT be compared with that discarded datum. Two subsequent
            # contacts verify the new reference at the same fixed X position.
            # Every approach is bounded to 10 mm at the stock slower speed.
            for tap in range(3):
                move_to(y=toolhead.get_position()[1] + self.BACKOFF)
                toolhead.dwell(1.)
                toolhead.wait_moves()
                guard()
                when = toolhead.get_last_move_time()
                if any(es.query_endstop(when) for es, _ in endstops):
                    raise gcmd.error('Y homing failed: sensor remained triggered after 5 mm backoff')
                start = list(toolhead.get_position())
                start[1] = yhi.position_endstop + 2. * self.BACKOFF
                toolhead.set_position(start, homing_axes=[1])
                target = list(start)
                target[1] = yhi.position_endstop
                hmove = HomingMove(printer, endstops)
                hmove.homing_move(target, yhi.second_homing_speed)
                toolhead.wait_moves()
                guard()
                delta = {sp.stepper_name: (sp.trig_pos - sp.start_pos) * sp.stepper.get_step_dist()
                         for sp in hmove.stepper_positions}
                travel = abs((delta['stepper_x'] - delta['stepper_y']) * .5)
                logging.info('Fixed-X Y home x=%.5f tap=%d travel=%.6f motor_delta=%s',
                             reference_x, tap + 1, travel, delta)
                if hmove.check_no_movement() is not None or not .01 <= travel < 10.:
                    raise gcmd.error('Y homing failed: no valid movement before reference contact (%.5f mm)' % travel)
                if tap and not 4. <= travel <= 6.:
                    raise gcmd.error('Y homing failed: confirmation travelled %.5f mm; expected about 5 mm' % travel)
                travels.append(travel)
                if tap == 2 and abs(travels[2] - travels[1]) > self.REPEAT_TOLERANCE:
                    raise gcmd.error('Y homing failed: repeat contacts differ by %.5f mm' % abs(travels[2] - travels[1]))
            state.trigger_mcu_pos = {sp.stepper_name: sp.trig_pos for sp in hmove.stepper_positions}
            state.adjust_pos = {}
            printer.send_event('homing:home_rails_end', state, [yrail])
            gcmd.respond_info('Y home verified at X=%.3f: first reference travel %.5f mm; repeat travel %.5f / %.5f mm' %
                              (reference_x, travels[0], travels[1], travels[2]))
        except Exception:
            # An interrupted/failed attempt has no trustworthy Y reference.
            # No persisted fault flag: a new explicit home can try again.
            kin.limits[1] = (1., -1.)
            raise
