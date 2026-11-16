"""Recovery stage completion must not impose a second exact-pose contract."""
from collections import namedtuple
import pytest

pytest_plugins = ['test_wm_material']


@pytest.mark.parametrize('container', [list, tuple, namedtuple('Coord', 'x y z e')])
def test_recovery_tolerates_native_pose_rounding_without_repeating_motion(recovery_reference_machine, container):
    material, objects, states, calls, review, request = recovery_reference_machine
    original = objects['toolhead'].get_status
    def status(now):
        result = dict(original(now))
        pose = list(result['position'])
        # Less than the verified helper's tolerance, but not exactly equal to
        # the commanded waypoint. Software pose roundoff is not physical drift.
        pose[0] += 1e-8
        result['position'] = container(*pose) if hasattr(container, '_fields') else container(pose)
        return result
    objects['toolhead'].get_status = status
    result = material._recovery_attempt.run(request, material._recovery_initial_stages(review))
    assert result['state'] == 'complete'
    assert calls.count('G1 X-13 Y80 F12000\nM400') == 2  # Purge and wipe entry.
    assert calls.count('G1 X-13 Y240 F12000\nM400') == 4
    assert calls.count('G1 X-13 Y275 F12000\nM400') == 4
    assert len([call for call in calls if call.startswith('G1 E')]) == 2


def test_recovery_still_rejects_on_bed_wipe_before_wipe_motion(recovery_reference_machine):
    material, objects, states, calls, review, request = recovery_reference_machine
    objects['save_variables'].values['variables']['wipe_position'] = [5., 240.]
    with pytest.raises(ValueError, match='off-bed wipe'):
        material._recovery_attempt.run(request, material._recovery_initial_stages(review))
    assert not any(call.startswith('G1 X5 ') for call in calls)
    assert len([call for call in calls if call.startswith('G1 E')]) == 2
