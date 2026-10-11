"""Actual C guard compatibility and the AArch64 callback entry stub."""
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'client-preload/head-config-guard/wmp_head_config_guard.c'


@pytest.fixture(scope='module')
def harness(tmp_path_factory):
    if not shutil.which('gcc'):
        pytest.skip('gcc required')
    directory = tmp_path_factory.mktemp('head-config-guard')
    source = directory / 'harness.c'
    source.write_text('#include "' + str(SOURCE) + '"\n' + r'''
#include <assert.h>
int main(int argc, char **argv) {
    unsigned char jump[16];
    write_jump(jump, (uintptr_t)0x123456789abcdef0);
    uint32_t instruction; uintptr_t target;
    memcpy(&instruction, jump, 4); assert(instruction == 0x58000050U);
    memcpy(&instruction, jump + 4, 4); assert(instruction == 0xd61f0200U);
    memcpy(&target, jump + 8, 8); assert(target == (uintptr_t)0x123456789abcdef0);
    if (argc != 2) return 2;
    FILE *f = fopen(argv[1], "rb"); if (!f) return 2;
    const struct profile *p = identify(f); fclose(f);
    return p ? 0 : 3;
}
''')
    binary = directory / 'harness'
    subprocess.run(['gcc', '-O2', '-Wall', '-Wextra', '-Werror', str(source), '-o', str(binary)], check=True)
    subprocess.run(['gcc', '-shared', '-fPIC', '-O2', '-Wall', '-Wextra', '-Werror', str(SOURCE), '-o', str(directory / 'guard.so')], check=True)
    return binary


@pytest.mark.parametrize('version,entry', [('1.1.08', 0x633c70), ('1.1.12', 0x633fd8), ('1.1.13', 0x633fc4)])
def test_only_reviewed_client_passes(harness, tmp_path, version, entry):
    assert subprocess.run([str(harness), str(harness)]).returncode == 3
    elf = ROOT / f'analysis/fw_{version}_payload/root/home/t13dp/TM_T1/bin/client'
    if not elf.exists():
        pytest.skip('vendor ELF absent')
    subprocess.run([str(harness), str(elf)], check=True)
    changed = tmp_path / 'modified-client'
    shutil.copyfile(elf, changed)
    with changed.open('r+b') as f:
        f.seek(entry - 0x400000)
        original = f.read(1)
        f.seek(-1, 1)
        f.write(bytes([original[0] ^ 1]))
    assert subprocess.run([str(harness), str(changed)]).returncode == 3
