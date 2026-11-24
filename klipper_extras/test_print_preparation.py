"""Preparation progress is informational; chamber holds honor the live inputs."""
from types import SimpleNamespace as NS
import copy
import pytest
from wmp_print_preparation import PrintPreparation


class Command:
    error = ValueError
    def __init__(self, **values): self.values = values
    def get(self, key, default=None): return self.values.get(key, default)
    def get_float(self, key, default=None, minval=None):
        value = float(self.get(key, default))
        if minval is not None and value < minval: raise self.error(key + ' is below minimum')
        return value


@pytest.fixture
def preparation():
    clock, observations, calls, objects = [0.], [], [], {}
    stats = {'state':'printing', 'filename':'example.gcode'}
    sd = NS(current_file=object())
    door = lambda: 'PRESSED'
    temperatures = {'chamber':lambda:45., 'bed':lambda:60.}
    objects.update(print_stats=NS(get_status=lambda now:dict(stats)), virtual_sdcard=sd)
    for i in (1,2): objects['gcode_button Door_button%d'%i] = NS(get_status=lambda now:{'state':door()})
    objects['heaters'] = NS(lookup_heater=lambda name:NS(get_temp=lambda now:(temperatures['chamber' if name=='chamber' else 'bed'](),45.)))
    objects['gcode'] = NS(run_script_from_command=calls.append)
    def pause(deadline):
        observations.append(copy.deepcopy(feature.state))
        clock[0] = deadline
    printer = NS(lookup_object=lambda name,default=None:objects.get(name,default),
                 get_reactor=lambda:NS(monotonic=lambda:clock[0],pause=pause),
                 is_shutdown=lambda:False, quick_stop_flag=False)
    material = NS(printer=printer, _print_cancel_active=lambda:False)
    feature = PrintPreparation(material)
    return NS(feature=feature,clock=clock,observations=observations,calls=calls,objects=objects,
              stats=stats,sd=sd,temperatures=temperatures,material=material,
              open_door=lambda fn:None)


def test_progress_reads_do_not_change_state_or_hold_machine(preparation):
    v=preparation; f=v.feature
    assert f.get_status(0)=={}
    f.cmd_BEGIN(Command(CHAMBER=0))
    before=copy.deepcopy(f.state)
    assert f.get_status(0)['active']
    assert f.state==before and not v.calls
    assert 'chamber' not in [step['phase'] for step in f.state['steps']]
    f.cmd_STAGE(Command(PHASE='homing'));assert f.get_status(0)['phase']=='homing'
    f.cmd_STAGE(Command(PHASE='printing'));assert not f.get_status(0)['active']
    assert not v.calls


def test_old_attempt_is_not_shown_for_new_print_of_same_filename(preparation):
    v=preparation;v.feature.cmd_BEGIN(Command())
    v.sd.current_file=object()
    assert not v.feature.get_status(0)['active']
    v.feature.cmd_BEGIN(Command());assert v.feature.get_status(0)['active']


def test_chamber_hold_finishes_after_continuous_stability(preparation):
    v=preparation;v.feature.cmd_BEGIN(Command(CHAMBER=45))
    v.feature.cmd_WAIT_CHAMBER(Command(TARGET=45,BED=60,HOLD=2))
    assert v.clock[0]==2 and v.feature.state['hold_remaining']==0
    assert not v.calls


@pytest.mark.parametrize('source',['chamber','bed','door'])
def test_temperature_or_door_change_restarts_stability_hold(preparation,source):
    v=preparation;v.feature.cmd_BEGIN(Command(CHAMBER=45))
    if source=='door':
        v.objects['gcode_button Door_button1'].get_status=lambda now:{'state':'RELEASED' if 1<=v.clock[0]<1.5 else 'PRESSED'}
    else:
        expected=45 if source=='chamber' else 60
        v.temperatures[source]=lambda: expected+5 if 1<=v.clock[0]<1.5 else expected
    v.feature.cmd_WAIT_CHAMBER(Command(TARGET=45,BED=60,HOLD=2))
    assert v.clock[0]==3.5
    if source=='door':assert any('Close the doors' in row['instruction'] for row in v.observations)


def test_existing_cancel_request_exits_wait_without_creating_a_hold(preparation):
    v=preparation;v.feature.cmd_BEGIN(Command(CHAMBER=45))
    v.material._print_cancel_active=lambda:v.clock[0]>=1
    with pytest.raises(ValueError,match='Print cancelled'):
        v.feature.cmd_WAIT_CHAMBER(Command(TARGET=45,BED=60,HOLD=60))
    v.stats['state']='cancelled'
    assert not v.feature.get_status(1)['active']
    assert not v.calls


def test_safe_cancel_branch_consumes_its_own_stop_request(preparation):
    v=preparation;v.material.stop_requested=lambda:{'scope':'print'}
    def stop(*details):v.calls.append(details);raise ValueError('stopped at existing stop point')
    v.material.check_stop_point=stop
    with pytest.raises(ValueError,match='existing stop point'):
        v.feature.cmd_WAIT_CHAMBER(Command(TARGET=45))
    assert v.calls==[('chamber_preparation', 'during chamber preparation',
                      'homed; chamber temperature stabilization interrupted')]


def test_incomplete_door_configuration_is_visible_not_a_hidden_blocker(preparation):
    v=preparation;v.objects.pop('gcode_button Door_button1');v.objects.pop('gcode_button Door_button2')
    v.feature.cmd_WAIT_CHAMBER(Command(TARGET=45,HOLD=0))
    assert 'door sensing is incomplete' in v.feature.state['note']
    assert not v.feature.get_status(0).get('active',False)


