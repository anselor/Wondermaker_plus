from pathlib import Path
import subprocess
from test_unified_ui import compile_cpp
ROOT = Path(__file__).resolve().parents[1]


def test_identification_result_and_restart_are_bound_to_backend_session(tmp_path):
    executable = tmp_path / 'identification-flow'
    compile_cpp(ROOT / 'tests/unified_ui/identification_flow.cpp', executable)
    subprocess.run([str(executable)], check=True)


def test_identification_constructor_and_retired_entries_are_exactly_profiled():
    import json
    client = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'
    data = client.read_bytes()
    profile = json.loads((ROOT / 'client-preload/unified-ui/native/profile1113.json').read_text())
    for name, address in [('setup_identification', 0x52a4cc), ('identification_event', 0x52a1e4), ('identification_worker', 0x510350), ('setup_guide_identification', 0x50fb98), ('guide_identification_refresh', 0x5100c8)]:
        row = next(r for r in profile['functions'] if r['name'] == name)
        assert int(row['address'], 16) == address
        assert bytes.fromhex(row['bytes']) == data[address-0x400000:address-0x400000+32]
    # Constructor trampoline copies only a frame prologue and argument store.
    assert data[0x52a4cc-0x400000:0x52a4cc-0x400000+16].hex() == 'fd7bbba9fd030091f30b00f9e01700f9'


def test_built_arm_retired_identification_paths_only_return(native_candidate):
    import hashlib
    import json
    import struct
    artifact = native_candidate / 'libwmp_unified_screen_candidate.so'
    manifest = json.loads(artifact.with_name('manifest.json').read_text())
    for name, digest in manifest['source_inputs'].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest, 'Rebuild stale ARM candidate'
    data = artifact.read_bytes()
    assert hashlib.sha256(data).hexdigest() == manifest['artifact']['sha256']
    symbols = subprocess.check_output(['readelf', '-Ws', str(artifact)], text=True).splitlines()
    phoff = struct.unpack_from('<Q', data, 32)[0]
    phsize, phnum = struct.unpack_from('<HH', data, 54)
    segments = [struct.unpack_from('<IIQQQQQQ', data, phoff+n*phsize) for n in range(phnum)]
    for name in ('unified_retired_identification_event', 'unified_retired_identification_worker', 'unified_retired_guide_identification_refresh'):
        entry = int(next(line.split()[1] for line in symbols if line.endswith(' ' + name)), 16)
        segment = next(s for s in segments if s[0] == 1 and s[3] <= entry < s[3]+s[5])
        offset = segment[2] + entry - segment[3]
        assert data[offset:offset+4] == bytes.fromhex('c0035fd6')  # RET; no calls, writes or commands
