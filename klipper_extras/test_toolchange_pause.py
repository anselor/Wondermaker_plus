"""Retained vendor SD/parser tests for stationary, explicit tool-change retry."""
import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from wm_material import WMMaterial

ROOT = Path(__file__).resolve().parents[1]

def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy' / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class Mutex:
    def __init__(self): self.held = False
    def __enter__(self): self.held = True
    def __exit__(self, *args): self.held = False
    def test(self): return self.held

@pytest.fixture
def job(tmp_path, monkeypatch):
    from wmp_stop_points import StopPoints
    actor = object()
    monkeypatch.setattr(StopPoints, "_current_actor", staticmethod(lambda: actor))
    gc = load('pause_retained_gcode', 'gcode.py')
    sdmod = load('pause_retained_sd', 'extras/virtual_sdcard.py')
    events, callbacks, objects = [], [], {}
    reactor = NS(NOW=0, NEVER=999999, monotonic=lambda: 1., pause=lambda when: None,
                 unregister_timer=lambda timer: None, mutex=Mutex)
    reactor.register_timer = lambda fn, when: callbacks.append(fn) or object()
    printer = NS(quick_stop_flag=False, get_start_args=lambda: {}, get_reactor=lambda: reactor,
                 register_event_handler=lambda *args: None, send_event=lambda *args: None,
                 is_shutdown=lambda: False, lookup_object=lambda name, default=None: objects.get(name, default),
                 invoke_shutdown=lambda message: pytest.fail(message))
    gcode = gc.GCodeDispatch(printer)
    objects['gcode'] = gcode
    gcode._respond_error = lambda message: events.append(('error', message))
    gcode.respond_info = lambda message: events.append(('info', message))
    gcode.respond_raw = lambda message: None
    material = WMMaterial.__new__(WMMaterial)
    material.printer, material.session_id = printer, 'session'
    objects['wm_material'] = material
    material._command_generation = 0
    material._cancellation()._print_cancel_active = lambda: False
    material._execution_evidence()._execution_command_completed = lambda boundary: events.append(('completed', boundary[2]))
    material._command_routing()._begin_explicit_physical_action = lambda action: events.append(('admit', action))
    material._material_status()._attachment = lambda now: {'state': 'attached', 'head': 'h3'}
    saved = {'fail_flag': -2, 't3_flow_extruder': 100., **{'box_modify_t%d'%i:i for i in range(4)}}
    context = {'pending': 1, 'success': 0, 'position': [120., 130., 4.], 'feedrate': 1800.,
               'absolute': True, 'absolute_e': True, 'override': 1., 'acceleration': 5000.}
    states = {'gcode_macro START_PRINT': {'print_body_ready': True},
              'gcode_macro _WMP_TOOL_RETURN_BEGIN': context, 'toolhead': {'homed_axes': 'xyz', 'extruder': 'extruder3'},
              'gcode_move': {'gcode_position': [120., 130., 4., 0.], 'homing_origin': [0.,0.,0.,0.], 'extrude_factor': 1.}, 'gcode_macro _descend_z': {'need_descend': 1}, 'save_variables': {'variables': saved}, 'wmp_recovery': {'z_reference_valid': True}}
    for name, state in states.items(): objects[name] = NS(get_status=lambda now, state=state: state)
    pause = objects['pause_resume'] = NS(is_paused=False, sd_paused=False, pause_command_sent=False)
    stats = objects['print_stats'] = NS(state='standby')
    stats.get_status = lambda now: {'state': stats.state}
    stats.note_start = lambda: setattr(stats, 'state', 'printing')
    stats.note_pause = lambda: setattr(stats, 'state', 'paused')
    stats.note_error = lambda message: setattr(stats, 'state', 'error')
    stats.note_complete = lambda: setattr(stats, 'state', 'complete')
    stats.note_cancel = lambda: setattr(stats, 'state', 'cancelled')
    path = tmp_path / 'body.gcode'
    path.write_text('T3\nG1 X130 E1\n')
    stats.filename = path.name
    sd = sdmod.VirtualSD.__new__(sdmod.VirtualSD)
    objects['virtual_sdcard'] = sd
    sd.printer, sd.gcode, sd.reactor, sd.print_stats = printer, gcode, reactor, stats
    sd.current_file = path.open()
    sd.file_position = sd.next_file_position = 0
    sd.file_size = path.stat().st_size
    sd.work_timer = object()
    sd.must_pause_work = sd.cmd_from_sd = False
    sd.on_error_gcode = NS(render=lambda: 'CANCEL_PRINT')
    gcode.register_command('CANCEL_PRINT', lambda cmd: events.append(('cancel',)))
    gcode.register_command('RESUME', lambda cmd: events.append(('stock_resume',)))
    gcode.register_command('M24', sd.cmd_M24)
    gcode.register_command('T3', lambda cmd: gcode.run_script_from_command('_WMP_TOOLCHANGE_FAULT REASON=pickup'))
    gcode.register_command('G1', lambda cmd: events.append(('extrusion',)))
    def restore_e(cmd):
        states['gcode_move']['gcode_position'] = list(states['gcode_move']['gcode_position'])[:3] + [cmd.get_float('E')]
        events.append(('restore_e', cmd.get_float('E')))
    gcode.register_command('G92', restore_e)
    gcode.register_command('M221', lambda cmd: states['gcode_move'].update(extrude_factor=cmd.get_float('S')/100.))
    def setvar(cmd):
        if cmd.get('MACRO') == '_WMP_TOOL_RETURN_BEGIN':
            context[cmd.get('VARIABLE')] = ast.literal_eval(cmd.get('VALUE'))
    gcode.register_command('SET_GCODE_VARIABLE', setvar)
    for name in ('_check_current_extruder_value', '_check_hall_sensor', '_check_tool_exist', '_CHANGING_TOOL',
                 '_CHECK_CHANGE_TOOL', '_CHECK_CHANGE_TOOL_AGAIN', '_WMP_TOOL_RETURN_FINISH', 'SAVE_VARIABLE', 'M400', 'WIPE_NOZZLE', '_WAIT_TOOL_TEMPERATURE', 'SET_HEATER_TEMPERATURE', 'TEMPERATURE_WAIT', '_WMP_CHECK_PICKUP_RELEASE'):
        gcode.register_command(name.upper(), lambda cmd: events.append(('retry', cmd.get_command())))
    material._cancel_routes_ready()
    gcode.gcode_handlers = gcode.ready_gcode_handlers
    gcode.is_printer_ready = True
    return NS(material=material, sd=sd, gcode=gcode, stats=stats, pause=pause, events=events,
              objects=objects, states=states, context=context, saved=saved, callbacks=callbacks, printer=printer)

