import os
import pytest
if not os.environ.get("OPENACE_NATIVE_BACKEND"):
    pytest.skip("native/backend integration requires OPENACE_NATIVE_BACKEND and its Python test dependencies", allow_module_level=True)
from pathlib import Path
import json,subprocess
import pytest
from tests.klipper.test_zero_unit_runtime import manual_printer
from tests.klipper.test_material_confirmation_context_runtime import ready,status
from tests.klipper.fake_klippy import FakeCommandError
from test_native_renderer import build_native_renderer

def test_rendered_native_port_click_context_is_rejected_when_stale_then_same_sd_continues(manual_printer,tmp_path):
 import openace
 from tests.klipper import loader
 expected=Path(os.environ["OPENACE_NATIVE_BACKEND"])
 print(openace.__file__,loader.ROOT)
 assert Path(openace.__file__).resolve()==expected/'openace/__init__.py'
 assert Path(loader.ROOT).resolve()==expected
 r,native,sd=ready(manual_printer,tmp_path);binary=build_native_renderer()
 def shown_command():
  p=tmp_path/'actual-status.json';p.write_text(json.dumps(r.obj.get_status(0)))
  return subprocess.check_output([str(binary),str(p)],text=True)
 old=shown_command();before=sum(x[0]=='extrude' for x in r.obj.printer_actions.calls)
 r.run('OPENACE_MATERIAL_FAMILY_SET MATERIAL=PLA+ FAMILY=PLA')
 with pytest.raises(FakeCommandError,match='changed|refresh'):r.run(old)
 assert status(r)['pending_confirmation'] and not status(r)['approved']
 fresh=shown_command();assert fresh!=old
 r.run(fresh);assert status(r)['approved']
 r.run('RESUME');assert not native.is_paused and sd.is_active()
 assert sum(x[0]=='extrude' for x in r.obj.printer_actions.calls)==before
 sd.run_sd_line(r.gcode,'G1 X24 Y25')
 assert r.printer.lookup_object('gcode_move').gcode_position[:2]==[24.,25.]
