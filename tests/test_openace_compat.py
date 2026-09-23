"""Exercise openACE gating, physical-heater rewriting, and ELF guards."""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'client-preload/openace-compat/wmp_openace_compat.c'


@pytest.fixture(scope='module')
def harness(tmp_path_factory):
    if not shutil.which('gcc'):
        pytest.skip('gcc is needed for the preload checks')
    tmp = tmp_path_factory.mktemp('openace-compat')
    source = tmp / 'harness.c'
    source.write_text('#define WMP_OPENACE_TEST\n#include "' + str(SOURCE) + '"\n' + r'''
#include <assert.h>
int main(int argc, char **argv) {
    if (argc == 2) {
        FILE *f = fopen(argv[1], "rb");
        if (!f) return 2;
        const struct profile *profile = identify(f);
        fclose(f);
        return profile ? 0 : 3;
    }
    char output[256];
    assert(!wmp_response_has_openace("HTTP/1.0 200 OK\r\n\r\n{\"objects\":[\"gcode\"]}"));
    assert(wmp_response_has_openace("HTTP/1.0 200 OK\r\n\r\n{\"objects\":[\"openace\"]}"));
    assert(wmp_rewrite_physical_heater("M104 T2 S220", output, sizeof output));
    assert(!strcmp(output, "SET_HEATER_TEMPERATURE HEATER=extruder2 TARGET=220"));
    assert(wmp_rewrite_physical_heater("M109 S220 T0", output, sizeof output));
    assert(!strcmp(output, "SET_HEATER_TEMPERATURE HEATER=extruder TARGET=220\n"
                           "TEMPERATURE_WAIT SENSOR=extruder MINIMUM=217.5 MAXIMUM=222.5"));
    assert(wmp_rewrite_physical_heater("m109 t3 s0", output, sizeof output));
    assert(!strcmp(output, "SET_HEATER_TEMPERATURE HEATER=extruder3 TARGET=0"));
    assert(!wmp_rewrite_physical_heater("M109 S220", output, sizeof output));
    assert(!wmp_rewrite_physical_heater("M109 T4 S220", output, sizeof output));
    assert(!wmp_rewrite_physical_heater("M109 T2 S220 R5", output, sizeof output));
    return 0;
}
''')
    binary = tmp / 'harness'
    subprocess.run([
        'gcc', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
        str(source), '-o', str(binary)], check=True)
    subprocess.run([
        'gcc', '-shared', '-fPIC', '-pthread', '-ldl', '-O2', '-Wall',
        '-Wextra', '-Werror', str(SOURCE), '-o', str(tmp / 'libwmp.so')], check=True)
    return binary


def test_openace_detection_and_heater_rewriting(harness):
    subprocess.run([str(harness)], check=True)


def test_unknown_client_is_rejected(harness):
    assert subprocess.run([str(harness), str(harness)]).returncode == 3


@pytest.mark.parametrize('version,resume,run_gcode', [
    ('1.1.08', 0x51A73C, 0x61425C),
    ('1.1.12', 0x51A7B4, 0x61434C),
])
def test_reviewed_client_guard_and_position_independent_prologues(
        harness, tmp_path, version, resume, run_gcode):
    elf = ROOT / f'analysis/fw_{version}_payload/root/home/t13dp/TM_T1/bin/client'
    if not elf.exists():
        pytest.skip(f'local vendor {version} binary is not present')
    subprocess.run([str(harness), str(elf)], check=True)
    with elf.open('rb') as f:
        f.seek(resume - 0x400000)
        assert f.read(16).hex() == 'ff032dd1fd7b00a9fd030091f30b00f9'
        f.seek(run_gcode - 0x400000)
        assert f.read(16).hex() == 'fd7bb2a9fd030091f30b00f9e01700f9'
    changed = tmp_path / f'changed-{version}'
    shutil.copyfile(elf, changed)
    with changed.open('r+b') as f:
        f.seek(resume - 0x400000)
        byte = f.read(1)
        f.seek(-1, 1)
        f.write(bytes([byte[0] ^ 1]))
    assert subprocess.run([str(harness), str(changed)]).returncode == 3
