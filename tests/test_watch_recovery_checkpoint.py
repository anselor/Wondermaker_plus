import copy
import errno
import io
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('watch_checkpoint', ROOT / 'tools/watch_recovery_checkpoint.py')
watch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(watch)


def test_execution_location_prefers_runtime_and_falls_back_only_when_missing():
    class Sftp:
        def __init__(self, runtime):
            self.runtime = runtime
            self.paths = []

        def open(self, path, mode):
            self.paths.append(path)
            if path == 'runtime':
                if isinstance(self.runtime, Exception):
                    raise self.runtime
                return io.BytesIO(self.runtime)
            return io.BytesIO(b'legacy')

    for runtime, expected, paths in (
        (b'current', b'current', ['runtime']),
        (b'', b'', ['runtime']),
        (FileNotFoundError(errno.ENOENT, 'missing'), b'legacy', ['runtime', 'legacy']),
    ):
        sftp = Sftp(runtime)
        assert watch.read_execution(sftp, 'runtime', 'legacy') == expected
        assert sftp.paths == paths
    for runtime, error_type in (
        (PermissionError(errno.EACCES, 'denied'), PermissionError),
        (b'x' * 65537, ValueError),
    ):
        sftp = Sftp(runtime)
        with pytest.raises(error_type):
            watch.read_execution(sftp, 'runtime', 'legacy')
        assert sftp.paths == ['runtime']


@pytest.fixture
def sample():
    binding = dict(attempt_id='attempt', session='session', filename='coupon.gcode', file_sha256='a' * 64)
    status = dict(webhooks=dict(state='ready'), print_stats=dict(state='printing', filename='coupon.gcode'),
                  virtual_sdcard=dict(is_active=True), pause_resume=dict(is_paused=False),
                  wm_material=dict(session_id='session', afc_metadata=dict(owner='standalone'), recovery_attempt=dict(
                      request=dict(id='attempt', session='session', file='coupon.gcode'), state='complete',
                      continuation=dict(state='started'), checkpoint=dict(job_fingerprint='job', file_position=100))))
    execution = dict(state='completed', session='session', job_fingerprint='job', file_position=200,
                     file=dict(path='coupon.gcode', sha256='a' * 64, size=1000))
    return status, execution, binding


def test_only_new_completed_bound_checkpoint_qualifies(sample):
    status, execution, binding = sample
    assert watch.decision(status, execution, **binding)
    for key, value in [('session', 'old'), ('job_fingerprint', 'other'), ('state', 'pending'),
                       ('file_position', 100), ('file_position', 1000)]:
        altered = copy.deepcopy(execution)
        altered[key] = value
        assert not watch.decision(status, altered, **binding)
    for key in ('path', 'sha256'):
        altered = copy.deepcopy(execution)
        altered['file'][key] = 'wrong'
        assert not watch.decision(status, altered, **binding)


@pytest.mark.parametrize('change', ['session', 'owner', 'attempt', 'finished', 'paused', 'inactive', 'shutdown'])
def test_changed_live_context_aborts(sample, change):
    status, execution, binding = sample
    if change == 'session': status['wm_material']['session_id'] = 'new'
    elif change == 'owner': status['wm_material']['afc_metadata']['owner'] = 'openace'
    elif change == 'attempt': status['wm_material']['recovery_attempt']['request']['id'] = 'new'
    elif change == 'finished': status['print_stats']['state'] = 'complete'
    elif change == 'paused': status['pause_resume']['is_paused'] = True
    elif change == 'inactive': status['virtual_sdcard']['is_active'] = False
    else: status['webhooks']['state'] = 'shutdown'
    with pytest.raises(ValueError): watch.decision(status, execution, **binding)


def test_preparation_waits_without_qualifying(sample):
    status, execution, binding = sample
    status['wm_material']['recovery_attempt']['state'] = 'running'
    status['wm_material']['recovery_attempt']['continuation'] = {}
    status['print_stats']['state'] = 'standby'
    assert not watch.decision(status, execution, **binding)


@pytest.mark.parametrize('field', ['session_id', 'id', 'session', 'file', 'owner'])
def test_identity_refusal_names_field_without_disclosing_binding(sample, field):
    status, execution, binding = sample
    material = status['wm_material']
    if field == 'session_id': material[field] = 'PRIVATE_BINDING'
    elif field == 'owner': material['afc_metadata'][field] = 'PRIVATE_BINDING'
    else: material['recovery_attempt']['request'][field] = 'PRIVATE_BINDING'
    with pytest.raises(ValueError) as error: watch.decision(status, execution, **binding)
    assert field in str(error.value) and 'PRIVATE_BINDING' not in str(error.value)
