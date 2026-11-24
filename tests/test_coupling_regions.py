"""An ordinary SD Stop may finish only its admitted coupling invocation."""
from pathlib import Path
from types import SimpleNamespace as NS
import sys
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'klipper_extras'))
from wmp_coupling_region import CouplingRegions
from wmp_command_routing import CommandRouting


class Command:
    error = ValueError
    def __init__(self, name, **fields): self.name, self.fields = name, fields
    def get_command(self): return self.name
    def get(self, name, default=None): return self.fields.get(name, default)
    def get_int(self, name, default=None, **bounds):
        value = self.fields.get(name, default)
        if value is None: raise ValueError('missing ' + name)
        return int(value)


@pytest.fixture
def rig():
    actor, events = [object()], []
    saved = dict(fail_flag=0, **{'t%d_%s' % (h, f): [h, 300] if f == 'position' else [0, 0, 0]
                                for h in range(4) for f in ('position', 'offset')})
    mutex = NS(test=lambda: True)
    handle = NS(closed=False)
    sd = NS(current_file=handle, is_cmd_from_sd=lambda: True)
    stats = NS(filename='cold.gcode')
    cancellation = NS(_print_cancel={'state': 'complete'}, _print_cancel_live_binding=None)
    material = NS(session_id='session', _command_generation=0)
    service = NS(material=material, _current_actor=lambda: actor[0])
    material._toolhead_service = service
    objects = {'wm_material': material, 'wmp_recovery': NS(), 'virtual_sdcard': sd,
               'print_stats': stats, 'gcode': NS(get_mutex=lambda: mutex, run_script_from_command=lambda cmd: events.append(cmd)),
               'save_variables': NS(get_status=lambda now: {'variables': saved})}
    printer = NS(lookup_object=lambda n, default=None: objects.get(n, default),
                 get_reactor=lambda: NS(monotonic=lambda: 0), is_shutdown=lambda: False)
    material.printer = printer
    material._cancellation = lambda: cancellation
    material._print_cancel_active = lambda: cancellation._print_cancel['state'] == 'pending'
    material.stop_requested = lambda: {'scope': 'print'} if material._print_cancel_active() else None
    def boundary(phase, label, state):
        if material._print_cancel_active():
            events.append(label)
            raise ValueError('Print cancellation requested; stopped ' + label)
    material.check_stop_point = boundary
    routing = CommandRouting(material)
    # CommandRouting delegates this shared property to the material coordinator.
    routing.__dict__['_command_generation'] = 0
    material._check_command_generation = lambda cmd, **kw: routing._check_command_generation(
        cmd, **dict({'coupling_owner': service} if kw.get('coupling_region') else {}, **kw))
    regions = service._coupling_regions = CouplingRegions(service)
    def stop():
        cancellation._coupling_finish_generation = material._command_generation
        material._command_generation += 1
        routing._command_generation = material._command_generation
        cancellation._print_cancel_live_binding = dict(session='session', file='cold.gcode', handle=handle, cancel_id='stop')
        cancellation._print_cancel = dict(id='stop', state='pending', phase='stopping')
    def cmd(name, **fields):
        return Command(name, SESSION='session', GENERATION=material._command_generation, **fields)
    return NS(regions=regions, material=material, service=service, objects=objects,
              saved=saved, events=events, actor=actor, stop=stop, cmd=cmd,
              cancellation=cancellation, routing=routing, printer=printer)


