"""Execute the retained WM pause/resume handoff with each supported owner.

This qualifies WM's boundary, not an unavailable third-party AFC wrapper.
"""
import pytest
from test_config_macros import HeaterModel, ROOT


def commands(model, name):
    script = model.templates[name].render(printer=model.p, params={}, rawparams="",
        action_respond_info=lambda *args: '', resume_bed=60,
        resume_temperature0=220, resume_temperature1=0,
        resume_temperature2=0, resume_temperature3=0, fan=128, afan=0, airfan=0)
    return [line.strip() for line in script.splitlines()
            if line.strip() and not line.strip().startswith('#')]


@pytest.mark.parametrize('owner', [None, 'openace', 'AFC'])
@pytest.mark.parametrize('entry', ['RESUME', 'M24'])
def test_owner_pause_then_resume_dispatches_only_its_own_helpers(owner, entry):
    model = HeaterModel(ROOT / 'config/live')
    model.p.update(wm_material={'paused_filament': {'wipe_completed': True}})
    model.p['heater_bed']['target'] = 60
    model.p['print_stats']['filename'] = 'part.gcode'
    model.p['gcode_macro _WMP_RECOVERY_BEGIN'] = {'active': False}
    variables = model.p['save_variables']['variables']
    variables['wmp_print_context'] = {}
    for i in range(4): variables['box_modify_t%d_backup' % i] = i
    if owner: model.p[owner] = {}
    emitted = []
    def dispatch(name):
        for line in commands(model, name):
            command = line.split()[0]
            if command in ('RESUME', 'M24'):
                dispatch(command)
                continue
            emitted.append(line)
            if command == 'BASE_PAUSE': model.p['pause_resume']['is_paused'] = True
            if command == 'CLEAR_PAUSE': model.p['pause_resume']['is_paused'] = False
    dispatch('PAUSE')
    assert model.p['pause_resume']['is_paused'] is True
    pause_end = len(emitted)
    dispatch(entry)
    names = [line.split()[0] for line in emitted]
    assert names.count('BASE_PAUSE') == 1
    assert names.count('M9924') == 1  # no recursive resume or duplicate SD start
    if owner:
        assert not any(name.startswith('WMP_') for name in names)
        if entry == 'RESUME':
            # A stale WM wiped flag must not suppress the retained owner's wipe.
            assert 'WIPE_NOZZLE' in names[pause_end:]
            assert names.index('CLEAR_PAUSE') < names.index('M9924')
    else:
        assert names.count('WMP_CAPTURE_PAUSE') == 1
        assert names.count('WMP_CHECK_RESUME') == 1
        assert names.count('WMP_PREPARE_RESUME_E') == 1
        assert names.count('WMP_RESTORE_RESUME_E') == 1
        checks = [i for i, name in enumerate(names) if name in ('WMP_CHECK_RESUME', 'WMP_PREPARE_RESUME_E')]
        assert checks[0] < names.index('TEMPERATURE_WAIT') < checks[1]
        assert checks[1] < names.index('WMP_RESTORE_RESUME_E') < names.index('CLEAR_PAUSE')
        assert 'WIPE_NOZZLE' not in names[pause_end:]


@pytest.mark.parametrize('active', [False, True])
def test_pause_distinguishes_stale_flag_from_established_pause(active):
    model = HeaterModel(ROOT / 'config/live')
    model.p.update(wm_material={}, virtual_sdcard={'is_active': active})
    model.p['pause_resume']['is_paused'] = True
    model.p['print_stats']['state'] = 'printing' if active else 'paused'
    emitted = commands(model, 'PAUSE')
    names = [line.split()[0] for line in emitted]
    if active:
        assert names.count('BASE_PAUSE') == 1
        assert names.index('CLEAR_PAUSE') < names.index('BASE_PAUSE')
        assert names.count('SAVE_GCODE_STATE') >= 1
    else:
        assert not emitted  # Do not replace saved positions or temperatures.


def test_m24_does_not_reenter_resume_for_stale_pause_flag():
    model = HeaterModel(ROOT / 'config/live')
    model.p.update(wm_material={}, virtual_sdcard={'is_active': True})
    model.p['pause_resume']['is_paused'] = True
    model.p['print_stats']['state'] = 'printing'
    model.p['gcode_macro _WMP_RECOVERY_BEGIN'] = {'active': False}
    model.p['save_variables']['variables']['wmp_print_context'] = {}
    emitted = commands(model, 'M24')
    names = [line.split()[0] for line in emitted]
    assert 'RESUME' not in names
    assert names.count('M9924') == 1
