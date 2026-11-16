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
    ('1.1.13', 0x51A7B4, 0x614338),
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


@pytest.mark.parametrize('unified', [False, True])
def test_resume_and_automatic_recovery_ownership(tmp_path, unified):
    source = tmp_path / 'resume.c'
    source.write_text('#define WMP_OPENACE_TEST\n' +
        ('#define WMP_UNIFIED_FILAMENT\n' if unified else '') +
        '#include "' + str(SOURCE) + '"\n' + r'''#include <assert.h>
static int stock_calls, sent;
static void stock(void) { ++stock_calls; }
static void send_command(const char *command) {
    assert(!strcmp(command, "RESUME")); ++sent;
}
int main(void) {
    for (int presence = -1; presence <= 1; ++presence) {
        stock_calls = sent = 0;
        dispatch_resume_prepare(presence, stock, send_command);
#ifdef WMP_UNIFIED_FILAMENT
        assert(sent == 1 && stock_calls == 0);
#else
        assert(sent == (presence > 0) && stock_calls == (presence <= 0));
#endif
        stock_calls = sent = 0;
        wmp_dispatch_runout_purge(presence, stock);
        wmp_dispatch_resume_check(presence, stock);
#ifdef WMP_UNIFIED_FILAMENT
        assert(stock_calls == 0 && sent == 0);
#else
        assert(stock_calls == (presence == 0 ? 2 : 0) && sent == 0);
#endif
    }
    return 0;
}
''')
    binary = tmp_path / 'resume'
    subprocess.run(['gcc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-Wno-unused-function', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
    # Compile the actual non-test callback bodies too, for both build modes.
    subprocess.run(['gcc', '-shared', '-fPIC', '-pthread', '-O2', '-Wall', '-Wextra', '-Werror',
                    *(['-DWMP_UNIFIED_FILAMENT'] if unified else []), str(SOURCE),
                    '-ldl', '-o', str(tmp_path / 'callbacks.so')], check=True)
