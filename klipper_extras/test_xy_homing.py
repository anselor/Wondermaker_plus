from types import SimpleNamespace as NS
import pytest
from wmp_xy_homing import XYHoming


@pytest.fixture
def rig():
    calls=[];position=[120.,90.,42.,7.];limits=[(-15,312),(-3,350),(0,305)]
    material=NS(_command_generation=1)
    sensor={'stuck':False};travels=[3.4625,4.98,5.01]
    class Rail:
        def __init__(self,name,positive):self.name=name;self.positive=positive
        def get_name(self):return self.name
        def get_range(self):return (-15,312) if self.positive else (-3,350)
        def get_homing_info(self):return NS(positive_dir=self.positive,position_endstop=308. if self.positive else 0.,speed=50.,second_homing_speed=25.,retract_speed=40.)
        def get_endstops(self):return [(NS(query_endstop=lambda t:sensor['stuck']),'y')]
    kin=NS(rails=[Rail('stepper_x',True),Rail('stepper_y',False)],limits=limits)
    def move(p,speed):calls.append(('move',list(p)));position[:]=p
    def set_position(p,**kwargs):calls.append(('set',list(p)));position[:]=p
    th=NS(get_kinematics=lambda:kin,get_position=lambda:list(position),move=move,set_position=set_position,wait_moves=lambda:None,dwell=lambda t:None,get_last_move_time=lambda:0.)
    def native(cmd):
        axis=next(iter(cmd));calls.append(('home',axis));position['XYZ'.index(axis)]=308. if axis=='X' else 0.
    gcode=NS(register_command=lambda *a,**k:None,create_gcode_command=lambda c,s,p:p,quick_stop_flag=False)
    objects={'gcode':gcode,'toolhead':th,'homing':NS(cmd_G28=native),'wm_material':material}
    printer=NS(lookup_object=lambda n,default=None:objects.get(n,default),is_shutdown=lambda:False,send_event=lambda *a:calls.append(('event',a[0])))
    class State:
        def __init__(self,p):pass
        def set_axes(self,a):assert a==[1]
    class HomingMove:
        def __init__(self,p,e):self.stepper_positions=[]
        def homing_move(self,target,speed):
            calls.append(('tap',position[0],speed));travel=travels.pop(0)
            self.stepper_positions=[NS(stepper_name=n,start_pos=0,trig_pos=d,stepper=NS(get_step_dist=lambda:1.)) for n,d in [('stepper_x',-travel),('stepper_y',travel)]]
            position[:]=target
        def check_no_movement(self):return None
    cmd=NS(error=ValueError,respond_info=lambda text:calls.append(('report',text)))
    return NS(helper=XYHoming(printer),cmd=cmd,State=State,Move=HomingMove,calls=calls,position=position,limits=limits,sensor=sensor,travels=travels,material=material,objects=objects)


def execute(r):r.helper._home(r.cmd,r.State,r.Move)


def test_fixed_corner_sequence_discards_coarse_y_and_never_moves_z(rig):
    execute(rig)
    significant=[c[:2] for c in rig.calls if c[0] in ('home','tap')]
    assert significant==[('home','Y'),('home','X'),('tap',298.),('tap',298.),('tap',298.)]
    assert rig.position==[298.,0.,42.,7.]
    assert [c[1][1] for c in rig.calls if c[0]=='move'][1:]==[5.,5.,5.]
    assert all(c[1][2:]==[42.,7.] for c in rig.calls if c[0] in ('move','set'))
    assert all(c[2]==25. for c in rig.calls if c[0]=='tap')


def test_stuck_sensor_stops_before_final_approach_and_invalidates_y(rig):
    rig.sensor['stuck']=True
    with pytest.raises(ValueError,match='remained triggered'):execute(rig)
    assert not any(c[0]=='tap' for c in rig.calls)
    assert rig.limits[1]==(1.,-1.)


@pytest.mark.parametrize('travel',[0.,.1,3.9,6.1,10.])
def test_bad_contact_distance_stops_without_accepting_home(rig,travel):
    rig.travels[:]=[3.4625,travel,5.]
    with pytest.raises(ValueError,match='confirmation travelled|no valid movement'):execute(rig)
    assert len([c for c in rig.calls if c[0]=='tap'])==2
    assert rig.limits[1]==(1.,-1.)


def test_disagreeing_contacts_are_not_accepted(rig):
    rig.travels[:]=[3.4625,4.5,5.]
    with pytest.raises(ValueError,match='repeat contacts differ'):execute(rig)
    assert rig.limits[1]==(1.,-1.)


def test_vendor_quick_stop_between_coarse_y_and_x_prevents_further_motion(rig):
    def native(cmd):
        rig.calls.append(('home',next(iter(cmd))))
        rig.helper.printer.quick_stop_flag=True
    rig.objects['homing'].cmd_G28=native
    with pytest.raises(ValueError,match='interrupted'):execute(rig)
    assert [c for c in rig.calls if c[0]=='home']==[('home','Y')]
    assert not any(c[0] in ('move','tap') for c in rig.calls)
def test_cancel_between_coarse_y_and_x_prevents_further_motion(rig):
    def native(cmd):
        rig.calls.append(('home',next(iter(cmd))))
        rig.material._command_generation+=1
    rig.objects['homing'].cmd_G28=native
    with pytest.raises(ValueError,match='interrupted'):execute(rig)
    assert [c for c in rig.calls if c[0]=='home']==[('home','Y')]
    assert not any(c[0] in ('move','tap') for c in rig.calls)
