import os
import pytest
if not os.environ.get("OPENACE_NATIVE_BACKEND"):
    pytest.skip("native/backend integration requires OPENACE_NATIVE_BACKEND and its Python test dependencies", allow_module_level=True)
"""Raw editing fields remain distinct from inventory display labels."""
from pathlib import Path
import pytest
from tests.klipper.test_zero_unit_runtime import manual_printer
from test_management_actual_backend import commands,emit

@pytest.mark.parametrize('name',['','Explicit spool name'])
def test_basic_edit_requires_actual_raw_name_to_preserve_structured_identity(manual_printer,name,commands,tmp_path):
 from tests.klipper import loader
 assert Path(loader.ROOT)==Path(os.environ["OPENACE_NATIVE_BACKEND"]).resolve()
 r=manual_printer()
 parts=(' NAME="'+name+'"') if name else ' VENDOR="Maker Co" LINE="Pro Line" COLOR_NAME="Ocean Blue"'
 r.run('OPENACE_SET_FILAMENT HEAD=h0 MATERIAL=PLA TEMP=210 BED=60 COLOR=112233'+parts)
 identity=r.obj.store.identities['h0'];status=r.obj.get_status(0)
 assert identity.name==name
 assert status['inventory']['h0']['name']==identity.display_name()
 assert not r.unit_calls
 # The published editing contract is distinct from inventory's display name.
 row=status['management']['identity_settings']['h0']['values']
 for key in ('name','vendor','line','color_name','material'):
  assert row[key]==getattr(identity,key)
 command=emit(commands,r,dict(action='set_filament',head='h0',fields=dict(nozzle_temp=214,color='445566')),tmp_path)
 r.run(command)
 edited=r.obj.store.identities['h0']
 for key in ('name','vendor','line','color_name','material'):
  assert getattr(edited,key)==getattr(identity,key)
 assert edited.nozzle_temp==214 and edited.color=='#445566' and not r.unit_calls
