from pathlib import Path
import hashlib,json,subprocess,struct
ROOT=Path(__file__).resolve().parents[1]
def test_actual_1113_symbols_and_instruction_windows_pin_idle_layout(native_client_elf):
 actual=native_client_elf
 data=actual.read_bytes();record=json.loads((ROOT/'native-port-windows.json').read_text())
 assert hashlib.sha256(data).hexdigest()==record['binary_sha256']
 symbols=subprocess.check_output(['nm','-an',str(actual)],text=True).splitlines()
 for address,name in record['main_objects'].items():
  assert any(row.split()==[format(int(address,16),'016x'),'b',name] for row in symbols)
 phoff=struct.unpack_from('<Q',data,32)[0];size,count=struct.unpack_from('<HH',data,54)
 for key,want in record['windows'].items():
  address=int(key,16);found=False
  for i in range(count):
   kind,flags,offset,start,_,length,_,_=struct.unpack_from('<IIQQQQQQ',data,phoff+i*size)
   if kind==1 and start<=address and address+32<=start+length:
    assert flags&1;assert data[offset+address-start:offset+address-start+32].hex()==want;found=True;break
  assert found,key


def test_owned_widget_diagnostic_getters_are_in_both_exact_prefix_manifests():
 import re
 record=json.loads((ROOT/'native-port-windows.json').read_text())
 header=(ROOT/'source/client/native1113_windows.hpp').read_text()
 for address in (0x6a6198,0x6aaacc,0x6ac4d8,0x69e868,0x6a1cc0,0x6a1cf4):
  key=hex(address)
  assert key in record['windows'], key
  match=re.search(r'\{'+key+r',\{([^}]+)\}\}',header)
  assert match, key
  assert bytes(int(n,16) for n in match.group(1).split(',')).hex()==record['windows'][key]
