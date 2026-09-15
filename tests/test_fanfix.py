"""Compile and execute the actual sender policy and check the reviewed ELF."""
from pathlib import Path
import shutil
import struct
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'client-preload/fan-fix/wmp_fanfix.c'


@pytest.fixture(scope='module')
def harness(tmp_path_factory):
    if not shutil.which('gcc'):
        pytest.skip('gcc is needed for the preload checks')
    tmp = tmp_path_factory.mktemp('fanfix')
    src = tmp / 'fanfix.c'
    src.write_text('#define WMP_FANFIX_TEST\n#include "' + str(SOURCE) + '"\n' + r'''
#include <assert.h>
int main(int argc, char **argv) {
    if (argc == 2) {
        FILE *f = fopen(argv[1], "rb");
        if (!f) return 2;
        int ok = identify(f);
        fclose(f);
        return ok ? 0 : 3;
    }
    unsigned char jump[16];
    write_jump(jump, (uintptr_t)0x123456789abcdef0);
    uint32_t instruction; uintptr_t target;
    memcpy(&instruction, jump, 4); assert(instruction == 0x58000050U);
    memcpy(&instruction, jump + 4, 4); assert(instruction == 0xd61f0200U);
    memcpy(&target, jump + 8, 8); assert(target == (uintptr_t)0x123456789abcdef0);
    atomic_int spent = 0;
    note_explicit_request(&spent, 1);
    assert(!should_start(&spent, 0, 1, 1, 1, 0));
    assert(!should_start(&spent, 1, 0, 1, 1, 0));
    note_explicit_request(&spent, 0);
    assert(should_start(&spent, 0, 1, 1, 1, 0));
    // Stale feedback during a long G-code: never issue another request.
    for (int i = 0; i < 10000; i++) assert(!should_start(&spent, 0, 1, 1, 1, 0));
    // Feedback acknowledges ON, then user OFF: preserve user choice.
    assert(!should_start(&spent, 0, 1, 1, 1, 1));
    assert(!should_start(&spent, 0, 1, 1, 1, 0));
    // Pause/resume and temporary missing state cannot re-arm.
    assert(!should_start(&spent, 0, 0, 1, 1, 0));
    assert(!should_start(&spent, 0, 1, 1, 1, 0));
    // Host error, even before the first request, stops this print's automation.
    atomic_store(&spent, 0);
    assert(!should_start(&spent, 0, 1, 0, 1, 0));
    assert(!should_start(&spent, 0, 1, 1, 1, 0));
    // A terminal print state while ready permits the next print.
    assert(!should_start(&spent, 1, 0, 1, 1, 0));
    assert(should_start(&spent, 0, 1, 1, 1, 0));
    // An already-running fan consumes the allowance too.
    assert(!should_start(&spent, 1, 0, 1, 1, 0));
    assert(!should_start(&spent, 0, 1, 1, 1, .5f));
    assert(!should_start(&spent, 0, 1, 1, 1, 0));
    // Installed/material checks still govern automatic activation.
    assert(!should_start(&spent, 1, 0, 1, 1, 0));
    assert(!should_start(&spent, 0, 1, 1, 0, 0));
    assert(should_start(&spent, 0, 1, 1, 1, 0));
    return 0;
}
''')
    binary = tmp / 'fanfix'
    subprocess.run(['gcc', '-O2', '-Wall', '-Wextra', '-Werror', str(src), '-o', str(binary)], check=True)
    subprocess.run(['gcc', '-shared', '-fPIC', '-pthread', '-O2', '-Wall', '-Wextra', '-Werror', str(SOURCE), '-o', str(tmp / 'libwmp.so')], check=True)
    return binary


def test_automatic_requests_are_bounded_and_user_off_is_preserved(harness):
    subprocess.run([str(harness)], check=True)


def test_unknown_client_is_rejected(harness):
    assert subprocess.run([str(harness), str(harness)]).returncode == 3


def test_actual_1108_guard_and_callback_target(harness, tmp_path):
    elf = ROOT / 'analysis/fw_1.1.08_payload/root/home/t13dp/TM_T1/bin/client'
    if not elf.exists(): pytest.skip('local vendor 1.1.08 binary is not present')
    subprocess.run([str(harness), str(elf)], check=True)
    with elf.open('rb') as f:
        f.seek(0x53fe54 - 0x400000)
        assert f.read(16).hex() == 'fd7bb9a9fd030091f30b00f9e02f00b9'
        f.seek(0x6385c8 - 0x400000)
        word = struct.unpack('<I', f.read(4))[0]
        assert word >> 26 == 0b100101
        displacement = word & 0x3ffffff
        if displacement & 0x2000000: displacement -= 0x4000000
        assert 0x6385c8 + 4 * displacement == 0x53fe54
    changed = tmp_path / 'changed-client'
    shutil.copyfile(elf, changed)
    with changed.open('r+b') as f:
        f.seek(0x61a8cc - 0x400000)
        f.write(b'\0')
    assert subprocess.run([str(harness), str(changed)]).returncode == 3