@pytest.mark.parametrize('field',['TARGET','BED','HOLD'])
def test_invalid_wait_numbers_are_explicit_errors(preparation,field):
    values={'TARGET':45,'BED':60,'HOLD':0,field:float('nan')}
    with pytest.raises(ValueError,match='finite'):
        preparation.feature.cmd_WAIT_CHAMBER(Command(**values))


def test_zero_chamber_target_does_not_add_a_wait(preparation):
    v=preparation
    v.feature.cmd_WAIT_CHAMBER(Command(TARGET=0))
    assert v.clock[0]==0 and v.feature.state=={} and v.calls==[]


def test_progress_labels_describe_head_mounting_before_mesh(preparation):
    v=preparation;v.feature.cmd_BEGIN(Command(CHAMBER=0))
    steps=v.feature.get_status(0)['steps']
    labels={row['phase']:row['label'] for row in steps}
    assert 'Mount head' in labels['homing']
    assert 'mounting' not in labels
    assert [row['phase'] for row in steps].index('homing') < [row['phase'] for row in steps].index('mesh')


def test_chamber_values_do_not_need_a_repeated_step_title(preparation):
    v=preparation;v.feature.cmd_BEGIN(Command(CHAMBER=45))
    v.feature.cmd_WAIT_CHAMBER(Command(TARGET=45,BED=60,HOLD=1))
    assert all(row['instruction']=='' for row in v.observations)



def test_mesh_progress_counts_points_without_mutating_probe_session(preparation):
    v=preparation;v.feature.cmd_BEGIN(Command());v.feature.cmd_STAGE(Command(PHASE='mesh'))
    points=[(x,y) for x in range(6) for y in range(6)]
    session=NS(multi_probe_pending=True,results=[(0,0,0)]*6)
    v.objects['bed_mesh']=NS(bmc=NS(probe_mgr=NS(probe_helper=NS(probe_points=points))))
    v.objects['probe']=NS(probe_session=session)
    assert v.feature.get_status(0)['mesh_progress']=={'point':7,'total':36}
    assert len(session.results)==6 and not v.calls
    session.multi_probe_pending=False
    assert 'mesh_progress' not in v.feature.get_status(0)


def test_heating_progress_contains_live_bed_temperature(preparation):
    v=preparation;v.feature.cmd_BEGIN(Command());v.feature.cmd_STAGE(Command(PHASE='bed'))
    v.objects['heater_bed']=NS(get_status=lambda now:{'temperature':43.5,'target':60.})
    assert v.feature.get_status(0)['temperatures']['bed']=={'actual':43.5,'target':60.}


def test_file_scan_progress_is_visible_before_preheat_and_bound_to_sd_attempt(preparation):
    v = preparation
    attempt = v.feature.begin_file_scan('example.gcode', 200)
    assert attempt and v.feature.get_status(0)['phase'] == 'file'
    v.feature.file_scan_progress(attempt, 80)
    assert v.feature.get_status(0)['file_progress'] == {'bytes': 80, 'total': 200}
    assert not v.calls
    v.sd.current_file = object()
    assert not v.feature.get_status(0)['active']
    v.feature.cmd_BEGIN(Command())
    v.feature.file_scan_progress(attempt, 200)
    assert v.feature.get_status(0)['phase'] == 'preheat'
    assert 'file_progress' not in v.feature.get_status(0)


@pytest.mark.parametrize('state,filename,has_stream', [
    ('complete', 'example.gcode', True),
    ('printing', 'previous.gcode', True),
    ('printing', 'example.gcode', False),
])
def test_pre_dispatch_file_scan_never_borrows_previous_print(preparation, state, filename, has_stream):
    v = preparation
    v.stats.update(state=state, filename=filename)
    if not has_stream:
        v.sd.current_file = None
    assert v.feature.begin_file_scan('example.gcode', 200) is None
    assert v.feature.get_status(0) == {}


def test_pending_file_progress_continues_into_the_actual_sd_preparation(preparation):
    v = preparation
    v.stats.update(state='complete', filename='previous.gcode')
    v.sd.current_file = None
    v.sd.is_active = lambda: False
    v.material.session_id = 'session'
    v.material.print_submission = {'id': 'print_1', 'session': 'session', 'file': 'example.gcode', 'state': 'pending'}
    attempt = v.feature.begin_submission(v.material.print_submission, 200)
    assert v.feature.get_status(0)['active']
    v.feature.file_scan_progress(attempt, 160)
    assert v.feature.get_status(0)['file_progress']['bytes'] == 160
    v.material.print_submission['state'] = 'not_started'
    assert not v.feature.get_status(0)['active']
    v.material.print_submission['state'] = 'submitted'
    v.stats.update(state='printing', filename='example.gcode')
    v.sd.current_file = object()
    v.feature.bind_dispatched_submission(v.material.print_submission)
    assert v.feature.get_status(0)['active']
    v.feature.cmd_BEGIN(Command())
    progress = v.feature.get_status(0)
    assert progress['id'] == attempt and progress['active'] and progress['phase'] == 'preheat'
    assert [step['phase'] for step in progress['steps']][:2] == ['file', 'preheat']
    v.feature.file_scan_progress(attempt, 200)
    assert 'file_progress' not in v.feature.get_status(0)
