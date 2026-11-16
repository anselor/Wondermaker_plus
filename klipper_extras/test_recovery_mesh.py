"""Verify recovery mesh offsets/fade against retained vendor transform methods."""
import ast
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from wm_material import WMMaterial

SOURCE = Path(__file__).resolve().parents[1] / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras/bed_mesh.py'


@pytest.fixture
def mesh_machine():
    if not SOURCE.exists():
        pytest.skip('retained vendor mesh unavailable')
    cls = next(node for node in ast.parse(SOURCE.read_text()).body
               if isinstance(node, ast.ClassDef) and node.name == 'BedMesh')
    methods = [node for node in cls.body if isinstance(node, ast.FunctionDef)
               and node.name in ('get_z_factor', 'get_position', 'cmd_BED_MESH_OFFSET')]
    namespace = {'constrain': lambda v, lo, hi: min(hi, max(lo, v))}
    exec(compile(ast.Module(body=methods, type_ignores=[]), str(SOURCE), 'exec'), namespace)
    grid = NS(mesh_offsets=[2., -3.], calc_z=lambda x, y: .2)
    grid.set_mesh_offsets = lambda values: setattr(grid, 'mesh_offsets', list(values))
    machine = [10., 20., 0., 8.]
    mesh = NS(z_mesh=grid, get_mesh=lambda: grid, fade_start=1., fade_end=10.,
              fade_dist=9., fade_target=.1, tool_offset=.5, last_position=[0., 0., 0., 0.],
              toolhead=NS(get_position=lambda: list(machine)))
    mesh.get_status = lambda now: {'profile_name': 'wmp_print',
        'mesh_matrix': [[.2, .2], [.2, .2]], 'mesh_min': [0., 0.], 'mesh_max': [300., 300.]}
    mesh.get_z_factor = lambda z: namespace['get_z_factor'](mesh, z)
    calls = []
    def dispatch(script):
        calls.append(script)
        if script == 'BED_MESH_PROFILE_BASE LOAD=wmp_print':
            grid.mesh_offsets = [0., 0.]
            mesh.tool_offset = 0.
        else:
            args = dict(part.split('=') for part in script.split()[1:])
            command = NS(get_float=lambda key, default=None: float(args[key]) if key in args else default)
            namespace['cmd_BED_MESH_OFFSET'](mesh, command)
    objects = {'bed_mesh': mesh,
               'gcode': NS(get_mutex=lambda: NS(test=lambda: True), run_script_from_command=dispatch),
               'gcode_move': NS(reset_last_position=lambda: None)}
    printer = NS(lookup_object=lambda name, default=None: objects.get(name, default),
                 get_reactor=lambda: NS(monotonic=lambda: 1.))
    mesh.printer = printer
    material = WMMaterial.__new__(WMMaterial)
    material.printer = printer
    return material, mesh, machine, calls, namespace


@pytest.mark.parametrize('z', [0., 1., 5., 9.5, 12.])
def test_restore_runtime_offsets_and_fade_matches_vendor_inverse(mesh_machine, z):
    material, mesh, machine, calls, namespace = mesh_machine
    factor = mesh.get_z_factor(z)
    machine[2] = z + factor * .2 + (1. - factor) * .1
    execution = {'mesh_fingerprint': material._recovery_mesh_fingerprint(),
                 'mesh_offsets': [2., -3., .5], 'parser_position': [10., 20., z, 8.],
                 'machine_position': list(machine)}
    assert material._restore_recovery_mesh(execution, lambda: None)
    # Actual vendor inverse must recover the original parser position.
    assert namespace['get_position'](mesh) == pytest.approx(execution['parser_position'])
    assert mesh.get_mesh().mesh_offsets == [2., -3.]
    assert mesh.tool_offset == .5
    assert calls == ['BED_MESH_PROFILE_BASE LOAD=wmp_print', 'BED_MESH_OFFSET X=2 Y=-3 ZFADE=0.5']


@pytest.mark.parametrize('offsets', [None, [], [0., 0.], [0., 0., float('nan')], [0., 0., True]])
def test_invalid_runtime_offsets_refuse_before_restore(mesh_machine, offsets):
    material, mesh, machine, calls, namespace = mesh_machine
    with pytest.raises(ValueError, match='mesh offsets'):
        material._restore_recovery_mesh({'mesh_offsets': offsets}, lambda: None)
    assert calls == []
