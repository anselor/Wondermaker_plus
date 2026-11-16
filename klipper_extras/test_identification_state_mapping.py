import itertools
import json

import pytest

from wm_material import WMMaterial
from wmp_identification import plan_filament_state_mapping


IDS = ['abcdef00000%d' % h for h in range(4)]
PROFILE = 'wmp_filaments.json'
LOADED = 'wmp_filament_loaded.json'
HISTORY = 'wmp_hotend_materials.json'


def encode(value):
    return json.dumps(value).encode()


def records():
    identities = {'h%d' % h: {'brand': 'Brand %d' % h, 'material': 'PLA',
                              'color': '#12345%d' % h} for h in range(4)}
    return {
        PROFILE: encode(identities),
        LOADED: encode({'h0': True, 'h1': False, 'h3': True}),
        HISTORY: encode({'version': 1, 'heads': {
            'h0': {'state': 'mixed', 'unknown_residue': True,
                   'materials': [identities['h0'], identities['h1']]},
            'h3': {'state': 'purged', 'unknown_residue': False,
                   'materials': [identities['h3']]}}}),
    }


def plan(snapshot, new):
    return plan_filament_state_mapping(snapshot, IDS, new, WMMaterial._validate_identity)


@pytest.mark.parametrize('order', list(itertools.permutations(range(4))))
def test_records_follow_identity_without_filling_unknown_state(order):
    before = records()
    after = plan(before, [IDS[h] for h in order])
    for name in before:
        original = json.loads(before[name])
        mapped = json.loads(after[name])
        if name == HISTORY:
            assert mapped['version'] == 1
            original, mapped = original['heads'], mapped['heads']
        assert mapped == {'h%d' % destination: original['h%d' % source]
                          for destination, source in enumerate(order) if 'h%d' % source in original}
    assert before == records()  # Caller-owned snapshot remains intact.


def test_missing_files_stay_absent_and_identity_mapping_is_byte_exact():
    snapshot = records()
    assert plan(snapshot, IDS) == snapshot
    snapshot = dict.fromkeys((PROFILE, LOADED, HISTORY))
    assert plan(snapshot, list(reversed(IDS))) == snapshot


@pytest.mark.parametrize('name,content', [
    (LOADED, b'{"h0":true,"h0":false}'),
    (LOADED, b'{"h0":1}'),
    (LOADED, b'{"h0":null}'),
    (LOADED, b'{"h4":true}'),
    (PROFILE, b'{"h0":{"brand":"B","material":"PLA","color":"bad"}}'),
    (PROFILE, b'{"h0":{"brand":"B","material":"PLA","color":"#123456","nozzle_temp":NaN}}'),
    (PROFILE, b'x' * 16385),
    (HISTORY, b'{"version":true,"heads":{}}'),
    (HISTORY, encode({'version': 1, 'heads': {'h0': {'state': 'purged', 'materials': [], 'unknown_residue': False}}})),
    (HISTORY, encode({'version': 1, 'heads': {'h0': {'state': 'purged', 'materials': [{}], 'unknown_residue': True}}})),
])
def test_malformed_evidence_cannot_be_silently_normalized(name, content):
    snapshot = records()
    snapshot[name] = content
    with pytest.raises(ValueError):
        plan(snapshot, list(reversed(IDS)))


def test_caller_must_include_all_record_files_and_supply_owner_validation():
    snapshot = records()
    del snapshot[HISTORY]
    with pytest.raises(ValueError, match='Complete'):
        plan(snapshot, IDS)
    with pytest.raises(ValueError, match='Complete'):
        plan_filament_state_mapping(records(), IDS, IDS, None)


def test_migrated_history_must_fit_normal_reader_limit():
    snapshot = records()
    identity = {'brand': '\U0001f600' * 64, 'material': '\U0001f600' * 64, 'color': '#123456'}
    heads = {'h%d' % h: {'state': 'mixed', 'unknown_residue': bool(h),
                         'materials': [identity] * 8} for h in range(4)}
    snapshot[HISTORY] = json.dumps({'version': 1, 'heads': heads}, ensure_ascii=False).encode()
    assert len(snapshot[HISTORY]) < 32768
    with pytest.raises(ValueError, match='size limit'):
        plan(snapshot, list(reversed(IDS)))