def paused(job):
    job.sd.work_handler(1.)
    assert job.stats.state == 'paused'
    assert job.pause.is_paused and job.pause.sd_paused
    assert job.sd.current_file and not job.sd.current_file.closed
    assert job.sd.file_position == job.sd.next_file_position == 0
    assert not job.sd.is_active()
    assert not any(event[0] in ('cancel', 'retry', 'extrusion', 'completed') for event in job.events)

@pytest.mark.parametrize('command', ['RESUME', 'M24'])
def test_retained_worker_pauses_and_standard_resume_retries_exactly_once(job, command):
    paused(job)
    original = dict(job.context)
    job.context['position'] = [0., 0., 0.]
    job.gcode.run_script(command)
    assert job.context == original
    assert job.sd.file_position == 3
    assert not job.pause.is_paused
    assert job.material._toolchange_pause is None
    assert not any(event[0] == 'stock_resume' for event in job.events)
    job.callbacks[-1](2.)
    assert job.stats.state == 'complete'
    assert sum(event[0] == 'extrusion' for event in job.events) == 1
    assert sum(event == ('retry', '_CHANGING_TOOL') for event in job.events) == 1


def test_repeated_retry_failure_keeps_job_paused(job):
    paused(job)
    job.gcode.register_command('_CHANGING_TOOL', None)
    job.gcode.register_command('_CHANGING_TOOL', lambda cmd: job.material.cmd_TOOLCHANGE_FAULT(cmd))
    for _ in range(2):
        with pytest.raises(job.gcode.error, match='Print remains paused'):
            job.gcode.run_script('RESUME')
        assert job.sd.file_position == 0 and not job.sd.is_active()
        assert job.pause.is_paused and job.stats.state == 'paused'
        assert job.sd.current_file and not job.sd.current_file.closed
    assert not any(event[0] == 'extrusion' for event in job.events)

