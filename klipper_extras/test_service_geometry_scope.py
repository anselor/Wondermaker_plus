"""Service admission validates geometry actually consumed by the route."""
from types import SimpleNamespace
import pytest
from test_wm_material import material, sequence_material, service_material, FakeCommand


def test_same_attached_head_does_not_require_any_dock(service_material):
    obj, objects, state = service_material
    saved = state['save_variables']['variables']
    for i in range(4): saved['t%d_position' % i] = None
    saved['t1_offset'] = saved['t3_offset'] = None
    scripts = []
    objects['gcode'] = SimpleNamespace(run_script_from_command=scripts.append)
    obj._prepare_service(2, obj._service_context(2, 1))
    assert not any('Y310' in script or 'LOCK' in script for script in scripts)
    assert any('G1 X-13' in script for script in scripts)


@pytest.mark.parametrize('attached,required', [('', {2}), ('h1', {1, 2})])
def test_switch_validates_only_visited_docks(service_material, attached, required):
    obj, _, state = service_material
    obj._material_status()._attachment = lambda now: {'state': 'attached' if attached else 'empty', 'head': attached}
    saved = state['save_variables']['variables']
    for i in set(range(4)) - required: saved['t%d_position' % i] = None
    context = obj._service_context(2, 1)
    assert set(context['dock_heads']) == required
    for index in required:
        old = saved['t%d_position' % index]
        saved['t%d_position' % index] = [100, 309]
        with pytest.raises(ValueError, match='Dock calibration'): obj._service_context(2, 1)
        saved['t%d_position' % index] = old


@pytest.mark.parametrize('index', [0, 2, 3])
def test_requested_probe_and_paused_original_offsets_required(service_material, index):
    obj, _, state = service_material
    state['save_variables']['variables']['t%d_offset' % index] = None
    with pytest.raises(ValueError, match='offsets'):
        obj._service_context(2, 1, offset_heads=(3,))


def test_homing_revalidates_newly_visited_dock_before_travel(service_material):
    obj, objects, state = service_material
    state['toolhead']['homed_axes'] = ''
    state['save_variables']['variables']['t2_position'] = None
    context = obj._service_context(2, 1, allow_homing=True)
    scripts = []
    def run(script):
        scripts.append(script)
        if script.startswith('G28'):
            state['toolhead']['homed_axes'] = 'xy'
            obj._material_status()._attachment = lambda now: {'state': 'empty', 'head': ''}
    objects['gcode'] = SimpleNamespace(run_script_from_command=run)
    with pytest.raises(ValueError, match='dock calibration'):
        obj._prepare_service(2, context)
    assert scripts == ['G28 X Y\nM400']


@pytest.mark.parametrize('busy', ['printing', 'paused', 'toolhead', 'filament'])
def test_nozzle_saved_future_settings_do_not_require_motion_idle(material, tmp_path, busy):
    from wmp_nozzles import NozzleSettings
    cfg, ini = tmp_path/'printer.cfg', tmp_path/'tmt1.ini'
    cfg.write_text('[extruder2]\nnozzle_diameter: 0.4\n')
    ini.write_text('[nozzle]\ntype2=0\n')
    material._nozzles = NozzleSettings(cfg, ini)
    if busy == 'printing': material.printer.state = 'printing'; material.printer.sd_active = True
    if busy == 'paused': material.printer.paused = True
    if busy == 'toolhead': material.toolhead_operation = {'state': 'running'}
    if busy == 'filament': material.filament_operation = {'state': 'running'}
    revision = material._nozzles.read()[1]
    material.cmd_SET_NOZZLE(FakeCommand(HEAD=2, DIAMETER='0.6', MATERIAL=1, EXPECT=revision, SESSION='test-session', ID='save'))
    assert material.nozzle_save['state'] == 'complete'
    assert 'nozzle_diameter: 0.6' in cfg.read_text()


def test_nozzle_save_excludes_actual_identification_writer(material):
    lookup = material.printer.lookup_object
    material.printer.lookup_object = lambda name, default=None: SimpleNamespace(get_status=lambda now: {'identification': {'state': 'running'}}) if name == 'wmp_recovery' else lookup(name, default)
    with pytest.raises(ValueError, match='identification'):
        material.cmd_SET_NOZZLE(FakeCommand())


def test_paused_plan_passes_origin_offset_into_geometry_validation(service_material):
    obj, _, state = service_material
    obj._material_settings()._idle_for_filament_settings = lambda now: False
    obj._pause_origin = {'head': 'h3'}
    obj._paused_service()._paused_filament_origin = lambda head, now: {'id': 'paused'}
    state['save_variables']['variables']['t3_offset'] = None
    with pytest.raises(ValueError, match='offsets for Head 4'):
        obj._filament_plan(2, 'load', 1)


def test_consumed_geometry_in_place_change_during_home_cannot_rewrite_snapshot(service_material):
    obj, objects, state = service_material
    state['toolhead']['homed_axes'] = ''
    context = obj._service_context(2, 1, allow_homing=True)
    scripts = []
    def run(script):
        scripts.append(script)
        if script.startswith('G28'):
            state['toolhead']['homed_axes'] = 'xy'
            state['save_variables']['variables']['t2_offset'][0] = 1.
    objects['gcode'] = SimpleNamespace(run_script_from_command=run)
    with pytest.raises(ValueError, match='calibration changed during homing'):
        obj._prepare_service(2, context)
    assert context['offsets'][2] == [0, 0, 0]
    assert scripts == ['G28 X Y\nM400']