@pytest.mark.parametrize('kind', ['dock', 'pickup'])
@pytest.mark.parametrize('when', ['approach', 'stroke', 'retreat'])
@pytest.mark.parametrize('template_generation', ['old', 'fresh'])
def test_sd_stop_finishes_only_backoff_then_unwinds(rig, kind, when, template_generation):
    r = rig
    def body(command):
        r.regions.begin(r.cmd('_WMP_COUPLING_BEGIN', KIND=kind, HEAD=2))
        for stage in ('approach', 'stroke', 'retreat'):
            r.events.append(stage)
            if stage == when: r.stop()
            if stage == 'approach' and kind == 'dock':
                c = r.cmd('_WMP_CHECK_DOCK_SUPPORT', HEAD=2)
            elif stage == 'stroke': c = r.cmd('_WMP_COUPLING_STROKE', LOCK=int(kind == 'pickup'))
            elif stage == 'retreat' and kind == 'pickup': c = r.cmd('_WMP_CHECK_PICKUP_RELEASE', HEAD=2)
            else: continue
            if template_generation == 'old': c.fields['GENERATION'] = 0
            r.material._check_command_generation(c, coupling_region=True)
        r.events.append('confirmed backoff')
        r.regions.end(r.cmd('_WMP_COUPLING_END', KIND=kind, HEAD=2))
        r.events.append('UNREACHABLE next stage')
    with pytest.raises(ValueError, match='Print cancellation requested'):
        r.regions.invoke(body, kind, Command('_UNLOCK_TOOL' if kind == 'dock' else '_LOCK_TOOL', T=2))
    assert r.events[:4] == ['approach', 'stroke', 'retreat', 'confirmed backoff']
    assert 'UNREACHABLE next stage' not in r.events and r.regions.scope is None
    if kind == 'pickup':
        assert r.events[4:7] == [
            'ACTIVATE_EXTRUDER EXTRUDER=extruder2',
            'SAVE_VARIABLE VARIABLE=current_extruder VALUE=2',
            'SET_GCODE_OFFSET X=0 Y=0 Z=0 MOVE=0',
        ]
        assert r.events[-1] == 'after verified tool pickup'


@pytest.mark.parametrize('change', ['actor', 'session', 'manager', 'component', 'file', 'filename',
                                    'generation', 'cancel_id', 'phase', 'fault', 'geometry',
                                    'quick_stop', 'shutdown', 'openace', 'AFC'])
def test_replaced_or_faulted_scope_never_gets_generation_permission(rig, change):
    r = rig
    def body(command):
        r.regions.begin(r.cmd('_WMP_COUPLING_BEGIN', KIND='dock', HEAD=2));r.stop()
        if change == 'actor': r.actor[0] = object()
        elif change == 'session': r.material.session_id = 'new'
        elif change == 'manager': r.objects['wm_material'] = object()
        elif change == 'component': r.material._toolhead_service = object()
        elif change == 'file': r.objects['virtual_sdcard'].current_file = object()
        elif change == 'filename': r.objects['print_stats'].filename = 'other.gcode'
        elif change == 'generation': r.material._command_generation += 1;r.routing._command_generation += 1
        elif change == 'cancel_id': r.cancellation._print_cancel['id'] = 'other'
        elif change == 'phase': r.cancellation._print_cancel['phase'] = 'draining'
        elif change == 'fault': r.saved['fail_flag'] = -3
        elif change == 'geometry': r.saved['t2_position'][1] += 1
        elif change == 'quick_stop': r.printer.quick_stop_flag = True
        elif change == 'shutdown': r.printer.is_shutdown = lambda: True
        else: r.objects[change] = object()
        c = r.cmd('_WMP_COUPLING_STROKE', LOCK=0);c.fields['GENERATION'] = 0
        assert not r.regions.allows(c)
        # No fallback from a failed invocation proof to the older stroke exception.
        with pytest.raises(ValueError): r.material._check_command_generation(c, coupling_region=True, finish_coupling=True)
    r.regions.invoke(body, 'dock', Command('_UNLOCK_TOOL', T=2))
    assert r.regions.scope is None


def test_stop_before_approach_does_not_arm_permission(rig):
    def body(command):
        rig.stop()
        rig.regions.begin(rig.cmd('_WMP_COUPLING_BEGIN', KIND='dock', HEAD=2))
        pytest.fail('approach admitted after Stop')
    with pytest.raises(ValueError): rig.regions.invoke(body, 'dock', Command('_UNLOCK_TOOL', T=2))
    assert rig.regions.scope is None


def test_macro_fault_retires_region_without_end_or_replay(rig):
    def body(command):
        rig.regions.begin(rig.cmd('_WMP_COUPLING_BEGIN', KIND='dock', HEAD=2))
        raise ValueError('actual actuator fault')
    with pytest.raises(ValueError, match='actual actuator fault'):
        rig.regions.invoke(body, 'dock', Command('_UNLOCK_TOOL', T=2))
    assert rig.regions.scope is None
    with pytest.raises(ValueError): rig.regions.end(rig.cmd('_WMP_COUPLING_END', KIND='dock', HEAD=2))


