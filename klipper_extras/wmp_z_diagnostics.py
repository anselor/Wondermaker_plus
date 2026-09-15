"""Optional, manually invoked Z-max investigation; NOT recovery implementation.

Never included by the normal W+ deployment. See docs/z-recovery-investigation.md.
Only WMP_Z_MAX_TEST moves; loading the extra and WMP_Z_SNAPSHOT do not move.
"""
import json
import logging


class ZDiagnostics:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        self.active = False
        self.phase = 'idle'
        self.last_result = None
        self.gcode.register_command('WMP_Z_SNAPSHOT', self.cmd_snapshot,
                                    desc='Record Z coordinates without moving')
        self.gcode.register_command('WMP_Z_MAX_TEST', self.cmd_max_test,
                                    desc='Empty-bed diagnostic: native Z-max home only')

    def _snapshot(self):
        now = self.printer.get_reactor().monotonic()
        th = self.printer.lookup_object('toolhead')
        th.wait_moves()
        th.flush_step_generation()
        z = next(s for s in th.get_kinematics().get_steppers()
                 if s.get_name() == 'stepper_z')
        gm = self.printer.lookup_object('gcode_move').get_status(now)
        mesh = self.printer.lookup_object('bed_mesh').get_status(now)
        return {
            'time': now, 'homed_axes': th.get_status(now)['homed_axes'],
            'toolhead_position': list(th.get_position()),
            'gcode_position': list(gm['gcode_position']),
            'homing_origin': list(gm['homing_origin']),
            'z_commanded': z.get_commanded_position(),
            'z_mcu_steps': z.get_mcu_position(), 'step_distance': z.get_step_dist(),
            'mesh': mesh['profile_name'],
        }

    def _report(self, label, result, gcmd):
        message = 'WMP_Z_DIAG %s %s' % (label, json.dumps(result, sort_keys=True))
        logging.info(message)
        gcmd.respond_info(message)

    def cmd_snapshot(self, gcmd):
        self._report('snapshot', self._snapshot(), gcmd)

    def _check_environment(self, gcmd):
        now = self.printer.get_reactor().monotonic()
        state = self.printer.lookup_object('print_stats').get_status(now)['state']
        paused = self.printer.lookup_object('pause_resume').get_status(now)['is_paused']
        if self.active or state not in ('standby', 'complete', 'cancelled') or paused:
            raise gcmd.error('Z-max diagnostic requires an idle printer with no paused print')
        settings = self.printer.lookup_object('configfile').get_status(now)['settings']
        z = settings['stepper_z']
        if (settings['printer']['kinematics'] != 'corexy'
                or z['endstop_pin'] != 'PD2' or not z['homing_positive_dir']
                or z['position_endstop'] != 300.0 or z['homing_retract_dist'] != 2.0):
            raise gcmd.error('Z-max diagnostic requires the inspected Wondermaker Z configuration')
        # Observe these outputs; do not pulse/reset them as part of the test.
        for name in ('LEVELING', 'GANTRY'):
            value = self.printer.lookup_object('output_pin ' + name).get_status(now)['value']
            if value != 1:
                raise gcmd.error('%s must already be inactive (high)' % name)

    def cmd_max_test(self, gcmd):
        self._check_environment(gcmd)
        before = self._snapshot()
        self._report('before', before, gcmd)
        self.active, self.phase, self.last_result = True, 'homing', None
        try:
            # Clear compensation without moving. Keep the inspected vendor
            # driver setup, but bypass homing_override and Z_HOMING entirely:
            # no z_rise, XY, pickup, LEVELING pulse, or G1 Z7 afterwards.
            self.gcode.run_script_from_command('BED_MESH_CLEAR')
            self.gcode.run_script_from_command('STEPPER_DIAG_ENABLE CHIP=stepper_z')
            try:
                native = self.printer.lookup_object('homing')
                z_only = self.gcode.create_gcode_command('G28', 'G28 Z', {'Z': '0'})
                native.cmd_G28(z_only)
                self.printer.lookup_object('toolhead').wait_moves()
            finally:
                self.gcode.run_script_from_command('STEPPER_DIAG_DISABLE CHIP=stepper_z')
            after = self._snapshot()
            result = {'before': before, 'after': after}
            if 'z' in before['homed_axes']:
                # Counts survive coordinate relabeling within this MCU session.
                # They measure commanded steps, not an encoder or bed position.
                result['max_z_in_previous_frame'] = (
                    before['z_commanded']
                    + (after['z_mcu_steps'] - before['z_mcu_steps'])
                    * before['step_distance'])
            self.last_result, self.phase = result, 'complete'
            self._report('complete', result, gcmd)
        except Exception:
            self.phase = 'failed'
            raise
        finally:
            self.active = False

    def get_status(self, eventtime):
        return {'phase': self.phase, 'last_result': self.last_result}


def load_config(config):
    return ZDiagnostics(config)