@pytest.mark.parametrize('change', ['startup', 'homing', 'shutdown', 'quick_stop', 'untyped'])
def test_unsupported_failure_keeps_existing_error_path(job, change):
    if change == 'startup': job.states['gcode_macro START_PRINT']['print_body_ready'] = False
    if change == 'homing': job.states['toolhead']['homed_axes'] = 'xy'
    if change == 'shutdown': job.printer.is_shutdown = lambda: True
    if change == 'quick_stop':
        # A vendor STOP (webhooks.py) arrives while the tool change is failing.
        def stopped(cmd):
            job.printer.quick_stop_flag = True
            job.material.cmd_TOOLCHANGE_FAULT(cmd)
        job.gcode.register_command('_WMP_TOOLCHANGE_FAULT', None)
        job.gcode.register_command('_WMP_TOOLCHANGE_FAULT', stopped)
    if change == 'untyped':
        job.gcode.register_command('T3', None)
        def ordinary(cmd): raise cmd.error('Tool change failed: same text is not classification')
        job.gcode.register_command('T3', ordinary)
    # Existing CANCEL_PRINT ingress is observed without running hardware cleanup.
    job.material._begin_print_cancel = lambda *args: job.events.append(('cancel',))
    job.stats.filename = 'body.gcode'
    job.sd.work_handler(1.)
    assert job.stats.state == 'error'
    assert not getattr(job.material, '_toolchange_pause', None)
    assert not job.pause.is_paused

@pytest.mark.parametrize('change', ['mapping', 'homing', 'owner', 'active'])
def test_retry_refuses_changed_current_context_before_motion(job, change):
    paused(job)
    if change == 'mapping': job.saved['box_modify_t3'] = 2
    if change == 'homing': job.states['toolhead']['homed_axes'] = 'xy'
    if change == 'owner': job.objects['openace'] = object()
    if change == 'active': job.sd.work_timer = object()
    with pytest.raises(job.gcode.error): job.gcode.run_script('RESUME')
    assert not any(event[0] == 'retry' for event in job.events)


def test_direct_sd_resume_cannot_skip_retry(job):
    paused(job)
    with pytest.raises(job.gcode.error, match='use Resume'):
        job.sd.do_resume()
    assert not job.sd.is_active() and job.sd.file_position == 0


def test_new_file_does_not_inherit_historical_fault(job, tmp_path):
    paused(job)
    job.sd.current_file.close()
    new = tmp_path / 'new.gcode'
    new.write_text('G1 E2\n')
    job.sd.current_file = new.open()
    job.stats.filename = new.name
    assert job.material._toolchange_pause_status() == {}
    job.gcode.run_script('M24')
    assert job.sd.is_active()


def test_cancel_during_retry_cannot_dispatch_return_or_resume(job):
    paused(job)
    job.gcode.register_command('_CHANGING_TOOL', None)
    def cancel(cmd):
        job.material._command_generation += 1
    job.gcode.register_command('_CHANGING_TOOL', cancel)
    with pytest.raises(job.gcode.error, match='interrupted'):
        job.gcode.run_script('RESUME')
    assert not job.sd.is_active() and job.sd.file_position == 0
    assert not any(event == ('retry', '_WMP_TOOL_RETURN_FINISH') for event in job.events)


def test_resume_reheats_saved_targets_after_idle_timeout(job):
    targets = {'heater_bed': {'target': 60.}, 'extruder3': {'target': 210.}}
    for name, state in targets.items():
        job.objects[name] = NS(get_status=lambda now, state=state: state)
    paused(job)
    for state in targets.values(): state['target'] = 0.
    writes = []
    job.gcode.register_command('SET_HEATER_TEMPERATURE', None)
    job.gcode.register_command('SET_HEATER_TEMPERATURE', lambda cmd: writes.append((cmd.get('HEATER'), cmd.get_float('TARGET'))))
    job.gcode.run_script('RESUME')
    assert writes == [('heater_bed', 60.), ('extruder3', 210.)]
    assert not job.pause.is_paused and job.sd.file_position == 3


