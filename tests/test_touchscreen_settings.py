"""Camera transaction fault paths; HTTP is modeled, no printer mutations."""
import copy
import pytest
from test_deploy import deploy
import touchscreen_settings as settings


class API:
    def __init__(self, existing=False):
        self.cameras = [dict(name='camera', uid='print-camera', source='config')]
        if existing:
            self.cameras.append(dict(settings.SCREEN, uid='existing-screen', source='database',
                                     extra_data={'operator': 'keep'}, target_fps=3))
        self.selected = 'previous camera name'
        self.fail = None
        self.writes = []

    def __call__(self, method, path, data):
        if method == 'GET':
            if path == settings.WEBCAMS:
                return {'webcams': copy.deepcopy(self.cameras)}
            return {'camera': self.selected, 'enabled': True, 'parkhead': False}
        self.writes.append((method, path, copy.deepcopy(data)))
        if path == settings.TIMELAPSE:
            assert set(data) == {'camera'}  # Never alter capture or motion options.
            self.selected = data['camera']
        elif method == 'DELETE':
            self.cameras = [c for c in self.cameras if c['uid'] != data['uid']]
        else:
            old = next((c for c in self.cameras if c['uid'] == data.get('uid') or c['name'] == data['name']), None)
            if old:
                old.update(data)
            else:
                self.cameras.append(dict(data, uid='new-screen', source='database'))
        if self.fail == (method, path):
            self.fail = None
            raise OSError('lost response after successful mutation')
        return {}


@pytest.mark.parametrize('existing', [False, True])
def test_apply_restore_preserves_original_settings_and_identity(existing):
    api = API(existing)
    before = copy.deepcopy(api.cameras), api.selected
    checkpoints = []
    receipt = settings.prepare(api)
    assert not api.writes
    settings.apply(api, receipt, checkpoints.append)
    assert api.selected == 'camera'
    assert checkpoints[-1]['state'] == 'applied'
    settings.restore(api, receipt, checkpoints.append)
    assert (api.cameras, api.selected) == before
    count = len(api.writes)
    settings.restore(api, receipt, checkpoints.append)
    assert len(api.writes) == count


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('path', [settings.ITEM, settings.TIMELAPSE])
def test_lost_apply_response_restores_from_durable_checkpoint(existing, path):
    api = API(existing)
    before = copy.deepcopy(api.cameras), api.selected
    receipt = settings.prepare(api)
    checkpoints = []
    api.fail = ('POST', path)
    with pytest.raises(OSError):
        settings.apply(api, receipt, checkpoints.append)
    # Model process loss: only the last recorded checkpoint survives.
    settings.restore(api, checkpoints[-1], checkpoints.append)
    assert (api.cameras, api.selected) == before


@pytest.mark.parametrize('kind', ['camera', 'selection', 'replacement'])
def test_later_edits_are_preserved_without_any_restore_writes(kind):
    api = API(True)
    receipt = settings.prepare(api)
    settings.apply(api, receipt, lambda r: None)
    if kind == 'selection':
        api.selected = 'operator-chosen'
    elif kind == 'replacement':
        api.cameras[-1]['uid'] = 'replacement-camera'
    else:
        api.cameras[-1]['target_fps'] = 7
    before = copy.deepcopy(api.cameras), api.selected
    api.writes.clear()
    with pytest.raises(ValueError, match='Concurrent'):
        settings.restore(api, receipt, lambda r: None)
    assert (api.cameras, api.selected) == before and not api.writes


@pytest.mark.parametrize('existing', [False, True])
def test_lost_restore_response_can_resume(existing):
    api = API(existing)
    before = copy.deepcopy(api.cameras), api.selected
    receipt = settings.prepare(api)
    checkpoints = []
    settings.apply(api, receipt, checkpoints.append)
    api.fail = ('POST' if existing else 'DELETE', settings.ITEM)
    with pytest.raises(OSError):
        settings.restore(api, receipt, checkpoints.append)
    settings.restore(api, checkpoints[-1], checkpoints.append)
    assert (api.cameras, api.selected) == before


def test_failed_checkpoint_prevents_first_mutation():
    api = API()
    receipt = settings.prepare(api)
    def fail(receipt):
        raise OSError('journal unavailable')
    with pytest.raises(OSError):
        settings.apply(api, receipt, fail)
    assert not api.writes


@pytest.mark.parametrize('reason', ['config-owned', 'ambiguous-screen'])
def test_unsupported_camera_state_refuses_before_mutation(reason):
    api = API(True)
    if reason == 'config-owned':
        api.cameras[-1]['source'] = 'config'
    elif reason == 'missing-print-camera':
        api.cameras.pop(0)
    else:
        api.cameras.append(copy.deepcopy(api.cameras[-1]))
    with pytest.raises(ValueError):
        settings.prepare(api)
    assert not api.writes


@pytest.mark.parametrize('mode', ['disabled', 'absent', 'ambiguous', 'unavailable', 'custom'])
def test_optional_timelapse_does_not_block_bridge_or_mutate_selection(mode):
    api = API()
    if mode in ('disabled', 'absent', 'unavailable'):
        api.cameras = []
    elif mode == 'ambiguous':
        api.cameras.append(dict(api.cameras[0], uid='duplicate'))
    elif mode == 'custom':
        api.cameras[0]['name'] = api.selected = 'My camera'
    def request(method, path, data):
        if method == 'GET' and path == settings.TIMELAPSE:
            if mode in ('absent', 'unavailable'):
                raise OSError('endpoint not available')
            result = api(method, path, data)
            result['enabled'] = mode != 'disabled'
            return result
        return api(method, path, data)
    before = copy.deepcopy(api.cameras), api.selected
    receipt = settings.prepare(request)
    assert not receipt['selection_managed']
    settings.apply(request, receipt, lambda r: None)
    assert any(c['name'] == 'Touchscreen' for c in api.cameras)
    # Operator can change unrelated selection while bridge is installed.
    api.selected = 'operator new selection'
    settings.restore(request, receipt, lambda r: None)
    assert api.cameras == before[0] and api.selected == 'operator new selection'
    assert not any(path == settings.TIMELAPSE for _, path, _ in api.writes)
    assert receipt['fixer_policy'] == ('preserve' if mode in ('absent', 'unavailable') else 'disable')
