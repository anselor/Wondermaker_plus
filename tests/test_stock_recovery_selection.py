"""Pin selected-file provenance needed by the future early recovery bridge."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('stock_recovery', ROOT / 'tools/inspect_stock_recovery.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_recovery_selection_provenance():
    client = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'
    if not client.exists():
        pytest.skip('reviewed vendor ELF not present')
    evidence = audit.inspect(client)
    assert evidence['literals'] == {
        'settings_path': '/home/t13dp/TM_T1/bin/plr.ini',
        'section': 'plr_print', 'file_key': 'plr_file',
        'missing_file_default': 'hanzao',
        'select_file_prefix': "SDCARD_SELECT_FILE FILENAME='",
    }
    # Both metadata and the later SD selection read the same mutable global.
    # Pin actual ADRP/ADD instructions, not just the name of a nearby symbol.
    metadata = bytes.fromhex(evidence['windows']['copy_file_for_metadata']['bytes'])
    select = bytes.fromhex(evidence['windows']['select_file_later_in_preparation']['bytes'])
    assert metadata[4:12].hex() == 'a00007f001e03f91'
    assert select[8:16].hex() == 'a00007d001e03f91'
    assert select[-4:].hex() == '6e96ff97'  # BL run_a_gcode at 0x614338


def test_unreviewed_client_rejected_before_symbol_inspection(tmp_path):
    client = tmp_path / 'client'
    client.write_bytes(b'not the reviewed ELF')
    with pytest.raises(ValueError, match='Unsupported client'):
        audit.inspect(client)


def test_recovery_preparation_uses_separate_head_and_mapping_globals():
    client = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'
    if not client.exists():
        pytest.skip('reviewed vendor ELF not present')
    evidence = audit.inspect(client)
    assert evidence['symbols']['current_extruder_backup'] == {
        'address': '0xe645710', 'size': 4, 'type': 'OBJECT'}
    assert evidence['symbols']['box_modify_t_backup']['address'] == '0x385c4e8'
    assert evidence['windows']['capture_resume_head']['bytes'] == 'c000079000401c91000040b9e06b0eb9'
    # Both sprintf arguments load the loop index: stock first writes identity
    # mappings, not the committed job's sliced-tool mapping.
    assert evidence['windows']['identity_map_before_heating']['bytes'][8:24] == 'e37f4eb9e27f4eb9'
    calls = evidence['preparation_command_calls']
    assert len(calls) == 41
    assert calls.index('0x62dad8') < calls.index('0x62db34') < calls.index('0x62dff4')
    assert calls.index('0x62e168') < calls.index('0x62e980') < calls.index('0x62eaa0')


def test_stock_recovery_prompt_requires_interrupted_record_at_ready():
    client = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'
    if not client.exists():
        pytest.skip('reviewed vendor ELF not present')
    evidence = audit.inspect(client)
    assert evidence['prompt_literals'] == {
        'interrupted_key': 'was_interrupted',
        'missing_default': 'False', 'required_value': 'True',
    }
    windows = evidence['windows']
    # Disabled PLR bypasses the interrupted-record lookup entirely.
    assert windows['prompt_enabled_gate']['bytes'] == '809101d000400e91000040391f000071800b0054'
    # Compare the recorded string to True; missing/default False cannot qualify.
    assert windows['prompt_interrupted_comparison']['bytes'] == '601200f001601c91c00007d000403f91ff23fa97001c00121f0000718000005433008052'
    # Ready initialization requires both if_need_plr() and plr_load_AorB().
    assert windows['prompt_ready_gates']['bytes'] == '24a2ff97001c00121f000071e0000054b0a2ff97001c00121f000071600000542000805202000014000080521f00007100070054'
    # Only then does it invoke draw_pop(3). This is not a replayable test action.
    assert windows['prompt_draw']['bytes'] == '6000805211ccfb97'


def test_native_recovery_cancel_deletes_records_then_parks():
    client = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'
    if not client.exists():
        pytest.skip('reviewed vendor ELF not present')
    evidence = audit.inspect(client)
    assert evidence['cancel_command'] == 'PARK_CURRENT_TOOL'
    block = bytes.fromhex(evidence['windows']['prompt_cancel_prefix']['bytes'])
    def bl_target(address):
        offset = address - 0x5304e4
        word = int.from_bytes(block[offset:offset + 4], 'little')
        assert word >> 26 == 0b100101
        displacement = word & 0x3ffffff
        if displacement & 0x2000000:
            displacement -= 0x4000000
        return address + displacement * 4
    assert bl_target(0x530500) == 0x630fac  # reset_plr_files
    assert bl_target(0x53052c) == 0x614338  # run_a_gcode(PARK_CURRENT_TOOL)
