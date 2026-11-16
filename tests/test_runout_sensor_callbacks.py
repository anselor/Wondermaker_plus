"""Exercise the actual four physical-head sensor templates without hardware."""
import configparser
from pathlib import Path

import jinja2
import pytest

ROOT = Path(__file__).resolve().parents[1]


def render(head, callback, *, state='printing', paused=False, active=None,
           present=False, enabled=True):
    cfg = configparser.RawConfigParser(inline_comment_prefixes=('#',))
    cfg.read(ROOT / f'config/live/extruder{head}.cfg')
    section = (f'delayed_gcode delayed_pause{head}' if callback == 'gcode'
               else f'filament_switch_sensor filament{head}')
    env = jinja2.Environment('{%', '%}', '{', '}',
                             undefined=jinja2.StrictUndefined)
    printer = {
        'print_stats': {'state': state},
        'pause_resume': {'is_paused': paused},
        'save_variables': {'variables': {
            'current_extruder': head if active is None else active}},
        f'filament_switch_sensor filament{head}': {
            'enabled': enabled, 'filament_detected': present},
        'gcode_macro G29': {'bed_leveling': False},
        'idle_timeout': {'state': 'Printing'},
    }
    text = env.from_string(cfg[section][callback]).render(
        printer=printer, action_respond_info=lambda _: '')
    return [line.strip() for line in text.splitlines() if line.strip()]


@pytest.mark.parametrize('head', range(4))
def test_active_runout_schedules_check_and_still_absent_pauses(head):
    detected = render(head, 'runout_gcode')
    assert detected[-1] == f'UPDATE_DELAYED_GCODE ID=delayed_pause{head} DURATION=2.5'
    assert 'PAUSE' not in detected
    delayed = render(head, 'gcode')
    assert delayed[-1] == 'PAUSE'
    assert len(delayed) == 2  # report, then the normal guarded pause path


@pytest.mark.parametrize('head', range(4))
@pytest.mark.parametrize('changed', [
    {'present': True}, {'enabled': False}, {'active': 99},
    {'state': 'standby'}, {'state': 'complete'}, {'state': 'cancelled'},
    {'state': 'error'}, {'state': 'paused'}, {'paused': True},
])
def test_delayed_callback_rechecks_current_state(head, changed):
    assert render(head, 'gcode', **changed) == []


@pytest.mark.parametrize('head', range(4))
def test_inactive_head_cannot_pause_other_head(head):
    for active in range(4):
        if active != head:
            assert render(head, 'runout_gcode', active=active) == []
            assert render(head, 'gcode', active=active) == []


@pytest.mark.parametrize('head', range(4))
@pytest.mark.parametrize('state,paused', [
    ('printing', False), ('paused', True), ('standby', False),
])
def test_reinsertion_cancels_timer_without_autoload(head, state, paused):
    assert render(head, 'insert_gcode', state=state, paused=paused,
                  present=True) == [
        f'UPDATE_DELAYED_GCODE ID=delayed_pause{head} DURATION=0']


@pytest.mark.parametrize('head', range(4))
@pytest.mark.parametrize('state,paused', [
    ('standby', False), ('paused', True), ('printing', True),
])
def test_runout_outside_active_print_does_not_schedule(head, state, paused):
    assert render(head, 'runout_gcode', state=state, paused=paused) == []
