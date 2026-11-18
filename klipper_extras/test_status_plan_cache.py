"""Idle display previews may be reused; command admission must remain live."""
import json
from pathlib import Path
import pytest
from test_wm_material import material, sequence_material, service_material, profile_command


@pytest.fixture
def cached_service(service_material, tmp_path, monkeypatch):
    m, objects, state = service_material
    m.ini_path = str(tmp_path / 'tmt1.ini')
    Path(m.ini_path).write_text('[slot]\nmaterial0=0\n')
    m._mtime, m._slots, m.print_submission = None, {}, {}
    calls = []
    original = m._filament_plan
    def observed(head, action, now, cache=None):
        calls.append((head, action))
        return original(head, action, now, cache)
    monkeypatch.setattr(m, '_filament_plan', observed)
    m.get_status(1., detailed=True)
    assert len(calls) == 8
    assert m._material_status()._procedure_status_cache is not None
    return m, objects, state, calls


def test_idle_status_reuses_previews_without_sharing_mutable_output(cached_service):
    m, _, _, calls = cached_service
    first = m.get_status(2., detailed=True)
    assert len(calls) == 8
    assert first['filament_procedures']
    first['filament_procedures'][0]['identity']['brand'] = 'Local draft'
    assert m.get_status(3., detailed=True)['filament_procedures'][0]['identity']['brand'] != 'Local draft'
    assert len(calls) == 8
    # The direct command-side planner does not consult the display cache.
    m._filament_plan(2, 'load', 3.)
    assert len(calls) == 9


@pytest.mark.parametrize('change', ['dock','offset','homing','attachment','sensor',
                                  'generation','feed','purge','history','limit','macro','profile'])
def test_plan_context_changes_rebuild_idle_previews(cached_service, monkeypatch, change):
    m, objects, state, calls = cached_service
    saved = state['save_variables']['variables']
    if change == 'dock': saved['t2_position'][0] += .1
    elif change == 'offset': saved['t2_offset'][2] += .01
    elif change == 'homing': state['toolhead']['homed_axes'] = 'z'
    elif change == 'attachment': monkeypatch.setattr(m._material_status(), '_attachment', lambda now: {'state':'empty','head':''})
    elif change == 'sensor': state['filament_switch_sensor filament2']['filament_detected'] = True
    elif change == 'generation': m._command_generation = getattr(m, '_command_generation', 0) + 1
    elif change == 'feed': m.load_feed_mm = 71.
    elif change == 'purge': m.load_purge_mm = 62.
    elif change == 'history': monkeypatch.setattr(m, '_hotend_material_history', lambda: {'h2': {'material':'ABS'}})
    elif change == 'limit':
        config = objects['configfile'].get_status(2.)
        config['settings']['extruder2']['max_temp'] = 249.
        objects['configfile'].get_status = lambda now: config
    elif change == 'macro': del objects['gcode_macro WIPE_NOZZLE']
    elif change == 'profile': m.cmd_SET_FILAMENT(profile_command(m, PROFILE=json.dumps({'brand':'Updated','material':'PETG','color':'#ab1234'}).encode().hex()))
    m.get_status(2., detailed=True)
    assert len(calls) == 16


def test_active_or_paused_work_never_uses_idle_preview_cache(cached_service):
    m, _, _, calls = cached_service
    m.printer.state = 'printing'
    m.get_status(2., detailed=True)
    assert len(calls) == 16 and m._material_status()._procedure_status_cache is None
    m.get_status(3., detailed=True)
    assert len(calls) == 24


def test_background_status_does_not_prepare_unused_operations(cached_service, monkeypatch):
    m, _, _, calls = cached_service
    calls.clear()
    def unused(*args, **kwargs):
        pytest.fail('Background status attempted filament-view work')
    monkeypatch.setattr(m, '_recipe_write_status', unused)
    monkeypatch.setattr(m._material_status(), '_procedure_status', unused)
    for now in (2., 3., 4.):
        status = m.get_status(now)
        assert status['filament_details_protocol'] == 1
        assert status['filament_procedures'] == []
        assert status['filament_recipe_write'] == {}
        assert status['filament_catalogue'] == []
        assert status['filament_presence']  # Live sensing remains available.
    assert calls == []


def test_details_endpoint_is_read_only_and_revalidates_context(cached_service):
    from types import SimpleNamespace
    m, _, state, calls = cached_service
    responses = []
    m._material_status().handle_details(SimpleNamespace(send=responses.append))
    assert responses[-1]['filament_procedures']
    state['save_variables']['variables']['t2_position'][0] += .1
    m._material_status().handle_details(SimpleNamespace(send=responses.append))
    assert len(calls) == 16
    assert responses[-1]['filament_procedures'] != responses[-2]['filament_procedures']


def test_background_nozzle_metadata_reuses_supported_session_capability(material, tmp_path, monkeypatch):
    from types import SimpleNamespace
    from wmp_nozzles import NozzleSettings
    config, ini = tmp_path/'printer.cfg', tmp_path/'tmt1.ini'
    config.write_text('[extruder2]\nnozzle_diameter: 0.4\n')
    ini.write_text('[nozzle]\ntype2=0\n')
    material._nozzles = NozzleSettings(config, ini)
    original = material.printer.lookup_object
    material.printer.lookup_object = lambda name, default=None: SimpleNamespace(get_status=lambda now: {'settings': {'extruder2': {'nozzle_diameter': .4}}}) if name == 'configfile' else original(name, default)
    checks = []
    monkeypatch.setattr(material._material_settings()._nozzle_runtime, 'supported', lambda name: (checks.append(name), True)[1])
    for now in (1., 2., 3.):
        assert material._nozzle_status(now, detailed=False)['nozzles']['h2']['diameter'] == .4
    assert checks == ['extruder2']
    material._nozzle_status(4., detailed=True)
    assert checks == ['extruder2', 'extruder2']
