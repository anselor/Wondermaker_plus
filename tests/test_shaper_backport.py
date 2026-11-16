"""Input shaper backport: overlay contents and installer behaviour."""
import hashlib
import importlib
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[1]
OVERLAY = REPO / 'klipper_backport/input_shaper/klippy'

sys.path.insert(0, str(REPO / 'tools'))
import shaper_backport as tool  # noqa: E402


# ------------------------------------------------------------ overlay files

def test_overlay_matches_installer_file_list():
    present = sorted(str(p.relative_to(OVERLAY)) for p in OVERLAY.rglob('*')
                     if p.is_file() and '__pycache__' not in p.parts)
    assert present == tool.FILES


def test_overlay_does_not_call_interfaces_missing_from_vendor_base():
    for rel in tool.FILES:
        text = (OVERLAY / rel).read_text()
        code = '\n'.join(line for line in text.splitlines()
                         if not line.lstrip().startswith(('#', '//')))
        assert 'lookup_object("motion_queuing")' not in code, rel
        assert 'toolhead.set_max_velocities(' not in code, rel
        assert 'toolhead.limit_next_junction_speed(' not in code, rel
        assert 'ffi_lib.input_shaper_update_sk' not in code, rel


def test_local_changes_are_marked():
    marked = {rel: (OVERLAY / rel).read_text().count('>>> wondermaker+ begin')
              for rel in tool.FILES}
    assert marked['chelper/kin_shaper.c'] == 1
    assert marked['extras/input_shaper.py'] == 2
    assert marked['extras/resonance_tester.py'] == 2
    # Unmodified upstream files
    assert marked['mathutil.py'] == 0
    assert marked['extras/shaper_defs.py'] == 0
    assert marked['extras/shaper_calibrate.py'] == 0
    for rel in tool.FILES:
        text = (OVERLAY / rel).read_text()
        assert (text.count('>>> wondermaker+ begin')
                == text.count('<<< wondermaker+ end')), rel


def test_c_helper_keeps_scan_window_function():
    source = (OVERLAY / 'chelper/kin_shaper.c').read_text()
    assert 'input_shaper_get_step_generation_window(' in source


# ------------------------------------------------- junction limit shim

@pytest.fixture
def resonance_tester(monkeypatch):
    monkeypatch.syspath_prepend(str(OVERLAY))
    for name in [n for n in sys.modules
                 if n == 'extras' or n.startswith('extras.')
                 or n in ('mathutil', 'queuelogger')]:
        monkeypatch.delitem(sys.modules, name)
    monkeypatch.setitem(sys.modules, 'queuelogger', SimpleNamespace())
    module = importlib.import_module('extras.resonance_tester')
    yield module
    for name in [n for n in sys.modules
                 if n == 'extras' or n.startswith('extras.')]:
        sys.modules.pop(name, None)


class StockMove:
    """Junction calculation shaped like the vendor toolhead.Move."""
    def __init__(self, cruise_v2, start_v2=0., delta_v2=1e9, kinematic=True):
        self.max_cruise_v2 = cruise_v2
        self.max_start_v2 = start_v2
        self.max_smoothed_v2 = start_v2
        self.delta_v2 = self.smooth_delta_v2 = delta_v2
        self.is_kinematic_move = kinematic

    def calc_junction(self, prev_move):
        if not self.is_kinematic_move or not prev_move.is_kinematic_move:
            return
        self.max_start_v2 = min(self.max_cruise_v2, prev_move.max_cruise_v2,
                                prev_move.max_start_v2 + prev_move.delta_v2)
        self.max_smoothed_v2 = min(
            self.max_start_v2,
            prev_move.max_smoothed_v2 + prev_move.smooth_delta_v2)


class NativeMove(StockMove):
    """The same calculation with the upstream junction limit term."""
    def __init__(self, *args, **kwargs):
        StockMove.__init__(self, *args, **kwargs)
        self.next_junction_v2 = 999999999.9

    def calc_junction(self, prev_move):
        if not self.is_kinematic_move or not prev_move.is_kinematic_move:
            return
        self.max_start_v2 = min(self.max_cruise_v2, prev_move.max_cruise_v2,
                                prev_move.next_junction_v2,
                                prev_move.max_start_v2 + prev_move.delta_v2)
        self.max_smoothed_v2 = min(
            self.max_start_v2,
            prev_move.max_smoothed_v2 + prev_move.smooth_delta_v2)


