"""Exercise stock accounting and stock activation across physical E frames."""
import ast
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import pytest

ROOT = Path(__file__).resolve().parents[1]
STOCK = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stock_method(path, cls, method):
    # Retain the vendor method verbatim without importing hardware dependencies.
    tree = ast.parse(path.read_text())
    node = next(n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == cls
                for n in c.body if isinstance(n, ast.FunctionDef) and n.name == method)
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[method]


@pytest.fixture
def rig():
    if not (STOCK / 'extras/print_stats.py').exists():
        pytest.skip('retained factory source is not distributed')
    stats_cls = load(STOCK / 'extras/print_stats.py', 'stock_stats').PrintStats
    activate = stock_method(STOCK / 'kinematics/extruder.py', 'PrinterExtruder', 'cmd_ACTIVATE_EXTRUDER')
    class Head:
        cmd_ACTIVATE_EXTRUDER = activate
        def __init__(self, name, position):
            self.name, self.last_position = name, position
    heads = [Head('extruder', 361.), Head('extruder1', 0.)]
    move = SimpleNamespace(position=361., factor=1.)
    move.get_status = lambda now: {'position': SimpleNamespace(e=move.position), 'extrude_factor': move.factor}
    tool = SimpleNamespace(active=heads[0], flushes=0)
    tool.get_extruder = lambda: tool.active
    def set_extruder(head, pos):
        tool.active.last_position = move.position
        tool.active = head
    tool.set_extruder = set_extruder
    def flush():
        tool.flushes += 1
    tool.flush_step_generation = flush
    stats = stats_cls.__new__(stats_cls)
    stats.gcode_move = move
    clock = SimpleNamespace(monotonic=lambda: 100.)
    stats.reactor = clock
    stats.reset()
    stats.note_start()
    stats.filament_used = 11.
    mux = ('EXTRUDER', {h.name: h.cmd_ACTIVATE_EXTRUDER for h in heads})
    objects = {'print_stats': stats, 'gcode': SimpleNamespace(mux_commands={'ACTIVATE_EXTRUDER': mux}), 'toolhead': tool}
    printer = SimpleNamespace(lookup_object=lambda name, default=None: objects.get(name, default), get_reactor=lambda: clock)
    def event(name):
        assert name == 'extruder:activate_extruder'
        move.position, move.factor = tool.active.last_position, 1.
    printer.send_event = event
    for h in heads:
        h.printer = printer
    gcmd = SimpleNamespace(respond_info=lambda message: None)
    helper = load(ROOT / 'klipper_extras/wmp_filament_accounting.py', 'accounting')
    return SimpleNamespace(stats=stats, move=move, tool=tool, printer=printer, mux=mux,
                           install=lambda: helper.install(printer), activate=lambda n: mux[1][heads[n].name](gcmd))


def test_stock_reproduction_and_fix(rig):
    rig.activate(1)
    rig.stats._update_filament_usage(100.)
    assert rig.stats.filament_used == -350.  # The unmodified stock defect.


def test_switches_count_both_heads_without_polling(rig):
    assert rig.install()
    rig.move.position += 3.
    rig.activate(1)
    assert rig.stats.filament_used == 14.
    rig.move.position = 7.
    rig.activate(0)
    rig.move.position += 2.
    rig.stats._update_filament_usage(100.)
    assert rig.stats.filament_used == 23.
    assert rig.tool.flushes == 2  # Only the stock handler's existing flushes.
    before = rig.mux[1].copy()
    assert rig.install() and rig.mux[1] == before


def test_pause_service_and_resume_do_not_count_service_extrusion(rig):
    rig.install()
    rig.move.position += 2.
    rig.stats.note_pause()
    rig.activate(1)
    rig.move.position += 30.
    rig.activate(0)
    rig.stats.note_start()
    rig.move.position += 4.
    rig.stats._update_filament_usage(100.)
    assert rig.stats.filament_used == 17.


def test_restored_total_flow_factor_retractions_and_noop(rig):
    rig.install()
    rig.stats.filament_used = 800.  # PLR's restored total must remain intact.
    rig.move.factor = 1.2
    rig.move.position += 12.
    rig.activate(1)
    assert rig.stats.filament_used == 810.
    rig.move.position -= 1.
    rig.activate(1)  # Already active: no extra stock flush, no frame change.
    assert rig.stats.filament_used == 809. and rig.tool.flushes == 1
    rig.move.position += 1.
    rig.stats._update_filament_usage(100.)
    assert rig.stats.filament_used == 810.
    rig.stats.reset()
    rig.activate(0)
    assert rig.stats.filament_used == 0.


def test_activation_error_preserves_error_and_count(rig):
    rig.install()
    rig.move.position += 2.
    def fail():
        raise ValueError('stock flush failed')
    rig.tool.flush_step_generation = fail
    with pytest.raises(ValueError, match='stock flush failed'):
        rig.activate(1)
    rig.stats._update_filament_usage(100.)
    assert rig.stats.filament_used == 13.


def test_custom_owner_is_untouched(rig):
    custom = lambda gcmd: None
    rig.mux[1]['extruder1'] = custom
    assert not rig.install()
    assert rig.mux[1]['extruder1'] is custom


@pytest.mark.parametrize('shape', ['missing', 'none', 'foreign'])
def test_unsupported_dispatcher_does_not_block_ready(rig, shape):
    gcode = rig.printer.lookup_object('gcode')
    if shape == 'missing':
        del gcode.mux_commands
    else:
        gcode.mux_commands = None if shape == 'none' else object()
    before = rig.mux[1].copy()
    assert not rig.install()
    assert rig.mux[1] == before
    assert rig.stats.filament_used == 11.
    assert not getattr(rig.stats, '_wmp_tool_frame_accounting', False)