def test_resume_schedule_failure_does_not_replay_completed_toolchange(job):
    paused(job)
    original = job.sd.reactor.register_timer
    job.sd.reactor.register_timer = lambda *args: (_ for _ in ()).throw(ValueError('timer unavailable'))
    with pytest.raises(job.gcode.error, match='Tool change complete'):
        job.gcode.run_script('RESUME')
    assert job.material._toolchange_pause['state'] == 'ready'
    assert job.sd.file_position == 3 and job.pause.is_paused
    assert sum(event == ('retry', 'WIPE_NOZZLE') for event in job.events) == 1
    before = list(job.events)
    job.sd.reactor.register_timer = original
    job.gcode.run_script('RESUME')
    assert job.events == before
    job.callbacks[-1](2.)
    assert sum(event[0] == 'extrusion' for event in job.events) == 1


def test_error_after_wipe_does_not_repeat_completed_wipe(job):
    paused(job)
    job.gcode.register_command('_WMP_TOOL_RETURN_FINISH', None)
    def fail(cmd): raise cmd.error('return interrupted')
    job.gcode.register_command('_WMP_TOOL_RETURN_FINISH', fail)
    with pytest.raises(job.gcode.error, match='return interrupted'):
        job.gcode.run_script('RESUME')
    job.gcode.register_command('_WMP_TOOL_RETURN_FINISH', None)
    job.gcode.register_command('_WMP_TOOL_RETURN_FINISH', lambda cmd: None)
    job.gcode.run_script('RESUME')
    assert sum(event == ('retry', 'WIPE_NOZZLE') for event in job.events) == 1


def test_changed_position_after_scheduling_failure_has_explicit_retry_exit(job):
    paused(job)
    original = job.sd.reactor.register_timer
    job.sd.reactor.register_timer = lambda *args: (_ for _ in ()).throw(ValueError('timer unavailable'))
    with pytest.raises(job.gcode.error): job.gcode.run_script('RESUME')
    job.states['gcode_move']['gcode_position'][0] += 10
    job.sd.reactor.register_timer = original
    with pytest.raises(job.gcode.error, match='Resume again'):
        job.gcode.run_script('RESUME')
    assert job.material._toolchange_pause['state'] == 'paused'
    assert job.sd.file_position == 0
    job.gcode.run_script('RESUME')
    assert job.sd.is_active()
    assert sum(event == ('retry', 'WIPE_NOZZLE') for event in job.events) == 1

