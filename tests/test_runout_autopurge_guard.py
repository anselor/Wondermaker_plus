"""Stock runout callback must not home/feed outside openACE's recovery flow."""
from pathlib import Path
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'client-preload/openace-compat/wmp_openace_compat.c'


def test_callback_dispatch_and_presence_fail_closed(tmp_path):
    source = tmp_path/'runout.c'
    source.write_text('#define WMP_OPENACE_TEST\n#include "'+str(SOURCE)+'"\n'+r'''
#include <assert.h>
static int calls;
static void stock(void) { calls++; }
static int checker_calls;
static void stock_checker(void) { checker_calls++; }
int main(void) {
    wmp_dispatch_runout_purge(1, stock); assert(calls == 0);
    wmp_dispatch_runout_purge(-1, stock); assert(calls == 0);
    wmp_dispatch_resume_check(1, stock_checker); assert(checker_calls == 0);
    wmp_dispatch_resume_check(-1, stock_checker); assert(checker_calls == 0);
    wmp_dispatch_runout_purge(0, stock); assert(calls == 1);
    wmp_dispatch_resume_check(0, stock_checker); assert(checker_calls == 1);
    assert(wmp_openace_presence_response("HTTP/1.1 200 OK\r\n\r\n{\"result\":{\"objects\":[\"gcode\",\"openace\"]}}") == 1);
    assert(wmp_openace_presence_response("HTTP/1.1 200 OK\r\n\r\n{\"result\":{\"objects\":[\"gcode\"]}}") == 0);
    assert(wmp_openace_presence_response(0) == -1);
    assert(wmp_openace_presence_response("HTTP/1.1 200 OK\r\n\r\n{\"result\":{\"objects\":[\"gcode\"]") == -1);
    assert(wmp_openace_presence_response("HTTP/1.1 500 Error\r\n\r\n{\"objects\":[]}") == -1);
    assert(wmp_openace_presence_response("HTTP/1.1 200 OK\r\n\r\n{\"result\":{}}") == -1);
    assert(wmp_openace_presence_response("HTTP/1.1 200 OK\r\n\r\n{\"error\":{\"objects\":[]}}") == -1);
    assert(wmp_openace_presence_response("HTTP/1.1 200 OK\r\n\r\n{\"result\":{\"objects\":[] garbage}}") == -1);
    assert(wmp_openace_presence_response("HTTP/1.1 200 OK\r\n\r\n{\"result\":{\"objects\":[false]}}") == -1);
    assert(wmp_openace_presence_response("HTTP/1.1 200 OK\r\n\r\n{\"result\":{\"objects\":[\"open\\u0061ce\"]}}") == -1);
    assert(wmp_openace_presence_response("HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\n{\"result\":{\"objects\":[]}}") == -1);
    return 0;
}
''')
    binary=tmp_path/'runout'
    subprocess.run(['gcc','-O2','-Wall','-Wextra','-Werror','-Wno-unused-function',str(source),'-o',str(binary)],check=True)
    subprocess.run([str(binary)],check=True)


@pytest.mark.parametrize('version,address', [('1.1.08',0x532850),('1.1.12',0x5328c8),('1.1.13',0x5328b4)])
def test_exact_profile_points_to_real_runout_function(tmp_path,version,address):
    elf=ROOT/f'analysis/fw_{version}_payload/root/home/t13dp/TM_T1/bin/client'
    if not elf.exists():
        pytest.skip('local vendor binary required for callback compatibility review')
    symbols=subprocess.run(['readelf','-Ws',str(elf)],text=True,capture_output=True,check=True).stdout
    row=next(line for line in symbols.splitlines() if line.endswith(' _ZL32auto_purge_after_filament_runoutv'))
    columns=row.split(); assert int(columns[1],16)==address and int(columns[2])==1168
    with elf.open('rb') as stream:
        stream.seek(address-0x400000)
        assert stream.read(16).hex()=='ff0308d1fd7b00a9fd030091f30b00f9'
    source=tmp_path/'profile.c'
    source.write_text('#define WMP_OPENACE_TEST\n#include "'+str(SOURCE)+'"\n'+r'''
#include <assert.h>
int main(int argc,char **argv) {
    assert(argc==2);FILE *f=fopen(argv[1],"rb");assert(f);
    const struct profile *p=identify(f);fclose(f);assert(p);
    assert(p->runout_purge==EXPECTED);return 0;
}
'''.replace('EXPECTED',hex(address)))
    binary=tmp_path/'profile'
    subprocess.run(['gcc','-O2','-Wall','-Wextra','-Werror','-Wno-unused-function',str(source),'-o',str(binary)],check=True)
    subprocess.run([str(binary),str(elf)],check=True)


