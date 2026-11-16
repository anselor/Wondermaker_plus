"""Calibration planning must bind PID gains to verified hardware identities."""
import itertools

import pytest

from test_identification_transaction import module, IDS


PREFIX = b'# custom motion and includes stay exact\r\n[printer]\r\nmax_velocity: 500\r\n'
MARKER = b'#*# <---------------------- SAVE_CONFIG ---------------------->\r\n'
MESH = b'#*# [bed_mesh default]\r\n#*# points = 0.1, 0.2\r\n'


def header(head):
    return ('#*# [extruder%s]\r\n' % (head or '')).encode()


def gains(head):
    return ('#*# control = pid\r\n#*# pid_Kp = %d\r\n'
            '#*# pid_Ki = %d\r\n#*# pid_Kd = %d\r\n' % (20 + head, 2 + head, 100 + head)).encode()


def configuration():
    return PREFIX + MARKER + b''.join(header(h) + gains(h) for h in range(4)) + MESH


@pytest.mark.parametrize('order', list(itertools.permutations(range(4))))
def test_every_permutation_moves_gains_with_identity_and_preserves_other_bytes(order):
    before = configuration()
    actual = module.plan_saved_pid_mapping(before, IDS, [IDS[h] for h in order])
    expected = PREFIX + MARKER + b''.join(header(h) + gains(source) for h, source in enumerate(order)) + MESH
    assert actual == expected
    assert module.plan_saved_pid_mapping(actual, [IDS[h] for h in order], IDS) == before


@pytest.mark.parametrize('defect', [
    'missing', 'duplicate-section', 'duplicate-field', 'partial', 'nonfinite',
    'negative', 'unknown-field', 'missing-marker', 'duplicate-marker',
])
def test_ambiguous_or_incomplete_calibration_is_not_migrated(defect):
    content = configuration()
    if defect == 'missing':
        content = content.replace(header(3) + gains(3), b'')
    elif defect == 'duplicate-section':
        content += header(3) + gains(3)
    elif defect == 'duplicate-field':
        content = content.replace(b'#*# pid_Kp = 20', b'#*# pid_Kp = 20\r\n#*# pid_kp = 21')
    elif defect == 'partial':
        content = content.replace(b'#*# pid_Ki = 2\r\n', b'')
    elif defect == 'nonfinite':
        content = content.replace(b'pid_Kp = 20', b'pid_Kp = nan')
    elif defect == 'negative':
        content = content.replace(b'pid_Kp = 20', b'pid_Kp = -1')
    elif defect == 'unknown-field':
        content = content.replace(b'#*# control = pid', b'#*# rotation_distance = 7\r\n#*# control = pid')
    elif defect == 'missing-marker':
        content = content.replace(MARKER, b'')
    else:
        content += MARKER
    with pytest.raises(ValueError):
        module.plan_saved_pid_mapping(content, IDS, list(reversed(IDS)))


@pytest.mark.parametrize('new', [IDS[:3], IDS[:3] + ['abcdefabcdef'], IDS[:3] + [IDS[0]], [], ['bad']])
def test_head_removal_replacement_or_bad_identity_needs_separate_review(new):
    with pytest.raises(ValueError):
        module.plan_saved_pid_mapping(configuration(), IDS, new)


def test_identity_case_is_not_a_hardware_change():
    ids = ['abcdef00000%d' % h for h in range(4)]
    assert module.plan_saved_pid_mapping(configuration(), ids, [v.upper() for v in ids]) == configuration()