@pytest.fixture
def clearance_job(job):
    """Retained SD/dispatcher executes real BEGIN/FINISH Jinja; only hardware stubbed."""
    import copy, re, jinja2
    from collections import namedtuple
    Coord = namedtuple('Coord', 'x y z e', defaults=(0.,))
    text = (ROOT / 'config/live/change_macros.cfg').read_text()
    env = jinja2.Environment('{%', '%}', '{', '}', undefined=jinja2.StrictUndefined)
    templates = {}
    for name in ('T3', '_CHANGE_TOOL', '_WMP_TOOL_RETURN_BEGIN', '_WMP_TOOL_RETURN_FINISH', '_WMP_XY_TRAVEL'):
        body = text.split('[gcode_macro '+name+']',1)[1].split('[gcode_macro ',1)[0]
        code = re.search(r'(?m)^gcode:\s*\n([\s\S]*)', body)[1]
        templates[name] = env.from_string('\n'.join(line.split('#',1)[0] for line in code.splitlines()))
    gm = job.states['gcode_move']
    gm.update(speed=1700.,speed_factor=.7,absolute_coordinates=False,absolute_extrude=False,
              homing_origin=Coord(0,0,0),position=Coord(120,130,4),gcode_position=Coord(120,130,4))
    th = job.states['toolhead'];th.update(max_accel=1234.,position=Coord(120,130,4),axis_maximum=Coord(300,300,5))
    job.states['gcode_macro _CHANGE_TOOL'] = {'save_position':1}
    job.states['wm_material'] = {'session_id':'session', 'command_generation':0}
    job.states['configfile'] = {'settings':{'printer':{'max_accel':5000., 'max_velocity':600.}}}
    job.context.update(pending=0)
    job.states['gcode_macro _WMP_XY_TRAVEL']={'travel_speed':300.,'hot_travel_speed':500.}
    job.saved.update(fail_flag=0,current_extruder=2,probe_tool=0,t0_offset=[0,0,0],t3_offset=[0,0,0])
    job.material._attachment=lambda now:{'state':'attached','head':'h%d'%job.saved['current_extruder']}
    def macro(cmd):
        snapshot=copy.deepcopy(job.states)
        snapshot['print_stats']={'state':job.stats.state}
        snapshot['pause_resume']={'is_paused':job.pause.is_paused}
        snapshot['wm_material']['command_generation']=job.material._command_generation
        def error(message):raise cmd.error(message)
        script=templates[cmd.get_command()].render(printer=snapshot,params=cmd.get_command_parameters(),action_raise_error=error, **snapshot.get('gcode_macro '+cmd.get_command(),{}))
        job.gcode.run_script_from_command(script)
    def register(name,fn):
        job.gcode.register_command(name,None);job.gcode.register_command(name,fn)
    for name in templates:register(name,macro)
    def setvar(cmd):
        job.states.setdefault('gcode_macro '+cmd.get('MACRO'),{})[cmd.get('VARIABLE')]=ast.literal_eval(cmd.get('VALUE'))
    # Retained spelling for descend and macro uppercasing are both exposed.
    job.states['gcode_macro _DESCEND_Z']=job.states['gcode_macro _descend_z']
    register('SET_GCODE_VARIABLE',setvar)
    def save(cmd):job.saved[cmd.get('VARIABLE')]=ast.literal_eval(cmd.get('VALUE'))
    register('SAVE_VARIABLE',save)
    def couple(cmd):
        job.events.append(('pickup',))
        job.saved['current_extruder']=3
    register('_CHANGING_TOOL',couple)
    def checked(cmd):
        if cmd.get('SKIP_WIPE','0')!='1':job.gcode.run_script_from_command('WIPE_NOZZLE')
        job.context['success']=1
    register('_CHECK_CHANGE_TOOL',checked)
    def move(cmd):
        if cmd.get('E',None) is not None:job.events.append(('extrusion',));return
        pos=list(gm['gcode_position'])
        for n,axis in enumerate('XYZ'):
            if cmd.get(axis,None) is not None:pos[n]=float(cmd.get(axis))
        gm['gcode_position']=Coord(*pos);gm['position']=Coord(*pos);th['position']=Coord(*pos)
        if cmd.get('F',None) is not None:gm['speed']=float(cmd.get('F'))
        job.events.append(('return_move',tuple(pos)))
    register('G1',move)
    register('G0',move)
    register('M220',lambda cmd:gm.update(speed_factor=float(cmd.get('S'))/100))
    register('SET_VELOCITY_LIMIT',lambda cmd:th.update(max_accel=float(cmd.get('ACCEL'))))
    for name,key,value in [('G90','absolute_coordinates',True),('G91','absolute_coordinates',False),('M82','absolute_extrude',True),('M83','absolute_extrude',False)]:
        register(name,lambda cmd,key=key,value=value:gm.update({key:value}))
    job.register=register;job.Coord=Coord
    return job


def clearance_paused(job):
    job.sd.work_handler(1.)
    assert job.stats.state=='paused' and job.pause.is_paused and job.pause.sd_paused
    assert job.sd.current_file and not job.sd.current_file.closed
    assert job.sd.file_position==job.sd.next_file_position==0 and not job.sd.is_active()
    assert not any(e[0] in ('cancel','extrusion','completed') for e in job.events)


def test_clearance_begin_repeated_pause_then_real_paused_begin_and_exact_suffix(clearance_job):
    j=clearance_job;clearance_paused(j)
    assert j.material._toolchange_pause['stage']=='begin'
    assert j.context['pending']==0
    assert not any(e[0] in ('pickup','return_move') for e in j.events)
    for _ in range(2):
        with pytest.raises(j.gcode.error,match='Insufficient Z travel'):j.gcode.run_script('RESUME')
        assert j.stats.state=='paused' and j.sd.file_position==0
        assert not any(e[0]=='pickup' for e in j.events)
    j.states['toolhead']['axis_maximum']=j.Coord(300,300,330)
    j.gcode.run_script('RESUME')
    assert j.saved['current_extruder_backup']==3 and j.saved['fail_tool']==2
    assert sum(e[0]=='pickup' for e in j.events)==1
    gm=j.states['gcode_move']
    assert gm['gcode_position']==j.Coord(120,130,4)
    assert (gm['speed'],gm['speed_factor'],gm['absolute_coordinates'],gm['absolute_extrude'])==(1700.,.7,False,False)
    j.callbacks[-1](2.)
    assert j.stats.state=='complete' and sum(e[0]=='extrusion' for e in j.events)==1


