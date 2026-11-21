"""Every component subset gets a deterministic dependency/removal order."""
import itertools,sys
from types import SimpleNamespace
import pytest
from test_deploy import deploy

NAMES=('config','material','moonraker','preload','touchscreen','shaper')
SUBSETS=[combo for count in range(1,len(NAMES)+1) for combo in itertools.combinations(NAMES,count)]


@pytest.mark.parametrize('selected',SUBSETS)
def test_selected_install_checks_full_dependency_closure_before_mutation(monkeypatch,selected):
    events=[]
    registry={name:SimpleNamespace(NAME=name,RESTART_AFTER=None,
        preflight=lambda ctx,name=name:events.append(('check',name)),
        install=lambda ctx,name=name:events.append(('install',name))) for name in NAMES}
    monkeypatch.setattr(deploy,'ORDER',list(NAMES));monkeypatch.setattr(deploy,'REGISTRY',registry)
    monkeypatch.setattr(deploy,'create_install_journal',lambda *args:None)
    monkeypatch.setattr(deploy.Context,'printing_now',lambda _:False)
    monkeypatch.setattr(sys,'argv',['deploy.py','install',*selected])
    assert deploy.main()==0
    closure=set(selected)
    if closure & {'config','material','preload'}:closure.update(('config','material','preload','moonraker'))
    expected=[name for name in NAMES if name in closure]
    assert events==[('check',name) for name in expected]+[('install',name) for name in expected]


@pytest.mark.parametrize('selected',SUBSETS)
def test_uninstall_preflight_does_not_remove_or_restart_any_component(monkeypatch,selected):
    events=[]
    registry={name:SimpleNamespace(NAME=name,RESTART_AFTER=None,
        preflight_uninstall=lambda ctx,name=name:events.append(('check',name)),
        uninstall=lambda ctx,name=name:pytest.fail('mutated during preflight')) for name in NAMES}
    monkeypatch.setattr(deploy,'ORDER',list(NAMES));monkeypatch.setattr(deploy,'REGISTRY',registry)
    monkeypatch.setattr(deploy.Context,'printing_now',lambda _:False)
    monkeypatch.setattr(sys,'argv',['deploy.py','uninstall',*selected,'--preflight-only'])
    assert deploy.main()==0
    order=('touchscreen','shaper','config','material','preload','moonraker')
    assert events==[('check',name) for name in order if name in selected]


def test_late_removal_conflict_prevents_earlier_consumer_removal(monkeypatch):
    def conflict(ctx):raise ValueError('unproven original')
    registry={name:SimpleNamespace(NAME=name,RESTART_AFTER=None,
        preflight_uninstall=conflict if name=='moonraker' else lambda ctx:None,
        uninstall=lambda ctx:pytest.fail('removed a component despite preflight conflict')) for name in NAMES}
    monkeypatch.setattr(deploy,'ORDER',list(NAMES));monkeypatch.setattr(deploy,'REGISTRY',registry)
    monkeypatch.setattr(deploy.Context,'printing_now',lambda _:False)
    monkeypatch.setattr(sys,'argv',['deploy.py','uninstall','all'])
    assert deploy.main()==1