def fake_toolhead(monkeypatch, last_move):
    module = SimpleNamespace(Move=StockMove)
    monkeypatch.setitem(sys.modules, 'wmp_fake_toolhead', module)
    toolhead_class = type('ToolHead', (), {'__module__': 'wmp_fake_toolhead'})
    toolhead = toolhead_class()
    toolhead.lookahead = SimpleNamespace(get_last=lambda: last_move)
    return toolhead


@pytest.mark.parametrize('limit', [None, 5., 30., 80., 500.])
@pytest.mark.parametrize('kinematic', [True, False])
def test_junction_limit_matches_native_calculation(
        resonance_tester, monkeypatch, limit, kinematic):
    prev, move = StockMove(60.**2, 20.**2, 900.), StockMove(70.**2)
    native_prev = NativeMove(60.**2, 20.**2, 900.)
    native_move = NativeMove(70.**2, kinematic=kinematic)
    move.is_kinematic_move = kinematic
    toolhead = fake_toolhead(monkeypatch, prev)
    original = StockMove.calc_junction
    with resonance_tester.JunctionSpeedLimits(toolhead):
        assert StockMove.calc_junction is not original
        if limit is not None:
            resonance_tester._limit_next_junction_speed(toolhead, limit)
            native_prev.next_junction_v2 = limit**2
        move.calc_junction(prev)
    native_move.calc_junction(native_prev)
    assert StockMove.calc_junction is original
    assert move.max_start_v2 == native_move.max_start_v2
    assert move.max_smoothed_v2 == native_move.max_smoothed_v2


def test_junction_limit_is_removed_when_the_test_fails(
        resonance_tester, monkeypatch):
    toolhead = fake_toolhead(monkeypatch, None)
    original = StockMove.calc_junction
    with pytest.raises(RuntimeError):
        with resonance_tester.JunctionSpeedLimits(toolhead):
            raise RuntimeError('move out of range')
    assert StockMove.calc_junction is original


def test_junction_limit_defers_to_native_toolhead_support(
        resonance_tester, monkeypatch):
    toolhead = fake_toolhead(monkeypatch, None)
    toolhead.limit_next_junction_speed = lambda speed: None
    original = StockMove.calc_junction
    with resonance_tester.JunctionSpeedLimits(toolhead):
        assert StockMove.calc_junction is original


# ------------------------------------------------------------ installer

HOME = '/home/printer'


def stock_bytes(rel, crlf=False):
    """Stand-in stock content whose hash the test registers as known."""
    data = ('stock %s\nline two\n' % rel).encode()
    return data.replace(b'\n', b'\r\n') if crlf else data


class FakePrinter:
    def __init__(self, ready_after_restart=(True,), crlf=()):
        self.home = HOME
        self.files = {}
        self.commands = []
        self.restarts = 0
        self.pid = 1000
        self.ready_results = list(ready_after_restart)
        self.klippy_ready = True
        self.printing = 'standby'
        self.helper_time = 100
        self.source_time = 50
        self.build_ok = True
        self.builds = self.published = 0
        self.live_source_at_build = None
        for rel in tool.FILES:
            self.files[self.klippy(rel)] = stock_bytes(rel, rel in crlf)
        self.files[self.klippy('toolhead.py')] = '\n'.join(
            tool.REQUIRED_SYMBOLS['toolhead.py']).encode()
        self.files[self.klippy('chelper/__init__.py')] = '\n'.join(
            tool.REQUIRED_SYMBOLS['chelper/__init__.py']).encode()

    klippy = tool.Printer.klippy
    state = tool.Printer.state

    def read(self, path):
        return self.files.get(path)

    def write(self, path, data):
        self.files[path] = data
        if path == self.klippy(tool.C_SOURCE):
            self.source_time = self.helper_time + 10

    def run(self, command, sudo=False, timeout=60):
        self.commands.append(command)
        if command.startswith('systemctl restart'):
            self.restarts += 1
            self.pid += 1
            self.klippy_ready = (self.ready_results.pop(0)
                                 if self.ready_results else True)
            if self.klippy_ready:
                self.helper_time = self.source_time + 10
            return 0, '', ''
        if command.startswith('bash ') and command.endswith('build.sh'):
            self.builds += 1
            self.live_source_at_build = self.files[self.klippy(tool.C_SOURCE)]
            return (0, 'built\n', '') if self.build_ok else (
                1, '', 'kin_shaper.c:1: error: example')
        if command.startswith('cp ') and 'c_helper.so.wmp-new' in command:
            self.published += 1
            self.helper_time = self.source_time + 10
            return 0, '', ''
        if command.startswith('touch '):
            self.source_time = self.helper_time + 10
            return 0, '', ''
        if command.startswith('stat '):
            return 0, '%d\n%d\n' % (self.helper_time, self.source_time), ''
        return 0, '', ''

    def klippy_state(self):
        return 'ready' if self.klippy_ready else 'error'

    def klippy_pid(self):
        return self.pid

    def print_state(self):
        return self.printing

    def close(self):
        pass


