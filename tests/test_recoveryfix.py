"""Exercise the actual preload record guard and emulate its ARM coordinate loads."""
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'client-preload/recovery-fix/wmp_recoveryfix.c'
ELF = ROOT / 'analysis/fw_1.1.08_payload/root/home/t13dp/TM_T1/bin/client'


@pytest.fixture(scope='module')
def harness(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('recoveryfix')
    src = tmp / 'harness.c'
    src.write_text('#define WMP_RECOVERYFIX_TEST\n#include "' + str(SOURCE) + '"\n' + r'''
#include <assert.h>
static int starts, loads, write_new;
static const char *fake_string(const void *p) { return p; }
static void fake_start(void) { starts++; }
static void fake_load(void *p) { (void)p; loads++; }
static void put(const char *path, const char *value) {
    FILE *f = fopen(path, "w"); assert(f); fputs(value, f); assert(!fclose(f));
}
static void fake_writer(void *name, double z, int pos, double e) {
    assert(z == 4.8 && pos == 185865 && e == 8.9);
    if (write_new) put(name, "[plr_data]\nlast_z=4.8\nlast_file_pos=185865\n");
}
int main(int argc, char **argv) {
    assert(argc == 3);
    if (!strcmp(argv[1], "identify")) {
        FILE *f = fopen(argv[2], "rb"); assert(f);
        int ok = identify(f); fclose(f); return ok ? 0 : 3;
    }
    if (!strcmp(argv[1], "words")) {
        for (size_t i = 0; i < 4; i++) {
            uint32_t words[3]; coordinate_words(words, coordinates[i].offset);
            assert(fwrite(words, sizeof words, 1, stdout) == 1);
        }
        return 0;
    }
    initialize(); /* Host executable must not match/patch. */
    assert(!chdir(argv[2]));
    char name[] = "plr_dataB.ini", marker[PATH_MAX]; uint64_t hash;
    assert(marker_path(name, marker, sizeof marker));
    string_data = fake_string; original_writer = fake_writer;
    original_loader = fake_load; original_start = fake_start;
    put(name, "[plr_data]\nlast_z=4.29526\nlast_file_pos=185865\n");
    assert(!verify_record(name, &hash));
    load_checkpoint(name); start_recovery(); assert(starts == 0 && loads == 1);
    /* A no-op writer cannot bless untouched legacy coordinates. */
    save_checkpoint(name, 4.8, 185865, 8.9);
    assert(!verify_record(name, &hash));
    /* An actual corrected write is marked and can be selected/resumed. */
    write_new = 1; save_checkpoint(name, 4.8, 185865, 8.9);
    assert(verify_record(name, &hash));
    start_recovery(); assert(starts == 0); /* cached legacy data is invalid */
    load_checkpoint(name); start_recovery(); assert(starts == 1);
    /* Stock overwrite, changed position, or partial file invalidates marker. */
    put(name, "[plr_data]\nlast_z=4.29526\nlast_file_pos=185865\n");
    assert(!verify_record(name, &hash)); start_recovery(); assert(starts == 1);
    put(name, ""); assert(!verify_record(name, &hash));
    put(name, "[plr_data]\nlast_z=4.8\nlast_file_pos=185865\n");
    put(marker, "WMP-RAW-XYZ-1 0\n"); assert(!verify_record(name, &hash));
    assert(stamp_record(name)); assert(verify_record(name, &hash));
    load_checkpoint(name);
    /* Even a newly valid record requires reloading the cached client state. */
    put(name, "[plr_data]\nlast_z=5.0\nlast_file_pos=190000\n");
    assert(stamp_record(name)); start_recovery(); assert(starts == 1);
    load_checkpoint(name); start_recovery(); assert(starts == 2);
    unlink(marker); start_recovery(); assert(starts == 2);
    return 0;
}
''')
    binary = tmp / 'harness'
    subprocess.run(['gcc', '-O2', '-Wall', '-Wextra', '-Werror', '-pthread', str(src), '-ldl', '-o', str(binary)], check=True)
    subprocess.run(['gcc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror', '-pthread', str(SOURCE), '-ldl', '-o', str(tmp / 'lib.so')], check=True)
    return binary


def test_checkpoint_format_and_cached_state_guard(harness, tmp_path):
    subprocess.run([str(harness), 'exercise', str(tmp_path)], check=True)


def test_only_reviewed_client_is_patched(harness, tmp_path):
    assert subprocess.run([str(harness), 'identify', str(harness)]).returncode == 3
    if not ELF.exists():
        pytest.skip('vendor ELF not present')
    subprocess.run([str(harness), 'identify', str(ELF)], check=True)
    changed = tmp_path / 'client'
    shutil.copyfile(ELF, changed)
    with changed.open('r+b') as f:
        f.seek(0x62f650 - 0x400000)
        original = f.read(1)
        f.seek(-1, 1)
        f.write(bytes([original[0] ^ 1]))
    assert subprocess.run([str(harness), 'identify', str(changed)]).returncode == 3


def test_arm_coordinate_loads_use_logical_xyz(harness):
    unicorn = pytest.importorskip('unicorn')
    from unicorn.arm64_const import UC_ARM64_REG_D0, UC_ARM64_REG_X0
    words = subprocess.check_output([str(harness), 'words', '-'])
    emu = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
    emu.mem_map(0x62f000, 0x1000)
    emu.mem_map(0xe645000, 0x1000)
    # Same physical point, with nonzero tool offset plus bed compensation.
    emu.mem_write(0xe645460, struct.pack('<4d', 188.078125, 252.032813, 4.29526255, 123))
    logical = [188.0, 252.3, 4.8, 8.9]
    emu.mem_write(0xe645868, struct.pack('<4f', *logical))
    for index, (address, axis) in enumerate([(0x62f648, 2), (0x62f660, 2), (0x62f6c8, 0), (0x62f72c, 1)]):
        emu.mem_write(address, words[index * 12:index * 12 + 12])
        emu.emu_start(address, address + 12)
        result = struct.unpack('<d', struct.pack('<Q', emu.reg_read(UC_ARM64_REG_D0)))[0]
        assert result == pytest.approx(logical[axis], abs=1e-5)
        assert emu.reg_read(UC_ARM64_REG_X0) == 0xe645000


def test_reviewed_prologues_and_precision_sites():
    if not ELF.exists():
        pytest.skip('vendor ELF not present')
    data = ELF.read_bytes()
    # All relocated instructions are stack/register operations, never PC relative.
    expected = {
        0x62f4bc: 'ff433dd1fd7b00a9fd030091f30b00f9',
        0x62c2a8: '0c0882d2ff632ccbfd7b00a9fd030091',
        0x62d5d8: 'ff033ad1fd7b00a9fd030091f30b00f9',
    }
    for address, prologue in expected.items():
        assert data[address - 0x400000:address - 0x400000 + 16].hex() == prologue
    for address in [0x62f630, 0x62f6b0, 0x62f714]:
        assert struct.unpack_from('<I', data, address - 0x400000)[0] == 0x52800020