@pytest.mark.parametrize('stop_at', ['approach', 'stroke', 'retreat'])
def test_retained_dispatcher_runs_native_dock_backoff_before_stop(rig, stop_at):
    """Execute real nested Jinja macros with the vendor command decorator."""
    import importlib.util
    import ast
    from test_config_macros import templates, ROOT
    path = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/gcode.py'
    spec = importlib.util.spec_from_file_location('coupling_vendor_gcode', path)
    vendor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vendor)
    r = rig
    mutex = r.objects['gcode'].get_mutex()
    r.printer.get_start_args = lambda: {}
    r.printer.register_event_handler = lambda *args: None
    r.printer.get_reactor = lambda: NS(monotonic=lambda: 0, mutex=lambda: mutex)
    r.printer.config_error = vendor.CommandError
    r.printer.command_error = vendor.CommandError
    r.printer.quick_stop_flag = False
    r.printer.send_event = lambda *args: None
    r.printer.invoke_shutdown = lambda msg: pytest.fail(msg)
    gc = r.objects['gcode'] = vendor.GCodeDispatch(r.printer)
    def boundary(phase, label, state):
        if r.material._print_cancel_active():
            r.events.append(label)
            raise vendor.CommandError('Print cancellation requested; stopped ' + label)
    r.material.check_stop_point = boundary
    r.saved.update(current_extruder=2, is_nozzle_setting=0)
    sensors = {'Raw': 4500, 'detected': True}
    ts = templates(ROOT / 'config/live')
    def snapshot():
        return dict(save_variables={'variables': r.saved},
                    toolhead={'homed_axes': 'xyz'},
                    gcode_move={'position': {'y': 200}},
                    wm_material={'session_id': 'session', 'command_generation': r.material._command_generation},
                    custom_hall={'Raw': sensors['Raw']},
                    **{'filament_switch_sensor sensor_b': {'filament_detected': sensors['detected']}})
    def macro(name):
        def run(cmd):
            script = ts[name].render(printer=snapshot(), params=cmd.get_command_parameters(),
                                    action_respond_info=lambda msg: '',
                                    action_raise_error=lambda msg: (_ for _ in ()).throw(vendor.CommandError(msg)))
            gc.run_script_from_command(script)
        return run
    for name in ('_UNLOCK_TOOL', '_CHECK_AND_UNLOCK', 'UNLOCK', 'UNLOCK_TOOL_FINISH'):
        gc.register_command(name, macro(name))
    gc.register_command('_WMP_COUPLING_BEGIN', r.regions.begin)
    gc.register_command('_WMP_COUPLING_END', r.regions.end)
    def guarded(cmd):
        r.material._check_command_generation(cmd, coupling_region=True)
        r.events.append(cmd.get_command())
        if cmd.get_command() == '_WMP_COUPLING_STROKE' and stop_at == 'stroke':
            r.stop()
            r.material._check_command_generation(cmd, coupling_region=True)
    gc.register_command('_WMP_CHECK_DOCK_SUPPORT', guarded)
    gc.register_command('_WMP_COUPLING_STROKE', guarded)
    def move(cmd):
        if cmd.get_command() == '_WMP_XY_TRAVEL' and not r.material._print_cancel_active() and stop_at == 'approach':
            r.stop()
        if cmd.get('Y', None) == '310' and cmd.get('F', None) == '6000':
            r.events.append('native backoff')
            sensors.update(Raw=5000, detected=False)
            if stop_at == 'retreat': r.stop()
    gc.register_command('_WMP_XY_TRAVEL', move)
    gc.register_command('G0', move)
    for name in ('G90', 'SET_GCODE_OFFSET', 'M400', 'G4', 'ECHELON_STEPPER_DISABLE'):
        gc.register_command(name, lambda cmd: None)
    def save(cmd):
        r.saved[cmd.get('VARIABLE')] = ast.literal_eval(cmd.get('VALUE'))
    gc.register_command('SAVE_VARIABLE', save)
    r.regions.install()
    r.regions.install()  # Reinstallation must not double-enter an invocation.
    gc._handle_ready()
    with pytest.raises(vendor.CommandError, match='Print cancellation requested'):
        gc.run_script_from_command('_UNLOCK_TOOL T=2\nM118 MUST_NOT_RUN')
    assert 'native backoff' in r.events
    assert r.events.index('_WMP_COUPLING_STROKE') < r.events.index('native backoff')
    assert r.events[-1] == 'after verified tool docking'
    assert r.saved['current_extruder'] == 99
    assert r.regions.scope is None
