import copy
import itertools
import json

import pytest

from wm_material import WMMaterial
from wmp_identification import plan_head_configuration
from wmp_nozzles import _value


IDS = ['abcdef00000%d' % h for h in range(4)]


def source():
    snapshot = {
        'printer.cfg': b'# retain travel/wipe includes\r\n[include custom.cfg]\r\n',
        'tmt1.ini': b'[printer]\r\nmodel=2\r\n[nozzle]\r\n',
        'wmp_filaments.json': None,
        'wmp_filament_loaded.json': b'{"h0": true, "h2": false}',
        'wmp_hotend_materials.json': None,
    }
    effective = {}
    saved = b'#*# <---------------------- SAVE_CONFIG ---------------------->\r\n'
    for head in range(4):
        section = 'extruder' + (str(head) if head else '')
        diameter = (head + 1) * 0.2
        snapshot['printer.cfg'] += ('[%s]\r\nnozzle_diameter: %.1f # keep\r\n' % (section, diameter)).encode()
        snapshot['tmt1.ini'] += ('type%d=%d ; keep\r\n' % (head, head % 2)).encode()
        snapshot['wm_zru_thr%d.cfg' % head] = ('[mcu T%d]\ncanbus_uuid: %s\n' % (head, IDS[head])).encode()
        saved += ('#*# [%s]\r\n#*# control = pid\r\n#*# pid_Kp = %d\r\n'
                  '#*# pid_Ki = 2\r\n#*# pid_Kd = 100\r\n' % (section, 20 + head)).encode()
        effective[section] = {'control': 'pid', 'nozzle_diameter': diameter,
                              'pid_kp': 20 + head, 'pid_ki': 2, 'pid_kd': 100}
        effective['mcu T%d' % head] = {'canbus_uuid': IDS[head]}
    snapshot['printer.cfg'] += saved + b'#*# [probe]\r\n#*# z_offset = 1.25\r\n'
    return snapshot, effective


@pytest.mark.parametrize('order', list(itertools.permutations(range(4))))
def test_combined_plan_keeps_uuid_pid_nozzle_and_loaded_state_together(order):
    snapshot, effective = source()
    before = copy.deepcopy(snapshot)
    result = plan_head_configuration(snapshot, [IDS[h] for h in order], effective, WMMaterial._validate_identity)
    assert snapshot == before
    assert set(result) == set(snapshot)
    for head, old in enumerate(order):
        assert IDS[old].encode() in result['wm_zru_thr%d.cfg' % head]
        section = 'extruder' + (str(head) if head else '')
        assert float(_value(result['printer.cfg'].decode(), section, 'nozzle_diameter', ':')) == pytest.approx((old + 1) * 0.2)
        assert _value(result['tmt1.ini'].decode(), 'nozzle', 'type%d' % head, '=') == str(old % 2)
        saved = result['printer.cfg'].split(('#*# [%s]\r\n' % section).encode())[1].split(b'#*# [')[0]
        assert ('pid_Kp = %d' % (20 + old)).encode() in saved
    assert result['printer.cfg'].startswith(b'# retain travel/wipe includes\r\n[include custom.cfg]\r\n')
    assert result['printer.cfg'].endswith(b'#*# [probe]\r\n#*# z_offset = 1.25\r\n')
    original_flags = json.loads(snapshot['wmp_filament_loaded.json'])
    assert json.loads(result['wmp_filament_loaded.json']) == {
        'h%d' % head: original_flags['h%d' % old] for head, old in enumerate(order) if 'h%d' % old in original_flags}
    if order == (0, 1, 2, 3):
        assert result == snapshot


@pytest.mark.parametrize('defect', ['pid', 'diameter', 'uuid', 'missing-runtime', 'missing-file',
                                  'saved-override', 'unknown-material', 'duplicate-nozzle'])
def test_combined_plan_refuses_inconsistent_provenance(defect):
    snapshot, effective = source()
    if defect == 'pid':
        effective['extruder']['pid_kp'] = 99
    elif defect == 'diameter':
        effective['extruder']['nozzle_diameter'] = 0.6
    elif defect == 'uuid':
        effective['mcu T0']['canbus_uuid'] = IDS[1]
    elif defect == 'missing-runtime':
        effective.clear()
    elif defect == 'missing-file':
        del snapshot['wmp_hotend_materials.json']
    elif defect == 'saved-override':
        snapshot['printer.cfg'] = snapshot['printer.cfg'].replace(b'#*# control = pid', b'#*# nozzle_diameter = 0.6\r\n#*# control = pid')
    elif defect == 'unknown-material':
        snapshot['tmt1.ini'] = snapshot['tmt1.ini'].replace(b'type0=0', b'type0=unknown')
    else:
        snapshot['printer.cfg'] = snapshot['printer.cfg'].replace(b'[extruder]\r\n', b'[extruder]\r\nnozzle_diameter: 0.6\r\n')
    before = copy.deepcopy(snapshot)
    with pytest.raises(ValueError):
        plan_head_configuration(snapshot, list(reversed(IDS)), effective, WMMaterial._validate_identity)
    assert snapshot == before