@pytest.mark.parametrize('version,entry,size,pause_entry,pause_size,prefix', [
    ('1.1.08', 0x61b1b8, 4768, 0x61aa80, 1848, 'ff4329d1fd7b00a9fd030091f30b00f9'),
    ('1.1.12', 0x61b2d8, 5160, 0x61ab70, 1896, 'ffc32ad1fd7b01a9fd430091f31300f9'),
    ('1.1.13', 0x61b2c4, 5160, 0x61ab5c, 1896, 'ffc32ad1fd7b01a9fd430091f31300f9'),
])
def test_resume_worker_profile_and_patch_plan_preserve_initial_pause(
        tmp_path, version, entry, size, pause_entry, pause_size, prefix):
    elf = ROOT / f'analysis/fw_{version}_payload/root/home/t13dp/TM_T1/bin/client'
    if not elf.exists():
        pytest.skip('local vendor binary required for callback compatibility review')
    symbols = subprocess.check_output(['readelf', '-Ws', str(elf)], text=True)
    for symbol, expected_entry, expected_size in [
        ('_Z25filament_check_for_resumev', entry, size),
        ('_Z24filament_check_for_pausev', pause_entry, pause_size),
    ]:
        row = next(line.split() for line in symbols.splitlines() if line.endswith(' ' + symbol))
        assert (int(row[1], 16), int(row[2])) == (expected_entry, expected_size)
    with elf.open('rb') as stream:
        stream.seek(entry - 0x400000)
        assert stream.read(16).hex() == prefix  # stack/register-only prologue
    source = tmp_path / 'resume-profile.c'
    source.write_text('#define WMP_OPENACE_TEST\n#include "' + str(SOURCE) + '"\n' + r'''
#include <assert.h>
int main(int argc, char **argv) {
    assert(argc == 2);
    FILE *f = fopen(argv[1], "rb"); assert(f);
    const struct profile *p = identify(f); fclose(f); assert(p);
    assert(p->resume_check == EXPECTED_ENTRY && p->resume_check_size == EXPECTED_SIZE);
    uintptr_t sites[PATCH_SITE_COUNT];
    wmp_patch_sites(p, sites);
    assert(PATCH_SITE_COUNT == 4);
    assert(sites[0] == p->resume_prepare && sites[1] == p->run_gcode);
    assert(sites[2] == p->runout_purge && sites[3] == p->resume_check);
    /* Pause code ends exactly where the resume worker starts. Check complete
     * 16-byte write intervals, not merely inequality of their entry addresses.
     */
    for (size_t i = 0; i < PATCH_SITE_COUNT; i++)
        assert(sites[i] + 16 <= PAUSE_ENTRY || sites[i] >= PAUSE_ENTRY + PAUSE_SIZE);
    return 0;
}
'''.replace('EXPECTED_ENTRY', hex(entry)).replace('EXPECTED_SIZE', str(size))
       .replace('PAUSE_ENTRY', hex(pause_entry)).replace('PAUSE_SIZE', str(pause_size)))
    binary = tmp_path / 'resume-profile'
    subprocess.run(['gcc', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                    str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary), str(elf)], check=True)
