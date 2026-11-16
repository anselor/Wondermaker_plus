"""Resume progress is ephemeral telemetry, never permission to move."""
from types import SimpleNamespace
import pytest
from wm_material import WMMaterial


def material(owner=None, tool_fault=False):
    m = WMMaterial.__new__(WMMaterial)
    m.printer = SimpleNamespace(lookup_object=lambda name, default=None: object() if name == owner else default)
    m._toolchange_pause_status = lambda: tool_fault
    return m


@pytest.mark.parametrize('error', [False, True])
def test_progress_nested_resume_clears_on_every_exit(error):
    m = material()
    def nested():
        assert m._resume_progress == {'phase': 'returning'}
        return 42
    def execute():
        assert m._resume_progress == {'phase': 'checking'}
        m._paused_service()._resume_phase('heating')
        assert m._resume_progress == {'phase': 'heating'}
        m._paused_service()._resume_phase('returning')
        assert m._observe_resume(nested) == 42
        assert m._resume_progress == {'phase': 'returning'}
        if error:
            raise RuntimeError('heater failed')
        return 7
    if error:
        with pytest.raises(RuntimeError, match='heater failed'):
            m._observe_resume(execute)
    else:
        assert m._observe_resume(execute) == 7
    assert m._resume_progress == {}
    m._paused_service()._resume_phase('heating')
    assert m._resume_progress == {}


@pytest.mark.parametrize('owner', ['openace', 'AFC'])
def test_external_owner_is_untouched(owner):
    m = material(owner)
    def execute():
        assert not hasattr(m, '_resume_progress')
        return 7
    assert m._observe_resume(execute) == 7


def test_tool_retry_does_not_claim_normal_restore_phases():
    m = material(tool_fault=True)
    def execute():
        assert m._resume_progress == {'phase': 'toolchange'}
        m._paused_service()._resume_phase('heating')
        assert m._resume_progress == {'phase': 'toolchange'}
    m._observe_resume(execute)
    assert m._resume_progress == {}
