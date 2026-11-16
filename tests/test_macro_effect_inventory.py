"""Static inventory must retain effects of backend-owned actuator boundaries."""
import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_coupling_effects_propagate_to_callers(tmp_path):
    # Load the actual scanner without running its repository-output entry point.
    source = ROOT / 'tools/audit_macro_effects.py'
    tree = ast.parse(source.read_text())
    definitions = [node for node in tree.body if
                   isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef))
                   or (isinstance(node, ast.Assign) and any(
                       isinstance(target, ast.Name) and target.id == 'RULES'
                       for target in node.targets))]
    namespace = {'ROOT': tmp_path}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(source), 'exec'), namespace)
    (tmp_path / 'coupling.cfg').write_text(
        '[gcode_macro LOCK]\ngcode:\n'
        '    _WMP_COUPLING_STROKE LOCK=1 SESSION=example GENERATION=0\n'
        '[gcode_macro TAKE]\ngcode:\n    LOCK\n'
        '[gcode_macro FAILED_PICKUP]\ngcode:\n    _WMP_FAILED_PICKUP_CLEANUP HEAD=2 SESSION=example GENERATION=0\n'
        '[gcode_macro DISPLAY_ONLY]\ngcode:\n    M117 Ready\n')
    rows = {row['name']: row for row in namespace['scan'](tmp_path)}
    expected = {'homing', 'axis-or-extruder-motion', 'persistent-state'}
    assert expected <= set(rows['LOCK']['direct_effects'])
    assert expected <= set(rows['TAKE']['possible_effects'])
    assert rows['TAKE']['direct_effects'] == []
    assert rows['DISPLAY_ONLY']['possible_effects'] == []

    assert {'homing', 'axis-or-extruder-motion'} <= set(rows['FAILED_PICKUP']['direct_effects'])
