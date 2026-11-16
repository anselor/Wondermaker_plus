"""Execute rendered legacy routes at the admission boundary; no printer motion."""
from pathlib import Path
import re
import shlex
import jinja2
import pytest

ROOT = Path(__file__).resolve().parents[1] / 'config/live'
ENV = jinja2.Environment('{%', '%}', '{', '}', undefined=jinja2.StrictUndefined)


def render(name, params, helper=True, mapping=(2, 0, 3, 1)):
    source = (ROOT / 'macros.cfg').read_text()
    section = re.search(r'(?ms)^\[gcode_macro ' + name + r'\].*?(?=^\[|\Z)', source).group()
    script = section.split('gcode:', 1)[1]
    printer = {'toolhead': {'extruder': 'extruder2'}, 'save_variables': {'variables': {
        'box_modify_t%d' % i: head for i, head in enumerate(mapping)}}}
    if helper:
        printer['wm_material'] = {}
    def fail(message):
        raise ValueError(message)
    result = ENV.from_string(script).render(
        printer=printer, params=params,
        rawparams=' '.join(key+'='+shlex.quote(value) for key, value in params.items()),
        action_raise_error=fail)
    return [line.strip() for line in result.splitlines()
            if line.strip() and not line.lstrip().startswith('#')]


@pytest.mark.parametrize('name', ['filament_insert', 'filament_insert_gcode'])
@pytest.mark.parametrize('params', [{}, {'T': '2'}, {'HEAD': '2', 'MM': '10'}])
def test_retired_sequences_refuse_before_emitting_any_commands(name, params):
    with pytest.raises(ValueError, match='Filaments'):
        render(name, params)


@pytest.mark.parametrize('name,action', [('LOAD_FILAMENT', 'load'), ('UNLOAD_FILAMENT', 'unload')])
@pytest.mark.parametrize('head', range(4))
@pytest.mark.parametrize('mapping', [(0, 1, 2, 3), (2, 0, 3, 1)])
def test_explicit_physical_service_has_one_managed_dispatch(name, action, head, mapping):
    commands = render(name, {'HEAD': str(head), 'ID': 'console-1'}, mapping=mapping)
    assert len(commands) == 1
    assert shlex.split(commands[0]) == [
        'WMP_FILAMENT_SERVICE', 'ACTION='+action, 'HEAD='+str(head), 'ID=console-1']


@pytest.mark.parametrize('name', ['LOAD_FILAMENT', 'UNLOAD_FILAMENT'])
@pytest.mark.parametrize('params', [{'HEAD': '4'}, {'HEAD': '-1'},
                                   {'HEAD': '2.5'}, {'HEAD': '2', 'T': '0'},
                                   {'HEAD': '2', 'ACTION': 'unload'},
                                   {'HEAD': '2', 'TEMP': '220'}])
def test_legacy_service_refuses_ambiguous_or_unsupported_requests(name, params):
    with pytest.raises(ValueError, match='physical|Unsupported'):
        render(name, params)


@pytest.mark.parametrize('name', ['LOAD_FILAMENT', 'UNLOAD_FILAMENT'])
def test_no_fallback_when_managed_backend_is_missing(name):
    with pytest.raises(ValueError, match='helper'):
        render(name, {'HEAD': '2'}, helper=False)


@pytest.mark.parametrize('name,action', [('LOAD_FILAMENT', 'load'), ('UNLOAD_FILAMENT', 'unload')])
@pytest.mark.parametrize('mapping', [(0, 1, 2, 3), (2, 0, 3, 1)])
def test_legacy_t_service_selects_physical_head(name, action, mapping):
    assert render(name, {'T': '1'}, mapping=mapping) == ['WMP_FILAMENT_SERVICE ACTION='+action+' HEAD=1']
    assert render(name, {}, mapping=mapping) == ['WMP_FILAMENT_SERVICE ACTION='+action+' HEAD=0']


def test_current_head_legacy_service_never_guesses_from_mapped_heater():
    assert render('EXTRUDE_FILAMENT', {'T': '0'}) == ['WMP_FILAMENT_SERVICE ACTION=load HEAD=2']
    with pytest.raises(ValueError, match='mapping differs'):
        render('EXTRUDE_FILAMENT', {'T': '2'})
    assert render('RETRACT_FILAMENT', {}) == ['WMP_FILAMENT_SERVICE ACTION=unload HEAD=2']
