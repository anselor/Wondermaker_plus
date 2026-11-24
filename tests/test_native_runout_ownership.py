"""Unified recovery must not depend on the competing compatibility constructor."""
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / 'client-preload/unified-ui/native'


def test_native_recovery_callbacks_never_run_automatic_motion(tmp_path):
    source = tmp_path / 'callbacks.cpp'
    source.write_text('#include "native/bootstrap.cpp"\n' + r'''
#include <cassert>
#include <vector>
static std::vector<std::string> commands;
static std::vector<int> popups;
static void pop(int kind) { popups.push_back(kind); }
static void send(std::string command) { commands.push_back(command); }
int main() {
 using namespace wmp_openace;
 original_draw_pop.store(&pop);
 unified_draw_pop(99); unified_draw_pop(100);
 assert(popups.empty());
 unified_draw_pop(62); assert(popups.size()==1 && popups[0]==62);
 original_command_sender.store(&send);
 for (int i=0;i<10;++i) { unified_runout_purge(); unified_resume_check(); }
 assert(commands.empty());
 unified_resume_prepare();
 assert(commands.size()==1 && commands[0]=="RESUME");
 original_command_sender.store(nullptr);
 unified_resume_prepare();
 assert(commands.size()==1);
}
''')
    executable = tmp_path / 'callbacks'
    subprocess.run(['g++', '-std=c++11', '-Wall', '-Wextra', '-Werror', '-pthread',
                    '-I'+str(NATIVE.parent), '-I'+str(NATIVE),
                    '-I'+str(ROOT/'client-preload/openace-compat/screen1113/source/client'),
                    '-I'+str(ROOT/'client-preload/openace-compat/screen1113/source/vendor'),
                    str(source), '-o', str(executable)], check=True)
    subprocess.run([str(executable)], check=True)


def test_recovery_entries_share_verified_native_installation():
    bootstrap = (NATIVE / 'bootstrap.cpp').read_text()
    profile = json.loads((NATIVE / 'profile1113.json').read_text())
    rows = {row['name']: row for row in profile['functions']}
    entries = re.search(r'navigation_hooks\[\]=\{(.*?)\};', bootstrap, re.S).group(1)
    replacements = re.search(r'const std::uintptr_t replacements\[\]=\{(.*?)\};', bootstrap, re.S).group(1)
    addresses = re.findall(r'\{([^,{}]+),nullptr', entries)
    for symbol in ('filament_pause', 'main_filament_updates'):
        addresses = [rows[symbol]['address'] if address == 'wmp_ui::native::' + symbol else address for address in addresses]
    handlers = []
    for entry in replacements.split(','):
        entry = entry.strip()
        handler = re.fullmatch(r'reinterpret_cast<std::uintptr_t>\(&([a-z_]\w*)\)', entry)
        if handler:
            handlers.append(handler.group(1))
        else:
            # The guarded Home hook jumps past the stock filament-only tail;
            # it targets a verified continuation, not a replacement function.
            assert entry == 'wmp_ui::native::main_common_return'
            handlers.append(entry)
    assert len(addresses) == len(handlers)
    bindings = dict(zip(addresses, handlers))
    assert bindings[rows['main_filament_updates']['address']] == 'wmp_ui::native::main_common_return'
    for name, address in [('resume_prepare', '0x51a7b4'), ('runout_purge', '0x5328b4'), ('resume_check', '0x61b2c4'), ('draw_pop', '0x5352e0'), ('popup_build', '0x532da8'), ('popup_event', '0x5303e4'), ('warning_callback', '0x54c93c')]:
        assert rows[name]['address'] == address
        assert bindings[address] == 'unified_' + name
    # Backend-owned runout suppresses the duplicate factory pause; other
    # callers still use the original factory trampoline.
    assert bindings[rows['filament_pause']['address']] == 'unified_filament_pause'
    callback = bootstrap.split('extern "C" void unified_filament_pause()', 1)[1].split('extern "C"', 1)[0]
    assert 'backend_runout_owned())return' in callback
    assert 'original_filament_pause.load())original()' in callback
    compat = (ROOT / 'client-preload/openace-compat/wmp_openace_compat.c').read_text()
    init = compat.split('static void initialize(void)\n{', 1)[1]
    assert re.match(r'\s*#ifdef WMP_UNIFIED_FILAMENT.*?return;\s*#endif', init, re.S)
