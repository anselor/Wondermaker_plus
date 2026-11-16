import os
import pytest
if not os.environ.get("OPENACE_NATIVE_BACKEND"):
    pytest.skip("native/backend integration requires OPENACE_NATIVE_BACKEND and its Python test dependencies", allow_module_level=True)
from pathlib import Path
import json,subprocess
import pytest
import openace
from tests.klipper import loader
from tests.klipper.test_zero_unit_runtime import manual_printer
from tests.klipper.test_material_family_runtime import paused
P=Path(__file__).resolve().parents[2]
BACKEND=Path(os.environ["OPENACE_NATIVE_BACKEND"]).resolve()
def capture(name,r,output):
 assert Path(loader.ROOT)==BACKEND and Path(openace.__file__)==BACKEND/'openace/__init__.py'
 f=output/(name+'.json');assert output in f.resolve().parents;f.write_text(json.dumps(r.obj.get_status(0),indent=2,sort_keys=True)+'\n')

def test_capture_real_ordinary_paused_no_prompt_prepare_plan_done(manual_printer,tmp_path):
 r=manual_printer();native,sd=paused(r,tmp_path)
 assert r.obj.get_status(0).get('material_change_prompt') is None
 capture('manual_ordinary1084',r,tmp_path)
 for name,command in [('prepared','OPENACE_LOAD_DIRECT HEAD=h0'),('planned','OPENACE_CHANGE_PLAN TOOL=0 PURGE_MM=80'),('complete','OPENACE_LOAD_DIRECT HEAD=h0 DONE=1 PRIME=80')]:
  context=r.obj.get_status(0)['manual_flow']['context'];r.run(command+' EXPECT_CONTEXT='+context);capture('manual_'+name+'1084',r,tmp_path)
 r.run('RESUME');assert not native.is_paused and sd.is_active();sd.run_sd_line(r.gcode,'G1 X21 Y22')
 assert r.printer.lookup_object('gcode_move').gcode_position[:2]==[21.,22.]


def test_capture_actual_runout_prepare_then_real_insertion_context(manual_printer,tmp_path):
 from tests.klipper.test_manual_runout_scripted_clear import loss
 r=manual_printer();native,sd,sensor,e=loss(r,tmp_path);capture('manual_loss1084',r,tmp_path)
 r.run('OPENACE_LOAD_DIRECT HEAD=h0 EXPECT_CONTEXT='+r.obj.get_status(0)['manual_flow']['context']);capture('manual_loss_prepared1084',r,tmp_path)
 sensor.set(True);capture('manual_loss_inserted1084',r,tmp_path)
 r.run('OPENACE_CHANGE_PLAN TOOL=0 PURGE_MM=80 EXPECT_CONTEXT='+r.obj.get_status(0)['manual_flow']['context']);capture('manual_loss_planned1084',r,tmp_path)
 r.run('OPENACE_LOAD_DIRECT HEAD=h0 DONE=1 PRIME=80 EXPECT_CONTEXT='+r.obj.get_status(0)['manual_flow']['context'])
 r.run('RESUME');assert not native.is_paused;sd.run_sd_line(r.gcode,'G1 X71 Y72')
