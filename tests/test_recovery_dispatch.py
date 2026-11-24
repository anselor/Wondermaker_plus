"""Recovery boundaries cross the retained nested G28 command dispatcher."""
from types import SimpleNamespace as NS

import pytest

from test_raw_homing import raw_home


@pytest.mark.parametrize('case', ['cancel', 'frame-fault', 'generation-change',
                                  'replacement-owner', 'foreign-actor', 'cleanup'])
def test_recovery_boundary_never_turns_an_expected_unwind_into_shutdown(raw_home, case):
    printer, calibration, dispatch, _, _, events, stock = raw_home
    from wmp_plr_attempt import RecoveryLifecycle
    from wmp_stop_points import check_operation_boundary

    actor, callbacks, shutdowns = object(), [], []
    printer.invoke_shutdown = shutdowns.append
    printer.is_shutdown = lambda: False
    printer.get_reactor = lambda: NS(monotonic=lambda: 1.)
    printer.objects['save_variables'] = NS(get_status=lambda now: {
        'variables': {'fail_flag': 0, 'is_nozzle_setting': 0}})
    printer.objects['webhooks'] = NS(get_status=lambda now: {'state': 'ready'})
    material = NS(printer=printer, session_id='recovery-session', _command_generation=0)
    printer.objects['wm_material'] = material
    lifecycle = RecoveryLifecycle(material)
    material._plr_lifecycle_component = lifecycle
    review = NS(_recovery_submission=None, _recovery_stop_request=None)
    material._plr_review_component = review
    lifecycle._recovery_attempt = runner = NS(record=None)
    lifecycle._current_actor = lambda: actor

    def guard():
        callbacks.append('frame checked')
        if case == 'frame-fault':
            raise ValueError('Recovery frame changed')

    scope = {'actor': actor, 'request': {'session': material.session_id},
             'runner': runner, 'record': None, 'generation': 0,
             'review_owner': review, 'submission': None,
             'owners': tuple((key, printer.lookup_object(key, None)) for key in
                             ('wm_material', 'gcode', 'virtual_sdcard', 'wmp_recovery', 'openace', 'AFC')),
             'guard': guard, 'cancelled': lambda: True, 'cancel_phase': '',
             'cleanup': case == 'cleanup'}
    lifecycle._execution_scope = scope
    if case == 'replacement-owner':
        printer.objects['wm_material'] = NS(session_id='replacement-owner')
    elif case == 'generation-change':
        material._command_generation += 1
    elif case == 'foreign-actor':
        lifecycle._current_actor = object

    dispatch.register_command('_WMP_OPERATION_STOP_POINT',
                              lambda gcmd: check_operation_boundary(printer, 'before Z homing'))
    calibration.raw_homing.original = lambda gcmd: dispatch.run_script_from_command(
        '_WMP_OPERATION_STOP_POINT PHASE=before_z_homing')
    dispatch.register_command('RECOVERY_TEST_ROOT',
                              lambda gcmd: dispatch.run_script_from_command('G28 X Y'))
    if case in ('replacement-owner', 'foreign-actor', 'cleanup'):
        dispatch.run_script_from_command('RECOVERY_TEST_ROOT')
        assert not callbacks and not scope['cancel_phase']
    else:
        text = {'cancel': 'Recovery preparation stopped', 'frame-fault': 'Recovery frame changed',
                'generation-change': 'Recovery preparation ownership changed'}[case]
        with pytest.raises(stock.CommandError, match=text):
            dispatch.run_script_from_command('RECOVERY_TEST_ROOT')
        assert 'gcode:command_error' in events
        assert scope['cancel_phase'] == ('before Z homing' if case == 'cancel' else '')
    assert not shutdowns
    assert not calibration.attempt_result, 'nested recovery G28 must retain its original owner'