@pytest.fixture
def printer(monkeypatch):
    monkeypatch.setattr(tool, 'STOCK_SHA256', {
        rel: hashlib.sha256(stock_bytes(rel)).hexdigest()
        for rel in tool.FILES})
    monkeypatch.setattr(tool.time, 'sleep', lambda seconds: None)
    monkeypatch.setattr(tool, 'clear_local_cache', lambda: None)
    return FakePrinter(crlf=('chelper/kin_shaper.c', 'extras/shaper_defs.py'))


ARGS = SimpleNamespace(dry_run=False)


def klippy_files(printer):
    return {rel: printer.files[printer.klippy(rel)] for rel in tool.FILES}


def test_stock_is_recognised_with_either_line_ending(printer):
    assert set(tool.survey(printer).values()) == {'stock'}


def test_install_replaces_files_and_keeps_exact_stock_copies(printer):
    before = klippy_files(printer)
    assert tool.cmd_install(printer, ARGS) == 0
    assert tool.describe(tool.survey(printer)) == 'installed'
    assert printer.restarts == 1
    manifest = json.loads(printer.files[printer.state('manifest.json')])
    for rel in tool.FILES:
        entry = manifest['files'][rel]
        assert printer.files[printer.state(entry['backup'])] == before[rel]


def test_install_is_idempotent(printer):
    assert tool.cmd_install(printer, ARGS) == 0
    assert tool.cmd_install(printer, ARGS) == 0
    assert printer.restarts == 1


def test_install_refuses_modified_vendor_file(printer):
    printer.files[printer.klippy('extras/input_shaper.py')] = b'vendor edit\n'
    before = dict(printer.files)
    with pytest.raises(tool.BackportError, match='input_shaper.py'):
        tool.cmd_install(printer, ARGS)
    assert printer.files == before and printer.restarts == 0


def test_install_refuses_changed_vendor_base(printer):
    printer.files[printer.klippy('toolhead.py')] = b'class ToolHead: pass\n'
    with pytest.raises(tool.BackportError, match='toolhead.py'):
        tool.cmd_install(printer, ARGS)
    assert printer.restarts == 0


@pytest.mark.parametrize('state', ['printing', 'paused'])
def test_install_refuses_during_a_print(printer, state):
    printer.printing = state
    before = dict(printer.files)
    with pytest.raises(tool.BackportError, match=state):
        tool.cmd_install(printer, ARGS)
    assert printer.files == before


def test_install_refuses_when_klipper_is_not_ready(printer):
    printer.klippy_ready = False
    with pytest.raises(tool.BackportError, match='not ready'):
        tool.cmd_install(printer, ARGS)


def test_dry_run_builds_but_replaces_nothing(printer):
    before = klippy_files(printer)
    assert tool.cmd_install(printer, SimpleNamespace(dry_run=True)) == 0
    assert klippy_files(printer) == before and printer.restarts == 0
    assert printer.builds == 1 and printer.published == 0


