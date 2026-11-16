import pytest
from test_wm_material import material, print_material, start_command


def test_sequenced_print_requests_do_not_exhaust_or_replay(print_material):
    material, objects, request, path = print_material
    material._print_requests = {'old-%d' % i for i in range(1024)}
    for sequence in range(1, 1030):
        candidate = dict(request, id='print_%d' % sequence, sequence=sequence)
        assert material._print_service()._remember_print_ticket(candidate)
        assert not material._print_service()._remember_print_ticket(candidate)
    assert len(material._print_requests) == 1024
    assert not material._print_service()._remember_print_ticket(dict(request, id='print_1', sequence=1))


@pytest.mark.parametrize('sensor', ['empty', 'unknown'])
def test_confirmation_never_overrides_empty_sensor(print_material, sensor):
    material, objects, request, path = print_material
    request['material_confirmation'] = True
    material._filament_state()._sensor_filament_status = lambda now: {'h2': {'state': sensor}}
    with pytest.raises(ValueError, match='sensor is empty or unavailable'):
        material.cmd_START_PRINT(start_command(request))
    assert objects['gcode'].scripts == []


def test_present_filament_missing_profile_can_be_explicitly_confirmed(print_material):
    material, objects, request, path = print_material
    material._material_settings()._profiles = lambda: ({}, 'empty-revision')
    material._filament_state()._loaded_filament_status = lambda now: {}
    request.update(profile_revision='empty-revision', material_confirmation=True)
    material.cmd_START_PRINT(start_command(request))
    assert material.print_submission['state'] == 'submitted'


def test_sliced_material_mismatch_requires_confirmation(print_material):
    material, objects, request, path = print_material
    request['sliced_materials'] = {'0': 'ABS'}
    with pytest.raises(ValueError, match='Confirm filament'):
        material.cmd_START_PRINT(start_command(request))
    request.update(id='new-request', material_confirmation=True)
    material.cmd_START_PRINT(start_command(request))
    assert material.print_submission['state'] == 'submitted'


def test_staging_failure_is_optional_but_final_sensor_rechecked(print_material):
    material, objects, request, path = print_material
    def fail(*args):
        material._filament_state()._sensor_filament_status = lambda now: {'h2': {'state': 'empty'}}
        raise OSError('disk full')
    material._recovery_jobs()._stage_recovery_job = fail
    with pytest.raises(ValueError, match='sensor is empty'):
        material.cmd_START_PRINT(start_command(request))
    assert material.print_submission['state'] == 'not_started'
    assert not any(line.startswith('SDCARD_PRINT_FILE') for line in objects['gcode'].scripts)


def test_staging_failure_does_not_abort_valid_print(print_material):
    material, objects, request, path = print_material
    material._recovery_jobs()._stage_recovery_job = lambda *args: (_ for _ in ()).throw(OSError('disk full'))
    material.cmd_START_PRINT(start_command(request))
    assert material.print_submission['state'] == 'submitted'
    assert 'disk full' in material._print_recovery_error

@pytest.mark.parametrize('filename', ['part#pink.gcode', 'part;pink.gcode', 'part*pink.gcode'])
def test_comment_filename_retains_vendor_sd_checks(print_material, monkeypatch, filename):
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace
    from test_wm_material import FakeCommand
    import urllib.request
    material, objects, request, path = print_material
    target = path.with_name(filename)
    path.rename(target)
    request['file']['path'] = filename
    objects['virtual_sdcard'].get_file_list = lambda recursive: [(filename, target.stat().st_size)]
    vendor = Path(__file__).resolve().parents[1] / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras/virtual_sdcard.py'
    spec = importlib.util.spec_from_file_location('b8_vendor_sd', vendor)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sd = objects['virtual_sdcard']
    sd.printer = material.printer
    sd.work_timer = None
    events = []
    sd._reset_file = lambda: events.append('reset')
    sd._load_file = lambda gcmd, name, check_subdirs: events.append(('load', name, check_subdirs))
    sd.do_resume = lambda: events.append('resume')
    sd.cmd_SDCARD_PRINT_FILE = lambda command: module.VirtualSD.cmd_SDCARD_PRINT_FILE(sd, command)
    objects['save_variables'].allVariables = {'thr_number': 4}
    class Reply:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self): return b'{"result": {}}'
    monkeypatch.setattr(urllib.request, 'urlopen', lambda *args, **kwargs: Reply())
    monkeypatch.setattr(module.os, 'statvfs', lambda path: SimpleNamespace(f_blocks=100, f_bavail=50))
    objects['gcode'].create_gcode_command = lambda cmd, line, params: FakeCommand(**params)
    run = objects['gcode'].run_script_from_command
    def dispatch(script):
        run(script)
        if script.startswith('_WMP_DISPATCH_SD_PRINT '):
            fields = dict(item.split('=', 1) for item in script.split()[1:])
            material.cmd_DISPATCH_SD_PRINT(FakeCommand(**fields))
    objects['gcode'].run_script_from_command = dispatch
    material.cmd_START_PRINT(start_command(request))
    script = objects['gcode'].scripts[-1]
    assert script.startswith('_WMP_DISPATCH_SD_PRINT ')
    params = dict(item.split('=', 1) for item in script.split()[1:])
    material.print_submission['state'] = 'pending'
    assert events == ['reset', ('load', filename, True), 'resume']
    sd.work_timer = object()
    with pytest.raises(ValueError, match='SD busy'):
        material.cmd_DISPATCH_SD_PRINT(FakeCommand(**params))
    assert len(events) == 3
    sd.work_timer = None
    material._command_generation = 1
    with pytest.raises(ValueError, match='retired'):
        material.cmd_DISPATCH_SD_PRINT(FakeCommand(**params))
    assert len(events) == 3
