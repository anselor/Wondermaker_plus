import os
import pytest
if not os.environ.get("OPENACE_NATIVE_BACKEND"):
    pytest.skip("native/backend integration requires OPENACE_NATIVE_BACKEND and its Python test dependencies", allow_module_level=True)
"""UI-generated fixed commands through real current backend; no source edits."""
from pathlib import Path
import json,subprocess
import pytest
from tests.klipper.test_zero_unit_runtime import manual_printer
from tests.klipper.test_unregistered_identification import inventory
from tests.klipper.test_management_command_context import available,reobserve,replaced
from tests.klipper.fake_klippy import FakeCommandError
from tests.klipper.extended_params import parse_extended_params_v012,parse_extended_params_v013
from test_management_commands import build,ROOT
EXPECTED=Path(os.environ["OPENACE_NATIVE_BACKEND"]).resolve()

@pytest.fixture(scope='module')
def commands():return build()

def emit(commands,r,request,tmp_path):
 from tests.klipper import loader
 import openace
 assert Path(loader.ROOT)==EXPECTED and Path(openace.__file__)==EXPECTED/'openace/__init__.py'
 status=tmp_path/'management-status.json';intent=tmp_path/'management-request.json'
 status.write_text(json.dumps(r.obj.get_status(0)));intent.write_text(json.dumps(request))
 return subprocess.check_output([str(commands),'--command',str(status),str(intent)],text=True)

def capture(name,r,output):
 output.joinpath(name+'.json').write_text(json.dumps(r.obj.get_status(0),indent=2,sort_keys=True)+'\n')

@pytest.mark.parametrize('naming',['explicit','structured'])
def test_generated_basic_edit_preserves_all_writable_identity_and_actual_parsers(manual_printer,tmp_path,commands,naming):
 r=manual_printer()
 parts=' NAME="O\'Reilly spool"' if naming=='explicit' else ' VENDOR="Maker Co" LINE="Pro Line" COLOR_NAME="Ocean Blue"'
 r.run('OPENACE_SET_FILAMENT HEAD=h0 MATERIAL=PLA TEMP=210 BED=60 COLOR=112233 SPOOL_ID=123 TEMP_MIN=190 TEMP_MAX=220'+parts)
 before=r.obj.store.identities['h0'];capture('management_'+naming+'1080',r,tmp_path)
 command=emit(commands,r,dict(action='set_filament',head='h0',fields=dict(material='PLA',nozzle_temp=214,color='445566')),tmp_path)
 old=parse_extended_params_v012(command);new=parse_extended_params_v013(command.split(' ',1)[1]);assert old==new
 assert old['NAME']==before.name and old['VENDOR']==before.vendor and old['LINE']==before.line and old['COLOR_NAME']==before.color_name
 r.run(command);after=r.obj.store.identities['h0']
 for name in ('name','vendor','line','color_name','spool_id','bed_temp','nozzle_temp_min','nozzle_temp_max'):assert getattr(after,name)==getattr(before,name)
 assert after.nozzle_temp==214 and after.color=='#445566' and after.source=='user'
 assert not r.unit_calls


def test_ui_commands_configure_four_already_hand_fed_heads_then_actual_file_selects_each_without_console_recovery(manual_printer,tmp_path,commands):
 r=manual_printer();capture('management_unset1080',r,tmp_path)
 for i in range(4):
  r.run(emit(commands,r,dict(action='map_tool',tool=i,head='h%d'%i),tmp_path))
  r.run(emit(commands,r,dict(action='set_filament',head='h%d'%i,fields=dict(material='PLA',nozzle_temp=210+i,color='112233')),tmp_path))
 assert not r.unit_calls
 native,starts=r.install_print();path=tmp_path/'four-manual.gcode';path.write_text('T0\nT1\nT2\nT3\nG1 X21 Y22\n')
 r.run('SDCARD_PRINT_FILE FILENAME="%s"'%path)
 sd=r.printer.lookup_object('virtual_sdcard')
 for line in ('T0','T1','T2','T3','G1 X21 Y22'):sd.run_sd_line(r.gcode,line)
 assert not native.is_paused and sd.is_active() and not r.unit_calls
 assert r.printer.lookup_object('gcode_move').gcode_position[:2]==[21.,22.]


def test_observed_add_stale_context_refuses_then_new_explicit_selection_registers(inventory,tmp_path,commands):
 r=inventory();shown=available(r)
 old=emit(commands,r,dict(action='unit_add',unit='ace0',context=shown['expect_context']),tmp_path)
 current=reobserve(r,(7,8,9))
 with pytest.raises(FakeCommandError,match='context|selection changed'):r.run(old)
 assert not r.obj.units and not r.device.moves
 fresh=emit(commands,r,dict(action='unit_add',unit='ace0',context=current['expect_context']),tmp_path)
 r.run(fresh);assert r.wait(lambda:r.obj.units['ace0'].status=='ready')
 assert r.obj.store.unit_identity('ace0')['device']==current['device_identity']
 # Ordinary field edits use their existing busy/current-document owner, no opaque token.
 setting=emit(commands,r,dict(action='source_set',unit='ace0',slot=0,fields=dict(feeder_hold_mm='10',feeder_to_inlet_mm='80',feed_timeout_s='240',feed_to_sensor_mm='2500')),tmp_path)
 assert 'EXPECT_CONTEXT' not in setting;r.run(setting)
 state=r.obj.get_status(0)['management']['source_settings']['ace0:0']
 assert state['effective']['feeder_to_inlet_mm']==80 and state['origins']['feed_timeout_s']=='persisted'
 r.run(emit(commands,r,dict(action='source_reset',unit='ace0',slot=0,fields=['feeder_to_inlet_mm']),tmp_path))
 assert r.obj.get_status(0)['management']['source_settings']['ace0:0']['effective']['feeder_to_inlet_mm'] is None
 assert not r.device.moves


