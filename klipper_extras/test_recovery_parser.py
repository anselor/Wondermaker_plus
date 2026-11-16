"""Exercise restoration against the retained vendor parser, without a printer."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from wm_material import WMMaterial

SOURCE = Path(__file__).resolve().parents[1] / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras/gcode_move.py'


@pytest.fixture
def parser_restore():
    if not SOURCE.exists():
        pytest.skip('retained vendor parser unavailable')
    spec = importlib.util.spec_from_file_location('vendor_gcode_move', SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    parser = module.GCodeMove.__new__(module.GCodeMove)
    parser.absolute_coord = parser.absolute_extrude = True
    parser.last_position = [11., 22., .3, 99.]  # E differs after recovery priming.
    parser.base_position = [0., 0., 0., 0.]
    parser.homing_position = [0., 0., 0., 0.]
    parser.speed, parser.speed_factor, parser.extrude_factor = 25., 1./60., 1.
    parser.Coord = lambda *values: values
    parser.printer = NS(quick_stop_flag=False)
    calls, transforms = [], []
    parser.move_with_transform = lambda position, speed: transforms.append((list(position), speed))
    class Command:
        def __init__(self, args):
            self.args = args
        def get_float(self, key, default=None, **kwargs):
            return float(self.args[key]) if key in self.args else default
        def get_int(self, key, default=None):
            return int(self.args[key]) if key in self.args else default
        def get_command_parameters(self):
            return self.args
        def error(self, message):
            return ValueError(message)
    def dispatch(script):
        calls.append(script)
        command, *tokens = script.split()
        args = dict(token.split('=', 1) if '=' in token else (token[0], token[1:]) for token in tokens)
        getattr(parser, 'cmd_' + command)(Command(args))
    objects = {'gcode_move': parser,
               'gcode': NS(get_mutex=lambda: NS(test=lambda: True), run_script_from_command=dispatch),
               'toolhead': NS(get_status=lambda now: {'position': [11., 22., .45, 99.]},
                              check_busy=lambda now: (100., 101., True))}
    material = WMMaterial.__new__(WMMaterial)
    material.printer = NS(lookup_object=lambda name: objects[name], get_reactor=lambda: NS(monotonic=lambda: 1.))
    execution = dict(gcode_position=[1., 2., .2, 12.], homing_origin=[.5, .6, .1, 0.],
                     parser_position=[11., 22., .3, 24.], machine_position=[11., 22., .45, 24.],
                     speed=12000., speed_factor=.8, extrude_factor=1.5,
                     absolute_coordinates=False, absolute_extrude=False)
    return material, parser, execution, calls, transforms, objects


@pytest.mark.parametrize('absolute,extrude', [(True, True), (True, False), (False, True), (False, False)])
def test_restore_parser_modes_and_g92_without_changing_pose(parser_restore, absolute, extrude):
    material, parser, execution, calls, transforms, objects = parser_restore
    execution.update(absolute_coordinates=absolute, absolute_extrude=extrude)
    assert material._recovery_motion()._restore_recovery_parser(execution)
    assert parser.base_position == pytest.approx([10., 20., .1, 81.])
    assert parser.last_position == [11., 22., .3, 99.]
    assert transforms == [([11., 22., .3, 99.], pytest.approx(160.))]
    assert 'G1 F12000' in calls
    assert not any('RESTORE_GCODE_STATE' in call or 'MOVE=1' in call for call in calls)


@pytest.mark.parametrize('drift', ['parser', 'machine', 'ownership', 'invalid'])
def test_restore_parser_refuses_before_dispatch(parser_restore, drift):
    material, parser, execution, calls, transforms, objects = parser_restore
    if drift == 'parser':
        parser.last_position[2] = .4
    elif drift == 'machine':
        execution['machine_position'][2] = .5
    elif drift == 'ownership':
        objects['gcode'].get_mutex = lambda: NS(test=lambda: False)
    else:
        execution['speed'] = float('nan')
    with pytest.raises(ValueError):
        material._recovery_motion()._restore_recovery_parser(execution)
    assert calls == transforms == []


def test_restore_parser_detects_ignored_command(parser_restore):
    material, parser, execution, calls, transforms, objects = parser_restore
    dispatch = objects['gcode'].run_script_from_command
    objects['gcode'].run_script_from_command = lambda script: None if script.startswith('G92') else dispatch(script)
    with pytest.raises(ValueError, match='not confirmed'):
        material._recovery_motion()._restore_recovery_parser(execution)


@pytest.mark.parametrize('motion', [(100., 99., True), (100., 101., False)])
def test_restore_parser_waits_for_actual_motion_completion(parser_restore, motion):
    material, parser, execution, calls, transforms, objects = parser_restore
    objects['toolhead'].check_busy = lambda now: motion
    with pytest.raises(ValueError, match='movement has not completed'):
        material._recovery_motion()._restore_recovery_parser(execution)
    assert calls == []


@pytest.fixture
def travel_frame(parser_restore):
    material, parser, execution, calls, transforms, objects = parser_restore
    machine = [11., 22., 300., 99.]
    objects['toolhead'].get_status = lambda now: {'position': list(machine), 'homed_axes': 'xyz'}
    active = [True]
    objects['bed_mesh'] = NS(get_mesh=lambda: object() if active[0] else None)
    parser.last_position = [11., 22., 299.8, 99.]
    parser.base_position = [5., -7., 1.2, 42.]
    parser.homing_position = [.2, -.3, .4, 0.]
    parser.absolute_coord = False
    parser.speed_factor = .7 / 60.
    original = objects['gcode'].run_script_from_command
    def dispatch(script):
        if script == 'BED_MESH_CLEAR':
            calls.append(script)
            active[0] = False
            parser.last_position = list(machine)  # vendor reset_last_position
        else:
            original(script)
    objects['gcode'].run_script_from_command = dispatch
    return material, parser, machine, calls, transforms, objects


def test_machine_frame_clears_mesh_g92_offsets_without_motion(travel_frame):
    material, parser, machine, calls, transforms, objects = travel_frame
    assert material._recovery_motion()._recovery_machine_frame(lambda: None) == machine
    assert parser.base_position[:3] == pytest.approx([0., 0., 0.])
    assert parser.base_position[3] == 42.
    assert parser.homing_position[:3] == [0., 0., 0.]
    assert parser.last_position == machine
    assert transforms == []
    assert len(calls) == 5
    assert not any(cmd.startswith(('G1 ', 'G28', 'RESTORE_GCODE_STATE')) for cmd in calls)


@pytest.mark.parametrize('ignored', ['BED_MESH_CLEAR', 'G90', 'M220', 'SET_GCODE_OFFSET', 'G92'])
def test_machine_frame_requires_each_state_change(travel_frame, ignored):
    material, parser, machine, calls, transforms, objects = travel_frame
    dispatch = objects['gcode'].run_script_from_command
    objects['gcode'].run_script_from_command = lambda script: None if script.startswith(ignored) else dispatch(script)
    with pytest.raises(ValueError, match='frame was not confirmed'):
        material._recovery_motion()._recovery_machine_frame(lambda: None)
    assert transforms == []


@pytest.mark.parametrize('failure', ['busy', 'unhomed', 'mutex', 'invalid'])
def test_machine_frame_refuses_before_commands(travel_frame, failure):
    material, parser, machine, calls, transforms, objects = travel_frame
    if failure == 'busy': objects['toolhead'].check_busy = lambda now: (100., 99., True)
    elif failure == 'unhomed': objects['toolhead'].get_status = lambda now: {'position': machine, 'homed_axes': 'xy'}
    elif failure == 'mutex': objects['gcode'].get_mutex = lambda: NS(test=lambda: False)
    else: machine[2] = float('nan')
    with pytest.raises(ValueError): material._recovery_motion()._recovery_machine_frame(lambda: None)
    assert calls == transforms == []


def test_machine_frame_stops_on_owner_change(travel_frame):
    material, parser, machine, calls, transforms, objects = travel_frame
    def guard():
        if calls: raise ValueError('owner changed')
    with pytest.raises(ValueError, match='owner changed'):
        material._recovery_motion()._recovery_machine_frame(guard)
    assert calls == ['BED_MESH_CLEAR']
