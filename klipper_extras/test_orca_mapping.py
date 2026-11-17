from types import SimpleNamespace as NS
import pytest
from wmp_orca_mapping import OrcaMapping


class Command:
    error=ValueError
    def __init__(self,**values):self.values=values;self.messages=[]
    def get(self,key,default=None):return self.values.get(key,default)
    def respond_info(self,message):self.messages.append(message)


@pytest.fixture
def rig():
    values={};calls=[];registered={};owners={};active=[False]
    def run(command):
        calls.append(command);words=dict(item.split('=') for item in command.split()[1:]);values[words['VARIABLE']]=int(words['VALUE'])
    gcode=NS(run_script_from_command=run,get_status=lambda now:{'commands':registered},register_command=lambda name,handler,**kw:registered.setdefault(name,handler))
    objects={'gcode':gcode,'save_variables':NS(get_status=lambda now:{'variables':dict(values)})}
    printer=NS(lookup_object=lambda name,default=None:owners.get(name,objects.get(name,default)),get_reactor=lambda:NS(monotonic=lambda:0))
    def admit(cmd):
        if active[0]:raise ValueError('Another print is active')
        if owners:raise ValueError('Another manager owns this printer')
    material=NS(printer=printer,_print_admission=admit,_begin_explicit_physical_action=lambda action:None)
    return NS(feature=OrcaMapping(material),values=values,calls=calls,registered=registered,owners=owners,active=active)


def test_exact_orca_reset_and_map_sequence(rig):
    rig.feature.reset(Command())
    rig.feature.set_map(Command(LANE='wmplus_tool_2',MAP='T0'))
    for suffix in ('','_backup'):
        assert [rig.values['box_modify_t%d%s'%(n,suffix)] for n in range(4)]==[2,1,2,3]
    assert all(c.startswith('SAVE_VARIABLE ') for c in rig.calls)


def test_multiple_maps_use_stable_physical_lanes(rig):
    rig.feature.reset(Command())
    rig.feature.set_map(Command(LANE='wmplus_tool_2',MAP='T0'))
    rig.feature.set_map(Command(LANE='wmplus_tool_0',MAP='T2'))
    assert rig.values['box_modify_t0']==2 and rig.values['box_modify_t2']==0


@pytest.mark.parametrize('lane,target',[('wmplus_tool_4','T0'),('openace_tool_2','T0'),('wmplus_tool_2','T4'),('wmplus_tool_2','T0\nM112')])
def test_invalid_mapping_has_no_effect(rig,lane,target):
    with pytest.raises(ValueError,match='SET_MAP requires'):rig.feature.set_map(Command(LANE=lane,MAP=target))
    assert not rig.calls


@pytest.mark.parametrize('command',['reset','set_map'])
def test_live_print_mapping_is_not_changed(rig,command):
    rig.active[0]=True
    with pytest.raises(ValueError,match='active'):getattr(rig.feature,command)(Command(LANE='wmplus_tool_2',MAP='T0'))
    assert not rig.calls


@pytest.mark.parametrize('owner',['openace','AFC'])
def test_external_owner_commands_are_not_registered(rig,owner):
    rig.owners[owner]=object();rig.feature.register();assert not rig.registered


def test_existing_command_not_replaced(rig):
    existing=object();rig.registered['SET_MAP']=existing;rig.feature.register()
    assert rig.registered['SET_MAP'] is existing
    assert 'RESET_AFC_MAPPING' in rig.registered