def test_clearance_return_retries_only_return_and_retains_parser(clearance_job):
    j=clearance_job;j.states['toolhead']['axis_maximum']=j.Coord(300,300,330)
    def wipe(cmd):
        j.events.append(('wipe',));j.states['toolhead']['axis_maximum']=j.Coord(300,300,5)
    j.register('WIPE_NOZZLE',wipe)
    clearance_paused(j)
    assert j.material._toolchange_pause['stage']=='return'
    assert sum(e[0]=='pickup' for e in j.events)==sum(e[0]=='wipe' for e in j.events)==1
    for _ in range(2):
        with pytest.raises(j.gcode.error,match='Insufficient Z travel'):j.gcode.run_script('RESUME')
    j.states['toolhead']['axis_maximum']=j.Coord(300,300,330)
    j.gcode.run_script('RESUME');j.callbacks[-1](2.)
    assert j.stats.state=='complete'
    assert sum(e[0]=='pickup' for e in j.events)==sum(e[0]=='wipe' for e in j.events)==1
    assert any(e==('retry','_WAIT_TOOL_TEMPERATURE') for e in j.events)
    assert j.states['gcode_move']['speed_factor']==.7
    assert not j.states['gcode_move']['absolute_coordinates']


@pytest.mark.parametrize('interruption',['cancel','shutdown'])
def test_clearance_begin_no_effects_after_interruption(clearance_job,interruption):
    j=clearance_job;clearance_paused(j)
    j.states['toolhead']['axis_maximum']=j.Coord(300,300,330)
    if interruption=='shutdown':j.printer.is_shutdown=lambda:True
    elif interruption=='cancel':j.material._print_cancel_active=lambda:True
    else:j.states['gcode_move']['gcode_position']=j.Coord(100,130,4)
    with pytest.raises(j.gcode.error):j.gcode.run_script('RESUME')
    assert not any(e[0] in ('pickup','return_move') for e in j.events)
    assert j.sd.file_position==0


def test_clearance_return_scheduling_failure_never_replays_pickup_or_wipe(clearance_job):
    j=clearance_job;j.states['toolhead']['axis_maximum']=j.Coord(300,300,330)
    def wipe(cmd):
        j.events.append(('wipe',));j.states['toolhead']['axis_maximum']=j.Coord(300,300,5)
    j.register('WIPE_NOZZLE',wipe);clearance_paused(j)
    j.states['toolhead']['axis_maximum']=j.Coord(300,300,330)
    original=j.sd.do_resume
    def fail():raise ValueError('scheduling unavailable')
    j.sd.do_resume=fail
    with pytest.raises(j.gcode.error,match='Tool change complete'):j.gcode.run_script('RESUME')
    assert j.material._toolchange_pause['state']=='ready'
    assert j.material._toolchange_pause['stage']=='return'
    j.sd.do_resume=original
    j.gcode.run_script('RESUME');j.callbacks[-1](2.)
    assert j.stats.state=='complete'
    assert sum(e[0]=='pickup' for e in j.events)==sum(e[0]=='wipe' for e in j.events)==1


@pytest.mark.parametrize('interruption',['shutdown','cancel'])
def test_clearance_return_interruption_cannot_emit_return(clearance_job,interruption):
    j=clearance_job;j.states['toolhead']['axis_maximum']=j.Coord(300,300,330)
    def wipe(cmd):j.states['toolhead']['axis_maximum']=j.Coord(300,300,5)
    j.register('WIPE_NOZZLE',wipe);clearance_paused(j)
    j.states['toolhead']['axis_maximum']=j.Coord(300,300,330)
    if interruption=='shutdown':j.printer.is_shutdown=lambda:True
    else:j.material._print_cancel_active=lambda:True
    with pytest.raises(j.gcode.error):j.gcode.run_script('RESUME')
    assert not any(e[0]=='return_move' for e in j.events)
    assert j.sd.file_position==0


def test_clearance_begin_rechecks_when_target_mounted_while_paused(clearance_job):
    j=clearance_job;clearance_paused(j);j.saved['current_extruder']=3
    with pytest.raises(j.gcode.error,match='Insufficient Z travel'):j.gcode.run_script('RESUME')
    assert not any(e[0] in ('pickup','return_move') for e in j.events)


