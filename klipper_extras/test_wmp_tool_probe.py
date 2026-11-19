import sys
import types
from types import SimpleNamespace as NS

import pytest

import wmp_tool_probe


class CommandError(Exception):
    pass


class Gcmd:
    error = CommandError

    def __init__(self, calls):
        self.calls = calls

    def get_float(self, name, default, **kwargs):
        return default

    def get_int(self, name, default, **kwargs):
        return default

    def get(self, name, default):
        return default

    def respond_info(self, text):
        self.calls.append(('report', text))


def make_vendor_module():
    module = types.ModuleType('fake_tools_calibrate_core')
    module.direction_types = {'x+': [0, +1], 'x-': [0, -1], 'y+': [1, +1], 'y-': [1, -1]}
    module.HINT_TIMEOUT = ' hint'

    class PrinterProbeMultiAxis:
        speed = 2.
        sample_count = 3
        sample_retract_dist = .75
        samples_tolerance = .5
        samples_retries = 3
        samples_result = 'median'

        def get_lift_speed(self, gcmd=None):
            return 5.

        def verify_no_crash(self):
            pass

        def _get_target_position(self, axis, sense, max_distance):
            pos = list(self.printer.lookup_object('toolhead').get_position())
            pos[axis] += sense * max_distance
            return pos

        def _move(self, coord, speed):
            self.printer.lookup_object('toolhead').manual_move(coord, speed)

        def _calc_mean(self, positions):
            return [sum(p[i] for p in positions) / len(positions) for i in range(3)]

        def _calc_median(self, positions, axis):
            ordered = sorted(positions, key=lambda p: p[axis])
            middle = len(positions) // 2
            if len(positions) & 1:
                return ordered[middle]
            return self._calc_mean(ordered[middle - 1:middle + 1])

        def run_probe(self, direction, gcmd, speed_ratio=1.0, samples=None, max_distance=100.0):
            raise AssertionError('vendor run_probe must be replaced')

    PrinterProbeMultiAxis.__module__ = module.__name__
    module.PrinterProbeMultiAxis = PrinterProbeMultiAxis
    return module


@pytest.fixture
def rig(monkeypatch):
    calls = []
    position = [10., 20., 5., 0.]
    # Each entry: trigger coordinate on the probing axis, 'same' for a trigger
    # a few steps from the touch start, or 'none' for no step at all.
    script = []
    module = make_vendor_module()
    monkeypatch.setitem(sys.modules, module.__name__, module)

    def manual_move(coord, speed):
        calls.append(('move', list(coord[:3])))
        position[:3] = coord[:3]

    toolhead = NS(get_position=lambda: list(position), manual_move=manual_move,
                  dwell=lambda t: calls.append(('dwell', t)),
                  wait_moves=lambda: calls.append(('wait',)))

    def probing_move(endstop, target, speed):
        axis = next(i for i in range(3) if target[i] != position[i])
        step = script.pop(0)
        if step == 'none':
            raise CommandError(wmp_tool_probe.NO_MOVEMENT)
        if step == 'timeout':
            raise CommandError('Timeout during endstop homing')
        sense = 1 if target[axis] > position[axis] else -1
        position[axis] = position[axis] + sense * .00625 if step == 'same' else step
        calls.append(('touch', round(position[axis], 6)))
        return list(position)

    endstop = NS(multi_probe_begin=lambda: calls.append(('begin',)),
                 multi_probe_end=lambda: calls.append(('end',)),
                 home_zero=lambda: calls.append(('zero',)))
    collision = NS(cmd_disable=lambda: calls.append(('collision_off',)))
    objects = {'toolhead': toolhead, 'homing': NS(probing_move=probing_move),
               'collision_detect': collision}
    printer = NS(lookup_object=lambda name, default=None: objects.get(name, default),
                 command_error=CommandError)
    probe = module.PrinterProbeMultiAxis()
    probe.printer = printer
    probe.mcu_probe = [endstop, endstop, endstop]
    probe.gcode = NS(respond_info=lambda text: calls.append(('report', text)))
    objects['tools_calibrate'] = NS(probe_multi_axis=probe)
    return NS(probe=probe, printer=printer, calls=calls, position=position,
              script=script, gcmd=Gcmd(calls), module=module)


def run(r, direction='x+', samples=None):
    return wmp_tool_probe.run_probe(r.probe, direction, r.gcmd, samples=samples)


def reports(r):
    return [c[1] for c in r.calls if c[0] == 'report']