def test_helper_is_built_from_staging_before_any_file_is_replaced(printer):
    stock_source = printer.files[printer.klippy(tool.C_SOURCE)]
    assert tool.cmd_install(printer, ARGS) == 0
    assert printer.live_source_at_build == stock_source
    staged = printer.files[printer.state('kin_shaper.c.backport')]
    assert staged == tool.overlay_bytes(tool.C_SOURCE)
    assert printer.builds == 1 and printer.published == 1
    order = [c.split()[0] for c in printer.commands
             if c.startswith(('bash ', 'cp ', 'systemctl '))]
    assert order == ['bash', 'cp', 'systemctl']


def test_failed_build_replaces_nothing_and_does_not_restart(printer):
    printer.build_ok = False
    before = klippy_files(printer)
    with pytest.raises(tool.BackportError, match='did not build'):
        tool.cmd_install(printer, ARGS)
    assert klippy_files(printer) == before
    assert printer.restarts == 0 and printer.published == 0


def test_build_script_is_valid_shell_and_checks_required_symbols(printer):
    tool.build_helper(printer)
    script = printer.files[printer.state('build.sh')].decode()
    import subprocess
    assert subprocess.run(['bash', '-n'], input=script, text=True).returncode == 0
    for symbol in tool.REQUIRED_SYMBOLS['chelper/__init__.py']:
        assert '"%s"' % symbol in script
    assert printer.klippy('chelper') in script
    assert printer.klippy('chelper/c_helper.so') not in script


def test_failed_start_restores_stock_and_rebuilds_helper(printer):
    printer.ready_results = [False, True]
    before = klippy_files(printer)
    assert tool.cmd_install(printer, ARGS) == 2
    assert klippy_files(printer) == before
    assert printer.restarts == 2
    assert any(c.startswith('touch ') and c.endswith('kin_shaper.c')
               for c in printer.commands)
    assert tool.helper_is_current(printer)


def test_uninstall_restores_exact_stock_bytes(printer):
    before = klippy_files(printer)
    tool.cmd_install(printer, ARGS)
    assert tool.cmd_uninstall(printer, ARGS) == 0
    assert klippy_files(printer) == before
    assert printer.restarts == 2 and tool.helper_is_current(printer)


def test_uninstall_refuses_altered_stock_copy(printer):
    tool.cmd_install(printer, ARGS)
    manifest = json.loads(printer.files[printer.state('manifest.json')])
    backup = manifest['files']['extras/shaper_defs.py']['backup']
    printer.files[printer.state(backup)] = b'tampered'
    with pytest.raises(tool.BackportError, match='shaper_defs.py'):
        tool.cmd_uninstall(printer, ARGS)


def test_reinstall_after_firmware_update_keeps_valid_stock_copies(printer):
    tool.cmd_install(printer, ARGS)
    # A vendor update rewrites the files with the same stock content.
    for rel in tool.FILES:
        printer.files[printer.klippy(rel)] = stock_bytes(rel, crlf=True)
    assert tool.describe(tool.survey(printer)) == 'stock'
    assert tool.cmd_install(printer, ARGS) == 0
    assert tool.cmd_uninstall(printer, ARGS) == 0
    assert all(printer.files[printer.klippy(rel)] == stock_bytes(rel, True)
               for rel in tool.FILES)


# ---------------------------------------------------------------- component

from components import shaper as component  # noqa: E402
import install_journal  # noqa: E402


class Ctx:
    class DeployError(Exception):
        pass


@pytest.fixture
def ctx(printer, monkeypatch):
    monkeypatch.setattr(component, '_Printer', lambda ctx: printer)
    return Ctx()


def test_component_preflight_builds_without_replacing(ctx, printer):
    before = klippy_files(printer)
    component.preflight(ctx)
    assert klippy_files(printer) == before
    assert printer.builds == 1 and printer.restarts == 0


def test_component_preflight_reports_refusals(ctx, printer):
    printer.files[printer.klippy('extras/input_shaper.py')] += b'# edited\n'
    with pytest.raises(Ctx.DeployError, match='refusing to replace'):
        component.preflight(ctx)


def test_component_install_and_rollback_restore_stock(ctx, printer):
    before = klippy_files(printer)
    receipt = component.install(ctx)
    assert receipt == {'kind': 'shaper-backport', 'version': 1,
                       'before': 'stock'}
    assert tool.describe(tool.survey(printer)) == 'installed'
    component.rollback(ctx, receipt)
    assert klippy_files(printer) == before


