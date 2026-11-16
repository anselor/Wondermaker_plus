import os
import pytest
if not os.environ.get("OPENACE_NATIVE_BACKEND"):
    pytest.skip("native/backend integration requires OPENACE_NATIVE_BACKEND and its Python test dependencies", allow_module_level=True)
from pathlib import Path
import subprocess,json
from tests.klipper.test_zero_unit_runtime import manual_printer
from tests.klipper.test_material_confirmation_context_runtime import ready,status
from tests.klipper.test_m600_declared_runtime import started,replacement
from tests.klipper.fake_klippy import FakeCommandError
import pytest
from test_view_contract import build,ROOT

def command(binary,r,path):
 path.write_text(json.dumps(r.obj.get_status(r.printer.get_reactor().monotonic())))
 return subprocess.check_output([str(binary),'--click',str(path)],text=True)

def test_cpp_explicit_click_is_bound_to_actual_display_then_same_job_continues(manual_printer,tmp_path):
 binary=build();r,native,sd=ready(manual_printer,tmp_path)
 generation=r.obj._job_generation;shown=command(binary,r,tmp_path/'shown.json')
 before=sum(x[0]=='extrude' for x in r.obj.printer_actions.calls)
 r.run('OPENACE_MATERIAL_FAMILY_SET MATERIAL=PLA+ FAMILY=PLA')
 with pytest.raises(FakeCommandError,match='changed|refresh'):r.run(shown)
 assert status(r)['pending_confirmation'] and not status(r)['approved']
 assert sum(x[0]=='extrude' for x in r.obj.printer_actions.calls)==before
 fresh=command(binary,r,tmp_path/'current.json');assert shown!=fresh
 r.run(fresh);assert status(r)['approved']
 assert sum(x[0]=='extrude' for x in r.obj.printer_actions.calls)==before
 r.run('RESUME');assert not native.is_paused and sd.is_active() and r.obj._job_generation==generation
 sd.run_sd_line(r.gcode,'G1 X21 Y22')
 assert r.printer.lookup_object('gcode_move').gcode_position[:2]==[21.,22.]

def test_cpp_declared_m600_click_uses_required_file_tool_and_exact_new_context(manual_printer,tmp_path):
 binary=build();r,native,sd=started(manual_printer,tmp_path)
 sd.run_sd_line(r.gcode,'M600 V1 P1 F2');replacement(r,color='778899')
 assert status(r)['pending_confirmation']
 full=r.obj.get_status(0)
 tmp_path.joinpath('declared_pending_compact.json').write_text(json.dumps(full,indent=2,sort_keys=True)+'\n')
 shown=command(binary,r,tmp_path/'declared.json')
 assert 'TOOL=3 ' in shown and 'EXPECT_CONTEXT=' in shown
 before=sum(x[0]=='extrude' for x in r.obj.printer_actions.calls)
 r.run(shown);assert status(r)['approved']
 r.run('RESUME');assert not native.is_paused and sd.is_active()
 assert r.obj.job_filaments.active=={3:2}
 assert sum(x[0]=='extrude' for x in r.obj.printer_actions.calls)==before
 sd.run_sd_line(r.gcode,'G1 X51 Y52')
 assert r.printer.lookup_object('gcode_move').gcode_position[:2]==[51.,52.]


def test_exact_backend_origin():
 import openace
 from tests.klipper import loader
 expected=Path(os.environ["OPENACE_NATIVE_BACKEND"]).resolve()
 print('openace.__file__='+str(openace.__file__))
 print('loader.ROOT='+str(loader.ROOT))
 assert Path(openace.__file__).resolve()==expected/'openace/__init__.py'
 assert Path(loader.ROOT).resolve()==expected