def test_clearance_begin_inspection_jog_does_not_replace_print_origin(clearance_job):
    j=clearance_job;clearance_paused(j)
    gm=j.states['gcode_move'];th=j.states['toolhead']
    gm['gcode_position']=gm['position']=th['position']=j.Coord(100,140,3)
    th['axis_maximum']=j.Coord(300,300,330)
    j.gcode.run_script('RESUME')
    assert gm['gcode_position']==j.Coord(120,130,4)
    assert gm['speed_factor']==.7 and not gm['absolute_coordinates']
    j.callbacks[-1](2.)
    assert j.stats.state=='complete'


def test_begin_retry_advances_to_return_only_if_later_clearance_fails(clearance_job):
    j=clearance_job;clearance_paused(j)
    j.states['toolhead']['axis_maximum']=j.Coord(300,300,330)
    def wipe(cmd):
        j.events.append(('wipe',));j.states['toolhead']['axis_maximum']=j.Coord(300,300,5)
    j.register('WIPE_NOZZLE',wipe)
    with pytest.raises(j.gcode.error,match='Insufficient Z travel for print return'):j.gcode.run_script('RESUME')
    assert j.material._toolchange_pause['stage']=='return'
    assert j.material._toolchange_pause['context']['success']==1
    j.states['toolhead']['axis_maximum']=j.Coord(300,300,330)
    j.gcode.run_script('RESUME');j.callbacks[-1](2.)
    assert j.stats.state=='complete'
    assert sum(e[0]=='pickup' for e in j.events)==sum(e[0]=='wipe' for e in j.events)==1


def test_fault_pause_manual_e_restored_without_replaying_or_parking(job):
    job.states['gcode_move']['gcode_position'][3] = 27.5
    paused(job)
    before = list(job.context['position'])
    job.states['gcode_move']['gcode_position'][3] = 92.
    job.gcode.run_script('RESUME')
    assert job.states['gcode_move']['gcode_position'][3] == 27.5
    assert ('restore_e', 27.5) in job.events
    assert job.context['position'] == before
    assert not any('PAUSEPARK' in str(event) or 'SAVE_GCODE_STATE' in str(event) for event in job.events)
    assert sum(event == ('retry', '_CHANGING_TOOL') for event in job.events) == 1


@pytest.mark.parametrize('state', ['pending', 'running', 'unknown', 'failed'])
def test_fault_pause_resume_uses_live_service_ownership_not_history(job, state):
    paused(job)
    job.material.filament_operation = {'state': state}
    if state in ('pending', 'running'):
        with pytest.raises(job.gcode.error, match='running filament operation'):
            job.gcode.run_script('RESUME')
        assert not any(event == ('retry', '_CHANGING_TOOL') for event in job.events)
    else:
        job.gcode.run_script('RESUME')
        assert job.sd.is_active()


def test_fault_service_unload_requires_present_reload_then_resumes(job):
    paused(job)
    record = job.material._toolchange_pause
    record['service_required'].add('h3')
    job.material._loaded_filament_status = lambda now: {'h3': {'state': 'empty'}}
    with pytest.raises(job.gcode.error, match='Load or check filament in Head 4'):
        job.gcode.run_script('RESUME')
    assert job.sd.file_position == 0 and job.pause.is_paused
    # An explicit load/check can resolve physical evidence even if an old
    # interrupted receipt remains unknown; no restart/secret reset is needed.
    job.material.filament_operation = {'state': 'unknown'}
    job.material._loaded_filament_status = lambda now: {'h3': {'state': 'loaded'}}
    job.gcode.run_script('RESUME')
    assert job.sd.is_active()


def test_fault_service_ready_retry_corrects_manual_e_without_second_pickup(job):
    job.states['gcode_move']['gcode_position'][3] = 17.
    paused(job)
    register = job.sd.reactor.register_timer
    job.sd.reactor.register_timer = lambda *args: (_ for _ in ()).throw(ValueError('timer unavailable'))
    with pytest.raises(job.gcode.error, match='Tool change complete'):
        job.gcode.run_script('RESUME')
    job.states['gcode_move']['gcode_position'][3] = 57.
    job.sd.reactor.register_timer = register
    job.gcode.run_script('RESUME')
    assert job.states['gcode_move']['gcode_position'][3] == 17.
    assert sum(event == ('retry', '_CHANGING_TOOL') for event in job.events) == 1
    assert sum(event == ('retry', 'WIPE_NOZZLE') for event in job.events) == 1


