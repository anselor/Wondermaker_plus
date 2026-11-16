"""The checked-in native profile is entirely reproducible from the stock ELF."""
from pathlib import Path
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT/'client-preload/unified-ui/native'


def test_profile_generator_reproduces_fonts_data_and_entry_windows(tmp_path):
    client = ROOT/'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'
    if not client.is_file():
        pytest.skip('exact stock client required')
    generator = tmp_path/'make_profile.py'
    generator.write_bytes((NATIVE/'make_profile.py').read_bytes())
    subprocess.run([sys.executable, str(generator), str(client)], check=True)
    for name in ('profile1113.hpp', 'profile1113.json'):
        assert (tmp_path/name).read_bytes() == (NATIVE/name).read_bytes()
