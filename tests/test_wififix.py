"""Compile the real C guard; optional vendor ELF checks use local analysis files."""
import shutil
import struct
import subprocess
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'client-preload/wifi-fix/wmp_wififix.c'


@pytest.fixture(scope='module')
def harness(tmp_path_factory):
    if not shutil.which('gcc'):
        pytest.skip('gcc is needed for the preload guard checks')
    tmp = tmp_path_factory.mktemp('wififix')
    src = tmp / 'guard.c'
    src.write_text('#define WMP_WIFIFIX_TEST\n#include "' + str(SOURCE) + '"\n' + r'''
int main(int argc, char **argv) {
    if (argc != 2) return 2;
    FILE *f = fopen(argv[1], "rb");
    if (!f) return 2;
    unsigned char code[CODE_SIZE], loaded[CODE_SIZE];
    const struct profile *p = identify(f, code);
    fclose(f);
    if (!p) return 3;
    memcpy(loaded, code, CODE_SIZE);
    if (!matches_memory(p, code, loaded)) return 4;
    for (size_t i = 0; i < SITE_COUNT; i++) {
        size_t offset = p->sites[i].addr - p->entry;
        uint32_t word;
        memcpy(&word, code + offset, 4);
        if (word != p->sites[i].expect) return 5;
        uint32_t nop = NOP;
        memcpy(loaded + offset, &nop, 4);
    }
    if (!matches_memory(p, code, loaded)) return 6;
    uint32_t nop = NOP;
    memcpy(loaded + p->wrong_key - p->entry, &nop, 4);
    if (matches_memory(p, code, loaded)) return 7;
    memcpy(loaded, code, CODE_SIZE);
    loaded[0] ^= 1;
    if (matches_memory(p, code, loaded)) return 8;
    printf("%s: all sites verified, intended NOPs accepted, WRONG_KEY/other edits rejected\n", p->version);
    return 0;
}
''')
    binary = tmp / 'guard'
    subprocess.run(['gcc', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function', str(src), '-o', str(binary)], check=True)
    subprocess.run(['gcc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror', str(SOURCE), '-o', str(tmp / 'libwmp.so')], check=True)
    return binary


def test_unrecognized_executable_is_rejected(harness):
    assert subprocess.run([str(harness), str(harness)]).returncode == 3


@pytest.mark.parametrize('version,entry,disconnect,wrong,sites', [
    ('1.1.04', 0x65ffcc, 0x662bcc, 0x6605ec, [0x6604d8, 0x660700, 0x660850]),
    ('1.1.08', 0x6607a8, 0x6633a8, 0x660dc8, [0x660cb4, 0x660edc, 0x66102c]),
    ('1.1.12', 0x660d10, 0x663910, 0x661330, [0x66121c, 0x661444, 0x661594]),
])
def test_vendor_binary_guards(harness, tmp_path, version, entry, disconnect, wrong, sites):
    elf = ROOT / f'analysis/fw_{version}_payload/root/home/t13dp/TM_T1/bin/client'
    if not elf.exists():
        pytest.skip(f'local vendor {version} binary is not present')
    run = subprocess.run([str(harness), str(elf)], capture_output=True, text=True)
    assert run.returncode == 0, run.stdout + run.stderr
    assert version in run.stdout
    with elf.open('rb') as f:
        for address in [*sites, wrong]:
            f.seek(address - 0x400000)
            word = struct.unpack('<I', f.read(4))[0]
            assert word >> 26 == 0b100101  # AArch64 BL
            displacement = word & 0x3ffffff
            if displacement & 0x2000000:
                displacement -= 0x4000000
            assert address + 4 * displacement == disconnect
    changed = tmp_path / 'changed-client'
    shutil.copyfile(elf, changed)
    with changed.open('r+b') as f:
        f.seek(entry - 0x400000)
        byte = f.read(1)
        f.seek(-1, 1)
        f.write(bytes([byte[0] ^ 1]))
    assert subprocess.run([str(harness), str(changed)]).returncode == 3
