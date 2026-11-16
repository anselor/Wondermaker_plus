import math
from contextlib import nullcontext
from types import SimpleNamespace as NS

import pytest
from wmp_nozzle_runtime import NozzleRuntime, active_settings, runtime_changes


@pytest.fixture
def rig():
    extruder = NS(nozzle_diameter=.4, filament_area=math.pi * .875 ** 2,
                  max_extrude_ratio=.3, max_e_velocity=12., max_e_accel=120.)
    state = dict(state='standby', is_paused=False, calibration_active=False)
    config = {'settings': {'extruder': {'nozzle_diameter': .4}}, 'config': {'extruder': {}}}
    timers, flushes = [], []
    reactor = NS(NEVER=1e30, monotonic=lambda: 1.,
                 register_timer=lambda cb, when: timers.append((cb, when)) or cb,
                 update_timer=lambda cb, when: None)
    objects = {'extruder': extruder, 'toolhead': NS(flush_step_generation=lambda: flushes.append(1)),
               'configfile': NS(get_status=lambda now: config),
               'gcode': NS(get_mutex=nullcontext)}
    for name in ('print_stats', 'pause_resume', 'wmp_recovery'):
        objects[name] = NS(get_status=lambda now: state)
    objects['virtual_sdcard'] = NS(is_active=lambda: state.get('sd', False))
    printer = NS(lookup_object=lambda name, default=None: objects.get(name, default),
                 get_reactor=lambda: reactor, is_shutdown=lambda: state.get('shutdown', False))
    saved = {'extruder': .6}
    runtime = NozzleRuntime(printer, saved.__getitem__)
    return NS(**locals())


def test_idle_applies_geometry_and_only_implicit_defaults(rig):
    rig.config['config']['extruder']['max_extrude_only_velocity'] = '12'
    rig.runtime.committed('extruder', .6, 1.)
    e = rig.extruder
    assert e.nozzle_diameter == .6
    assert e.max_extrude_ratio == pytest.approx(.3 * 2.25)
    assert e.max_e_velocity == 12.
    assert e.max_e_accel == pytest.approx(270.)
    assert rig.flushes == [1] and not rig.timers
    assert rig.config['settings']['extruder']['nozzle_diameter'] == .4
    assert active_settings(rig.printer, rig.config['settings'])['extruder']['nozzle_diameter'] == .6
    rig.runtime.committed('extruder', .6, 2.)
    assert rig.flushes == [1]


@pytest.mark.parametrize('option,field', [('max_extrude_cross_section', 'max_extrude_ratio'),
    ('max_extrude_only_velocity', 'max_e_velocity'), ('max_extrude_only_accel', 'max_e_accel')])
def test_explicit_limits_preserved_independently(rig, option, field):
    changes = runtime_changes(rig.extruder, .8, {option: 'configured'})
    assert field not in changes
    assert changes['nozzle_diameter'] == .8


@pytest.mark.parametrize('busy', [{'state': 'printing'}, {'is_paused': True},
                                  {'sd': True}, {'calibration_active': True}])
def test_defers_until_actual_activity_ends_and_reads_do_not_apply(rig, busy):
    rig.state.update(busy)
    rig.runtime.committed('extruder', .6, 1.)
    rig.runtime.committed('extruder', .6, 2.)
    assert len(rig.timers) == 1 and rig.extruder.nozzle_diameter == .4
    assert rig.runtime._tick(3.) == 4.
    rig.state.update(state='standby', is_paused=False, sd=False, calibration_active=False)
    active_settings(rig.printer, rig.config['settings'])
    assert rig.extruder.nozzle_diameter == .4
    assert rig.runtime._tick(4.) == rig.reactor.NEVER
    assert rig.extruder.nozzle_diameter == .6 and not rig.runtime.pending


def test_newest_save_wins_and_saved_file_change_retires_pending(rig):
    rig.state['state'] = 'printing'
    rig.runtime.committed('extruder', .6, 1.)
    rig.saved['extruder'] = .8
    rig.runtime.committed('extruder', .8, 2.)
    rig.state['state'] = 'standby'
    rig.runtime._tick(3.)
    assert rig.extruder.nozzle_diameter == .8
    rig.state['state'] = 'printing'
    rig.saved['extruder'] = .6
    rig.runtime.committed('extruder', .6, 4.)
    rig.saved['extruder'] = .4
    rig.state['state'] = 'standby'
    rig.runtime._tick(5.)
    assert rig.extruder.nozzle_diameter == .8 and not rig.runtime.pending
    assert 'changed' in rig.runtime.errors['extruder']


def test_flush_failure_is_diagnostic_and_explicit_save_retries(rig):
    def fail():
        raise RuntimeError('planner unavailable')
    rig.objects['toolhead'].flush_step_generation = fail
    rig.runtime.committed('extruder', .6, 1.)
    assert rig.extruder.nozzle_diameter == .4 and not rig.runtime.pending
    assert rig.runtime.errors['extruder'] == 'planner unavailable'
    rig.objects['toolhead'].flush_step_generation = lambda: None
    rig.runtime.committed('extruder', .6, 2.)
    assert rig.extruder.nozzle_diameter == .6 and not rig.runtime.errors


def test_shutdown_retires_pending(rig):
    rig.state['state'] = 'printing'
    rig.runtime.committed('extruder', .6, 1.)
    rig.state['shutdown'] = True
    assert rig.runtime._tick(2.) == rig.reactor.NEVER
    assert not rig.runtime.pending and rig.extruder.nozzle_diameter == .4


@pytest.mark.parametrize('diameter', [0., -1., float('nan'), 2.])
def test_invalid_geometry_rejected_before_mutation(rig, diameter):
    with pytest.raises(ValueError):
        rig.runtime.prepare('extruder', diameter)
    assert rig.extruder.nozzle_diameter == .4 and not rig.flushes


def test_runtime_assignment_failure_restores_geometry(rig):
    class Extruder:
        def __setattr__(self, key, value):
            if key == 'max_e_velocity' and value != 12.:
                raise RuntimeError('velocity assignment failed')
            object.__setattr__(self, key, value)
    e = Extruder()
    e.__dict__.update(vars(rig.extruder))
    rig.objects['extruder'] = e
    rig.runtime.committed('extruder', .6, 1.)
    assert vars(e) == vars(rig.extruder)
    assert rig.runtime.errors['extruder'] == 'velocity assignment failed'
    assert not rig.runtime.pending


def test_timer_failure_retires_pending_without_blocking_printer(rig):
    rig.state['state'] = 'printing'
    rig.runtime.committed('extruder', .6, 1.)
    def fail():
        raise RuntimeError('mutex unavailable')
    rig.objects['gcode'].get_mutex = fail
    assert rig.runtime._tick(2.) == rig.reactor.NEVER
    assert rig.runtime.errors['extruder'] == 'mutex unavailable'
    assert not rig.runtime.pending and rig.extruder.nozzle_diameter == .4
