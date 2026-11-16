import os
import pytest
if not os.environ.get("OPENACE_NATIVE_BACKEND"):
    pytest.skip("native/backend integration requires OPENACE_NATIVE_BACKEND and its Python test dependencies", allow_module_level=True)
from copy import deepcopy
from tests.klipper.test_zero_unit_runtime import manual_printer
from tests.klipper.test_material_family_runtime import paused
from tests.klipper.test_runout_provenance_runtime import assess_manual_old_path_removed
from openace.interfaces.types import OpResult
from test_native_wire import binary,drive


def test_known10_physical_removal_then_native_fresh80_continues_same_sd(manual_printer,tmp_path,monkeypatch,binary):
 r=manual_printer();native,sd=paused(r,tmp_path);generation=r.obj._job_generation
 r.run('OPENACE_LOAD_DIRECT HEAD=h0');r.run('OPENACE_CHANGE_PLAN TOOL=0 PURGE_MM=80')
 target=r.obj.printer_actions;original=target.extrude;calls=[]
 def partial(head,mm,op):
  calls.append(mm)
  return OpResult(False,op,'definite pre-submission refusal') if len(calls)==2 else original(head,mm,op)
 monkeypatch.setattr(target,'extrude',partial)
 r.run('OPENACE_LOAD_DIRECT HEAD=h0 DONE=1 PRIME=80')
 assert r.obj.get_status(0)['manual_flow']['purge']['completed_mm']==10
 old=deepcopy(r.obj.material_changes.record().document()['purge_receipts']);instance=r.obj.store.material_state['instances']['h0']
 sensor=r.printer.lookup_object('filament_switch_sensor filament0');sensor.set(False)
 r.run('OPENACE_RECOVER HEAD=h0 EMPTY=1');assess_manual_old_path_removed(r)
 assert r.obj.head_journal.owner.for_head('h0') is None
 monkeypatch.setattr(target,'extrude',original)
 plan,problems=target.forward_clear_plan('h0',210);assert not problems
 macro=r.printer.lookup_object('gcode_macro _OPENACE_ZRU_EXTRUDE');before=len(macro.calls)
 commands=drive(binary,r,'normal',sensor)
 assert sum(float(c['MM']) for c in macro.calls[before:])==plan.total_mm+80
 assert plan.total_mm==110
 assert [c.split('PRIME=')[1].split()[0] for c in commands if 'DONE=1' in c]==['80']
 assert not any('PRIME=70 ' in c for c in commands)
 assert r.obj.store.material_state['instances']['h0']>instance
 history=[x for row in r.obj.store.material_state['changes'].values() for x in row['purge_receipts']]
 assert all(receipt in history for receipt in old)
 r.run('RESUME');assert not native.is_paused and sd.is_active() and r.obj._job_generation==generation
 sd.run_sd_line(r.gcode,'G1 X31 Y32');assert r.printer.lookup_object('gcode_move').gcode_position[:2]==[31.,32.]
 assert not r.unit_calls