@pytest.mark.parametrize('initial_head', ['extruder2', 'extruder3'])
@pytest.mark.parametrize('stage', ['coupling', 'return'])
@pytest.mark.parametrize('manual_switch', [False, True])
def test_fault_retry_matches_uninterrupted_retained_extrusion_coordinates(job, initial_head, stage, manual_switch):
    """Use actual vendor M221/ACTIVATE callback/G92, not a no-op E fixture."""
    module = load('fault_retained_gcode_move', 'extras/gcode_move.py')
    def parser():
        gm = module.GCodeMove.__new__(module.GCodeMove)
        gm.Coord = job.gcode.Coord
        gm.printer = job.printer
        gm.is_printer_ready = True
        gm.base_position = [0., 0., 0., 8.]
        gm.last_position = [120., 130., 4., 42.]
        gm.homing_position = [0., 0., 0., 0.]
        gm.absolute_coord = gm.absolute_extrude = True
        gm.speed, gm.speed_factor, gm.extrude_factor = 25., 1./60., .8
        gm.saved_states = {}
        gm.position_with_transform = lambda: list(gm.last_position)
        return gm
    def command(name, **params):
        return job.gcode.create_gcode_command(name, name, {key: str(value) for key, value in params.items()})
    def stock_success(gm, active):
        gm.cmd_M221(command('M221', S=93))
        if active != 'extruder3':
            # Exact retained ACTIVATE event; target extruder carries its own
            # physical E position, which is unrelated to the old parser E.
            gm.last_position[3] = 107.
            gm._handle_activate_extruder()
        return 'extruder3'
    baseline = parser()
    stock_success(baseline, initial_head)
    expected = baseline.get_status()
    live = parser()
    job.objects['gcode_move'] = live
    job.states['toolhead']['extruder'] = initial_head
    job.saved['t3_flow_extruder'] = 93.
    job.gcode.register_command('M221', None)
    job.gcode.register_command('M221', live.cmd_M221)
    job.gcode.register_command('G92', None)
    job.gcode.register_command('G92', live.cmd_G92)
    def checked(cmd):
        job.states['toolhead']['extruder'] = stock_success(live, job.states['toolhead']['extruder'])
        job.events.append(('stock_checked',))
    job.gcode.register_command('_CHECK_CHANGE_TOOL', None)
    job.gcode.register_command('_CHECK_CHANGE_TOOL', checked)
    if stage == 'return':
        checked(None)
        job.gcode.register_command('T3', None)
        job.gcode.register_command('T3', lambda cmd: job.gcode.run_script_from_command(
            '_WMP_TOOLCHANGE_FAULT STAGE=return REQUIRED=10 MAXIMUM=5'))
    paused(job)
    original_return = list(job.material._toolchange_pause['context']['position'])
    if manual_switch:
        job.states['toolhead']['extruder'] = 'extruder2'
        live.last_position[3] = 301.
        live._handle_activate_extruder()
        if stage == 'return':
            # Repair restores the completed target; retry must not recouple it.
            job.states['toolhead']['extruder'] = 'extruder3'
            live.last_position[3] = 107.
            live._handle_activate_extruder()
    live.cmd_M221(command('M221', S=120))
    live.cmd_G92(command('G92', E=999))
    job.gcode.run_script('RESUME')
    actual = live.get_status()
    assert actual['gcode_position'][3] == pytest.approx(expected['gcode_position'][3])
    assert actual['extrude_factor'] == pytest.approx(expected['extrude_factor'])
    assert original_return == job.context['position']
    assert sum(event == ('stock_checked',) for event in job.events) == 1
    assert job.sd.is_active()


def test_resume_checks_final_pickup_identity_after_wipe_before_print_return(job):
    paused(job)
    job.gcode.run_script('RESUME')
    commands = [event[1] for event in job.events if event[0] == 'retry']
    assert commands.index('WIPE_NOZZLE') < commands.index('_WMP_CHECK_PICKUP_RELEASE') < commands.index('_WMP_TOOL_RETURN_FINISH')
    assert not job.pause.is_paused and job.sd.is_active()