def test_clean_group_matches_vendor_sequence(rig):
    rig.script[:] = [13., 13.003125, 13.]
    result = run(rig)
    assert result[0] == 13.
    assert [c[0] for c in rig.calls] == [
        'begin', 'dwell', 'zero',
        'touch', 'report', 'move', 'touch', 'report', 'move', 'touch', 'report', 'end']
    assert rig.calls[5] == ('move', [12.25, 20., 5.])
    assert all(text.startswith('Probe made contact at') for text in reports(rig))


def test_false_trigger_on_first_touch_is_rezeroed_and_repeated(rig):
    rig.script[:] = ['same', 13., 13., 13.]
    result = run(rig)
    assert result[0] == 13.
    assert [c[0] for c in rig.calls[:9]] == [
        'begin', 'dwell', 'zero', 'touch', 'report', 'move', 'wait', 'dwell', 'zero']
    assert rig.calls[4][1].startswith('WM+: load-cell false trigger after 0.006')
    assert rig.calls[5] == ('move', [10., 20., 5.])
    assert sum(text.startswith('Probe made contact') for text in reports(rig)) == 3
    assert 'Probe samples exceed tolerance. Retrying...' not in reports(rig)


def test_false_trigger_mid_group_keeps_earlier_touches(rig):
    rig.script[:] = [13., 'same', 13.003125, 13.]
    result = run(rig)
    assert result[0] == 13.
    # The repeat starts from the lifted position of the discarded touch.
    assert ('move', [12.25, 20., 5.]) in rig.calls
    assert rig.calls.count(('zero',)) == 2
    assert sum(text.startswith('Probe made contact') for text in reports(rig)) == 3


def test_no_movement_error_counts_as_false_trigger(rig):
    rig.script[:] = ['none', 13., 13., 13.]
    assert run(rig)[0] == 13.
    assert reports(rig)[0] == wmp_tool_probe.FALSE_TRIGGER_REPORT % 0.


def test_second_no_movement_error_is_raised(rig):
    rig.script[:] = ['none', 'none']
    with pytest.raises(CommandError, match=wmp_tool_probe.NO_MOVEMENT):
        run(rig)
    assert rig.calls[-1] == ('end',)


def test_second_false_trigger_falls_back_to_vendor_retry(rig):
    # One repeat is allowed; the next short touch is kept and the vendor
    # tolerance check restarts the group.
    rig.script[:] = ['same', 13., 'same', 13., 13., 13.]
    assert run(rig)[0] == 13.
    assert reports(rig).count('Probe samples exceed tolerance. Retrying...') == 1
    assert sum(text.startswith('WM+: load-cell false trigger') for text in reports(rig)) == 1


def test_tolerance_exhaustion_disables_collision_detect(rig):
    rig.probe.samples_retries = 0
    rig.script[:] = [13., 14.]
    with pytest.raises(CommandError, match='exceed samples_tolerance'):
        run(rig)
    assert rig.calls[-2:] == [('end',), ('collision_off',)]


def test_negative_direction_and_sample_override(rig):
    rig.script[:] = [7., 7.]
    result = run(rig, direction='y-', samples=2)
    assert result[1] == 7.
    assert ('move', [10., 7.75, 5.]) in rig.calls


def test_timeout_keeps_vendor_hint(rig):
    rig.script[:] = ['timeout']
    with pytest.raises(CommandError, match='Timeout during endstop homing hint'):
        run(rig)


def test_install_refuses_unreviewed_vendor_source(rig):
    assert wmp_tool_probe.install(rig.printer) is False
    assert 'run_probe' not in vars(rig.probe)


def test_install_replaces_reviewed_vendor_method(rig, monkeypatch):
    import hashlib
    import inspect
    source = 'def run_probe(self): pass\n'
    monkeypatch.setattr(inspect, 'getsource', lambda obj: source)
    monkeypatch.setattr(wmp_tool_probe, 'STOCK_RUN_PROBE_SHA256',
                        hashlib.sha256(source.encode()).hexdigest())
    assert wmp_tool_probe.install(rig.printer) is True
    rig.script[:] = [13., 13., 13.]
    assert rig.probe.run_probe('x+', rig.gcmd)[0] == 13.


def test_install_without_tools_calibrate(rig):
    printer = NS(lookup_object=lambda name, default=None: default)
    assert wmp_tool_probe.install(printer) is False


def test_config_section_installs_on_connect(rig, monkeypatch):
    handlers = {}
    installed = []
    monkeypatch.setattr(wmp_tool_probe, 'install', installed.append)
    printer = NS(register_event_handler=lambda name, callback: handlers.update({name: callback}))
    wmp_tool_probe.load_config(NS(get_printer=lambda: printer))
    assert installed == []
    handlers['klippy:connect']()
    assert installed == [printer]