def test_component_rollback_keeps_an_earlier_installation(ctx, printer):
    component.install(ctx)
    receipt = component.install(ctx)
    assert receipt['before'] == 'installed' and printer.restarts == 1
    component.rollback(ctx, receipt)
    assert tool.describe(tool.survey(printer)) == 'installed'


def test_component_checks_the_head_guard_before_restarting(ctx, printer,
                                                          monkeypatch):
    from components import preload
    events = []
    monkeypatch.setattr(preload, 'verify_guard',
                        lambda ctx: events.append(printer.restarts))
    ctx.installing_components = {'preload', 'shaper'}
    component.install(ctx)
    assert events == [0] and printer.restarts == 1


def test_component_does_not_restart_without_the_head_guard(ctx, printer,
                                                           monkeypatch):
    from components import preload

    def missing(ctx):
        raise Ctx.DeployError('guard not active')
    monkeypatch.setattr(preload, 'verify_guard', missing)
    ctx.installing_components = {'preload', 'shaper'}
    before = klippy_files(printer)
    with pytest.raises(Ctx.DeployError, match='guard not active'):
        component.install(ctx)
    assert klippy_files(printer) == before and printer.restarts == 0


def test_component_failed_start_raises_after_restoring(ctx, printer):
    printer.ready_results = [False, True]
    before = klippy_files(printer)
    with pytest.raises(Ctx.DeployError, match='stock files were restored'):
        component.install(ctx)
    assert klippy_files(printer) == before


@pytest.mark.parametrize('receipt', [
    None, {}, {'kind': 'shaper-backport', 'version': 1, 'before': 'other'},
    {'kind': 'shaper-backport', 'version': True, 'before': 'stock'},
    {'kind': 'other', 'version': 1, 'before': 'stock'}])
def test_component_rollback_rejects_invalid_receipts(ctx, receipt):
    with pytest.raises(Ctx.DeployError, match='Invalid'):
        component.rollback(ctx, receipt)


def test_component_is_registered_last_and_journal_accepts_its_receipt(tmp_path):
    from components import ORDER, REGISTRY
    assert ORDER[-1] == 'shaper' and REGISTRY['shaper'] is component
    assert 'shaper' in install_journal.COMPONENTS
    journal = install_journal.Journal(tmp_path / 'journal.json')
    journal.acquire()
    try:
        journal.create('printer', 'user', ['shaper'])
        journal.begin('shaper')
        receipt = {'kind': 'shaper-backport', 'version': 1, 'before': 'stock'}
        journal.prepare_component('shaper', receipt)
        assert journal.recovery_receipts() == [('shaper', receipt)]
        with pytest.raises(ValueError):
            journal.prepare_component('shaper', dict(receipt, before='x'))
    finally:
        journal.release()


@pytest.mark.parametrize('state', ['error', 'shutdown'])
def test_staging_accepts_nonready_backend_with_terminal_job(printer, monkeypatch, state):
    before=klippy_files(printer)
    monkeypatch.setattr(printer,'klippy_state',lambda:state)
    printer.printing='error'
    tool.prepare(printer)
    assert klippy_files(printer)==before and printer.restarts==0
    assert printer.builds==1 and printer.published==0


@pytest.mark.parametrize('active,pid,allowed', [('inactive',0,True),('failed',0,True),('active',123,False),('failed',123,False)])
def test_staging_unavailable_http_requires_positive_stopped_service(printer, monkeypatch, active, pid, allowed):
    before=klippy_files(printer)
    def unavailable(): raise OSError('backend unavailable')
    monkeypatch.setattr(printer,'print_state',unavailable)
    run=printer.run
    def command(cmd, **kwargs):
        if cmd.startswith('systemctl show '):
            return 0, 'LoadState=loaded\nActiveState=%s\nMainPID=%s\n'%(active,pid), ''
        return run(cmd, **kwargs)
    monkeypatch.setattr(printer,'run',command)
    if allowed:
        tool.prepare(printer)
        assert printer.builds==1
    else:
        with pytest.raises(tool.BackportError,match='not confirmed stopped'):tool.prepare(printer)
        assert printer.builds==0
    assert klippy_files(printer)==before and printer.restarts==0
