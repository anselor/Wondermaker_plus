import os
import pytest
if not os.environ.get("OPENACE_NATIVE_BACKEND"):
    pytest.skip("native/backend integration requires OPENACE_NATIVE_BACKEND and its Python test dependencies", allow_module_level=True)
from pathlib import Path
import json,subprocess
import pytest,openace
from tests.klipper import loader
from tests.klipper.test_zero_unit_runtime import manual_printer
from tests.klipper.test_material_family_runtime import paused
from tests.klipper.test_manual_runout_scripted_clear import loss
from tests.klipper.fake_klippy import FakeCommandError
P=Path(__file__).resolve().parents[2]
BACKEND=Path(os.environ["OPENACE_NATIVE_BACKEND"]).resolve()
@pytest.fixture(scope='module')
def binary():
 out=P/'build/native-manual-wire'
 subprocess.run(['g++','-std=c++11','-Wall','-Wextra','-Werror','-pthread','-I'+str(P/'source/client'),'-I'+str(P/'source/vendor'),str(P/'tests/native_manual_wire.cpp'),'-o',str(out)],check=True)
 return out

def drive(binary,r,mode,sensor=None):
 assert Path(loader.ROOT)==BACKEND and Path(openace.__file__)==BACKEND/'openace/__init__.py'
 process=subprocess.Popen([str(binary),mode],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
 commands=[]
 try:
  for line in process.stdout:
   request=json.loads(line)
   if 'get' in request:
    assert request['get']=='/printer/objects/query?openace=session_id,material_change_prompt,loaded,manual_flow'
    status=r.obj.get_status(0);selected={key:status[key] for key in ('session_id','material_change_prompt','loaded','manual_flow') if key in status}
    response={'result':{'status':{'openace':selected}}}
   elif 'post' in request:
    command=request['post']['script'];commands.append(command)
    if mode=='cancel_before_post' and len(commands)==1:r.printer.lookup_object('print_stats').note_cancel()
    if mode=='source_edit_before_post' and len(commands)==1:r.run('SET_COLOR LANE=T0 COLOR=445566')
    try:r.run(command);response={'result':'ok'}
    except FakeCommandError as error:response={'error':{'message':str(error)}}
    if (mode=='unknown_prepare' and len(commands)==1) or (mode=='lost_done' and 'DONE=1' in command):response={'throw':True}
   elif 'insert' in request:
    if sensor is not None:sensor.set(True)
    response={'result':'ok'}
   elif 'check_no_auto' in request:
    assert len(commands)==1;response={'result':'ok'}
   elif 'finished' in request:
    process.stdin.write('{}\n');process.stdin.flush();break
   else:raise AssertionError(request)
   process.stdin.write(json.dumps(response)+'\n');process.stdin.flush()
  assert process.wait(timeout=3)==0,commands
 finally:
  if process.poll() is None:process.kill();process.wait()
 return commands

@pytest.mark.parametrize('mode',['normal','unknown_prepare','lost_done','cancel_before_post','source_edit_before_post'])
def test_actual_ordinary_pause_null_prompt_native_requests_and_same_sd(manual_printer,tmp_path,binary,mode):
 r=manual_printer();native,sd=paused(r,tmp_path)
 assert r.obj.get_status(0).get('material_change_prompt') is None
 before=len(r.printer.lookup_object('gcode_macro _OPENACE_ZRU_EXTRUDE').calls)
 commands=drive(binary,r,mode)
 assert all(c.startswith(('OPENACE_LOAD_DIRECT ','OPENACE_CHANGE_PLAN ')) for c in commands)
 if mode in ('cancel_before_post','source_edit_before_post'):
  assert len(commands)==1 and len(r.printer.lookup_object('gcode_macro _OPENACE_ZRU_EXTRUDE').calls)==before
  if mode=='cancel_before_post':assert not sd.is_active() and not r.obj.get_status(0)['manual_flow']['available']
  else:assert native.is_paused and r.obj.store.identities['h0'].color=='#445566'
  return
 assert sum('DONE=1' in c for c in commands)==1
 assert sum('DONE=1' not in c and c.startswith('OPENACE_LOAD_DIRECT') for c in commands)==(2 if mode=='unknown_prepare' else 1)
 assert r.obj.get_status(0)['manual_flow']['purge']['remaining_mm']==0
 r.run('RESUME');assert not native.is_paused and sd.is_active();sd.run_sd_line(r.gcode,'G1 X21 Y22')
 assert r.printer.lookup_object('gcode_move').gcode_position[:2]==[21.,22.] and not r.unit_calls

@pytest.mark.parametrize('mode',['normal','unknown_prepare','lost_done'])
def test_real_first_head_loss_prepare110_then_insertion_prime80_and_same_sd(manual_printer,tmp_path,binary,mode):
 r=manual_printer();native,sd,sensor,episode=loss(r,tmp_path);old=episode.runout.old_tail.document()
 commands=drive(binary,r,mode,sensor)
 assert r.obj.store.recovery_records[episode.episode_id]['runout']['old_tail']==old
 assert sum(float(c['MM']) for c in r.printer.lookup_object('gcode_macro _OPENACE_ZRU_EXTRUDE').calls)==190
 assert r.obj.get_status(0)['manual_flow']['purge']['remaining_mm']==0
 r.run('RESUME');assert not native.is_paused;sd.run_sd_line(r.gcode,'G1 X71 Y72')
 assert r.printer.lookup_object('gcode_move').gcode_position[:2]==[71.,72.] and not r.unit_calls


def test_physical_head0_file_tool7_is_not_reinterpreted_as_tool0(manual_printer,tmp_path,binary):
 r=manual_printer();r.prepare_heads();r.run('OPENACE_MAP_TOOL TOOL=7 HEAD=h0');native,starts=r.install_print()
 path=tmp_path/'tool-seven.gcode';path.write_text('T7\nG1 X41 Y42\n')
 r.run('SDCARD_PRINT_FILE FILENAME="%s"'%path);sd=r.printer.lookup_object('virtual_sdcard')
 sd.run_sd_line(r.gcode,'T7');sd.run_sd_line(r.gcode,'PAUSE')
 assert r.obj.get_status(0)['manual_flow']['tool']==7 and r.obj.get_status(0)['manual_flow']['head']=='h0'
 commands=drive(binary,r,'normal');assert any(c.startswith('OPENACE_CHANGE_PLAN TOOL=7 ') for c in commands)
 assert not any('TOOL=0 ' in c for c in commands)
 r.run('RESUME');assert not native.is_paused;sd.run_sd_line(r.gcode,'G1 X41 Y42')
 assert r.printer.lookup_object('gcode_move').gcode_position[:2]==[41.,42.]

@pytest.mark.parametrize('uncertain',[False,True])
def test_native_partial_continuation_vs_unknown_suffix_never_repeats_known_e(manual_printer,tmp_path,binary,monkeypatch,uncertain):
 from openace.interfaces.types import OpResult
 r=manual_printer();native,sd=paused(r,tmp_path);target=r.obj.printer_actions;original=target.extrude;calls=[]
 def partial(head,mm,op):
  calls.append(mm)
  if len(calls)==2:
   if uncertain:raise RuntimeError('actual delivery suffix unknown')
   return OpResult(False,op,'definite refusal before target issue')
  return original(head,mm,op)
 monkeypatch.setattr(target,'extrude',partial)
 commands=drive(binary,r,'unknown_suffix' if uncertain else 'partial')
 assert calls==([10,10] if uncertain else [10,10]+[10]*7)
 if uncertain:
  assert len([c for c in commands if 'DONE=1' in c])==1
  assert r.obj.get_status(0)['manual_flow']['correction_required'] and native.is_paused
 else:
  assert [c.split('PRIME=')[1].split()[0] for c in commands if 'DONE=1' in c]==['80','70']
  assert sum(float(c['MM']) for c in r.printer.lookup_object('gcode_macro _OPENACE_ZRU_EXTRUDE').calls)==80
  r.run('RESUME');assert not native.is_paused;sd.run_sd_line(r.gcode,'G1 X21 Y22')


def test_save_failure_and_screen_restart_hold_then_exact_receipt_recovery_has_no_e(manual_printer,tmp_path,binary,monkeypatch):
 import ast
 r=manual_printer(state_path=tmp_path/'screen-save.cfg');native,sd=paused(r,tmp_path)
 save=r.obj.persist_material_candidate;failures=[]
 def fail(literal,revision):
  document=ast.literal_eval(literal)
  if not failures and any(c.get('purge_completed_mm')==80 for c in document.get('material_state',{}).get('changes',{}).values()):
   failures.append(True);raise OSError('physical receipt save failed')
  return save(literal,revision)
 monkeypatch.setattr(r.obj,'persist_material_candidate',fail)
 commands=drive(binary,r,'save_failed');assert failures and len([c for c in commands if 'DONE=1' in c])==1
 macro=r.printer.lookup_object('gcode_macro _OPENACE_ZRU_EXTRUDE');count=len(macro.calls)
 assert drive(binary,r,'restart_hold')==[] and len(macro.calls)==count
 # This is the existing explicit same-runtime receipt recovery, not a GUI replay button.
 view=r.obj.get_status(0)['manual_flow'];r.run('OPENACE_LOAD_DIRECT HEAD=h0 DONE=1 PRIME=80 EXPECT_CONTEXT='+view['context'])
 assert len(macro.calls)==count and r.obj.get_status(0)['manual_flow']['purge']['remaining_mm']==0
 r.run('RESUME');assert not native.is_paused;sd.run_sd_line(r.gcode,'G1 X21 Y22')


def test_genuine_host_restart_does_not_restore_a_manual_preparation_invitation(manual_printer,tmp_path,binary):
 state=tmp_path/'manual-screen-restart.cfg';r=manual_printer(state_path=state);native,sd=paused(r,tmp_path)
 drive(binary,r,'lost_done');r.close();restored=manual_printer(state_path=state)
 assert not restored.obj.get_status(0)['manual_flow']['available']
 assert drive(binary,restored,'no_manual')==[]
 assert not restored.unit_calls and not any(c[0]=='extrude' for c in restored.obj.printer_actions.calls)


def test_declared_change_keeps_from_to_and_separate_explicit_context_colour_button(manual_printer,tmp_path,binary):
 r=manual_printer();native,sd=paused(r,tmp_path)
 r.run('OPENACE_SET_FILAMENT HEAD=h0 MATERIAL=PLA+ TEMP=210 COLOR=445566');r.run('M600')
 assert r.obj.get_status(0).get('material_change_prompt')
 commands=drive(binary,r,'colour')
 approvals=[c for c in commands if c.startswith('OPENACE_CONFIRM_CHANGE ')]
 assert len(approvals)==1 and 'EXPECT_CONTEXT=' in approvals[0]
 assert not r.obj.get_status(0)['recovery']['material_change']['pending_confirmation']
 r.run('RESUME');assert not native.is_paused;sd.run_sd_line(r.gcode,'G1 X21 Y22')
