"""Exercise the actual preload record guard and emulate its ARM coordinate loads."""
from pathlib import Path
import shutil
import struct
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'client-preload/recovery-fix/wmp_recoveryfix.c'


@pytest.fixture(scope='module')
def harness(tmp_path_factory):
    tmp = tmp_path_factory.mktemp('recoveryfix')
    src = tmp / 'harness.c'
    src.write_text('#define WMP_RECOVERYFIX_TEST\n#include "' + str(SOURCE) + '"\n' + r'''
#include <assert.h>
static int starts, loads, write_new;
static int selections, accept_selection = 1;
static int reviews, accept_review = 1;
static int ready_state;
static int fake_ready(unsigned version) { assert(version == 1); return ready_state; }
static int fake_review(unsigned version, unsigned reason) {
    assert(version == 1 && (reason == 1 || reason == 2));
    reviews++; return accept_review;
}
static char selected_file[256] = "nested/part.gcode";
static int fake_selection(unsigned version, const char *file, const char *checkpoint,
                          const char *checkpoint_hash, const char *job_hash) {
    assert(version == 1 && !strcmp(file, "nested/part.gcode"));
    assert(!strcmp(checkpoint, "plr_dataB.ini"));
    assert(strlen(checkpoint_hash) == 16 && strlen(job_hash) == 16);
    selections++; return accept_selection;
}

static const char *change_material;
static const char *fake_string(const void *p) { return p; }
static void fake_start(void) { starts++; }
static void fake_load(void *p) { (void)p; loads++; }
static void put(const char *path, const char *value) {
    FILE *f = fopen(path, "w"); assert(f); fputs(value, f); assert(!fclose(f));
}
static void fake_writer(void *name, double z, int pos, double e) {
    assert(z == 4.8 && pos == 185865 && e == 8.9);
    if (write_new) put(name, "[plr_data]\nlast_z=4.8\nlast_file_pos=185865\n");
    if (change_material) put(change_material, "{\"id\":\"changed-during-write\"}");
}
int main(int argc, char **argv) {
    assert(argc == 3);
    if (!strcmp(argv[1], "identify")) {
        FILE *f = fopen(argv[2], "rb"); assert(f);
        const struct profile *ok = identify(f); fclose(f);
        if (ok) printf("%lx\n", (unsigned long)ok->selected_file);
        return ok ? 0 : 3;
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
    char job[PATH_MAX]; assert(snprintf(job, sizeof job, "%s/job.json", argv[2]) > 0);
    assert(!setenv("WMP_RECOVERY_JOB_PATH", job, 1));
    struct material_binding required_binding;
    assert(!setenv("WMP_RECOVERY_JOB_REQUIRED", "1", 1));
    assert(!material_binding(&required_binding)); /* no unmanaged downgrade */
    assert(!unsetenv("WMP_RECOVERY_JOB_REQUIRED"));
    char name[] = "plr_dataB.ini", marker[PATH_MAX]; uint64_t hash;
    assert(marker_path(name, marker, sizeof marker));
    string_data = fake_string; original_writer = fake_writer;
    original_loader = fake_load; original_start = fake_start;
    selected_file_string = selected_file; test_managed_selection = fake_selection;
    if (!strcmp(argv[1], "unready-legacy")) {
        test_managed_ready = fake_ready; ready_state = 0;
        active_profile = &profiles[0]; /* verified 1.1.08: no native UI */
        put(name, "[plr_data]\nlast_z=4.8\nlast_file_pos=185865\n");
        assert(stamp_record(name)); load_checkpoint(name); start_recovery();
        assert(starts == 1 && selections == 0);
        active_profile = &profiles[1]; start_recovery(); assert(starts == 2);
        active_profile = &profiles[2]; start_recovery(); assert(starts == 2);
        active_profile = &profiles[0];
        assert(!setenv("WMP_RECOVERY_JOB_REQUIRED", "1", 1)); start_recovery(); assert(starts == 2);
        assert(!unsetenv("WMP_RECOVERY_JOB_REQUIRED"));
        put(job, "{\"version\":1,\"state\":\"committed\",\"id\":\"job-a\"}");
        assert(stamp_record(name)); load_checkpoint(name); start_recovery(); assert(starts == 2 && selections == 0);
        ready_state = 1; start_recovery(); assert(starts == 2 && selections == 1);
        return 0;
    }
    if (!strcmp(argv[1], "missing-managed-job")) {
        test_managed_review = fake_review;
        put(name, "[plr_data]\nlast_z=4.8\nlast_file_pos=185865\n");
        assert(stamp_record(name)); /* old coordinate-only record */
        struct stat marker_info; assert(!stat(marker, &marker_info));
        assert((marker_info.st_mode & 0777) == 0644);
        load_checkpoint(name);
        start_recovery(); assert(starts == 0 && selections == 0);
        assert(reviews == 1);
        assert(!setenv("WMP_RECOVERY_JOB_REQUIRED", "0", 1));
        start_recovery(); assert(starts == 0 && selections == 0);
        accept_selection = 0; /* receiver exists even if its runtime is unavailable */
        accept_review = 0;
        start_recovery(); assert(starts == 0 && selections == 0);
        assert(verify_record(name, &hash, NULL)); /* preserve the original evidence */
        test_managed_selection = NULL; /* coordinate-fix-only installation */
        start_recovery(); assert(starts == 1 && selections == 0);
        assert(!setenv("WMP_RECOVERY_JOB_REQUIRED", "1", 1));
        start_recovery(); assert(starts == 1 && selections == 0);
        return 0;
    }
    if (!strcmp(argv[1], "material")) {
        put(name, "[plr_data]\nlast_z=4.8\nlast_file_pos=185865\n");
        assert(stamp_record(name));
        put(job, "{\"version\":1,\"state\":\"committed\",\"id\":\"job-a\"}");
        /* A legacy coordinate-only marker cannot authorize a managed job. */
        assert(!verify_record(name, &hash, NULL));
        assert(stamp_record(name)); assert(verify_record(name, &hash, NULL));
        load_checkpoint(name); start_recovery(); assert(starts == 0 && selections == 1);
        put(job, "{\"version\":1,\"state\":\"committed\",\"id\":\"job-b\"}");
        assert(!verify_record(name, &hash, NULL));
        start_recovery(); assert(starts == 0 && selections == 1);
        /* Same coordinates and new sidecar still require reloading job binding. */
        assert(stamp_record(name)); assert(verify_record(name, &hash, NULL));
        start_recovery(); assert(starts == 0 && selections == 1);
        load_checkpoint(name); start_recovery(); assert(starts == 0 && selections == 2);
        test_managed_selection = NULL; start_recovery(); assert(starts == 0 && selections == 2);
        test_managed_selection = fake_selection;
        selected_file_string = NULL; start_recovery(); assert(starts == 0 && selections == 2);
        selected_file_string = selected_file;
        selected_file[0] = 0; start_recovery(); assert(starts == 0 && selections == 2);
        strcpy(selected_file, "different.gcode"); start_recovery(); assert(starts == 0 && selections == 2);
        strcpy(selected_file, "nested/part.gcode");
        accept_selection = 0; start_recovery(); assert(starts == 0 && selections == 3);
        selections = 2; accept_selection = 1;
        put(name, "[plr_data]\nlast_z=5.0\nlast_file_pos=190000\n");
        write_new = 1; change_material = job;
        save_checkpoint(name, 4.8, 185865, 8.9);
        assert(!verify_record(name, &hash, NULL));
        change_material = NULL;
        assert(stamp_record(name)); assert(verify_record(name, &hash, NULL));
        unlink(job); assert(!verify_record(name, &hash, NULL));
        start_recovery(); assert(starts == 0 && selections == 2);
        put(job, "");
        assert(!stamp_record(name));
        unlink(job); assert(!mkdir(job, 0700)); assert(!stamp_record(name));
        assert(!rmdir(job));
        assert(!symlink(name, job)); assert(!stamp_record(name)); assert(!unlink(job));
        put(marker, ""); assert(!verify_record(name, &hash, NULL));
        return 0;
    }
    test_managed_selection = NULL; /* legacy coordinate-fix-only mode */
    put(name, "[plr_data]\nlast_z=4.29526\nlast_file_pos=185865\n");
    assert(!verify_record(name, &hash, NULL));
    load_checkpoint(name); start_recovery(); assert(starts == 0 && loads == 1);
    /* A no-op writer cannot bless untouched legacy coordinates. */
    save_checkpoint(name, 4.8, 185865, 8.9);
    assert(!verify_record(name, &hash, NULL));
    /* An actual corrected write is marked and can be selected/resumed. */
    write_new = 1; save_checkpoint(name, 4.8, 185865, 8.9);
    assert(verify_record(name, &hash, NULL));
    start_recovery(); assert(starts == 0); /* cached legacy data is invalid */
    load_checkpoint(name); start_recovery(); assert(starts == 1);
    /* Stock overwrite, changed position, or partial file invalidates marker. */
    put(name, "[plr_data]\nlast_z=4.29526\nlast_file_pos=185865\n");
    assert(!verify_record(name, &hash, NULL)); start_recovery(); assert(starts == 1);
    put(name, ""); assert(!verify_record(name, &hash, NULL));
    put(name, "[plr_data]\nlast_z=4.8\nlast_file_pos=185865\n");
    put(marker, "WMP-RAW-XYZ-1 0\n"); assert(!verify_record(name, &hash, NULL));
    assert(stamp_record(name)); assert(verify_record(name, &hash, NULL));
    load_checkpoint(name);
    /* Even a newly valid record requires reloading the cached client state. */
    put(name, "[plr_data]\nlast_z=5.0\nlast_file_pos=190000\n");
    assert(stamp_record(name)); start_recovery(); assert(starts == 1);
    load_checkpoint(name); start_recovery(); assert(starts == 2);
    char malformed[160];
    assert(file_hash(name, &hash));
    snprintf(malformed, sizeof malformed, FORMAT " %016llx garbage\n", (unsigned long long)hash);
    put(marker, malformed); assert(!verify_record(name, &hash, NULL));
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


def test_checkpoint_material_binding_and_cached_job_guard(harness, tmp_path):
    subprocess.run([str(harness), 'material', str(tmp_path)], check=True)


@pytest.mark.parametrize('version,changed_address', [
    ('1.1.08', 0x62f650),
    ('1.1.12', 0x62f9b8),
    ('1.1.13', 0x62f9a4),
])
def test_only_reviewed_client_is_patched(harness, tmp_path, version, changed_address):
    elf = ROOT / f'analysis/fw_{version}_payload/root/home/t13dp/TM_T1/bin/client'
    assert subprocess.run([str(harness), 'identify', str(harness)]).returncode == 3
    if not elf.exists():
        pytest.skip('vendor ELF not present')
    subprocess.run([str(harness), 'identify', str(elf)], check=True)
    changed = tmp_path / 'client'
    shutil.copyfile(elf, changed)
    with changed.open('r+b') as f:
        f.seek(changed_address - 0x400000)
        original = f.read(1)
        f.seek(-1, 1)
        f.write(bytes([original[0] ^ 1]))
    assert subprocess.run([str(harness), 'identify', str(changed)]).returncode == 3


@pytest.mark.parametrize('writer', [0x62f4bc, 0x62f824, 0x62f810])
def test_arm_coordinate_loads_use_logical_xyz(harness, writer):
    unicorn = pytest.importorskip('unicorn')
    from unicorn.arm64_const import UC_ARM64_REG_D0, UC_ARM64_REG_X0
    words = subprocess.check_output([str(harness), 'words', '-'])
    emu = unicorn.Uc(unicorn.UC_ARCH_ARM64, unicorn.UC_MODE_ARM)
    emu.mem_map(0x62f000, 0x2000)
    emu.mem_map(0xe645000, 0x1000)
    # Same physical point, with nonzero tool offset plus bed compensation.
    emu.mem_write(0xe645460, struct.pack('<4d', 188.078125, 252.032813, 4.29526255, 123))
    logical = [188.0, 252.3, 4.8, 8.9]
    emu.mem_write(0xe645868, struct.pack('<4f', *logical))
    for index, (address, axis) in enumerate([(writer + 0x18c, 2), (writer + 0x1a4, 2), (writer + 0x20c, 0), (writer + 0x270, 1)]):
        emu.mem_write(address, words[index * 12:index * 12 + 12])
        emu.emu_start(address, address + 12)
        result = struct.unpack('<d', struct.pack('<Q', emu.reg_read(UC_ARM64_REG_D0)))[0]
        assert result == pytest.approx(logical[axis], abs=1e-5)
        assert emu.reg_read(UC_ARM64_REG_X0) == 0xe645000


@pytest.mark.parametrize('version,expected,precision', [
    ('1.1.08', {
        0x62f4bc: 'ff433dd1fd7b00a9fd030091f30b00f9',
        0x62c2a8: '0c0882d2ff632ccbfd7b00a9fd030091',
        0x62d5d8: 'ff033ad1fd7b00a9fd030091f30b00f9',
    }, [0x62f630, 0x62f6b0, 0x62f714]),
    ('1.1.12', {
        0x62f824: 'ff433dd1fd7b00a9fd030091f30b00f9',
        0x62c600: '0c0882d2ff632ccbfd7b00a9fd030091',
        0x62d930: 'ff033ad1fd7b00a9fd030091f30b00f9',
    }, [0x62f998, 0x62fa18, 0x62fa7c]),
    ('1.1.13', {
        0x62f810: 'ff433dd1fd7b00a9fd030091f30b00f9',
        0x62c5ec: '0c0882d2ff632ccbfd7b00a9fd030091',
        0x62d91c: 'ff033ad1fd7b00a9fd030091f30b00f9',
    }, [0x62f984, 0x62fa04, 0x62fa68]),
])
def test_reviewed_prologues_and_precision_sites(version, expected, precision):
    elf = ROOT / f'analysis/fw_{version}_payload/root/home/t13dp/TM_T1/bin/client'
    if not elf.exists():
        pytest.skip('vendor ELF not present')
    data = elf.read_bytes()
    # All relocated instructions are stack/register operations, never PC relative.
    for address, prologue in expected.items():
        assert data[address - 0x400000:address - 0x400000 + 16].hex() == prologue
    for address in precision:
        assert struct.unpack_from('<I', data, address - 0x400000)[0] == 0x52800020


def test_1113_recovery_coordinate_sources_still_need_conversion():
    elf = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/bin/client'
    if not elf.exists():
        pytest.skip('vendor ELF not present')
    data = elf.read_bytes()
    # ADRP/ADD still address compensated double[4] at 0xe645460, not
    # the logical float[4] vector at 0xe645868 used by coordinate_words.
    for offset, load in [(0x18c, '000840fd'), (0x1a4, '000840fd'),
                         (0x20c, '000040fd'), (0x270, '000440fd')]:
        address = 0x62f810 + offset - 0x400000
        assert data[address:address + 12].hex() == 'a00007d000801191' + load


def test_managed_receiver_blocks_legacy_fallback_without_job_or_environment(harness, tmp_path):
    subprocess.run([str(harness), 'missing-managed-job', str(tmp_path)], check=True)


@pytest.mark.parametrize('version', ['1.1.08', '1.1.12', '1.1.13'])
def test_selected_filename_uses_verified_nonexported_stock_global(harness, version):
    elf = ROOT / f'analysis/fw_{version}_payload/root/home/t13dp/TM_T1/bin/client'
    if not elf.exists():
        pytest.skip('reviewed vendor ELF not present')
    symbol = '_Z14plr_gcode_pathB5cxx11'
    dynamic = subprocess.check_output(['readelf', '--dyn-syms', '-W', str(elf)], text=True)
    assert symbol not in dynamic  # dlsym cannot resolve this stock global.
    symbols = subprocess.check_output(['readelf', '-Ws', str(elf)], text=True)
    entry = next(line.split() for line in symbols.splitlines() if line.endswith(symbol))
    address = int(subprocess.check_output([str(harness), 'identify', str(elf)]), 16)
    assert address == int(entry[1], 16) and entry[2:4] == ['32', 'OBJECT']


def test_exported_unready_receiver_does_not_claim_legacy_ownership(harness, tmp_path):
    subprocess.run([str(harness), 'unready-legacy', str(tmp_path)], check=True)