def test_head_settings_apply_failure_retry_and_restart_keep_exact_effective_values(manual_printer,tmp_path,commands,monkeypatch):
 from tests.klipper.test_head_settings_runtime import empty_head,shipped_defaults
 shipped_defaults(monkeypatch)  # Actual shipped unset-capture template; legacy rig capture10 is a config override.
 state=tmp_path/'ui-head-state.cfg';r=manual_printer(state_path=state);empty_head(r)
 request=dict(action='head_set',head='h0',fields=dict(capture_mm='18',capture_step_mm='3'))
 command=emit(commands,r,request,tmp_path);before=r.obj.store.to_literal()
 variables=r.printer.lookup_object('save_variables');save=variables.cmd_SAVE_VARIABLE
 def fail(gcmd):raise OSError('read only storage')
 with monkeypatch.context() as m:
  m.setattr(variables,'cmd_SAVE_VARIABLE',fail)
  with pytest.raises(FakeCommandError,match='storage|saved|read only'):r.run(command)
 assert r.obj.store.to_literal()==before
 # A new deliberate Apply emits the same exact intended values after refresh.
 r.run(emit(commands,r,request,tmp_path));info=r.obj.get_status(0)['management']['head_settings']['h0']
 assert info['effective']==dict(capture_mm=18,capture_step_mm=3) and set(info['origins'].values())=={'persisted'}
 r.close();again=manual_printer(state_path=state)
 assert again.obj.get_status(0)['management']['head_settings']['h0']==info
 empty_head(again)
 again.run(emit(commands,again,dict(action='head_reset',head='h0',fields=['capture_mm','capture_step_mm']),tmp_path))
 now=again.obj.get_status(0)['management']['head_settings']['h0']
 assert now['origins']==dict(capture_mm='default',capture_step_mm='default')
 assert not r.unit_calls


def test_current_accept_command_is_display_bound_not_legacy_current_device(inventory,tmp_path,commands):
 r=inventory();row=available(r)
 r.run(emit(commands,r,dict(action='unit_add',unit='ace0',context=row['expect_context']),tmp_path))
 assert r.wait(lambda:r.obj.units['ace0'].status=='ready')
 runtime=replaced(r,(7,8,9));shown=r.obj.get_status(0)['management']['units']['ace0']
 old=emit(commands,r,dict(action='unit_accept',unit='ace0',context=shown['accept_context']),tmp_path)
 r.run(old);assert r.wait(lambda:runtime.status=='ready')
 replaced(r,(10,11,12))
 with pytest.raises(FakeCommandError,match='context|selection changed'):r.run(old)
 now=r.obj.get_status(0)['management']['units']['ace0']
 r.run(emit(commands,r,dict(action='unit_accept',unit='ace0',context=now['accept_context']),tmp_path))
 assert r.wait(lambda:runtime.status=='ready')
 assert r.obj.store.unit_identity('ace0')['device']==now['observed_identity']['device'] and not r.device.moves

@pytest.fixture(scope='module')
def native_commands():
 from test_native_management_command import build_native_management_command
 return build_native_management_command()

def native_emit(binary,r,tmp_path,action,index,*values):
 from tests.klipper import loader
 import openace
 assert Path(loader.ROOT)==EXPECTED and Path(openace.__file__)==EXPECTED/'openace/__init__.py'
 status=tmp_path/'native-management-status.json';status.write_text(json.dumps(r.obj.get_status(0)))
 return subprocess.check_output([str(binary),str(status),action,str(index)]+list(values),text=True)

def test_actual_native_widget_drafts_apply_four_initial_assignments_then_same_file_runs(manual_printer,tmp_path,native_commands):
 r=manual_printer()
 for i in range(4):
  r.run(native_emit(native_commands,r,tmp_path,'map_tool',i))
  r.run(native_emit(native_commands,r,tmp_path,'set_filament',i,'PLA',str(210+i),'112233'))
 assert not r.unit_calls
 native,starts=r.install_print();path=tmp_path/'native-four-heads.gcode'
 path.write_text('T0\nT1\nT2\nT3\nG1 X31 Y32\n')
 r.run('SDCARD_PRINT_FILE FILENAME="%s"'%path)
 sd=r.printer.lookup_object('virtual_sdcard')
 for line in ('T0','T1','T2','T3','G1 X31 Y32'):sd.run_sd_line(r.gcode,line)
 assert not native.is_paused and sd.is_active() and not r.unit_calls
 assert r.printer.lookup_object('gcode_move').gcode_position[:2]==[31.,32.]

def test_actual_native_head_editor_apply_preserves_other_heads(manual_printer,tmp_path,native_commands,monkeypatch):
 from tests.klipper.test_head_settings_runtime import empty_head,shipped_defaults
 shipped_defaults(monkeypatch)  # Same real shipped unset template as the direct-command test above.
 r=manual_printer();empty_head(r)
 before=r.obj.get_status(0)['management']['head_settings']
 r.run(native_emit(native_commands,r,tmp_path,'head_set',0,'18'))
 after=r.obj.get_status(0)['management']['head_settings']
 assert after['h0']['effective']['capture_mm']==18
 assert all(after[h]==before[h] for h in before if h!='h0')
 assert not r.unit_calls
