"""Factory originals survive update waves and shared component removal."""
import pytest
from test_deploy import deploy
import file_ownership as store


def test_updates_restore_original_not_previous_wmp():
    state = store.load(None, {'helper.py'})
    store.install(state, 'helper.py', b'factory', b'r3', 'config', {})
    store.install(state, 'helper.py', b'r3', b'r4', 'config', {})
    state = store.load(store.encode(state), {'helper.py'})
    updated, changes = store.removal(state, 'config', lambda _: b'r4')
    assert changes == {'helper.py': b'factory'}
    assert updated['files']['helper.py']['owners'] == []


def test_component_shared_helpers_survive_until_last_owner():
    state = store.load(None, {'helper.py'})
    store.install(state, 'helper.py', None, b'r4', 'config', {})
    store.install(state, 'helper.py', b'r4', b'r4', 'material', {})
    updated, changes = store.removal(state, 'config', lambda _: b'r4')
    assert changes == {}
    updated, changes = store.removal(updated, 'material', lambda _: b'r4')
    assert changes == {'helper.py': None}


def test_known_legacy_wmp_is_not_promoted_to_factory():
    state = store.load(None, {'helper.py'})
    known = {'helper.py': [store.digest(b'r3')]}
    store.install(state, 'helper.py', b'r3', b'r4', 'config', known)
    _, changes = store.removal(state, 'config', lambda _: b'r4')
    assert changes == {'helper.py': None}


def test_unknown_edit_blocks_entire_removal_before_planning_mutations():
    state = store.load(None, {'a.py', 'b.py'})
    for name in ('a.py', 'b.py'):
        store.install(state, name, None, b'r4', 'config', {})
    with pytest.raises(ValueError, match='changed before removal'):
        store.removal(state, 'config', lambda name: b'edit' if name=='b.py' else b'r4')
    assert all(row['owners']==['config'] for row in state['files'].values())


def test_interrupted_removal_can_resume_without_adopting_restored_bytes():
    state = store.load(None, {'a.py', 'b.py'})
    for name in ('a.py', 'b.py'):
        store.install(state, name, b'factory', b'r4', 'config', {})
    updated, changes = store.removal(state, 'config', lambda name: b'factory' if name=='a.py' else b'r4')
    assert changes == {'b.py': b'factory'}
    for row in updated['files'].values():
        assert row['original_hash']==store.digest(b'factory')


@pytest.mark.parametrize('name', ['../../escape.py', '/tmp/escape.py', 'unexpected.py'])
def test_receipts_cannot_authorize_arbitrary_paths(name):
    state = store.load(None, {name})
    store.install(state, name, None, b'r4', 'config', {})
    with pytest.raises(ValueError, match='Unexpected owned helper'):
        store.load(store.encode(state), {'helper.py'})
