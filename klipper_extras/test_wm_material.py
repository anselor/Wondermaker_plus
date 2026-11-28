from wm_material import parse_slot_materials, material_name, material_temp

SAMPLE = """[printer]
model=2

[slot]
; orca-color0=#8ED8F8
color0=18
material0=0
; orca-color1=#FF0000
color1=3
material1=3
material2 = 12
material3=bogus

[nozzle]
type0=0
"""


def test_parses_slots_and_skips_bad_values():
    assert parse_slot_materials(SAMPLE) == {0: 0, 1: 3, 2: 12}


def test_ignores_material_keys_outside_slot_section():
    assert parse_slot_materials("[other]\nmaterial0=5\n") == {}


def test_names_and_temps():
    assert material_name(3) == "PETG" and material_temp(3) == 250
    assert material_name(12) == "TPU" and material_temp(12) == 230
    assert material_name(-1) == "Unknown" and material_temp(99) == 0


import json
import os
from pathlib import Path
import pytest
from wm_material import WMMaterial


@pytest.fixture(autouse=True)
def filament_command_actor(monkeypatch):
    # This hardware harness is synchronous; explicit actor-switch tests below
    # model reactor callbacks without requiring Klipper's greenlet extension.
    from wmp_filament_service import FilamentService
    from wmp_toolhead_service import ToolheadService
    from wmp_plr_attempt import RecoveryLifecycle
    from wmp_stop_points import StopPoints
    actor = object()
    monkeypatch.setattr(FilamentService, '_current_actor', staticmethod(lambda: actor))
    monkeypatch.setattr(ToolheadService, '_current_actor', staticmethod(lambda: actor))
    monkeypatch.setattr(RecoveryLifecycle, '_current_actor', staticmethod(lambda: actor))
    monkeypatch.setattr(StopPoints, '_current_actor', staticmethod(lambda: actor))


class FakeCommand:
    def __init__(self, **args):
        self.args = args
    def get(self, key, *default):
        return self.args.get(key, default[0]) if default else self.args[key]
    def get_int(self, key, minval, maxval):
        value = int(self.args[key])
        if not minval <= value <= maxval:
            raise ValueError('range')
        return value
    def error(self, message):
        return ValueError(message)
    def respond_info(self, message):
        self.message = message
    def get_command_parameters(self):
        return dict(self.args)


class FakePrinter:
    def __init__(self):
        self.owner = None
        self.state = 'standby'
        self.paused = False
        self.sd_active = False
        self.from_sd = False
    def lookup_object(self, name, default=None):
        if name == 'openace':
            return self.owner
        if name in ('print_stats', 'pause_resume', 'virtual_sdcard'):
            return self
        return self if name == 'extruder2' else default
    def get_reactor(self):
        return self
    def monotonic(self):
        return 1.0
    def pause(self, waketime):
        return waketime
    def get_status(self, eventtime):
        return {'state': self.state, 'is_paused': self.paused}
    def is_active(self):
        return self.sd_active
    def is_cmd_from_sd(self):
        return self.from_sd


@pytest.fixture
def material(tmp_path):
    import queue
    obj = WMMaterial.__new__(WMMaterial)
    obj._async_completions = queue.SimpleQueue()
    obj.printer = FakePrinter()
    obj.printer.get_start_args = lambda: {"config_file": str(tmp_path / "printer.cfg")}
    obj.session_id = "test-session"
    obj._filament_checks = {}
    obj.filament_operation = {}
    obj.profile_path = str(tmp_path / 'wmp_filaments.json')
    return obj


def test_nozzle_save_reports_restart_without_changing_active_config(material, tmp_path):
    from types import SimpleNamespace
    from wmp_nozzles import NozzleSettings
    config = tmp_path / "printer.cfg"
    ini = tmp_path / "tmt1.ini"
    config.write_text("[extruder2]\nnozzle_diameter: 0.4\n")
    ini.write_text("[nozzle]\ntype2=0\n")
    material._nozzles = NozzleSettings(config, ini)
    original = material.printer.lookup_object
    active = {"extruder2": {"nozzle_diameter": 0.4}}
    material.printer.lookup_object = lambda name, default=None: SimpleNamespace(get_status=lambda now: {"settings": active}) if name == "configfile" else original(name, default)
    state = material._nozzle_status(1)
    assert state["nozzle_settings_protocol"] == 1 and not state["nozzles"]["h2"]["restart_required"]
    cmd = FakeCommand(HEAD=2, DIAMETER="0.6", MATERIAL=1, EXPECT=state["nozzle_revision"], SESSION="test-session", ID="nozzle-test")
    material.cmd_SET_NOZZLE(cmd)
    state = material._nozzle_status(1)
    assert state["nozzle_save"]["state"] == "complete"
    assert state["nozzles"]["h2"] == {"diameter": 0.6, "material": "Stainless steel", "active_diameter": 0.4, "restart_required": True, "live_update_supported": False, "apply_pending": False, "apply_error": ""}
    assert active["extruder2"]["nozzle_diameter"] == 0.4
    active["extruder2"]["nozzle_diameter"] = 0.6
    assert not material._nozzle_status(1)["nozzles"]["h2"]["restart_required"]
    with pytest.raises(ValueError, match="changed"):
        material.cmd_SET_NOZZLE(cmd)


@pytest.mark.parametrize("condition", ["owner", "afc", "session", "printing", "paused", "sd_active"])
def test_nozzle_save_admission_rejects_before_storage(material, condition):
    from types import SimpleNamespace
    material._nozzles = SimpleNamespace(save=lambda *args: pytest.fail("Rejected request reached storage"))
    if condition == "printing": material.printer.state = "printing"
    if condition == "paused": material.printer.paused = True
    if condition == "sd_active": material.printer.sd_active = True
    if condition == "owner": material.printer.owner = object()
    if condition == "afc":
        lookup = material.printer.lookup_object
        material.printer.lookup_object = lambda name, default=None: object() if name == 'AFC' else lookup(name, default)
    if condition == "operation": material.toolhead_operation = {"state": "running"}
    cmd = FakeCommand(HEAD=2, DIAMETER="0.6", MATERIAL=1, EXPECT="a" * 64, SESSION="old-session" if condition == "session" else "test-session", ID="test")
    reason = "Finish or cancel" if condition in ("printing", "paused", "sd_active") else ""
    with pytest.raises(ValueError, match=reason):
        material.cmd_SET_NOZZLE(cmd)


def profile_command(material, **updates):
    identity = {'brand': 'Generic', 'material': 'PETG', 'color': '#ab1234'}
    args = {'HEAD': '2', 'EXPECT': material._profiles()[1],
            'PROFILE': json.dumps(identity).encode().hex()}
    args.update(updates)
    return FakeCommand(**args)


def test_profiles_persist_and_reject_stale_edit(material):
    command = profile_command(material)
    material.cmd_SET_FILAMENT(command)
    profiles, revision = material._profiles()
    assert profiles == {'h2': {'brand': 'Generic', 'material': 'PETG', 'color': '#ab1234'}}
    assert revision != command.args['EXPECT']
    with pytest.raises(ValueError, match='changed'):
        material.cmd_SET_FILAMENT(command)
    assert material._profiles()[0] == profiles


def test_profile_cache_reuses_validation_but_observes_external_edits(material, monkeypatch):
    import os
    from pathlib import Path
    path = Path(material.profile_path)
    original = {'h2': {'brand': 'Generic', 'material': 'PETG', 'color': '#ab1234'}}
    path.write_text(json.dumps(original))
    calls = []
    validate = material._validate_identity
    def counted(identity):
        calls.append(dict(identity))
        validate(identity)
    monkeypatch.setattr(material, '_validate_identity', counted)
    profiles, revision = material._profiles()
    profiles['h2']['brand'] = 'Caller mutation'
    repeated, same_revision = material._profiles()
    assert repeated == original and same_revision == revision
    repeated['h2']['material'] = 'Another mutation'
    assert material._profiles()[0] == original
    assert len(calls) == 1
    stamp = path.stat()
    path.write_text(path.read_text().replace('#ab1234', '#cd5678'))
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    changed, new_revision = material._profiles()
    assert changed['h2']['color'] == '#cd5678' and new_revision != revision
    assert len(calls) == 2
    with pytest.raises(ValueError, match='changed'):
        material.cmd_SET_FILAMENT(profile_command(material, EXPECT=revision))


def test_profile_cache_never_masks_invalid_or_missing_file(material):
    from pathlib import Path
    path = Path(material.profile_path)
    valid = json.dumps({'h2': {'brand': 'Generic', 'material': 'PLA', 'color': '#123456'}})
    path.write_text(valid)
    original = material._profiles()
    for invalid in ('broken', '[]', ' ' * 16385):
        path.write_text(invalid)
        with pytest.raises(ValueError):
            material._profiles()
    path.unlink()
    empty = material._profiles()
    assert empty[0] == {} and empty[1] != original[1]
    path.write_text(valid)
    assert material._profiles() == original


@pytest.mark.parametrize('state', ['printing', 'paused', 'unknown'])
def test_profile_save_rejects_nonidle(material, state):
    material.printer.state = state
    with pytest.raises(ValueError, match='idle'):
        material.cmd_SET_FILAMENT(profile_command(material))
    assert material._profiles()[0] == {}


def test_profile_save_rejects_openace_and_unknown_head(material):
    material.printer.owner = object()
    with pytest.raises(ValueError, match='owns filament settings'):
        material.cmd_SET_FILAMENT(profile_command(material))
    material.printer.owner = None
    with pytest.raises(ValueError, match='not installed'):
        material.cmd_SET_FILAMENT(profile_command(material, HEAD='1'))


@pytest.mark.parametrize('payload', ['zz', '0', '7b', '00', 'ff', 'aa' * 513])
def test_profile_save_rejects_invalid_payload(material, payload):
    with pytest.raises(ValueError):
        material.cmd_SET_FILAMENT(profile_command(material, PROFILE=payload))
    assert material._profiles()[0] == {}


def test_corrupt_store_not_overwritten(material):
    command = profile_command(material)
    from pathlib import Path
    Path(material.profile_path).write_text('broken')
    with pytest.raises(ValueError):
        material.cmd_SET_FILAMENT(command)
    assert Path(material.profile_path).read_text() == 'broken'


def test_write_failure_preserves_original(material, monkeypatch):
    material.cmd_SET_FILAMENT(profile_command(material))
    original = material._profiles()
    def fail(*args):
        raise OSError('simulated write failure')
    monkeypatch.setattr('wm_material.os.replace', fail)
    with pytest.raises(ValueError, match='write failure'):
        material.cmd_SET_FILAMENT(profile_command(material))
    assert material._profiles() == original
    from pathlib import Path
    assert not list(Path(material.profile_path).parent.glob('.wmp-filaments-*'))


def test_attachment_requires_all_observations(material):
    class Status:
        def __init__(self, data):
            self.data = data
        def get_status(self, eventtime):
            return self.data
    objects = {
        'save_variables': {'variables': {'current_extruder': 2}},
        'custom_hall': {'Raw': 4000},
        'filament_switch_sensor sensor_b': {'filament_detected': True},
        **{'filament_switch_sensor docked%d' % i: {'filament_detected': i != 2} for i in range(4)},
        'toolhead': {'extruder': 'extruder2'},
    }
    material.printer.lookup_object = lambda key, default=None: Status(objects[key]) if key in objects else default
    assert material._attachment(1) == {'state': 'attached', 'head': 'h2'}
    objects['filament_switch_sensor docked2']['filament_detected'] = True
    assert material._attachment(1)['state'] == 'unknown'
    objects['filament_switch_sensor docked2']['filament_detected'] = False
    objects['toolhead']['extruder'] = 'extruder1'
    objects['save_variables']['variables']['current_extruder'] = 0
    assert material._attachment(1) == {'state': 'attached', 'head': 'h2'}
    objects['filament_switch_sensor docked2']['filament_detected'] = True
    objects['save_variables']['variables']['current_extruder'] = 99
    objects['custom_hall']['Raw'] = 5000
    objects['filament_switch_sensor sensor_b']['filament_detected'] = False
    assert material._attachment(1)['state'] == 'empty'
    del objects['custom_hall']
    assert material._attachment(1)['state'] == 'unknown'


@pytest.fixture
def print_material(material, tmp_path):
    class Status:
        def __init__(self, **values):
            self.values = values
        def get_status(self, now):
            return self.values
    class SD:
        sdcard_dirname = str(tmp_path)
        active = False
        from_sd = False
        def is_active(self):
            return self.active
        def is_cmd_from_sd(self):
            return self.from_sd
        def get_file_list(self, recursive):
            return [('part.gcode', 8)]
    class Gcode:
        scripts = None
        fail_at = None
        def __init__(self):
            self.scripts = []
        def run_script_from_command(self, script):
            self.scripts.append(script)
            if len(self.scripts) == self.fail_at:
                raise ValueError('injected failure')
            if script.startswith('SAVE_VARIABLE '):
                fields = dict(item.split('=', 1) for item in script.split()[1:])
                objects['save_variables'].values['variables'][fields['VARIABLE']] = int(fields['VALUE'])
    objects = {
        'virtual_sdcard': SD(), 'gcode': Gcode(),
        'pause_resume': Status(is_paused=False),
        'save_variables': Status(variables={'box_modify_t%d' % i: i for i in range(4)}),
    }
    original = material.printer.lookup_object
    material.printer.lookup_object = lambda name, default=None: objects.get(name, original(name, default))
    material.session_id = 'test-session'
    material._print_requests = set()
    material.print_submission = {}
    material.cmd_SET_FILAMENT(profile_command(material))
    material._filament_state()._sensor_filament_status = lambda now: {'h2': {'state': 'loaded'}}
    material._filament_state()._loaded_filament_status = lambda now: {
        'h2': {'state': 'loaded', 'source': 'external:h2',
               'identity': material._profiles()[0]['h2']}}
    path = tmp_path / 'part.gcode'
    path.write_text('G1 X1\n')
    request = {'id': 'start-1', 'session': material.session_id,
               'profile_revision': material._profiles()[1],
               'file': {'path': path.name, 'size': path.stat().st_size,
                        'modified': path.stat().st_mtime},
               'mapping': {'0': 2}, 'expected_mapping': [0, 1, 2, 3],
               'leveling': True}
    return material, objects, request, path


def start_command(request):
    return FakeCommand(REQUEST=json.dumps(request).encode().hex())


@pytest.mark.parametrize('observed', ['empty', 'unknown', 'missing'])
def test_print_refuses_metadata_without_completed_loading(print_material, observed):
    material, objects, request, path = print_material
    material._filament_state()._loaded_filament_status = lambda now: {} if observed == 'missing' else {'h2': {'state': observed, 'sensor_present': True}}
    with pytest.raises(ValueError, match='Confirm filament metadata/loading for Head 3'):
        material.cmd_START_PRINT(start_command(request))
    assert objects['gcode'].scripts == []
    assert material.print_submission['state'] == 'refused'


@pytest.mark.parametrize("leveling,command", [(True, "G30"), (False, "G31")])
def test_print_submission_prepares_both_mappings_and_levels_once(print_material, leveling, command):
    material, objects, request, path = print_material
    request["leveling"] = leveling
    material.cmd_START_PRINT(start_command(request))
    scripts = objects['gcode'].scripts
    assert scripts[:2] == ['SAVE_VARIABLE VARIABLE=box_modify_t0 VALUE=2',
                           'SAVE_VARIABLE VARIABLE=box_modify_t0_backup VALUE=2']
    assert scripts[-2:] == [command, 'SDCARD_PRINT_FILE FILENAME="part.gcode"']
    assert len(scripts) == 10
    assert not any(s.startswith(('G28', 'START_PRINT', 'RESUME')) for s in scripts)
    assert material.print_submission['state'] == 'submitted'
    with pytest.raises(ValueError, match='already attempted'):
        material.cmd_START_PRINT(start_command(request))
    assert len(scripts) == 10


@pytest.mark.parametrize('change', [
    'owner', 'printing', 'paused', 'sd_active', 'from_sd', 'session',
    'profiles', 'mapping_drift', 'absent_head', 'bool_head', 'bad_tool',
    'empty_mapping', 'file_size', 'file_time', 'missing_file', 'outside',
    'injection', 'traversal', 'bool_leveling',
])
def test_print_refusal_has_no_side_effects(print_material, change):
    material, objects, request, path = print_material
    if change == 'owner': material.printer.owner = object()
    elif change == 'printing': material.printer.state = 'printing'
    elif change == 'paused': objects['pause_resume'].values['is_paused'] = True
    elif change == 'sd_active': objects['virtual_sdcard'].active = True
    elif change == 'from_sd': objects['virtual_sdcard'].from_sd = True
    elif change == 'session': request['session'] = 'old'
    elif change == 'profiles': request['profile_revision'] = 'old'
    elif change == 'mapping_drift': request['expected_mapping'] = [3, 2, 1, 0]
    elif change == 'absent_head': request['mapping']['0'] = 1
    elif change == 'bool_head': request['mapping']['0'] = True
    elif change == 'bad_tool': request['mapping'] = {'4': 2}
    elif change == 'empty_mapping': request['mapping'] = {}
    elif change == 'file_size': request['file']['size'] += 1
    elif change == 'file_time': request['file']['modified'] += 1
    elif change == 'missing_file': path.unlink()
    elif change == 'outside':
        path.unlink(); path.symlink_to('/etc/hosts')
    elif change == 'injection': request['file']['path'] = 'part.gcode"\nG28'
    elif change == 'traversal': request['file']['path'] = '../part.gcode'
    elif change == 'bool_leveling': request['leveling'] = 1
    with pytest.raises(ValueError):
        material.cmd_START_PRINT(start_command(request))
    assert objects['gcode'].scripts == []
    assert material.print_submission == {} if change == "session" else material.print_submission["state"] == "refused"


@pytest.mark.parametrize('failure', range(1, 11))
@pytest.mark.parametrize('leveling', [False, True])
def test_print_submission_failure_boundary_and_never_retried(print_material, failure, leveling):
    material, objects, request, path = print_material
    request['leveling'] = leveling
    objects['gcode'].fail_at = failure
    with pytest.raises(ValueError, match='injected'):
        material.cmd_START_PRINT(start_command(request))
    assert material.print_submission['state'] == ('unknown' if failure == 10 else 'not_started')
    assert material._pending_recovery_submission is None
    if failure < 10:
        assert 'may have changed' in material.print_submission['message']
        assert material.print_submission['error'] == 'injected failure'
    if failure > 1:
        # The first accepted mapping write remains; terminal is not rollback.
        assert objects['save_variables'].values['variables']['box_modify_t0'] == 2
    if failure < 10:
        assert not any(s.startswith('SDCARD_PRINT_FILE') for s in objects['gcode'].scripts)
    assert len(objects['gcode'].scripts) == failure
    objects['gcode'].fail_at = None
    with pytest.raises(ValueError, match='already attempted'):
        material.cmd_START_PRINT(start_command(request))
    assert len(objects['gcode'].scripts) == failure


def test_file_change_during_preparation_prevents_start(print_material):
    material, objects, request, path = print_material
    original = objects['gcode'].run_script_from_command
    def mutate(script):
        original(script)
        if script == 'G30': path.write_text('replacement contents\n')
    objects['gcode'].run_script_from_command = mutate
    with pytest.raises(ValueError, match='file changed'):
        material.cmd_START_PRINT(start_command(request))
    assert not any(s.startswith('SDCARD_PRINT_FILE') for s in objects['gcode'].scripts)
    assert material.print_submission['state'] == 'not_started'


@pytest.mark.parametrize('drift', ['mapping', 'profile', 'paused', 'unloaded'])
def test_prepared_print_rechecks_backend_before_sd_dispatch(print_material, drift):
    material, objects, request, path = print_material
    original = objects['gcode'].run_script_from_command
    def change(script):
        original(script)
        if script == 'G30':
            if drift == 'mapping':
                objects['save_variables'].values['variables']['box_modify_t0_backup'] = 1
            elif drift == 'profile':
                profiles, revision = material._profiles()
                profiles['h2']['material'] = 'PLA'
                with open(material.profile_path, 'w') as stream:
                    json.dump(profiles, stream)
            elif drift == 'unloaded':
                material._filament_state()._loaded_filament_status = lambda now: {'h2': {'state': 'empty'}}
            else:
                objects['pause_resume'].values['is_paused'] = True
    objects['gcode'].run_script_from_command = change
    with pytest.raises(ValueError):
        material.cmd_START_PRINT(start_command(request))
    assert not any(s.startswith('SDCARD_PRINT_FILE') for s in objects['gcode'].scripts)
    assert material.print_submission['state'] == 'not_started'


@pytest.fixture
def filament_check(material):
    class Sensor:
        enabled = True
        detected = True
        def get_status(self, now):
            return {'enabled': self.enabled, 'filament_detected': self.detected}
    sensor = Sensor()
    material._set_filament_loaded("h2", True)
    original = material.printer.lookup_object
    material.printer.lookup_object = lambda name, default=None: sensor if name == 'filament_switch_sensor filament2' else original(name, default)
    material.cmd_SET_FILAMENT(profile_command(material))
    command = FakeCommand(HEAD='2', STATE='loaded', SESSION=material.session_id, EXPECT=material._profiles()[1])
    return material, sensor, command


def test_operator_check_is_separate_from_configured_identity(filament_check):
    material, sensor, command = filament_check
    material.cmd_CONFIRM_FILAMENT(command)
    record = material._filament_status(1)['h2']
    assert record['state'] == 'loaded' and record['evidence'] == 'operator'
    assert record['identity']['material'] == 'PETG'
    changed = {'brand': 'Generic', 'material': 'PLA', 'color': '#ffffff'}
    material.cmd_SET_FILAMENT(profile_command(material, PROFILE=json.dumps(changed).encode().hex()))
    assert material._filament_status(1)['h2']['identity']['material'] == 'PETG'
    sensor.detected = False
    assert material._filament_status(1) == {}
    sensor.detected = True
    assert material._filament_status(1) == {}  # evidence must not resurrect


@pytest.mark.parametrize('reason', ['pause_flag', 'sd_active', 'from_sd', 'missing_pause', 'missing_sd'])
def test_nominally_complete_print_cannot_admit_filament_edits_or_checks(filament_check, reason):
    material, sensor, command = filament_check
    material.cmd_CONFIRM_FILAMENT(command)
    profiles = material._profiles()
    pending_edit = profile_command(material, PROFILE=json.dumps(dict(profiles[0]["h2"], nozzle_temp=240)).encode().hex())
    material.printer.state = 'complete'
    if reason == 'pause_flag': material.printer.paused = True
    elif reason == 'sd_active': material.printer.sd_active = True
    elif reason == 'from_sd': material.printer.from_sd = True
    else:
        missing = 'pause_resume' if reason == 'missing_pause' else 'virtual_sdcard'
        original = material.printer.lookup_object
        material.printer.lookup_object = lambda name, default=None: default if name == missing else original(name, default)
    with pytest.raises(ValueError, match='idle'):
        material.cmd_SET_FILAMENT(pending_edit)
    assert material._profiles() == profiles
    with pytest.raises(ValueError, match='idle'):
        material.cmd_CONFIRM_FILAMENT(command)
    assert material._filament_status(1) == {}
    # Clearing the contradictory state cannot resurrect the old assertion.
    if reason.startswith('missing_'): material.printer.lookup_object = original
    material.printer.paused = material.printer.sd_active = material.printer.from_sd = False
    assert material._filament_status(1) == {}
    material.cmd_CONFIRM_FILAMENT(command)
    assert material._filament_status(1)['h2']['state'] == 'loaded'


@pytest.mark.parametrize('missing', ['print_stats', 'pause_resume', 'virtual_sdcard'])
def test_idle_check_uses_optional_lookup_for_missing_klipper_objects(material, missing):
    # Real Klipper raises config_error for a lookup without an explicit default.
    class ConfigError(Exception):
        pass
    sentinel = object()
    original = material.printer.lookup_object
    def lookup(name, default=sentinel):
        if name == missing:
            if default is sentinel:
                raise ConfigError('Unknown config object')
            return default
        return original(name, None if default is sentinel else default)
    material.printer.lookup_object = lookup
    material._filament_checks['h2'] = {'state': 'loaded'}
    assert material._idle_for_filament_settings(1) is False
    assert material._filament_status(1) == {}


@pytest.mark.parametrize('reason', ['sensor', 'session', 'revision', 'owner', 'printing', 'paused'])
def test_operator_check_refuses_inconsistent_or_stale_evidence(filament_check, reason):
    material, sensor, command = filament_check
    if reason == 'sensor': sensor.detected = False
    elif reason == 'disabled': sensor.enabled = False
    elif reason == 'session': command.args['SESSION'] = 'previous-session'
    elif reason == 'revision': command.args['EXPECT'] = 'old'
    elif reason == 'owner': material.printer.owner = object()
    else: material.printer.state = reason
    with pytest.raises(ValueError): material.cmd_CONFIRM_FILAMENT(command)
    assert material._filament_checks == {}


def test_empty_check_and_print_activity_clear_evidence(filament_check):
    material, sensor, command = filament_check
    sensor.detected = False; command.args['STATE'] = 'empty'
    material.cmd_CONFIRM_FILAMENT(command)
    assert material._filament_status(1)['h2']['state'] == 'empty'
    assert 'identity' not in material._filament_status(1)['h2']
    material.printer.state = 'printing'
    assert material._filament_status(1) == {}
    material.printer.state = 'standby'
    material.cmd_CONFIRM_FILAMENT(command)
    material._clear_filament_checks()
    assert material._filament_status(1) == {}


def test_manual_move_forgets_only_its_head_check(filament_check):
    material, sensor, command = filament_check
    material.cmd_CONFIRM_FILAMENT(command)
    material.cmd_FORGET_FILAMENT(FakeCommand(HEAD='1'))
    assert material._filament_status(1)['h2']['state'] == 'loaded'
    material.cmd_FORGET_FILAMENT(FakeCommand(HEAD='2'))
    assert material._filament_status(1) == {}


@pytest.mark.parametrize('failure', [False, True])
@pytest.mark.parametrize('absolute', [False, True])
@pytest.mark.parametrize('recipe,net', [('pla', -110), ('petg', -27), ('abs', -57), ('soft', -57)])
def test_sequence_restores_real_vendor_state_after_g92(failure, absolute, recipe, net):
    """Use firmware's actual state handlers, including its nonstandard restore."""
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace
    from collections import namedtuple
    from wm_material import run_standalone_extrusion_sequence
    path = Path(__file__).resolve().parents[1] / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras/gcode_move.py'
    if not path.exists():
        pytest.skip('local vendor analysis source is not distributed')
    spec = importlib.util.spec_from_file_location('vendor_sequence_move', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    move = module.GCodeMove.__new__(module.GCodeMove)
    move.Coord = namedtuple('Coord', 'x y z e')
    move.absolute_coord = move.absolute_extrude = absolute
    move.base_position = [1., 2., 3., 20.]
    move.last_position = [50., 60., 10., 100.]
    move.homing_position = [4., 5., 6., 0.]
    move.speed, move.speed_factor, move.extrude_factor = 35., 1.5 / 60., .8
    move.saved_states = {'caller': {'untouched': True}}
    sent, commands = [], []
    move.move_with_transform = lambda pos, speed: sent.append((list(pos), speed))
    objects = {
        'gcode_move': move,
        'custom_hall': SimpleNamespace(last_adc_value_raw=4000),
        'toolhead': SimpleNamespace(get_status=lambda now: {'extruder': 'extruder2'}),
        'save_variables': SimpleNamespace(allVariables={'current_extruder': 2}),
    }
    class Command:
        def __init__(self, args): self.args = args
        def get(self, name, default=None): return self.args.get(name, default)
        def get_float(self, name, default=None, **kw):
            value = self.get(name, default)
            return None if value is None else float(value)
        def get_int(self, name, default=0): return int(self.get(name, default))
        def get_command_parameters(self): return self.args
        def error(self, message): return RuntimeError(message)
    def run(script):
        for line in script.splitlines():
            # Match G-code comment handling before dispatching test commands.
            line = line.split('#', 1)[0].split(';', 1)[0].strip()
            words = line.split()
            if not words: continue
            commands.append(line)
            command = words[0]
            if command == 'M400': continue
            if command == 'FAIL': raise RuntimeError('injected procedure failure')
            args = dict(word.split('=', 1) if '=' in word else (word[0], word[1:]) for word in words[1:])
            getattr(move, 'cmd_' + command)(Command(args))
    objects['gcode'] = SimpleNamespace(run_script_from_command=run)
    printer = SimpleNamespace(quick_stop_flag=False,
        get_reactor=lambda: SimpleNamespace(monotonic=lambda: 1.),
        lookup_object=lambda name, default=None: objects.get(name, default))
    move.printer = printer
    import re
    import jinja2
    source = (Path(__file__).resolve().parents[1] / 'config/live/macros.cfg').read_text()
    section = source.split('[gcode_macro _TIP_SHAPE_MOVES]', 1)[1].split('\n[gcode_macro ', 1)[0]
    template = section.split('gcode:', 1)[1]
    sequence = jinja2.Environment('{%', '%}', '{', '}', undefined=jinja2.StrictUndefined).from_string(template).render(
        printer={}, params={'CLASS': recipe}, cooling_moves=3, cooling_len=10,
        cooling_speed_list=[300, 240, 150], stamp_len=35)
    sequence = '\n'.join(line.split(';', 1)[0] for line in sequence.splitlines())
    expected_moves = [(float(e), float(f) / 60.) for e, f in re.findall(r'G1 E([-+0-9.]+) F([-+0-9.]+)', sequence)]
    if failure:
        lines = sequence.splitlines()
        move_lines = [i for i, line in enumerate(lines) if line.strip().startswith('G1 ')]
        executed = len(move_lines) // 2
        lines.insert(move_lines[executed], 'FAIL')
        expected_moves = expected_moves[:executed]
        with pytest.raises(RuntimeError, match='injected'):
            run_standalone_extrusion_sequence(printer, '\n'.join(lines))
    else:
        run_standalone_extrusion_sequence(printer, sequence)
    position = 100.
    assert len(sent) == len(expected_moves)
    for actual, (delta, speed) in zip(sent, expected_moves):
        position += delta
        assert actual[0][3] == pytest.approx(position)
        assert actual[1] == pytest.approx(speed)
    if not failure:
        assert position == pytest.approx(100. + net)
    assert all(p[0][:3] == [50., 60., 10.] for p in sent)
    assert move.base_position[:3] == [1., 2., 3.]
    assert move.homing_position == [4., 5., 6., 0.]
    assert move.absolute_coord == move.absolute_extrude == absolute
    assert move.speed == 35. and move.speed_factor == 1.5 / 60.
    assert move.extrude_factor == .8
    assert move.get_status()['gcode_position'].e == pytest.approx(100.)
    assert move.saved_states == {'caller': {'untouched': True}}
    assert commands[-1] == 'G92 E100'

    if recipe == 'pla' and not failure:
        # Reproduce the live Resume bug using the actual vendor handlers:
        # service preserves logical E, then PAUSE restore adds its delta again.
        from wm_material import WMMaterial
        import copy
        run('SAVE_GCODE_STATE NAME=PAUSE')
        captured = copy.deepcopy(move.saved_states['PAUSE'])
        run_standalone_extrusion_sequence(printer, 'G1 E105 F400')
        material = WMMaterial.__new__(WMMaterial)
        material.printer = printer
        material._pause_origin = {'states': {'PAUSE': captured}, 'serviced': True}
        checks = []
        material._paused_service().cmd_CHECK_RESUME = lambda command: checks.append('admitted')
        material.cmd_PREPARE_RESUME_E(FakeCommand())
        run('RESTORE_GCODE_STATE NAME=PAUSE MOVE=1 MOVE_SPEED=60')
        assert move.get_status()['gcode_position'].e != pytest.approx(100.)
        before = list(move.last_position)
        move_count = len(sent)
        material.cmd_RESTORE_RESUME_E(FakeCommand())
        assert checks == ['admitted']
        assert move.last_position == before and len(sent) == move_count
        assert move.get_status()['gcode_position'].e == pytest.approx(100.)
        assert move.extrude_factor == .8
        assert move.absolute_extrude == absolute
        run('G1 E%s F600' % ('101' if absolute else '1'))
        assert move.last_position[3] - before[3] == pytest.approx(.8)

        # Ordinary paused manual extrusion never marks a load/unload service.
        # Render the actual manual-step macro,
        # followed by an operator's raw extrusion, through retained handlers.
        for manual in (False, True):
            run('M82' if absolute else 'M83')
            run('G92 E100')
            run('SAVE_GCODE_STATE NAME=PAUSE')
            captured = copy.deepcopy(move.saved_states['PAUSE'])
            material._pause_origin = {'states': {'PAUSE': captured}, 'serviced': False}
            if manual:
                manual_template = source.split('[gcode_macro WMP_EXTRUDER_STEP]', 1)[1].split('\n[gcode_macro ', 1)[0].split('gcode:', 1)[1]
                manual_script = jinja2.Environment('{%', '%}', '{', '}', undefined=jinja2.StrictUndefined).from_string(manual_template).render(
                    params={'HEAD': 2, 'MM': 1}, printer={
                        'print_stats': {'state': 'paused'},
                        'toolhead': {'extruder': 'extruder2'},
                        'extruder2': {'can_extrude': True},
                        'gcode_move': {'extrude_factor': move.extrude_factor,
                                       'speed_factor': move.speed_factor},
                        'wm_material': {'attachment': {'state': 'attached', 'head': 'h2'},
                                        'filament_operation': {'state': 'complete'}}})
                run('G91\nG1 X5 F600')
                run(manual_script)
                run('M83\nG1 E1 F120')
            material.cmd_PREPARE_RESUME_E(FakeCommand())
            run('RESTORE_GCODE_STATE NAME=PAUSE MOVE=1 MOVE_SPEED=60')
            if manual:
                assert move.get_status()['gcode_position'].e != pytest.approx(100.)
            before = list(move.last_position)
            move_count = len(sent)
            material.cmd_RESTORE_RESUME_E(FakeCommand())
            assert move.last_position == before and len(sent) == move_count
            assert move.get_status()['gcode_position'].e == pytest.approx(100.)
            assert move.absolute_extrude == absolute
            assert move.extrude_factor == .8
            assert material._pause_origin['serviced'] is False
            assert material._pause_origin['states']['PAUSE'] == captured
            run('G1 E%s F600' % ('101' if absolute else '1'))
            assert move.last_position[3] - before[3] == pytest.approx(.8)


@pytest.mark.parametrize('owner' , ['openace', 'AFC'])
def test_sequence_refuses_owner_before_touching_state(owner):
    from types import SimpleNamespace
    from wm_material import run_standalone_extrusion_sequence
    def lookup(name, default=None):
        assert name in ('openace', 'AFC')
        return object() if name == owner else default
    with pytest.raises(ValueError, match='owns filament'):
        run_standalone_extrusion_sequence(SimpleNamespace(lookup_object=lookup), 'G1 E20')


@pytest.fixture
def sequence_material(material):
    from types import SimpleNamespace
    material.cmd_SET_FILAMENT(profile_command(material))
    material._filament_requests = set()
    material.filament_operation = {}
    objects = {
        'pause_resume': SimpleNamespace(get_status=lambda now: {'is_paused': False}),
        'virtual_sdcard': SimpleNamespace(is_active=lambda: False, is_cmd_from_sd=lambda: False),
        'extruder2': SimpleNamespace(get_status=lambda now: {'temperature': 250., 'target': 250., 'can_extrude': True}),
        'configfile': SimpleNamespace(get_status=lambda now: {'settings': {'extruder2': {'max_temp': 350}}}),
        'gcode_macro _TIP_SHAPE_MOVES': object(),
        'gcode_macro WIPE_NOZZLE': object(),
        'toolhead': SimpleNamespace(get_status=lambda now: {'extruder': 'extruder2'}),
    }
    original = material.printer.lookup_object
    material.printer.lookup_object = lambda name, default=None: objects.get(name, original(name, default))
    material._material_status()._attachment = lambda now: {'state': 'attached', 'head': 'h2'}
    return material, objects


def sequence_command(material, action='load', **updates):
    plan = material._filament_plan(2, action, 1.)
    args = {'ID': 'request-1', 'HEAD': 2, 'ACTION': action, 'TOKEN': plan['token']}
    args.update(updates)
    return FakeCommand(**args)


def test_load_sequence_once_without_claiming_loaded(sequence_material, monkeypatch):
    material, objects = sequence_material
    calls = []
    monkeypatch.setattr('wm_material.run_standalone_extrusion_sequence', lambda printer, script: calls.append(script))
    cmd = sequence_command(material)
    material.cmd_FILAMENT_SEQUENCE(cmd)
    assert calls == ['G1 E55 F400', 'G1 E50 F400']
    assert material.filament_operation['state'] == 'complete'
    assert material._filament_checks == {}
    with pytest.raises(ValueError, match='already attempted'):
        material.cmd_FILAMENT_SEQUENCE(cmd)
    assert len(calls) == 2


@pytest.mark.parametrize('change', ['openace', 'paused', 'printing', 'sd', 'from_sd', 'attachment', 'cold', 'target', 'stale'])
def test_sequence_refuses_without_motion(sequence_material, monkeypatch, change):
    from types import SimpleNamespace
    material, objects = sequence_material
    cmd = sequence_command(material)
    if change == 'openace': material.printer.owner = object()
    elif change == 'paused': objects['pause_resume'] = SimpleNamespace(get_status=lambda now: {'is_paused': True})
    elif change == 'printing': material.printer.state = 'printing'
    elif change == 'sd': objects['virtual_sdcard'] = SimpleNamespace(is_active=lambda: True)
    elif change == 'from_sd': objects['virtual_sdcard'] = SimpleNamespace(is_active=lambda: False, is_cmd_from_sd=lambda: True)
    elif change == 'attachment': material._material_status()._attachment = lambda now: {'state': 'unknown', 'head': ''}
    elif change in ('cold', 'target'): objects['extruder2'] = SimpleNamespace(get_status=lambda now: {'temperature': 28 if change == 'cold' else 250, 'target': 0 if change == 'target' else 250, 'can_extrude': True})
    else: cmd.args['TOKEN'] = 'stale'
    monkeypatch.setattr('wm_material.run_standalone_extrusion_sequence', lambda *args: pytest.fail('motion on refusal'))
    with pytest.raises(ValueError): material.cmd_FILAMENT_SEQUENCE(cmd)
    assert material.filament_operation['state'] == 'refused'
    assert material._filament_requests == {'request-1'}


@pytest.mark.parametrize("drained", [False, True])
def test_unload_uses_observed_identity_and_reports_failure(sequence_material, monkeypatch, drained):
    from types import SimpleNamespace
    material, objects = sequence_material
    profiles, revision = material._profiles()
    material._set_filament_loaded("h2", True)
    material._filament_checks['h2'] = {'state': 'loaded', 'identity': profiles['h2']}
    material._filament_state()._sensor_filament_status = lambda now: material._filament_checks
    objects['extruder2'] = SimpleNamespace(get_status=lambda now: {'temperature': 250, 'target': 250, 'can_extrude': True})
    # Configured spool may change; unload must still shape the observed PETG.
    material.cmd_SET_FILAMENT(profile_command(material, PROFILE=json.dumps({'brand': 'Generic', 'material': 'PLA', 'color': '#ffffff'}).encode().hex()))
    cmd = sequence_command(material, 'unload')
    calls = []
    def interrupted(printer, script):
        calls.append(script)
        raise RuntimeError('interrupted')
    monkeypatch.setattr('wm_material.run_standalone_extrusion_sequence', interrupted)
    drains = []
    if drained:
        objects['gcode'] = SimpleNamespace(run_script_from_command=lambda script: drains.append(script))
    with pytest.raises(RuntimeError, match='interrupted'): material.cmd_FILAMENT_SEQUENCE(cmd)
    assert calls == ['_TIP_SHAPE_MOVES CLASS=petg']
    assert material._filament_checks == {}
    assert material.filament_operation['state'] == ('failed' if drained else 'unknown')
    assert drains == (['M400'] if drained else [])
    with pytest.raises(ValueError, match='already attempted'): material.cmd_FILAMENT_SEQUENCE(cmd)


def test_status_publishes_supported_material_catalogue(material):
    from wm_material import MATERIALS
    material._material_status()._refresh = lambda: None
    material._mtime = 1
    material._slots = {}
    material.ini_path = '/unused/test.ini'
    material.print_submission = {}
    material.filament_operation = {}
    material._material_status()._attachment = lambda now: {'state': 'unknown', 'head': ''}
    material._filament_state()._filament_status = lambda now: {}
    def unavailable(*args):
        raise ValueError('Take the selected head first')
    material._filament_planning()._filament_plan = unavailable
    status = material.get_status(1.)
    assert status['filament_materials'] == [name for name, temperature in MATERIALS]
    assert status['filament_materials'][18:] == ['PCTG', 'PA6', 'PA12', 'PP']
    assert status['filament_procedures'] == []
    assert status['filament_procedure_errors'] == {}
    assert len(material.get_status(1., detailed=True)['filament_procedure_errors']) == 8


def openace_start_fixture(print_material):
    material, objects, old, path = print_material
    class Ace:
        values = {'session_id': 42, 'config_revision': 7, 'operation': None, 'job': {'active': False},
                  'default_tool_map': {'7': {'head': 'h2', 'unit': 'ace0', 'slot': 1}}}
        def get_status(self, now):
            return self.values
    objects['openace'] = Ace()
    request = {'id': 'ace-start-1', 'session': material.session_id, 'owner': 'openace',
               'ace_session': 42, 'config_revision': 7, 'pairs': [[0, 7]],
               'file': old['file'], 'leveling': False}
    return material, objects, request, path


def test_openace_start_uses_public_virtual_map_without_vendor_mapping(print_material):
    material, objects, request, path = openace_start_fixture(print_material)
    previous = dict(objects['save_variables'].values['variables'])
    material.cmd_START_PRINT(start_command(request))
    assert objects['gcode'].scripts == ['G31', 'SDCARD_PRINT_FILE FILENAME="part.gcode" OPENACE_MAP="[[0,7]]"']
    assert objects['save_variables'].values['variables'] == previous
    assert material.print_submission['state'] == 'submitted'
    with pytest.raises(ValueError, match='already attempted'):
        material.cmd_START_PRINT(start_command(request))
    assert len(objects['gcode'].scripts) == 2


@pytest.mark.parametrize('mutation', ['session', 'revision', 'operation', 'missing', 'pairs', 'duplicate', 'file', 'paused'])
def test_openace_start_refuses_before_any_preparation(print_material, mutation):
    material, objects, request, path = openace_start_fixture(print_material)
    if mutation == 'session': request['ace_session'] = 43
    elif mutation == 'revision': request['config_revision'] = 8
    elif mutation == 'operation': objects['openace'].values['operation'] = 'loading'
    elif mutation == 'missing': del objects['openace']
    elif mutation == 'pairs': request['pairs'] = [[0, 8]]
    elif mutation == 'duplicate': request['pairs'] = [[0, 7], [0, 7]]
    elif mutation == 'file': path.write_text('changed file')
    elif mutation == 'paused': objects['pause_resume'].values['is_paused'] = True
    with pytest.raises(ValueError): material.cmd_START_PRINT(start_command(request))
    assert objects['gcode'].scripts == []
    assert material.print_submission['state'] == 'refused'


@pytest.mark.parametrize('mutation', ['revision', 'file', 'operation'])
def test_openace_start_rechecks_after_leveling_and_never_retries(print_material, mutation):
    material, objects, request, path = openace_start_fixture(print_material)
    original = objects['gcode'].run_script_from_command
    def changed(script):
        original(script)
        if mutation == 'revision': objects['openace'].values['config_revision'] += 1
        elif mutation == 'file': path.write_text('changed file')
        else: objects['openace'].values['operation'] = 'loading'
    objects['gcode'].run_script_from_command = changed
    with pytest.raises(ValueError): material.cmd_START_PRINT(start_command(request))
    assert objects['gcode'].scripts == ['G31']
    assert material.print_submission['state'] == 'not_started'
    with pytest.raises(ValueError): material.cmd_START_PRINT(start_command(request))
    assert objects['gcode'].scripts == ['G31']


def ace_unload_fixture(print_material):
    from contextlib import nullcontext
    from types import SimpleNamespace
    material, objects, request, path = openace_start_fixture(print_material)
    callbacks = []
    material.printer.get_reactor = lambda: SimpleNamespace(monotonic=lambda: 1., register_callback=callbacks.append, callbacks=callbacks)
    objects['gcode'].get_mutex = nullcontext
    material._filament_requests = set()
    material.filament_operation = {}
    objects['openace'].values['loaded'] = {'h2': {
        'state': 'loaded', 'verified': True,
        'destination': {'head': 'h2', 'unit': 'ace0', 'slot': 1},
        'identity': {'material': 'PLA', 'color': '#123456'}}}
    plan = material._filament_plan(2, 'unload', 0)
    cmd = FakeCommand(ID='unload-1', HEAD='2', ACTION='unload', TOKEN=plan['token'])
    return material, objects, cmd


def run_ace_filament_request(material, objects, command):
    material.cmd_FILAMENT_SEQUENCE(command)
    assert objects['gcode'].scripts == []
    callbacks = material.printer.get_reactor().callbacks
    assert len(callbacks) == 1
    callbacks.pop()(1.)


def test_ace_unload_calls_public_owner_only_and_requires_empty_readback(print_material):
    material, objects, cmd = ace_unload_fixture(print_material)
    original = objects['gcode'].run_script_from_command
    def unload(script):
        original(script)
        objects['openace'].values['loaded']['h2'] = {'state': 'empty'}
    objects['gcode'].run_script_from_command = unload
    run_ace_filament_request(material, objects, cmd)
    assert objects['gcode'].scripts == ['OPENACE_UNLOAD HEAD=h2']
    assert material.filament_operation['state'] == 'complete'
    with pytest.raises(ValueError, match='already attempted'): material.cmd_FILAMENT_SEQUENCE(cmd)
    assert len(objects['gcode'].scripts) == 1


@pytest.mark.parametrize('mutation', ['loaded', 'session', 'revision', 'paused', 'operation'])
def test_ace_unload_rejects_changed_review_without_commands(print_material, mutation):
    material, objects, cmd = ace_unload_fixture(print_material)
    ace = objects['openace'].values
    if mutation == 'loaded': ace['loaded']['h2']['identity']['color'] = '#ffffff'
    elif mutation == 'session': ace['session_id'] += 1
    elif mutation == 'revision': ace['config_revision'] += 1
    elif mutation == 'paused': objects['pause_resume'].values['is_paused'] = True
    else: ace['operation'] = 'loading'
    with pytest.raises(ValueError): material.cmd_FILAMENT_SEQUENCE(cmd)
    assert not objects['gcode'].scripts
    assert material.filament_operation['state'] == 'refused'


def test_ace_unload_return_without_empty_is_unknown_and_not_replayed(print_material):
    material, objects, cmd = ace_unload_fixture(print_material)
    run_ace_filament_request(material, objects, cmd)
    assert objects['gcode'].scripts == ['OPENACE_UNLOAD HEAD=h2']
    assert material.filament_operation['state'] == 'unknown'
    with pytest.raises(ValueError, match='already attempted'): material.cmd_FILAMENT_SEQUENCE(cmd)
    assert len(objects['gcode'].scripts) == 1


def test_ace_unload_status_cache_is_local_to_publication(print_material):
    material, objects, cmd = ace_unload_fixture(print_material)
    original = objects['openace'].get_status
    calls = []
    def observed(now):
        calls.append(now)
        return original(now)
    objects['openace'].get_status = observed
    cache = {}
    for head in range(4):
        try: material._filament_plan(head, 'unload', 0, cache)
        except ValueError: pass
    assert len(calls) == 1
    material._filament_plan(2, 'unload', 1)
    assert calls == [0, 1]


def ace_load_fixture(print_material):
    material, objects, cmd = ace_unload_fixture(print_material)
    ace = objects['openace'].values
    ace['loaded']['h2'] = {'state': 'empty'}
    ace['inventory'] = {'ace0:1': {'material': 'PLA', 'color': '#123456', 'nozzle_temp': 220}}
    ace['devices'] = {'units': {'ace0': {'connected': True}}}
    plan = material._openace_load_plans(2, 0)[0]
    cmd = FakeCommand(ID='load-1', HEAD='2', ACTION='load', TOKEN=plan['token'])
    return material, objects, cmd, plan


def test_ace_load_uses_reviewed_virtual_tool_and_verified_destination(print_material):
    material, objects, cmd, plan = ace_load_fixture(print_material)
    original = objects['gcode'].run_script_from_command
    def load(script):
        original(script)
        objects['openace'].values['loaded']['h2'] = {'state': 'loaded', 'verified': True, 'destination': plan['destination'], 'identity': dict(plan['identity'])}
    objects['gcode'].run_script_from_command = load
    run_ace_filament_request(material, objects, cmd)
    assert objects['gcode'].scripts == ['OPENACE_SELECT TOOL=7']
    assert material.filament_operation['state'] == 'complete'
    with pytest.raises(ValueError, match='already attempted'): material.cmd_FILAMENT_SEQUENCE(cmd)
    assert len(objects['gcode'].scripts) == 1


@pytest.mark.parametrize('mutation', ['route', 'identity', 'offline', 'blocked', 'loaded', 'session', 'revision', 'paused', 'active-job', 'missing-job'])
def test_ace_load_rejects_changed_selected_source_before_motion(print_material, mutation):
    material, objects, cmd, plan = ace_load_fixture(print_material)
    ace = objects['openace'].values
    if mutation == 'route': ace['default_tool_map']['7']['slot'] = 2
    elif mutation == 'identity': ace['inventory']['ace0:1']['color'] = '#ffffff'
    elif mutation == 'offline': ace['devices']['units']['ace0']['connected'] = False
    elif mutation == 'blocked': ace['blocked_tools'] = {'7': 'held'}
    elif mutation == 'loaded': ace['loaded']['h2']['state'] = 'unknown'
    elif mutation == 'session': ace['session_id'] += 1
    elif mutation == 'revision': ace['config_revision'] += 1
    elif mutation == 'active-job': ace['job']['active'] = True
    elif mutation == 'missing-job': del ace['job']
    else: objects['pause_resume'].values['is_paused'] = True
    with pytest.raises(ValueError): material.cmd_FILAMENT_SEQUENCE(cmd)
    assert objects['gcode'].scripts == []
    assert material.filament_operation['state'] == 'refused'


@pytest.mark.parametrize('result', ['wrong-source', 'unverified', 'empty', 'wrong-identity'])
def test_ace_load_does_not_claim_completion_from_return_alone(print_material, result):
    material, objects, cmd, plan = ace_load_fixture(print_material)
    original = objects['gcode'].run_script_from_command
    def load(script):
        original(script)
        loaded = {'state': 'loaded', 'verified': True, 'destination': dict(plan['destination']), 'identity': dict(plan['identity'])}
        if result == 'wrong-source': loaded['destination']['slot'] = 2
        elif result == 'unverified': loaded['verified'] = False
        elif result == 'wrong-identity': loaded['identity']['material'] = 'PETG'
        else: loaded['state'] = 'empty'
        objects['openace'].values['loaded']['h2'] = loaded
    objects['gcode'].run_script_from_command = load
    run_ace_filament_request(material, objects, cmd)
    assert objects['gcode'].scripts == ['OPENACE_SELECT TOOL=7']
    assert material.filament_operation['state'] == 'unknown'


def test_ace_load_aliases_share_source_but_display_chosen_tool(print_material):
    material, objects, cmd, plan = ace_load_fixture(print_material)
    ace = objects['openace'].values
    ace['default_tool_map']['9'] = dict(ace['default_tool_map']['7'])
    plans = material._openace_load_plans(2, 0)
    assert len(plans) == 1 and plans[0]['tool'] == 7
    assert 'Tool T7' in plans[0]['description']
    ace['blocked_tools'] = {'7': 'blocked'}
    plans = material._openace_load_plans(2, 0)
    assert len(plans) == 1 and plans[0]['tool'] == 9
    assert plans[0]['token'] != plan['token']


@pytest.mark.parametrize('action', ['load', 'unload'])
@pytest.mark.parametrize('change', ['session', 'revision', 'paused', 'loaded', 'identity'])
def test_ace_queued_worker_revalidates_before_owner_command(print_material, action, change):
    if action == 'load':
        material, objects, command, _ = ace_load_fixture(print_material)
    else:
        material, objects, command = ace_unload_fixture(print_material)
    material.cmd_FILAMENT_SEQUENCE(command)
    assert not objects['gcode'].scripts
    ace = objects['openace'].values
    if change == 'session': ace['session_id'] += 1
    elif change == 'revision': ace['config_revision'] += 1
    elif change == 'paused': objects['pause_resume'].values['is_paused'] = True
    elif change == 'loaded': ace['loaded']['h2']['state'] = 'unknown'
    elif action == 'load': ace['inventory']['ace0:1']['color'] = '#FFFFFF'
    else: ace['loaded']['h2']['identity']['color'] = '#FFFFFF'
    material.printer.get_reactor().callbacks.pop()(1.)
    assert objects['gcode'].scripts == []
    assert material.filament_operation['state'] == 'refused'


@pytest.mark.parametrize('action', ['load', 'unload'])
@pytest.mark.parametrize('pending', [False, True])
def test_ace_slot_stop_and_reconciliation_preserve_owner_filament_state(print_material, action, pending):
    import copy
    from types import SimpleNamespace
    if action == 'load':
        material, objects, command, _ = ace_load_fixture(print_material)
    else:
        material, objects, command = ace_unload_fixture(print_material)
    owner = objects['openace']
    owner.values.setdefault('devices', {}).update(
        abort={'requested': False, 'scopes': []}, stop_pending={'ace0': {}} if pending else {})
    objects['extruder2'] = SimpleNamespace(get_status=lambda now: {'target': 0})
    aborts = []
    def abort(reason):
        aborts.append(reason)
        owner.values['operation'] = None
        return True
    owner.abort_operation = abort
    before = copy.deepcopy(owner.values['loaded'])
    original = objects['gcode'].run_script_from_command
    operation_command = 'OPENACE_SELECT TOOL=7' if action == 'load' else 'OPENACE_UNLOAD HEAD=h2'
    def run(script):
        original(script)
        if script == operation_command:
            owner.values['operation'] = 'select T7' if action == 'load' else 'unload h2'
            material._handle_filament_cancel(cancellation_request(material, id=command.args['ID']))
    objects['gcode'].run_script_from_command = run
    run_ace_filament_request(material, objects, command)
    assert len(aborts) == 1
    assert objects['gcode'].scripts == [operation_command, 'M400', 'SET_HEATER_TEMPERATURE HEATER=extruder2 TARGET=0']
    assert material.filament_operation['state'] == ('unknown' if pending else 'failed')
    if pending:
        owner.values['devices']['stop_pending'] = {}
        material.cmd_RECOVER_FILAMENT(FakeCommand(ID=command.args['ID'], HEAD='2', SESSION=material.session_id, GENERATION='0'))
        assert objects['gcode'].scripts[-2:] == ['M400', 'SET_HEATER_TEMPERATURE HEATER=extruder2 TARGET=0']
    assert material.filament_operation['stopped'] is True
    assert objects['gcode'].scripts.count(operation_command) == 1
    assert owner.values['loaded'] == before


@pytest.fixture
def ace_direct_load(print_material, request):
    from contextlib import nullcontext
    from types import SimpleNamespace
    material, objects, _, _ = ace_load_fixture(print_material)
    ace = objects['openace'].values
    ace['default_tool_map'] = {}
    ace['management'] = {'identity_settings': {'h2': {'values': {
        'material': 'PLA', 'color': '#123456', 'nozzle_temp': 220}}}}
    state = {'present': getattr(request, 'param', False), 'time': 1.}
    callbacks = []
    material._filament_state()._sensor_filament_status = lambda now: {'h2': {
        'state': 'loaded' if state['present'] else 'empty'}}
    def pause(wake):
        state['time'] = wake
        state['present'] = True
    reactor = SimpleNamespace(monotonic=lambda: state['time'],
                              pause=pause, register_callback=callbacks.append)
    material.printer.get_reactor = lambda: reactor
    objects['gcode'].get_mutex = nullcontext
    plan = material._openace_load_plans(2, 1.)[0]
    original = objects['gcode'].run_script_from_command
    def run(script):
        original(script)
        if script == 'OPENACE_LOAD_DIRECT HEAD=h2 DONE=1':
            ace['loaded']['h2'] = {'state': 'loaded', 'verified': True,
                                  'destination': plan['destination'],
                                  'identity': dict(plan['identity'])}
    objects['gcode'].run_script_from_command = run
    command = FakeCommand(ID='direct-load', HEAD='2', ACTION='load', TOKEN=plan['token'])
    material.cmd_FILAMENT_SEQUENCE(command)
    assert len(callbacks) == 1 and objects['gcode'].scripts == []
    return material, objects, plan, state, reactor, callbacks[0]


@pytest.mark.parametrize('ace_direct_load', [False, True], indirect=True)
def test_openace_direct_load_waits_for_presence_then_verifies_owner(ace_direct_load):
    material, objects, plan, state, reactor, execute = ace_direct_load
    already_inserted = state['present']
    execute(1.)
    assert objects['gcode'].scripts == [
        'OPENACE_LOAD_DIRECT HEAD=h2 TEMP=220.000',
        'OPENACE_LOAD_DIRECT HEAD=h2 DONE=1']
    assert state['time'] == (1. if already_inserted else 1.25)
    assert material.filament_operation['state'] == 'complete'


@pytest.mark.parametrize('owner_state', ['loaded', 'unknown', None])
def test_openace_direct_presence_does_not_override_owner_load(ace_direct_load, owner_state):
    material, objects, plan, state, reactor, execute = ace_direct_load
    state['present'] = True
    objects['openace'].values['loaded']['h2'] = {'state': owner_state}
    with pytest.raises(ValueError, match='resolve openACE state'):
        material._openace_load_plans(2, 1.)
    assert objects['gcode'].scripts == []


def test_openace_direct_review_binds_owner_load_before_preparation(ace_direct_load):
    material, objects, plan, state, reactor, execute = ace_direct_load
    objects['openace'].values['loaded']['h2']['state'] = 'unknown'
    assert plan['owner_load']['state'] == 'empty'
    execute(1.)
    assert objects['gcode'].scripts == []
    assert material.filament_operation['state'] == 'refused'


def test_openace_direct_empty_record_does_not_replace_unreadable_sensor(ace_direct_load):
    material, objects, plan, state, reactor, execute = ace_direct_load
    material._filament_state()._sensor_filament_status = lambda now: {'h2': {'state': 'unknown'}}
    with pytest.raises(ValueError, match='resolve openACE state'):
        material._openace_load_plans(2, 1.)
    assert objects['gcode'].scripts == []


@pytest.mark.parametrize('change', ['session', 'revision', 'identity', 'job',
                                    'operation', 'owner', 'generation', 'paused'])
@pytest.mark.parametrize('when', ['preparation', 'insertion'])
def test_openace_direct_wait_revalidates_before_feed_and_cleanup(ace_direct_load, change, when):
    material, objects, plan, state, reactor, execute = ace_direct_load
    original_pause = reactor.pause
    def mutate():
        state['present'] = True  # Sensor presence must not bypass admission.
        ace = objects['openace'].values
        if change == 'session': ace['session_id'] += 1
        elif change == 'revision': ace['config_revision'] += 1
        elif change == 'identity':
            ace['management']['identity_settings']['h2']['values']['material'] = 'PETG'
        elif change == 'job': ace['job']['active'] = True
        elif change == 'operation': ace['operation'] = 'another operation'
        elif change == 'owner': del objects['openace']
        elif change == 'generation': material._command_generation = 1
        else: objects['pause_resume'].values['is_paused'] = True
    if when == 'insertion':
        def pause(wake):
            original_pause(wake)
            mutate()
        reactor.pause = pause
    else:
        original_run = objects['gcode'].run_script_from_command
        def prepare(script):
            original_run(script)
            mutate()
        objects['gcode'].run_script_from_command = prepare
    execute(1.)
    assert objects['gcode'].scripts == ['OPENACE_LOAD_DIRECT HEAD=h2 TEMP=220.000']
    assert material.filament_operation['state'] == 'unknown'


def test_openace_direct_timeout_cools_only_unchanged_context(ace_direct_load):
    material, objects, plan, state, reactor, execute = ace_direct_load
    def timeout(wake):
        state['time'] = 182.
    reactor.pause = timeout
    execute(1.)
    assert objects['gcode'].scripts == [
        'OPENACE_LOAD_DIRECT HEAD=h2 TEMP=220.000',
        'SET_HEATER_TEMPERATURE HEATER=extruder2 TARGET=0']
    assert material.filament_operation['state'] == 'unknown'


@pytest.mark.parametrize('phase', ['preparation', 'insertion', 'feeding'])
@pytest.mark.parametrize('evidence', ['settled', 'abort', 'scope', 'pending', 'heater', 'missing'])
def test_openace_direct_stop_reaches_owner_or_cancels_local_wait(ace_direct_load, phase, evidence):
    from types import SimpleNamespace
    material, objects, plan, state, reactor, execute = ace_direct_load
    owner = objects['openace']
    owner.values['devices'].update(abort={'requested': False, 'scopes': []}, stop_pending={})
    objects['extruder2'] = SimpleNamespace(get_status=lambda now: {'target': 220 if evidence == 'heater' else 0})
    if evidence == 'abort': owner.values['devices']['abort']['requested'] = True
    elif evidence == 'scope': owner.values['devices']['abort']['scopes'] = ['unresolved']
    elif evidence == 'pending': owner.values['devices']['stop_pending'] = {'ace0': {}}
    elif evidence == 'missing': del owner.values['devices']['abort']
    aborts, requests = [], []
    def abort(reason):
        aborts.append(reason)
        owner.values['operation'] = None
        return True
    owner.abort_operation = abort
    def stop():
        assert material.filament_operation['openace_cancel_supported'] is True
        request = cancellation_request(material, id='direct-load')
        material._handle_filament_cancel(request)
        requests.append(request.response)
        # An HTTP retry acknowledges the same intent without aborting twice.
        material._handle_filament_cancel(request)
    original_run = objects['gcode'].run_script_from_command
    def run(script):
        original_run(script)
        if ((phase == 'preparation' and 'TEMP=' in script)
                or (phase == 'feeding' and 'DONE=1' in script)):
            owner.values['operation'] = 'openace_load_direct h2'
            stop()
    objects['gcode'].run_script_from_command = run
    original_pause = reactor.pause
    def pause(wake):
        original_pause(wake)
        if phase == 'insertion': stop()
    reactor.pause = pause
    execute(1.)
    assert len(requests) == 1 and requests[0]['state'] == 'requested'
    assert len(aborts) == (0 if phase == 'insertion' else 1)
    assert sum('DONE=1' in script for script in objects['gcode'].scripts) == (phase == 'feeding')
    assert objects['gcode'].scripts[-1] == 'SET_HEATER_TEMPERATURE HEATER=extruder2 TARGET=0'
    # Abort acceptance alone is not evidence that all physical actions settled.
    assert 'M400' in objects['gcode'].scripts
    assert material.filament_operation['state'] == ('failed' if evidence == 'settled' else 'unknown')
    assert material.filament_operation.get('stopped', False) == (evidence == 'settled')
    assert material.filament_operation['cancel_requested'] is True
    assert material._openace_filament_cancel is None
    assert 'openace_cancel_supported' not in material.filament_operation


def test_openace_stop_retries_failed_abort_without_repeating_success(ace_direct_load):
    material, objects, plan, state, reactor, execute = ace_direct_load
    owner = objects['openace']
    attempts = []
    def abort(reason):
        attempts.append(reason)
        if len(attempts) == 1:
            raise ValueError('abort delivery failed')
        return True
    owner.abort_operation = abort
    original = objects['gcode'].run_script_from_command
    def run(script):
        original(script)
        if script.startswith('OPENACE_LOAD_DIRECT') and 'TEMP=' in script:
            owner.values['operation'] = 'openace_load_direct h2'
            request = cancellation_request(material, id='direct-load')
            with pytest.raises(ValueError, match='abort delivery failed'):
                material._handle_filament_cancel(request)
            assert material.filament_operation['cancel_requested'] is True
            assert request.response is None
            material._handle_filament_cancel(request)
            assert len(attempts) == 2
            material._handle_filament_cancel(request)
            assert len(attempts) == 2
    objects['gcode'].run_script_from_command = run
    execute(1.)
    assert len(attempts) == 2
    assert not any('DONE=1' in script for script in objects['gcode'].scripts)


@pytest.mark.parametrize('change', ['request', 'owner', 'ace_session', 'operation', 'job'])
def test_openace_direct_stop_cannot_abort_replacement_operation(ace_direct_load, change):
    from types import SimpleNamespace
    material, objects, plan, state, reactor, execute = ace_direct_load
    owner = objects['openace']
    aborts = []
    owner.abort_operation = aborts.append
    original_pause = reactor.pause
    def pause(wake):
        original_pause(wake)
        request = cancellation_request(material, id='direct-load')
        if change == 'request': request.params['id'] = 'stale'
        elif change == 'owner': objects['openace'] = SimpleNamespace(get_status=owner.get_status)
        elif change == 'ace_session': owner.values['session_id'] += 1
        elif change == 'operation': owner.values['operation'] = 'openace_load_direct h1'
        else: owner.values['job']['active'] = True
        with pytest.raises(ValueError): material._handle_filament_cancel(request)
        assert not material.filament_operation.get('cancel_requested')
    reactor.pause = pause
    execute(1.)
    assert aborts == []
    if change != 'request':
        assert not any('DONE=1' in script for script in objects['gcode'].scripts)


@pytest.mark.parametrize('failure', ['drain', 'cool', 'replacement-after-drain'])
def test_openace_direct_stop_cleanup_failure_remains_unresolved(ace_direct_load, failure):
    material, objects, plan, state, reactor, execute = ace_direct_load
    owner = objects['openace']
    owner.abort_operation = lambda reason: True
    original_run = objects['gcode'].run_script_from_command
    def run(script):
        original_run(script)
        if script == 'M400':
            if failure == 'drain': raise ValueError('drain failed')
            if failure == 'replacement-after-drain': owner.values['session_id'] += 1
        if script.startswith('SET_HEATER_TEMPERATURE') and failure == 'cool':
            raise ValueError('cool failed')
    objects['gcode'].run_script_from_command = run
    def pause(wake):
        state['time'] = wake
        material._handle_filament_cancel(cancellation_request(material, id='direct-load'))
    reactor.pause = pause
    execute(1.)
    assert material.filament_operation['state'] == 'unknown'
    assert not material.filament_operation.get('stopped')
    assert not any('DONE=1' in script for script in objects['gcode'].scripts)
    if failure == 'replacement-after-drain':
        assert not any('SET_HEATER_TEMPERATURE' in script for script in objects['gcode'].scripts)


@pytest.fixture
def ace_direct_unresolved(ace_direct_load):
    from types import SimpleNamespace
    material, objects, plan, state, reactor, execute = ace_direct_load
    owner = objects['openace']
    owner.abort_operation = lambda reason: True
    owner.values['devices'].update(abort={'requested': False, 'scopes': []}, stop_pending={'ace0': {}})
    objects['extruder2'] = SimpleNamespace(get_status=lambda now: {'target': 0})
    def pause(wake):
        state['time'] = wake
        material._handle_filament_cancel(cancellation_request(material, id='direct-load'))
    reactor.pause = pause
    execute(1.)
    assert material.filament_operation['state'] == 'unknown'
    assert material.filament_operation['openace_recovery_supported'] is True
    owner.values['devices']['stop_pending'] = {}
    objects['gcode'].scripts.clear()
    command = FakeCommand(ID='direct-load', HEAD='2', SESSION=material.session_id, GENERATION='0')
    return material, objects, command


def test_openace_direct_recovery_verifies_stop_without_replaying_load(ace_direct_unresolved):
    import copy
    material, objects, command = ace_direct_unresolved
    loaded = copy.deepcopy(objects['openace'].values['loaded'])
    with pytest.raises(ValueError, match='unresolved'):
        material.cmd_FILAMENT_SEQUENCE(FakeCommand(ID='retry', HEAD='2', ACTION='load', TOKEN='unused'))
    material.cmd_RECOVER_FILAMENT(command)
    assert objects['gcode'].scripts == ['M400', 'SET_HEATER_TEMPERATURE HEATER=extruder2 TARGET=0']
    assert objects['openace'].values['loaded'] == loaded
    assert material.filament_operation['stopped'] is True
    assert material.filament_operation['recovered'] is True
    assert material.filament_operation['state'] == 'failed'
    assert material._openace_filament_recovery is None
    assert 'openace_recovery_supported' not in material.filament_operation
    with pytest.raises(ValueError, match='does not need'):
        material.cmd_RECOVER_FILAMENT(command)
    assert len(objects['gcode'].scripts) == 2


@pytest.mark.parametrize('change', ['request', 'session', 'head', 'generation', 'owner', 'ace-session', 'job'])
def test_openace_direct_recovery_refuses_stale_context_without_commands(ace_direct_unresolved, change):
    from types import SimpleNamespace
    material, objects, command = ace_direct_unresolved
    if change == 'request': command.args['ID'] = 'old'
    elif change == 'session': command.args['SESSION'] = 'old'
    elif change == 'head': command.args['HEAD'] = '1'
    elif change == 'generation': command.args['GENERATION'] = '1'
    elif change == 'owner': objects['openace'] = SimpleNamespace(get_status=objects['openace'].get_status)
    elif change == 'ace-session': objects['openace'].values['session_id'] += 1
    else: objects['openace'].values['job']['active'] = True
    with pytest.raises(ValueError): material.cmd_RECOVER_FILAMENT(command)
    assert objects['gcode'].scripts == []
    assert material.filament_operation['state'] == 'unknown'


def test_openace_direct_recovery_rechecks_owner_after_motion_drain(ace_direct_unresolved):
    from types import SimpleNamespace
    material, objects, command = ace_direct_unresolved
    original = objects['gcode'].run_script_from_command
    def drain(script):
        original(script)
        objects['openace'] = SimpleNamespace(get_status=objects['openace'].get_status)
    objects['gcode'].run_script_from_command = drain
    with pytest.raises(ValueError): material.cmd_RECOVER_FILAMENT(command)
    assert objects['gcode'].scripts == ['M400']
    assert material.filament_operation['state'] == 'unknown'


def test_presence_follows_sensor_without_confirmation(filament_check):
    material, sensor, command = filament_check
    material._filament_checks['h2'] = {'state': 'empty'}
    assert material._sensor_filament_status(1)['h2']['state'] == 'loaded'
    sensor.detected = False
    assert material._sensor_filament_status(1)['h2']['state'] == 'empty'
    assert 'identity' not in material._sensor_filament_status(1)['h2']
    sensor.enabled = False  # runout handling is disabled, switch still reports
    sensor.detected = True
    assert material._sensor_filament_status(1)['h2']['state'] == 'loaded'
    sensor.detected = None
    assert material._sensor_filament_status(1)['h2']['state'] == 'unknown'


def test_sensor_presence_survives_print_state_without_saved_metadata(filament_check):
    material, sensor, command = filament_check
    import os
    os.unlink(material.profile_path)
    material.printer.state = 'printing'
    record = material._sensor_filament_status(1)['h2']
    assert record['state'] == 'loaded' and record['identity'] == {}

@pytest.fixture
def service_material(sequence_material):
    from types import SimpleNamespace
    material, objects = sequence_material
    state = {
        'toolhead': {'extruder': 'extruder', 'homed_axes': 'xyz', 'position': [100, 100, 20, 0], 'axis_minimum': [-20, -10, 0], 'axis_maximum': [330, 350, 350]},
        'wmp_recovery': {'z_reference_valid': True},
        'gcode_move': {'homing_origin': [0, 0, 0, 0]},
        'save_variables': {'variables': {**{'t%d_position' % i: [i*75, 330] for i in range(4)}, **{'t%d_offset' % i: [0, 0, 0] for i in range(4)}}},
        'filament_switch_sensor filament2': {'filament_detected': False},
    }
    for name, value in state.items():
        objects[name] = SimpleNamespace(get_status=lambda now, value=value: value)
    return material, objects, state


def test_service_load_plans_cold_head_with_sensor_attachment(service_material):
    material, objects, state = service_material
    from types import SimpleNamespace
    objects['extruder2'] = SimpleNamespace(get_status=lambda now: {'temperature': 25, 'target': 0, 'can_extrude': False})
    plan = material._filament_plan(2, 'load', 1)
    assert plan['service']['attachment']['head'] == 'h2'
    assert plan['target'] == 250
    assert 'heat' in plan['description']
    assert state['toolhead']['extruder'] == 'extruder'  # selection is reconciled during preparation


@pytest.mark.parametrize('maximum', [250., 251., 254., 255.])
def test_filament_recipe_uses_configured_heater_limit_without_extra_margin(service_material, maximum):
    material, objects, state = service_material
    config = objects['configfile'].get_status(1)
    config['settings']['extruder2']['max_temp'] = maximum
    objects['configfile'].get_status = lambda now: config
    plan = material._filament_plan(2, 'load', 1)
    assert plan['target'] == 250
    assert material.filament_operation == {}  # Review dispatches nothing.


def test_filament_recipe_above_actual_heater_limit_reports_both_values(service_material):
    material, objects, state = service_material
    config = objects['configfile'].get_status(1)
    config['settings']['extruder2']['max_temp'] = 249.
    objects['configfile'].get_status = lambda now: config
    with pytest.raises(ValueError, match='Recipe requires 250 C; extruder2 maximum is 249 C'):
        material._filament_plan(2, 'load', 1)
    assert material.filament_operation == {}


@pytest.mark.parametrize('action', ['load', 'unload'])
def test_afc_owner_refuses_standalone_filament_plan_and_command(service_material, action):
    material, objects, state = service_material
    objects['AFC'] = object()
    with pytest.raises(ValueError, match='AFC owns'):
        material._filament_plan(2, action, 1)
    with pytest.raises(ValueError, match='AFC owns'):
        material.cmd_FILAMENT_SEQUENCE(FakeCommand(HEAD=2, ACTION=action, ID='afc-refusal', TOKEN='unused'))
    assert material.filament_operation['state'] == 'refused'
    assert not Path(material._filament_service()._filament_operation_path()).exists()


@pytest.mark.parametrize('mutation', ['calibration', 'active_setup'])
def test_service_refuses_invalid_travel_before_dispatch(service_material, mutation):
    material, objects, state = service_material
    if mutation == 'calibration':
        state['save_variables']['variables']['t2_offset'] = [999, 0, 0]
    else:
        state['save_variables']['variables']['is_nozzle_setting'] = 1
    with pytest.raises(ValueError): material._filament_plan(2, 'load', 1)
    assert material.filament_operation == {}


@pytest.mark.parametrize('fault', [-2, -3, -5])
def test_service_preview_does_not_treat_historical_failure_as_active_setup(service_material, fault):
    material, objects, state = service_material
    variables = state['save_variables']['variables']
    variables['fail_flag'] = fault
    plan = material._filament_plan(2, 'load', 1)
    assert plan['head'] == 'h2' and plan['action'] == 'load'
    assert variables['fail_flag'] == fault  # Read-only preview does not clear history.
    assert material.filament_operation == {}
    # Only an explicit fresh action may retire history before actual movement.
    with pytest.raises(ValueError, match='fail_flag'):
        material._service_context(2, 1)


def test_service_same_head_reconciles_motor_without_toolchange(service_material):
    material, objects, state = service_material
    from types import SimpleNamespace
    scripts = []
    objects['gcode'] = SimpleNamespace(run_script_from_command=scripts.append)
    material._prepare_service(2, material._service_context(2, 1))
    script = '\n'.join(scripts)
    assert 'ACTIVATE_EXTRUDER EXTRUDER=extruder2' in script
    assert 'SAVE_VARIABLE VARIABLE=current_extruder VALUE=2' in script
    assert '_WMP_XY_TRAVEL X=-13' in script and '_WMP_XY_TRAVEL Y=80' in script
    assert 'LOCK' not in script and 'G28' not in script
    assert 'MOVE=1' not in script


def test_lane_metadata_has_afc_types_and_live_sensor_presence(filament_check):
    material, sensor, command = filament_check
    rows = material._lane_data(1)
    row = rows['wmplus_tool_2']
    assert row['lane'] == '2' and row['extruder_index'] == 2
    assert row['color'] == '#ab1234' and row['material'] == 'PETG'
    assert row['unit'] is None and row['slot'] is None and row['loaded'] is True
    sensor.detected = False
    assert material._lane_data(1)['wmplus_tool_2']['loaded'] is False
    material.printer.owner = object()
    assert material._lane_data(1) == {}


@pytest.mark.parametrize('extra', [{'nozzle_temp_min': 260, 'nozzle_temp_max': 220}, {'nozzle_temp': float('nan')}, {'bed_temp': 200}, {'nozzle_temp': True}])
def test_invalid_temperature_metadata_cannot_replace_settings(material, extra):
    identity = {'brand': 'Generic', 'material': 'PLA', 'color': '#abcdef', **extra}
    with pytest.raises(ValueError): material.cmd_SET_FILAMENT(profile_command(material, PROFILE=json.dumps(identity).encode().hex()))
    assert material._profiles()[0] == {}


def test_afc_metadata_commands_use_atomic_native_store(filament_check):
    from types import SimpleNamespace
    material, sensor, _ = filament_check
    original = material.printer.lookup_object
    gcode = SimpleNamespace(create_gcode_command=lambda command, line, args: FakeCommand(**args))
    material.printer.lookup_object = lambda name, default=None: gcode if name == 'gcode' else original(name, default)
    class Command(FakeCommand):
        def get(self, key, default=None): return self.args.get(key, default)
        def get_command(self): return self.args['command']
    for name, params in [('SET_COLOR', {'COLOR': '00FF00'}), ('SET_MATERIAL', {'MATERIAL': 'PLA'}), ('WMP_SET_BRAND', {'BRAND': 'SUNLU'}), ('AFC_SET_SPOOL_TEMP', {'EXTRUDER_TEMP': '220', 'MIN_TEMP': '200', 'MAX_TEMP': '230'})]:
        material.cmd_AFC_METADATA(Command(command=name, LANE='wmplus_tool_2', **params))
    profile = material._profiles()[0]['h2']
    assert profile == {'brand': 'SUNLU', 'material': 'PLA', 'color': '#00FF00', 'nozzle_temp': 220., 'nozzle_temp_min': 200., 'nozzle_temp_max': 230.}
    before = material._profiles()
    with pytest.raises(ValueError): material.cmd_AFC_METADATA(Command(command='SET_COLOR', LANE='wmplus_tool_2', COLOR='INVALID'))
    assert material._profiles() == before
    material.printer.owner = object()
    with pytest.raises(ValueError, match='owns'): material.cmd_AFC_METADATA(Command(command='SET_COLOR', LANE='wmplus_tool_2', COLOR='ffffff'))
    assert material._profiles() == before


@pytest.mark.parametrize('changed', [False, True, 'cancelled'])
@pytest.mark.parametrize('entry', ['reviewed', 'public'])
def test_service_returns_receipt_then_revalidates_under_gcode_lock(service_material, changed, entry):
    from types import SimpleNamespace
    from contextlib import contextmanager
    material, objects, state = service_material
    callbacks, executed = [], []
    locked = [False]
    @contextmanager
    def mutex():
        locked[0] = True
        try: yield
        finally: locked[0] = False
    objects['gcode'] = SimpleNamespace(get_mutex=mutex, create_gcode_command=lambda name, line, args: FakeCommand(**args))
    material.printer.get_reactor = lambda: SimpleNamespace(monotonic=lambda: 1., register_callback=callbacks.append)
    def execute(command, head, action, plan):
        assert locked[0]
        executed.append(head)
        material.filament_operation['state'] = 'complete'
    material._filament_service()._execute_filament = execute
    command = sequence_command(material) if entry == 'reviewed' else FakeCommand(HEAD='2', ACTION='load', ID='public-async')
    submit = material.cmd_FILAMENT_SEQUENCE if entry == 'reviewed' else material.cmd_FILAMENT_SERVICE
    submit(command)
    assert len(callbacks) == 1 and executed == []
    assert material.filament_operation['state'] == 'running'
    with pytest.raises(ValueError, match='already running'):
        submit(command)
    if changed == 'cancelled':
        material._command_generation = 1
        material._print_cancel = {'state': 'complete'}
    elif changed: state['toolhead']['homed_axes'] = ''
    callbacks[0](1.)
    assert executed == ([] if changed else [2])
    assert material.filament_operation['state'] == ('refused' if changed else 'complete')

@pytest.fixture
def toolhead_material(service_material):
    from types import SimpleNamespace
    from contextlib import nullcontext
    material, objects, state = service_material
    material.toolhead_operation = {}
    material.printer.is_shutdown = lambda: False
    material._toolhead_requests = set()
    scripts, callbacks = [], []
    objects['gcode_macro _CHANGE_TOOL'] = object()
    objects['gcode_macro PARK_CURRENT_TOOL'] = object()
    objects['gcode'] = SimpleNamespace(get_mutex=nullcontext, run_script_from_command=scripts.append)
    material.printer.register_callback = callbacks.append
    return material, objects, state, scripts, callbacks


def toolhead_command(material, **updates):
    args = dict(ID='take-1', SESSION=material.session_id, HEAD='2', ACTION='take', ATTACHED='h2')
    args.update(updates)
    return FakeCommand(**args)


def test_toolhead_take_uses_physical_macro_and_waits_for_callback(toolhead_material):
    material, objects, state, scripts, callbacks = toolhead_material
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material))
    assert scripts == [] and material.toolhead_operation['state'] == 'running'
    assert material.toolhead_operation['phase'] == 'checking'
    assert [s['phase'] for s in material.toolhead_operation['steps']] == ['checking', 'moving', 'verifying']
    callbacks.pop()(1)
    assert '_CHANGE_TOOL T=2' in scripts, material.toolhead_operation.get('message')
    assert not any(s in ('T0', 'T1', 'T2', 'T3') for s in scripts)
    assert scripts[0] == 'SAVE_VARIABLE VARIABLE=current_extruder VALUE=2'
    assert material.toolhead_operation['state'] == 'complete'
    assert material.toolhead_operation['phase'] == 'verifying'
    with pytest.raises(ValueError, match='already attempted'):
        material.cmd_TOOLHEAD_ACTION(toolhead_command(material))


def test_toolhead_dock_requires_observed_empty_completion(toolhead_material):
    material, objects, state, scripts, callbacks = toolhead_material
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material, ACTION='dock'))
    callbacks.pop()(1)
    assert 'PARK_CURRENT_TOOL' in scripts
    assert material.toolhead_operation['state'] == 'unknown'
    # The stopped attempt remains visible, but a new user action rechecks the
    # current attachment instead of requiring a secret history reset.
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material, ID='another'))
    callbacks.pop()(1)
    assert material.toolhead_operation['state'] == 'complete'


@pytest.mark.parametrize('change', ['owner', 'busy', 'sensor', 'session', 'wrong_dock', 'filament'])
def test_toolhead_refuses_invalid_requests_before_motion(toolhead_material, change):
    material, objects, state, scripts, callbacks = toolhead_material
    args = {}
    if change == 'owner': objects['openace'] = object()
    if change == 'busy': material.printer.state = 'printing'
    if change == 'sensor': args['ATTACHED'] = 'h1'
    if change == 'session': args['SESSION'] = 'stale'
    if change == 'wrong_dock': args.update(ACTION='dock', HEAD='1')
    if change == 'filament': material.filament_operation = {'state': 'running'}
    with pytest.raises(ValueError): material.cmd_TOOLHEAD_ACTION(toolhead_command(material, **args))
    assert not scripts and not callbacks
    if change != 'session':
        assert material.toolhead_operation['state'] == 'refused'
        assert material.toolhead_operation['id'] == 'take-1'
        assert material.toolhead_operation['session'] == material.session_id
        with pytest.raises(ValueError, match='already attempted'):
            material.cmd_TOOLHEAD_ACTION(toolhead_command(material, **args))


@pytest.mark.parametrize('enqueue_first', [False, True])
def test_toolhead_scheduler_error_retires_receipt_and_callback(toolhead_material, enqueue_first):
    material, objects, state, scripts, callbacks = toolhead_material
    def reject(callback):
        if enqueue_first:
            callbacks.append(callback)
        raise RuntimeError('scheduler failed')
    material.printer.register_callback = reject
    with pytest.raises(RuntimeError, match='scheduler failed'):
        material.cmd_TOOLHEAD_ACTION(toolhead_command(material))
    assert material.toolhead_operation['state'] == 'refused'
    for callback in callbacks:
        callback(1.)
    assert scripts == []
    material.toolhead_operation = {}
    material._restore_toolhead_operation()
    assert material.toolhead_operation['state'] == 'refused'


def test_toolhead_revalidates_before_macro_dispatch(toolhead_material):
    material, objects, state, scripts, callbacks = toolhead_material
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material))
    material.printer.state = 'printing'
    callbacks.pop()(1)
    assert not scripts
    assert material.toolhead_operation['state'] == 'refused'


@pytest.mark.parametrize('owner', ['openace', 'AFC'])
@pytest.mark.parametrize('when', ['admission', 'dispatch'])
@pytest.mark.parametrize('action', ['take', 'dock'])
def test_toolhead_owner_blocks_standalone_dispatch(toolhead_material, owner, when, action):
    material, objects, state, scripts, callbacks = toolhead_material
    command = toolhead_command(material, ACTION=action)
    if when == 'dispatch':
        material.cmd_TOOLHEAD_ACTION(command)
    objects[owner] = object()
    if when == 'admission':
        with pytest.raises(ValueError, match='owns toolhead|manager owns'):
            material.cmd_TOOLHEAD_ACTION(command)
        assert not callbacks
    else:
        callbacks.pop()(1)
        assert material.toolhead_operation['state'] == 'refused'
        material.toolhead_operation = {}
        material._restore_toolhead_operation()
        assert material.toolhead_operation['state'] == 'refused'
    assert not scripts


@pytest.mark.parametrize('job', ['standby', 'printing', 'paused'])
def test_profile_import_commands_return_before_result_and_require_review(material, tmp_path, monkeypatch, job):
    from types import SimpleNamespace
    from wmp_orca_profiles import UsbProfileImport
    root = tmp_path / 'usb'; root.mkdir()
    (root / 'pla.json').write_text(json.dumps({'type':'filament', 'name':'PLA example',
        'filament_vendor':['Example'], 'filament_type':['PLA'], 'nozzle_temperature':['220']}))
    material._profile_importer = UsbProfileImport(root, tmp_path / 'catalogue.json')
    material._profile_import_busy = False
    material.profile_import = {'state':'idle'}
    workers, callbacks = [], []
    monkeypatch.setattr('wm_material.threading.Thread', lambda target, **kw: SimpleNamespace(start=lambda:workers.append(target)))
    material.printer.register_async_callback = callbacks.append
    material.printer.state = job
    material.cmd_PROFILE_IMPORT(FakeCommand(ACTION='scan', ID='scan1'))
    assert material.profile_import['state'] == 'busy' and not (tmp_path / 'catalogue.json').exists()
    with pytest.raises(ValueError, match='busy'): material.cmd_PROFILE_IMPORT(FakeCommand(ACTION='scan', ID='scan2'))
    workers.pop()(); assert material._profile_import_busy
    callbacks.pop()(1); entry = material.profile_import['files'][0]['id']
    material.cmd_PROFILE_IMPORT(FakeCommand(ACTION='review', ID='review1', FILE=entry))
    workers.pop()(); callbacks.pop()(1)
    token = material.profile_import['token']
    assert material.profile_import['id'] == 'review1' and not (tmp_path / 'catalogue.json').exists()
    if job != 'standby':
        with pytest.raises(ValueError, match='idle'):
            material.cmd_PROFILE_IMPORT(FakeCommand(ACTION='save', ID='busy-save', TOKEN=token))
        assert not (tmp_path / 'catalogue.json').exists()
    material.printer.state = 'standby'
    material._status_catalogue_snapshot = ({}, 'old-revision')
    material.cmd_PROFILE_IMPORT(FakeCommand(ACTION='save', ID='save1', TOKEN=token))
    workers.pop()(); callbacks.pop()(1)
    assert material.profile_import['state'] == 'saved' and (tmp_path / 'catalogue.json').exists()
    assert material._status_catalogue_snapshot is None
    material.printer.owner = object()
    with pytest.raises(ValueError, match='standalone'): material.cmd_PROFILE_IMPORT(FakeCommand(ACTION='scan', ID='other'))


@pytest.mark.parametrize('enqueue_first', [False, True])
def test_filament_scheduler_failure_cannot_run_later(service_material, enqueue_first):
    material, objects, state = service_material
    callbacks, executed = [], []
    def reject(callback):
        if enqueue_first:
            callbacks.append(callback)
        raise RuntimeError('scheduler failed')
    material.printer.register_callback = reject
    material._filament_service()._execute_filament = lambda *args: executed.append(args)
    with pytest.raises(RuntimeError, match='scheduler failed'):
        material.cmd_FILAMENT_SEQUENCE(sequence_command(material))
    assert material.filament_operation['state'] == 'refused'
    for callback in callbacks:
        callback(1.)
    assert not executed
    material.filament_operation = {}
    material._restore_filament_operation()
    assert material.filament_operation['state'] == 'refused'


def test_filament_intent_write_failure_does_not_block_or_duplicate_dispatch(service_material, monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    material, objects, state = service_material
    objects['gcode'] = SimpleNamespace(get_mutex=nullcontext)
    callbacks, executed = [], []
    material.printer.register_callback = callbacks.append
    def fail(): raise OSError('journal unavailable')
    monkeypatch.setattr(material._filament_service(), '_persist_filament_operation', fail)
    def execute(*args):
        executed.append(args)
        material.filament_operation['state'] = 'complete'
    monkeypatch.setattr(material._filament_service(), '_execute_filament', execute)
    command = sequence_command(material)
    material.cmd_FILAMENT_SEQUENCE(command)
    assert material.filament_operation['state'] == 'running'
    assert material.filament_operation['persistence_error'] == 'journal unavailable'
    with pytest.raises(ValueError): material.cmd_FILAMENT_SEQUENCE(command)
    callbacks.pop()(1)
    assert len(executed) == 1
    with pytest.raises(ValueError, match='already attempted'):
        material.cmd_FILAMENT_SEQUENCE(command)


def test_filament_scheduler_refusal_write_failure_retains_refusal(service_material, monkeypatch):
    material, objects, state = service_material
    callbacks, executed = [], []
    def reject(callback):
        callbacks.append(callback)
        raise RuntimeError('scheduler failed')
    persist = material._filament_service()._persist_filament_operation
    def fail_refusal():
        if material.filament_operation['state'] == 'refused':
            raise OSError('refusal journal unavailable')
        persist()
    material.printer.register_callback = reject
    material._filament_service()._execute_filament = lambda *args: executed.append(args)
    monkeypatch.setattr(material._filament_service(), '_persist_filament_operation', fail_refusal)
    with pytest.raises(RuntimeError, match='scheduler failed'):
        material.cmd_FILAMENT_SEQUENCE(sequence_command(material))
    callbacks.pop()(1.)
    assert not executed and material.filament_operation['state'] == 'refused'
    material.filament_operation = {}
    material._restore_filament_operation()
    assert material.filament_operation['state'] == 'unknown'


def test_profile_worker_start_failure_clears_busy(material, monkeypatch):
    material._profile_import_busy = False
    def reject(**kwargs):
        raise RuntimeError('thread unavailable')
    monkeypatch.setattr('wm_material.threading.Thread', reject)
    with pytest.raises(RuntimeError, match='thread unavailable'):
        material.cmd_PROFILE_IMPORT(FakeCommand(ACTION='scan', ID='scan1'))
    assert not material._profile_import_busy
    assert material.profile_import['state'] == 'error'


@pytest.mark.parametrize('enqueue_first', [False, True])
def test_profile_completion_survives_failed_reactor_wakeup(material, monkeypatch, enqueue_first):
    from types import SimpleNamespace
    material._profile_import_busy = False
    material._profile_importer = SimpleNamespace(scan=lambda: {'state': 'scanned', 'files': []})
    workers, callbacks = [], []
    monkeypatch.setattr('wm_material.threading.Thread', lambda target, **kw:
                        SimpleNamespace(start=lambda: workers.append(target)))
    def reject(callback):
        if enqueue_first:
            callbacks.append(callback)
        raise RuntimeError('wakeup failed')
    material.printer.register_async_callback = reject
    material.cmd_PROFILE_IMPORT(FakeCommand(ACTION='scan', ID='scan1'))
    workers.pop()()
    assert material._profile_import_busy
    material._drain_async_completions(1.)
    assert not material._profile_import_busy
    assert material.profile_import == {'state': 'scanned', 'files': [], 'id': 'scan1'}
    # A delayed callback cannot replay an old result over the next request.
    material.profile_import = {'state': 'busy', 'id': 'scan2'}
    for callback in callbacks:
        callback(2.)
    assert material.profile_import == {'state': 'busy', 'id': 'scan2'}


def test_afc_thread_start_failure_releases_only_publisher_busy(material, monkeypatch):
    material._afc_stopped = material._afc_busy = False
    material._afc_last = None
    material._material_owners()._lane_data = lambda now: {'head': {}}
    def reject(**kwargs):
        raise RuntimeError('thread unavailable')
    monkeypatch.setattr('wm_material.threading.Thread', reject)
    assert material._afc_tick(1.) == 3.
    assert not material._afc_busy
    assert 'thread unavailable' in material._afc_error


def test_afc_completion_is_drained_by_timer_after_lost_wakeup(material, monkeypatch):
    material.printer.NEVER = float('inf')
    material._afc_stopped = False
    material._afc_busy = True
    material._afc_last = None
    def fail(*args, **kwargs):
        raise RuntimeError('publisher unavailable')
    monkeypatch.setattr('wm_material.urllib.request.urlopen', fail)
    material.printer.register_async_callback = fail
    material._afc_publish({})
    assert material._afc_busy  # Worker does not mutate reactor-owned flags.
    material._afc_stopped = True  # Drain completion without starting another publish.
    material._afc_tick(1.)
    assert not material._afc_busy and 'publisher unavailable' in material._afc_error

class CancelWebRequest:
    error = ValueError
    def __init__(self, **params):
        self.params = params
        self.response = None
    def get_str(self, key, default=None):
        value = self.params.get(key, default)
        if not isinstance(value, str):
            raise ValueError('Invalid string')
        return value
    def send(self, value):
        self.response = value


def cancellation_request(material, **updates):
    params = dict(session=material.session_id, id='cancel-test', head='h2')
    params.update(updates)
    return CancelWebRequest(**params)


@pytest.mark.parametrize('change', ['session', 'id', 'head', 'finished', 'openace'])
def test_filament_cancel_rejects_wrong_operation(material, change):
    material.filament_operation = dict(id='cancel-test', session=material.session_id, head='h2', state='running')
    request = cancellation_request(material, **({change: 'wrong'} if change in ('session', 'id', 'head') else {}))
    if change == 'finished': material.filament_operation['state'] = 'complete'
    if change == 'openace': material.printer.owner = object()
    before = dict(material.filament_operation)
    with pytest.raises(ValueError): material._handle_filament_cancel(request)
    assert material.filament_operation == before and request.response is None


@pytest.mark.parametrize('phase', ['preparing', 'heating', 'inserting', 'feeding'])
@pytest.mark.parametrize('cleanup_fails', [False, True])
def test_filament_cancel_at_checkpoints_stops_then_confirms_heater_off(service_material, monkeypatch, phase, cleanup_fails):
    from types import SimpleNamespace
    from wm_material import FilamentCancelled
    material, objects, state = service_material
    calls, feeds = [], []
    heater = {'temperature': 25 if phase == 'heating' else 250, 'target': 0, 'can_extrude': phase != 'heating'}
    clock = [1.]
    material.filament_operation = dict(id='cancel-test', session=material.session_id, head='h2', state='running')
    def cancel():
        request = cancellation_request(material)
        material._handle_filament_cancel(request)
        assert request.response['state'] == 'requested'
        assert material.filament_operation['state'] == 'running'
    def pause(deadline):
        clock[0] = deadline
        cancel()  # callback runs while the operation is waiting, without G-code
    material.printer.get_reactor = lambda: SimpleNamespace(monotonic=lambda: clock[0], pause=pause)
    objects['extruder2'] = SimpleNamespace(get_status=lambda now: dict(heater))
    state['toolhead']['extruder'] = 'extruder2'
    def run(script):
        calls.append(script)
        if 'TARGET=' in script:
            target = float(script.split('TARGET=')[1])
            if target == 0 and cleanup_fails: raise ValueError('heater cleanup failed')
            heater['target'] = target
    objects['gcode'] = SimpleNamespace(run_script_from_command=run)
    # Positioning now owns starting the selected physical heater.
    material._filament_planning()._prepare_service = lambda head, context: run(
        "SET_HEATER_TEMPERATURE HEATER=extruder%d TARGET=%.3f" % (head, context["heat_target"]))
    def feed(printer, sequence):
        feeds.append(sequence)
        cancel()
    monkeypatch.setattr('wm_material.run_standalone_extrusion_sequence', feed)
    if phase == 'preparing': cancel()
    if phase == 'feeding': state['filament_switch_sensor filament2']['filament_detected'] = True
    plan = {'service': {}, 'target': 250, 'head': 'h2', 'class': 'pla',
            'identity': material._profiles()[0]['h2']}
    with pytest.raises(FilamentCancelled): material._filament_service()._execute_filament(FakeCommand(), 2, 'load', plan)
    assert len(feeds) == (1 if phase == 'feeding' else 0)
    assert 'M400' in calls
    assert material.filament_operation['cancelled'] is True
    assert material.filament_operation['state'] == ('unknown' if cleanup_fails else 'failed')
    if not cleanup_fails: assert heater['target'] == 0


@pytest.mark.parametrize('action', ['load', 'unload'])
@pytest.mark.parametrize('axes', ['xy', 'xyz'])
@pytest.mark.parametrize('fault', ['none', 'ignored_off', 'off_exception', 'transient_off', 'sensor', 'purge', 'wipe'])
def test_service_completion_requires_heater_off_and_sensor_readback(service_material, monkeypatch, action, fault, axes):
    from types import SimpleNamespace
    material, objects, state = service_material
    state['toolhead']['homed_axes'] = axes
    if action == "unload" and fault in ("purge", "wipe"): return
    calls, feeds = [], []
    heater = dict(temperature=250, target=0, can_extrude=True)
    material.filament_operation = dict(id='finish-test', session=material.session_id, head='h2', state='running')
    objects['extruder2'] = SimpleNamespace(get_status=lambda now: dict(heater))
    state['toolhead']['extruder'] = 'extruder2'
    state['filament_switch_sensor filament2']['filament_detected'] = True
    off_attempts = []
    def run(script):
        calls.append(script)
        if script == 'WIPE_NOZZLE XY_ONLY=1\nM400':
            assert len(feeds) == 2 and heater['target'] == 250
            if fault == 'wipe': raise ValueError('wipe failed')
        if 'TARGET=' not in script: return
        target = float(script.split('TARGET=')[1])
        if target == 0:
            off_attempts.append(script)
            if fault == 'ignored_off': return
            if fault == 'off_exception' or (fault == 'transient_off' and len(off_attempts) == 1):
                raise ValueError('heater off failed')
        heater['target'] = target
    objects['gcode'] = SimpleNamespace(run_script_from_command=run)
    # Positioning now owns starting the selected physical heater.
    material._filament_planning()._prepare_service = lambda head, context: run(
        "SET_HEATER_TEMPERATURE HEATER=extruder%d TARGET=%.3f" % (head, context["heat_target"]))
    def feed(printer, sequence):
        feeds.append(sequence)
        if fault == "purge" and len(feeds) == 2: raise ValueError("purge failed")
        state['filament_switch_sensor filament2']['filament_detected'] = (action == 'load') != (fault == 'sensor')
    monkeypatch.setattr('wm_material.run_standalone_extrusion_sequence', feed)
    plan = dict(service={}, target=250, head='h2', identity=material._profiles()[0]['h2'], **{'class': 'pla'})
    if fault == 'none' or (fault == 'sensor' and action == 'unload'):
        material._filament_service()._execute_filament(FakeCommand(), 2, action, plan)
        assert material.filament_operation['state'] == 'complete'
        assert len(off_attempts) == 1
    else:
        with pytest.raises(ValueError): material._filament_service()._execute_filament(FakeCommand(), 2, action, plan)
        assert material.filament_operation['state'] == ('unknown' if fault in ('ignored_off', 'off_exception') else 'failed')
        assert 'M400' in calls
        assert len(off_attempts) == (1 if fault in ("purge", "wipe") or (fault == "sensor" and action == "load") else 2)
    if action == 'load' and fault == 'none':
        assert feeds == ['G1 E55 F400', 'G1 E50 F400']
        assert 'WIPE_NOZZLE XY_ONLY=1\nM400' in calls
        assert material._filament_state()._load_filament_flags()['h2'] is True
    if fault == 'purge':
        assert 'WIPE_NOZZLE XY_ONLY=1\nM400' not in calls
        assert material._hotend_material_history()['h2']['state'] == 'mixed'
    if fault == 'wipe':
        assert material._hotend_material_history()['h2']['state'] == 'purged'
    if fault in ('purge', 'wipe'): assert material._filament_state()._load_filament_flags().get('h2', False) is False
    assert len(feeds) == (2 if action == 'load' and fault != 'sensor' else 1)  # No replay during cleanup.
    assert (heater['target'] == 0) == (fault not in ('ignored_off', 'off_exception'))


@pytest.mark.parametrize('detected', [False, None])
def test_empty_lane_hides_saved_identity_without_forgetting_it(filament_check, detected):
    material, sensor, _ = filament_check
    saved = material._profiles()
    sensor.detected = detected
    row = material._lane_data(1)['wmplus_tool_2']
    assert row['loaded'] is False
    for field in ('material', 'brand', 'color', 'name'): assert row[field] == ''
    for field in ('nozzle_temp', 'bed_temp', 'nozzle_temp_min', 'nozzle_temp_max'): assert row[field] == 0
    assert material._profiles() == saved
    sensor.detected = True
    assert material._lane_data(1)['wmplus_tool_2']['material'] == 'PETG'  # a brief edge is not a durable unload


@pytest.mark.parametrize('scenario', ['standalone', 'openace', 'AFC', 'changed_owner', 'changed_session', 'stopped', 'write_failure'])
def test_lane_publisher_reconciles_only_verified_owner_projections(material, monkeypatch, scenario):
    import io
    from types import SimpleNamespace
    from urllib.parse import urlparse, parse_qs
    database = {'openace_tool_0': {'lane': '0'}, 'wmplus_tool_9': {'lane': '9'},
                'foreign_lane': {'lane': '8'}, 'openace_tool_custom': {'lane': '7'}}
    before = dict(database)
    owner = scenario if scenario in ('openace', 'AFC') else 'standalone'
    rows = {} if owner != 'standalone' else {'wmplus_tool_0': {'lane': '0', 'loaded': False}}
    material._afc_stopped = scenario == 'stopped'
    material._afc_busy = True
    material._afc_last = None
    checks, writes = [], []
    material.printer.get_reactor = lambda: SimpleNamespace(register_async_callback=lambda f: f(0))
    def urlopen(request, timeout):
        parsed = urlparse(request.full_url)
        if parsed.path == '/printer/objects/query':
            checks.append(True)
            current = 'openace' if scenario == 'changed_owner' and len(checks) > 1 else owner
            session = 'new-session' if scenario == 'changed_session' else material.session_id
            result = {'status': {'wm_material': {'session_id': session, 'afc_metadata': {'owner': current}}}}
        elif request.method == 'GET': result = {'value': dict(database)}
        else:
            if scenario == 'write_failure': raise OSError('database unavailable')
            writes.append(request.method)
            if request.method == 'POST':
                body = json.loads(request.data);database[body['key']] = body['value']
            else: database.pop(parse_qs(parsed.query)['key'][0])
            result = {}
        return io.BytesIO(json.dumps({'result': result}).encode())
    monkeypatch.setattr('wm_material.urllib.request.urlopen', urlopen)
    material._afc_publish(rows)
    assert material._afc_busy is False
    if scenario in ('changed_owner', 'changed_session', 'stopped', 'write_failure'):
        assert database == before and material._afc_error and material._afc_last is None
    else:
        assert not material._afc_error and material._afc_last == rows
        assert 'wmplus_tool_9' not in database
        assert ('openace_tool_0' in database) == (owner != 'standalone')
        if owner == 'standalone': assert writes[0] == 'POST' and database['wmplus_tool_0'] == rows['wmplus_tool_0']
    assert database['foreign_lane'] == before['foreign_lane']
    assert database['openace_tool_custom'] == before['openace_tool_custom']


@pytest.mark.parametrize('lane', ['wmplus_tool_0', 'T0', 't0', '0'])
def test_remote_lane_alias_identifies_physical_head_despite_job_mapping(filament_check, lane):
    from types import SimpleNamespace
    material, sensor, _ = filament_check
    original = material.printer.lookup_object
    gcode = SimpleNamespace(create_gcode_command=lambda command, line, args: FakeCommand(**args))
    saved = SimpleNamespace(get_status=lambda now: {'variables': {'box_modify_t0': 2}})
    material.printer.lookup_object = lambda name, default=None: gcode if name == 'gcode' else saved if name == 'save_variables' else original('extruder2', default) if name == 'extruder' else original(name, default)
    class Command(FakeCommand):
        def get_command(self): return 'SET_COLOR'
    material.cmd_AFC_METADATA(Command(LANE=lane, COLOR='123456'))
    profiles = material._profiles()[0]
    assert profiles['h0']['color'] == '#123456'
    assert profiles['h2']['color'] != '#123456'
    assert material._lane_data(1)['wmplus_tool_0']['extruder_index'] == 0


@pytest.mark.parametrize('lane', ['openace_tool_2', 'h2', 'T4', '-1', '2.0', 'T2 extra', ''])
def test_remote_lane_alias_rejects_foreign_or_invalid_identifiers(filament_check, lane):
    material, _, _ = filament_check
    before = material._profiles()
    with pytest.raises(ValueError, match='Unknown WM\\+ lane'):
        material.cmd_AFC_METADATA(FakeCommand(LANE=lane, COLOR='123456'))
    assert material._profiles() == before


@pytest.mark.parametrize('presence', [True, False])
@pytest.mark.parametrize('fault', ['', 'drain', 'heater', 'ignored_off', 'sensor', 'attachment', 'journal', 'journal_always', 'journal_after_write'])
def test_filament_recovery_confirms_stop_without_replaying_moves(service_material, presence, fault, monkeypatch):
    from types import SimpleNamespace
    material, objects, state = service_material
    calls = []
    heater = {'target': 250}
    material.filament_operation = dict(id='interrupted', session=material.session_id, head='h2', action='load', state='unknown')
    material.filament_operation['command_generation'] = 7  # Prior process/generation; cleanup must remain possible.
    state['filament_switch_sensor filament2']['filament_detected'] = None if fault == 'sensor' else presence
    objects['extruder2'] = SimpleNamespace(get_status=lambda now: dict(heater))
    if fault == 'attachment': material._material_status()._attachment = lambda now: {'state': 'unknown', 'head': ''}
    def run(script):
        calls.append(script)
        if script == 'M400' and fault == 'drain': raise ValueError('drain failed')
        if 'TARGET=0' in script:
            if fault == 'heater': raise ValueError('heater command failed')
            if fault != 'ignored_off': heater['target'] = 0
    objects['gcode'] = SimpleNamespace(run_script_from_command=run)
    # Exercise the same recovery after losing the Python process, rather than
    # relying only on an in-memory unknown record.
    material.filament_operation['state'] = 'running'
    material._filament_service()._persist_filament_operation()
    material.filament_operation = {}
    material.session_id = 'restarted-session'
    material._restore_filament_operation()
    assert material.filament_operation['state'] == 'unknown'
    assert material.filament_operation['previous_session'] == 'test-session'
    command = FakeCommand(HEAD='2', SESSION=material.session_id, ID='interrupted')
    if fault.startswith('journal'):
        persist = material._filament_service()._persist_filament_operation
        def fail_terminal_write():
            if fault == 'journal_always':
                raise OSError('storage remains unavailable')
            if material.filament_operation.get('recovered'):
                if fault == 'journal_after_write':
                    persist()
                raise OSError('result storage unavailable')
            persist()
        monkeypatch.setattr(material._filament_service(), '_persist_filament_operation', fail_terminal_write)
    if fault and not fault.startswith('journal'):
        with pytest.raises(ValueError, match='Recovery not confirmed'): material.cmd_RECOVER_FILAMENT(command)
        assert material.filament_operation['state'] == 'unknown'
        assert not material.filament_operation.get('recovered')
        # Cleanup must still turn the heater off after an earlier failure, but
        # the progress display must retain the first failed stage.
        expected_phase = ('draining' if fault == 'drain' else
                          'cooling' if fault in ('heater', 'ignored_off') else 'verifying')
        assert material.filament_operation['phase'] == expected_phase
    else:
        material.cmd_RECOVER_FILAMENT(command)
        assert material.filament_operation['state'] == 'failed'  # Never converts a partial load to complete.
        assert material.filament_operation['recovered'] is True
        if fault.startswith('journal'):
            assert material.filament_operation['persistence_error']
        assert material.filament_operation['recovery_presence'] == ('loaded' if presence else 'empty')
        with pytest.raises(ValueError, match='does not need'): material.cmd_RECOVER_FILAMENT(command)
    assert calls == ['M400', 'SET_HEATER_TEMPERATURE HEATER=extruder2 TARGET=0']


@pytest.mark.parametrize('change', ['session', 'id', 'head', 'running', 'complete', 'owner', 'busy', 'tool'])
def test_filament_recovery_rejects_changed_context_before_commands(service_material, change):
    from types import SimpleNamespace
    material, objects, state = service_material
    material.filament_operation = dict(id='interrupted', session=material.session_id, head='h2', action='load', state='unknown')
    calls = []
    objects['gcode'] = SimpleNamespace(run_script_from_command=calls.append)
    args = dict(HEAD='2', SESSION=material.session_id, ID='interrupted')
    if change == 'session': args['SESSION'] = 'old-session'
    elif change == 'id': args['ID'] = 'other-operation'
    elif change == 'head': args['HEAD'] = '1'
    elif change in ('running', 'complete'): material.filament_operation['state'] = change
    elif change == 'owner': objects['openace'] = object()
    elif change == 'busy': material._material_settings()._idle_for_filament_settings = lambda now: False
    elif change == 'tool': material.toolhead_operation = {'state': 'running'}
    before = dict(material.filament_operation)
    with pytest.raises(ValueError): material.cmd_RECOVER_FILAMENT(FakeCommand(**args))
    assert calls == [] and material.filament_operation == before


def test_unknown_filament_history_allows_new_edit_and_print_admission(material):
    material.filament_operation = {'state': 'unknown', 'id': 'interrupted'}
    material.cmd_SET_FILAMENT(profile_command(material))
    material._print_admission(FakeCommand())
    assert material.filament_operation == {'state': 'unknown', 'id': 'interrupted'}


@pytest.fixture
def interrupted_toolhead(toolhead_material):
    material, objects, state, scripts, callbacks = toolhead_material
    material.toolhead_operation = dict(id='interrupted-tool', session=material.session_id,
                                       head='h2', action='take', state='unknown')
    state['save_variables']['variables'].update(fail_flag=0, is_nozzle_setting=0)
    command = FakeCommand(ID='interrupted-tool', SESSION=material.session_id, HEAD='2')
    return material, objects, state, scripts, command


@pytest.mark.parametrize('attached', ['h0', 'h2', ''])
def test_toolhead_recovery_records_sensors_without_replaying_action(interrupted_toolhead, attached):
    material, objects, state, scripts, command = interrupted_toolhead
    observed = {'state': 'attached' if attached else 'empty', 'head': attached}
    material._material_status()._attachment = lambda now: dict(observed)
    before = dict(state['save_variables']['variables'])
    material.cmd_RECOVER_TOOLHEAD(command)
    assert scripts == ['M400']
    assert state['save_variables']['variables'] == before
    assert material.toolhead_operation['state'] == 'failed'
    assert material.toolhead_operation['recovered'] is True
    assert material.toolhead_operation['recovery_attachment'] == observed
    with pytest.raises(ValueError, match='does not need'):
        material.cmd_RECOVER_TOOLHEAD(command)
    assert scripts == ['M400']


@pytest.mark.parametrize('change', ['session', 'id', 'head', 'running', 'complete',
                                    'owner', 'afc', 'busy', 'filament', 'sensor',
                                    'fault', 'setup'])
def test_toolhead_recovery_refuses_changed_or_unresolved_context(interrupted_toolhead, change):
    material, objects, state, scripts, command = interrupted_toolhead
    args = dict(ID='interrupted-tool', SESSION=material.session_id, HEAD='2')
    if change == 'session': args['SESSION'] = 'old-session'
    elif change == 'id': args['ID'] = 'other'
    elif change == 'head': args['HEAD'] = '1'
    elif change in ('running', 'complete'): material.toolhead_operation['state'] = change
    elif change == 'owner': objects['openace'] = object()
    elif change == 'afc': objects['AFC'] = object()
    elif change == 'busy': material._material_settings()._idle_for_filament_settings = lambda now: False
    elif change == 'filament': material.filament_operation = {'state': 'running'}
    elif change == 'sensor': material._material_status()._attachment = lambda now: {'state': 'unknown', 'head': ''}
    elif change == 'fault': state['save_variables']['variables']['fail_flag'] = -2
    elif change == 'setup': state['save_variables']['variables']['is_nozzle_setting'] = 1
    before = dict(material.toolhead_operation)
    with pytest.raises(ValueError): material.cmd_RECOVER_TOOLHEAD(FakeCommand(**args))
    assert scripts == []
    after = dict(material.toolhead_operation)
    message = after.pop("message", "")
    assert after == before
    if change not in ("session", "id", "head", "running", "complete"):
        assert message.startswith("Recovery not confirmed:")


def test_toolhead_recovery_missing_historical_flag_does_not_block_reconciliation(interrupted_toolhead):
    material, objects, state, scripts, command = interrupted_toolhead
    state['save_variables']['variables'].pop('fail_flag')
    material.cmd_RECOVER_TOOLHEAD(command)
    assert scripts == ['M400']  # Observe completion; never replay pickup/docking.
    assert state['save_variables']['variables']['fail_flag'] == 0
    assert material.toolhead_operation['recovered'] is True
    assert material.toolhead_operation['state'] == 'failed'


@pytest.mark.parametrize('change', ['drain', 'busy', 'sensor', 'fault', 'owner'])
def test_toolhead_recovery_rechecks_after_draining(interrupted_toolhead, change):
    material, objects, state, scripts, command = interrupted_toolhead
    def run(script):
        scripts.append(script)
        if change == 'drain': raise ValueError('drain failed')
        if change == 'busy': material._material_settings()._idle_for_filament_settings = lambda now: False
        if change == 'sensor': material._material_status()._attachment = lambda now: {'state': 'unknown', 'head': ''}
        if change == 'fault': state['save_variables']['variables']['fail_flag'] = -2
        if change == 'owner': objects['openace'] = object()
    objects['gcode'].run_script_from_command = run
    with pytest.raises(ValueError, match='Recovery not confirmed'):
        material.cmd_RECOVER_TOOLHEAD(command)
    assert scripts == ['M400']
    assert material.toolhead_operation['state'] == 'unknown'
    assert not material.toolhead_operation.get('recovered')


def test_imported_target_is_shared_by_load_and_unload(service_material):
    material, objects, state = service_material
    identity = {'brand': 'Generic', 'material': 'PLA', 'color': '#12ABCD',
                'nozzle_temp': 215, 'nozzle_temp_min': 190, 'nozzle_temp_max': 230}
    material.cmd_SET_FILAMENT(profile_command(material, PROFILE=json.dumps(identity).encode().hex()))
    assert material._filament_plan(2, 'load', 1)['target'] == 215
    state['filament_switch_sensor filament2']['filament_detected'] = True
    material._set_filament_loaded('h2', True)
    assert material._filament_plan(2, 'unload', 1)['target'] == 215
    assert material.filament_operation == {}
    assert material._profiles()[0]['h2'] == identity



@pytest.mark.parametrize('temperature', [None, 260])
def test_petg_service_load_and_unload_share_default_or_profile_temperature(service_material, temperature):
    material, objects, state = service_material
    identity = {'brand': 'Example', 'material': 'PETG', 'color': '#cd001a'}
    if temperature is not None:
        identity.update(nozzle_temp=temperature, nozzle_temp_min=240, nozzle_temp_max=270)
    material.cmd_SET_FILAMENT(profile_command(material, PROFILE=json.dumps(identity).encode().hex()))
    load = material._filament_plan(2, 'load', 1)
    state['filament_switch_sensor filament2']['filament_detected'] = True
    material._set_filament_loaded('h2', True)
    unload = material._filament_plan(2, 'unload', 1)
    assert load['target'] == unload['target'] == (250 if temperature is None else temperature)
    assert unload['class'] == 'petg'
    assert material.filament_operation == {}


@pytest.mark.parametrize('name', ['PLA-CF', 'PA6-GF', 'Custom'])
def test_explicit_temperature_does_not_invent_unknown_material_recipe(service_material, name):
    material, objects, state = service_material
    identity = {'brand': 'Generic', 'material': name, 'color': '#12ABCD', 'nozzle_temp': 250}
    material.cmd_SET_FILAMENT(profile_command(material, PROFILE=json.dumps(identity).encode().hex()))
    if name == 'Custom':
        with pytest.raises(ValueError, match='No supported load recipe for ' + name):
            material._filament_plan(2, 'load', 1)
    else:
        assert material._filament_plan(2, 'load', 1)['target'] == 250
    assert material.filament_operation == {}


@pytest.mark.parametrize('name,load_temp,unload_temp', [
    ('PCTG', 260, 260), ('PA6', 260, 260), ('PA12', 260, 260), ('PP', 240, 240)])
def test_builtin_added_materials_have_service_plans(service_material, name, load_temp, unload_temp):
    material, objects, state = service_material
    identity = {'brand': 'Generic', 'material': name, 'color': '#12ABCD'}
    material.cmd_SET_FILAMENT(profile_command(material, PROFILE=json.dumps(identity).encode().hex()))
    assert material._filament_plan(2, 'load', 1)['target'] == load_temp
    state['filament_switch_sensor filament2']['filament_detected'] = True
    material._set_filament_loaded('h2', True)
    assert material._filament_plan(2, 'unload', 1)['target'] == unload_temp
    assert material.filament_operation == {}


@pytest.mark.parametrize('axes,reference', [('', False), ('xy', False), ('xyz', False), ('xy', True)])
def test_service_never_homes_missing_z_reference(service_material, axes, reference):
    material, objects, state = service_material
    state['toolhead']['homed_axes'] = axes
    state['wmp_recovery']['z_reference_valid'] = reference
    plan = material._filament_plan(2, 'load', 1)
    assert plan['service']['needs_home'] == (axes == '')


@pytest.mark.parametrize('axes', ['', 'x', 'y', 'z', 'xz', 'yz'])
def test_service_plans_xy_homing_only(service_material, axes):
    material, objects, state = service_material
    state['toolhead']['homed_axes'] = axes
    plan = material._filament_plan(2, 'load', 1)
    assert plan['service']['needs_home']
    assert plan['description'].startswith('Home X/Y')


@pytest.mark.parametrize('result', ['ok', 'failure', 'unhomed', 'calibration', 'probe', 'cancel'])
def test_service_homing_precedes_travel_and_stops_on_failure(service_material, result):
    from types import SimpleNamespace
    material, objects, state = service_material
    state['toolhead']['homed_axes'] = 'z'
    state['wmp_recovery']['z_reference_valid'] = True
    context = material._service_context(2, 1, allow_homing=True)
    scripts = []
    def run(script):
        scripts.append(script)
        if script == 'G28 X Y\nM400':
            if result == 'failure': raise ValueError('homing failed')
            state['toolhead']['homed_axes'] = '' if result == 'unhomed' else 'xyz'
            state['wmp_recovery']['z_reference_valid'] = result != 'reference'
            state['toolhead']['position'][2] = 7
            state['save_variables']['variables']['probe_tool'] = 1 if result == 'probe' else 0
            if result == 'calibration': state['save_variables']['variables']['t2_offset'] = [1, 0, 0]
            if result == 'cancel': material.filament_operation['cancel_requested'] = True
    objects['gcode'] = SimpleNamespace(run_script_from_command=run)
    if result == 'ok':
        material._prepare_service(2, context)
        assert scripts[0] == 'G28 X Y\nM400'
        assert any('_WMP_XY_TRAVEL X=-13' in script for script in scripts[1:])
    else:
        with pytest.raises(Exception): material._prepare_service(2, context)
        assert scripts == ['G28 X Y\nM400']


@pytest.mark.parametrize('failed_macro', ['_UNLOCK_TOOL', '_LOCK_TOOL'])
def test_service_shared_dock_mount_failure_stops_before_filament_service(service_material, failed_macro):
    from types import SimpleNamespace
    material, objects, state = service_material
    material._material_status()._attachment = lambda now: {'state': 'attached', 'head': 'h1'}
    calls = []
    def run(command):
        calls.append(command)
        if command.startswith(failed_macro + ' '):
            raise ValueError('shared toolhead check failed')
    objects['gcode'] = SimpleNamespace(run_script_from_command=run)
    context = material._service_context(2, 1)
    with pytest.raises(ValueError, match='shared toolhead check failed'):
        material._prepare_service(2, context)
    assert '_UNLOCK_TOOL T=1 SERVICE=1' in calls
    assert calls[-1].startswith(failed_macro + ' ')
    assert not any('ACTIVATE_EXTRUDER' in command or '_WMP_XY_TRAVEL X=-13' in command for command in calls)
    assert not any(command.startswith('_CHECK_CHANGE_TOOL ') for command in calls)


def test_loaded_flag_persists_but_present_sensor_does_not_reload(filament_check):
    material, sensor, _ = filament_check
    assert material._loaded_filament_status(1)['h2']['state'] == 'loaded'
    del material._loaded_flags
    assert material._loaded_filament_status(1)['h2']['state'] == 'loaded'
    sensor.detected = False
    assert material._loaded_filament_status(1)['h2']['state'] == 'empty'
    material._loaded_filament_status(1.3)  # Sustained loss, not a single poll.
    sensor.detected = True
    del material._loaded_flags
    record = material._loaded_filament_status(1)['h2']
    assert record['state'] == 'empty' and record['sensor_present'] is True
    assert 'identity' not in record
    material._set_filament_loaded('h2', True)
    material._set_filament_loaded('h2', False)
    del material._loaded_flags
    assert material._loaded_filament_status(1)['h2']['state'] == 'empty'


def test_present_unloaded_head_admits_load(service_material):
    material, objects, state = service_material
    material._set_filament_loaded('h2', False)
    reviewed = material._filament_plan(2, 'load', 1)
    state['filament_switch_sensor filament2']['filament_detected'] = True
    plan = material._filament_plan(2, 'load', 1)
    assert plan['head'] == 'h2'
    assert plan['token'] == reviewed['token']
    with pytest.raises(ValueError):
        material._filament_plan(2, 'unload', 1)


@pytest.mark.parametrize('needs_home', [False, True])
def test_filament_service_starts_heating_after_xy_home_before_tool_travel(service_material, needs_home):
    from types import SimpleNamespace
    material, objects, state = service_material
    material._material_status()._attachment = lambda now: {'state': 'attached', 'head': 'h0'}
    state['toolhead']['homed_axes'] = 'z' if needs_home else 'xyz'
    context = material._service_context(2, 1, allow_homing=True)
    calls = []
    def run(command):
        calls.append(command)
        if command.startswith('G28'):
            state['toolhead']['homed_axes'] = 'xyz'
    objects['gcode'] = SimpleNamespace(run_script_from_command=run)
    material._prepare_service(2, dict(context, heat_target=250))
    heat = calls.index('SET_HEATER_TEMPERATURE HEATER=extruder2 TARGET=250.000')
    assert heat < calls.index('_UNLOCK_TOOL T=0 SERVICE=1')
    assert heat < calls.index('_LOCK_TOOL T=2 SERVICE=1')
    assert heat < next(i for i, command in enumerate(calls) if command.startswith('_WMP_XY_TRAVEL X=-13'))
    if needs_home:
        assert calls.index('G28 X Y\nM400') < heat
    assert 'heat_target' not in context


def test_filament_service_homing_failure_does_not_start_heating(service_material):
    from types import SimpleNamespace
    material, objects, state = service_material
    state['toolhead']['homed_axes'] = 'z'
    context = material._service_context(2, 1, allow_homing=True)
    calls = []
    def run(command):
        calls.append(command)
        if command.startswith('G28'):
            raise ValueError('homing failed')
    objects['gcode'] = SimpleNamespace(run_script_from_command=run)
    with pytest.raises(ValueError, match='homing failed'):
        material._prepare_service(2, dict(context, heat_target=250))
    assert not any('SET_HEATER_TEMPERATURE' in command for command in calls)


def test_filament_service_mount_failure_turns_early_heating_off(service_material):
    from types import SimpleNamespace
    material, objects, state = service_material
    material._material_status()._attachment = lambda now: {'state': 'empty', 'head': ''}
    plan = material._filament_plan(2, 'load', 1)
    material.filament_operation = dict(id='mount-failure',session=material.session_id,head='h2',action='load',state='running')
    heater = {'temperature': 25, 'target': 0, 'can_extrude': False}
    objects['extruder2'] = SimpleNamespace(get_status=lambda now: dict(heater))
    calls = []
    def run(command):
        calls.append(command)
        if command.startswith('SET_HEATER_TEMPERATURE'):
            heater['target'] = float(command.split('TARGET=')[1])
        if command.startswith('_LOCK_TOOL'):
            raise ValueError('mount failed')
    objects['gcode'] = SimpleNamespace(run_script_from_command=run)
    with pytest.raises(ValueError, match='mount failed'):
        material._filament_service()._execute_filament(FakeCommand(), 2, 'load', plan)
    assert 'SET_HEATER_TEMPERATURE HEATER=extruder2 TARGET=250.000' in calls
    assert calls[-1] == 'SET_HEATER_TEMPERATURE HEATER=extruder2 TARGET=0'
    assert heater['target'] == 0
    assert not any(command.startswith('G1 E') for command in calls)


def test_load_recipe_distances_are_bound_to_plan_and_wipe_is_required(service_material):
    material, objects, state = service_material
    first = material._filament_plan(2, 'load', 1)
    assert (first['feed_mm'], first['purge_mm']) == (55, 50)
    material.load_purge_mm = 75
    second = material._filament_plan(2, 'load', 1)
    assert second['purge_mm'] == 75 and second['token'] != first['token']
    objects.pop('gcode_macro WIPE_NOZZLE')
    with pytest.raises(ValueError, match='wipe macro is unavailable'):
        material._filament_plan(2, 'load', 1)


def test_restart_sensor_defaults_do_not_erase_persisted_loaded_flag(filament_check):
    material, sensor, _ = filament_check
    material._filament_sensors_unavailable()
    sensor.detected = False
    del material._loaded_flags
    assert material._loaded_filament_status(1)['h2']['state'] == 'unknown'
    assert material._filament_state()._load_filament_flags()['h2'] is True
    material._filament_sensors_ready()
    ready_at = material._filament_sensors_ready_at
    assert material._loaded_filament_status(ready_at - .1)['h2']['state'] == 'unknown'
    assert material._filament_state()._load_filament_flags()['h2'] is True
    sensor.detected = True
    assert material._loaded_filament_status(ready_at)['h2']['state'] == 'loaded'
    sensor.detected = False
    assert material._loaded_filament_status(ready_at + 1)['h2']['state'] == 'empty'
    material._loaded_filament_status(ready_at + 1.3)
    del material._loaded_flags
    assert material._filament_state()._load_filament_flags()['h2'] is False


def test_shutdown_sensor_defaults_do_not_erase_loaded_flag(filament_check):
    material, sensor, _ = filament_check
    material._filament_sensors_unavailable()
    sensor.detected = False
    assert material._loaded_filament_status(10000)['h2']['state'] == 'unknown'
    assert material._filament_state()._load_filament_flags()['h2'] is True

@pytest.fixture
def paused_origin_material(service_material):
    import io
    from types import SimpleNamespace
    material, objects, service_state = service_material
    service_state["toolhead"]["extruder"] = "extruder2"
    state = {'paused': True, 'job': 'paused', 'active': False, 'from_sd': False,
             'resume': {**{'resume_temperature%d' % i: 220 for i in range(4)},
                        'resume_bed': 60, 'zhop': 10, 'fan': 128, 'afan': 0, 'airfan': 0},
             'variables': {**service_state['save_variables']['variables'], **{'box_modify_t%d_backup' % i: i for i in range(4)}}}
    objects['pause_resume'] = SimpleNamespace(get_status=lambda now: {'is_paused': state['paused']})
    objects['print_stats'] = SimpleNamespace(get_status=lambda now: {'state': state['job']})
    objects['virtual_sdcard'] = SimpleNamespace(current_file=io.StringIO('G1 X20'), file_position=120,
        is_active=lambda: state['active'], is_cmd_from_sd=lambda: state['from_sd'])
    objects['gcode_move'] = SimpleNamespace(get_status=lambda now: {'homing_origin': [0.2, -0.1, 0.05, 0]}, saved_states={'PAUSE': {'last_position': [20, 30, 5, 42]},
                                                        'PAUSEPARK': {'last_position': [150, 20, 15, 42]}})
    objects['save_variables'] = SimpleNamespace(get_status=lambda now: {'variables': state['variables']})
    objects['gcode_macro RESUME'] = SimpleNamespace(get_status=lambda now: state['resume'])
    material.cmd_CAPTURE_PAUSE(FakeCommand())
    assert material._pause_origin is not None
    return material, objects, state


def test_pause_origin_binds_after_sd_worker_stops_without_altering_saved_state(paused_origin_material):
    material, objects, state = paused_origin_material
    state['from_sd'] = state['active'] = True
    with pytest.raises(ValueError, match='fully paused'):
        material._paused_filament_origin(2, 1)
    assert material._pause_origin['position'] is None
    objects['virtual_sdcard'].file_position = 125
    state['from_sd'] = state['active'] = False
    origin = material._paused_filament_origin(2, 1)
    assert origin['head'] == 'h2' and origin['file_position'] == 125
    assert origin == material._paused_filament_origin(2, 2)
    assert objects['gcode_move'].saved_states['PAUSE']['last_position'] == [20, 30, 5, 42]


@pytest.mark.parametrize('invalid', ['busy', 'openace', 'AFC', 'factor', 'missing'])
def test_prepare_resume_e_refuses_invalid_context_without_g92(paused_origin_material, invalid):
    from types import SimpleNamespace
    material, objects, state = paused_origin_material
    material._pause_origin['serviced'] = True
    calls = []
    objects['gcode'] = SimpleNamespace(run_script_from_command=calls.append)
    move = objects['gcode_move']
    saved = material._pause_origin['states']['PAUSE']
    saved.update(base_position=[0., 0., 0., 2.], extrude_factor=.8)
    move.last_position = list(saved['last_position'])
    move.extrude_factor = .8
    # Isolate post-return validation; busy exercises the real admission guard.
    if invalid == 'busy':
        state['active'] = True
    else:
        material._paused_service().cmd_CHECK_RESUME = lambda command: None
    if invalid in ('openace', 'AFC'):
        objects[invalid] = object()
    elif invalid == 'position':
        move.last_position[0] += 1
    elif invalid == 'factor':
        saved['extrude_factor'] = 0.
    elif invalid == 'missing':
        del saved['base_position']
    with pytest.raises(ValueError):
        material.cmd_PREPARE_RESUME_E(FakeCommand())
    assert calls == []


@pytest.mark.parametrize('change', ['session', 'owner', 'afc', 'unpaused', 'job', 'active', 'from_sd',
    'file', 'closed', 'position', 'return_position', 'park_position', 'mapping', 'temperature', 'head'])
def test_pause_origin_refuses_changed_job_or_resume_context(paused_origin_material, change):
    import io
    material, objects, state = paused_origin_material
    material._paused_filament_origin(2, 1)
    head = 2
    if change == 'session': material.session_id = 'new-session'
    elif change == 'owner': objects['openace'] = object()
    elif change == 'afc': objects['AFC'] = object()
    elif change == 'unpaused': state['paused'] = False
    elif change == 'job': state['job'] = 'printing'
    elif change in ('active', 'from_sd'): state[change] = True
    elif change == 'file': objects['virtual_sdcard'].current_file = io.StringIO('same filename, new job')
    elif change == 'closed': objects['virtual_sdcard'].current_file.close()
    elif change == 'position': objects['virtual_sdcard'].file_position += 1
    elif change == 'return_position': objects['gcode_move'].saved_states['PAUSE']['last_position'][0] += 1
    elif change == 'park_position': objects['gcode_move'].saved_states['PAUSEPARK']['last_position'][0] += 1
    elif change == 'mapping': state['variables']['box_modify_t2_backup'] = 1
    elif change == 'temperature': state['resume']['resume_temperature2'] = 240
    elif change == 'head': head = 1
    if change in ('mapping', 'temperature'):
        material._paused_filament_origin(head, 2)
    else:
        with pytest.raises(ValueError): material._paused_filament_origin(head, 2)


def test_failed_pause_capture_invalidates_previous_origin_without_moving(paused_origin_material):
    material, objects, state = paused_origin_material
    state['paused'] = False
    material.cmd_CAPTURE_PAUSE(FakeCommand())
    assert material._pause_origin is None
    with pytest.raises(ValueError, match='unavailable'): material._paused_filament_origin(2, 2)


def test_paused_load_plan_is_bound_to_original_job_and_offsets(paused_origin_material):
    material, objects, state = paused_origin_material
    plan = material._filament_plan(2, 'load', 1)
    assert plan['pause_origin'] == material._paused_filament_origin(2, 1)
    assert plan['service']['restore_offset'] == [0.2, -0.1, 0.05]
    assert material._filament_context_valid(plan, 2)
    state['resume']['fan'] = 0
    assert material._filament_context_valid(plan, 3)
    assert not material._filament_context_valid({'head': 'h2'}, 3)


@pytest.mark.parametrize('condition', ['other_head', 'detached', 'no_service'])
def test_paused_plan_refuses_head_change_or_missing_service(paused_origin_material, condition):
    material, objects, state = paused_origin_material
    head = 2
    if condition == 'other_head': head = 1
    elif condition == 'detached': material._material_status()._attachment = lambda now: {'state': 'empty', 'head': ''}
    else: objects['wmp_recovery'] = None
    with pytest.raises(ValueError): material._filament_plan(head, 'load', 1)


@pytest.mark.parametrize('condition', ['running', 'unknown', 'unloaded', 'wrong_head', 'wrong_motor', 'sensor_clear', 'job_changed', 'ready'])
def test_resume_requires_completed_service_and_original_loaded_head(paused_origin_material, condition):
    material, objects, state = paused_origin_material
    material._pause_origin.update(serviced=True, ready=True)
    material._filament_state()._loaded_filament_status = lambda now: {'h2': {'state': 'loaded'}}
    if condition in ('running', 'unknown'): material.filament_operation = {'state': condition}
    elif condition == 'unloaded': material._pause_origin['ready'] = False
    elif condition == 'wrong_head': material._material_status()._attachment = lambda now: {'state': 'attached', 'head': 'h1'}
    elif condition == 'wrong_motor': objects['toolhead'].get_status(1)['extruder'] = 'extruder'
    elif condition == 'sensor_clear': material._filament_state()._loaded_filament_status = lambda now: {'h2': {'state': 'empty'}}
    elif condition == 'job_changed': state['job'] = 'printing'
    if condition in ('ready', 'unknown'): material.cmd_CHECK_RESUME(FakeCommand())
    else:
        with pytest.raises(ValueError): material.cmd_CHECK_RESUME(FakeCommand())
    assert state['paused'] is True  # guard never resumes or moves by itself


def test_pause_capture_cannot_erase_unresolved_service(paused_origin_material):
    material, objects, state = paused_origin_material
    origin = material._pause_origin
    origin.update(serviced=True, ready=False)
    with pytest.raises(ValueError): material.cmd_CAPTURE_PAUSE(FakeCommand())
    assert material._pause_origin is origin


@pytest.mark.parametrize('failure', ['none', 'purge', 'job_drift'])
def test_paused_load_preserves_origin_and_only_allows_resume_after_full_completion(paused_origin_material, monkeypatch, failure):
    from types import SimpleNamespace
    from copy import deepcopy
    material, objects, state = paused_origin_material
    sensor = objects['filament_switch_sensor filament2'].get_status(1)
    sensor['filament_detected'] = False
    material._set_filament_loaded('h2', False)
    plan = material._filament_plan(2, 'load', 1)
    before = deepcopy(objects['gcode_move'].saved_states)
    material._pause_origin.update(serviced=True, ready=False)
    material.filament_operation = {'id': 'paused-service', 'session': material.session_id, 'action': plan['action'], 'state': 'running', 'head': 'h2', 'pause_origin': plan['pause_origin']}
    heater = {'temperature': 250, 'target': 0, 'can_extrude': True}
    objects['extruder2'] = SimpleNamespace(get_status=lambda now: dict(heater))
    calls, feeds = [], []
    def run(script):
        calls.append(script)
        if 'TARGET=' in script: heater['target'] = float(script.split('TARGET=')[1])
    objects['gcode'] = SimpleNamespace(run_script_from_command=run)
    sensor['filament_detected'] = True  # presented at the gears, not yet loaded
    def feed(printer, script):
        feeds.append(script)
        if len(feeds) == 2 and failure == 'purge': raise ValueError('purge failed')
        if len(feeds) == 1 and failure == 'job_drift': objects['virtual_sdcard'].file_position += 1
    monkeypatch.setattr('wm_material.run_standalone_extrusion_sequence', feed)
    if failure == 'none':
        material._filament_service()._execute_filament(FakeCommand(), 2, 'load', plan)
        material.cmd_CHECK_RESUME(FakeCommand())
        assert material._pause_origin['ready'] is True
        assert feeds == ['G1 E55 F400', 'G1 E50 F400']
        assert calls.count('WIPE_NOZZLE XY_ONLY=1\nM400') == 1
    else:
        with pytest.raises(ValueError): material._filament_service()._execute_filament(FakeCommand(), 2, 'load', plan)
        with pytest.raises(ValueError): material.cmd_CHECK_RESUME(FakeCommand())
        assert not material._pause_origin['ready']
        assert 'WIPE_NOZZLE XY_ONLY=1\nM400' not in calls
    assert objects['gcode_move'].saved_states == before
    assert state['paused'] is True and state['job'] == 'paused'
    assert heater['target'] == 0
    assert not any(command in '\n'.join(calls) for command in ('G28', 'RESTORE_GCODE_STATE', 'M24', 'RESUME', 'LOCK'))
    assert 'SET_GCODE_OFFSET X=0.20000 Y=-0.10000 Z=0.05000 MOVE=0' in calls


@pytest.mark.parametrize('condition', ['valid', 'missing_token', 'wrong_token', 'wrong_head',
    'loaded', 'unknown', 'detached', 'job_changed', 'cancelled', 'running'])
def test_paused_identity_edit_is_scoped_and_never_moves(paused_origin_material, condition):
    material, objects, state = paused_origin_material
    material._filament_state()._loaded_filament_status = lambda now: {'h2': {'state': 'empty'}}
    updated = dict(material._profiles()[0]['h2'], nozzle_temp=240)
    command = profile_command(material, PAUSE=material._pause_origin['id'], PROFILE=json.dumps(updated).encode().hex())
    if condition == 'missing_token': command.args.pop('PAUSE')
    elif condition == 'wrong_token': command.args['PAUSE'] = '0' * 32
    elif condition == 'wrong_head': command.args['HEAD'] = '1'
    elif condition in ('loaded', 'unknown'):
        material._filament_state()._loaded_filament_status = lambda now: {'h2': {'state': condition}}
    elif condition == 'detached': material._material_status()._attachment = lambda now: {'state': 'none'}
    elif condition == 'job_changed': state['job'] = 'printing'
    elif condition == 'cancelled': state.update(job='cancelled', paused=False)
    elif condition == 'running': material.filament_operation = {'state': 'running'}
    before = material._profiles()
    if condition == 'valid':
        material.cmd_SET_FILAMENT(command)
        assert material._profiles()[0]['h2']['material'] == 'PETG'
    else:
        with pytest.raises(ValueError): material.cmd_SET_FILAMENT(command)
        assert material._profiles() == before
    assert state['paused'] == (condition != 'cancelled')


@pytest.mark.parametrize('condition', ['idle', 'worker_active', 'sd_command', 'tool_running', 'tool_unknown'])
def test_resume_refuses_unpaused_or_busy_context_even_without_service(paused_origin_material, condition):
    material, objects, state = paused_origin_material
    assert not material._pause_origin.get('serviced')
    if condition == 'idle': state.update(paused=False, job='standby')
    elif condition == 'worker_active': state['active'] = True
    elif condition == 'sd_command': state['from_sd'] = True
    else: material.toolhead_operation = {'state': condition.removeprefix('tool_')}
    if condition == 'tool_unknown': material.cmd_CHECK_RESUME(FakeCommand())
    else:
        with pytest.raises(ValueError): material.cmd_CHECK_RESUME(FakeCommand())


@pytest.mark.parametrize('condition', ['loaded', 'empty', 'unknown', 'missing_origin'])
def test_resume_checks_runout_before_any_replacement_operation(paused_origin_material, condition):
    material, objects, state = paused_origin_material
    material._filament_state()._loaded_filament_status = lambda now: {'h2': {'state': condition}}
    if condition == 'missing_origin': material._pause_origin = None
    material.cmd_CHECK_RESUME(FakeCommand())  # No loss or WM+ service in this job.
    assert state['paused'] is True


@pytest.mark.parametrize('paused', [False, True])
@pytest.mark.parametrize('axes', ['', 'xy', 'z', 'xyz'])
@pytest.mark.parametrize('reference', [False, True])
def test_filament_position_guidance_never_requires_z(service_material, paused, axes, reference):
    from types import SimpleNamespace
    material, objects, state = service_material
    objects['pause_resume'] = SimpleNamespace(get_status=lambda now: {'is_paused': paused})
    state['toolhead']['homed_axes'] = axes
    state['wmp_recovery']['z_reference_valid'] = reference
    position = material._filament_position_status(1)
    assert position == {'ready': True, 'home_xy': 'xy' not in axes}
    assert material._service_context(2, 1, allow_homing=True)['needs_home'] == ('xy' not in axes)
    assert material.filament_operation == {}


@pytest.mark.parametrize('state', ['pending', 'running', 'complete', 'failed'])
def test_only_running_identification_blocks_filament_and_print(material, state):
    from types import SimpleNamespace
    original = material.printer.lookup_object
    recovery = SimpleNamespace(get_status=lambda now: {'identification': {'state': state}})
    material.printer.lookup_object = lambda name, default=None: recovery if name == 'wmp_recovery' else original(name, default)
    if state in ('pending', 'running'):
        assert not material._idle_for_filament_settings(1)
        with pytest.raises(ValueError, match='head identification'):
            material._service_context(2, 1)
        with pytest.raises(ValueError, match='head identification'):
            material._print_admission(FakeCommand())
    else:
        assert material._idle_for_filament_settings(1)
        material.cmd_SET_FILAMENT(profile_command(material))
        material._print_admission(FakeCommand())
    recovery.get_status = lambda now: {'identification': {'state': 'idle'}}
    assert material._idle_for_filament_settings(1)


def test_paused_editor_cannot_bypass_identification_lock(material):
    from types import SimpleNamespace
    original = material.printer.lookup_object
    recovery = SimpleNamespace(get_status=lambda now: {'identification': {'state': 'running'}})
    material.printer.lookup_object = lambda name, default=None: recovery if name == 'wmp_recovery' else original(name, default)
    material.printer.paused = True
    def unexpected_origin(*args):
        raise AssertionError('Paused editor must not be consulted during identification lock')
    material._paused_service()._paused_filament_origin = unexpected_origin
    with pytest.raises(ValueError, match='Resolve head identification'):
        material.cmd_SET_FILAMENT(FakeCommand(HEAD=2, PAUSE='previous-paused-job'))



def test_hotend_history_survives_unload_sensor_clear_and_profile_edit(filament_check):
    material, sensor, _ = filament_check
    identity = {'brand': 'Generic', 'material': 'PETG', 'color': '#112233',
                'nozzle_temp_min': 230, 'nozzle_temp_max': 250}
    material._record_hotend_material('h2', identity, purged=True)
    identity['material'] = 'PLA'  # Caller mutation must not rewrite history.
    material._set_filament_loaded('h2', False)
    sensor.detected = False
    material._loaded_filament_status(1)
    material.cmd_SET_FILAMENT(profile_command(material))
    restarted = WMMaterial.__new__(WMMaterial)
    restarted.profile_path = material.profile_path
    record = restarted._hotend_material_history()['h2']
    assert record == {'state': 'purged', 'materials': [dict(identity, material='PETG')],
                      'unknown_residue': False}


def test_interrupted_feed_preserves_both_residual_materials(sequence_material, monkeypatch):
    material, _ = sequence_material
    incoming = dict(material._profiles()[0]['h2'], nozzle_temp_min=230, nozzle_temp_max=270)
    material.cmd_SET_FILAMENT(profile_command(material, PROFILE=json.dumps(incoming).encode().hex()))
    previous = {'brand': 'Generic', 'material': 'ABS', 'color': '#ffffff', 'nozzle_temp_min': 240, 'nozzle_temp_max': 260}
    material._record_hotend_material('h2', previous, purged=True)
    incoming = material._profiles()[0]['h2']
    def interrupted(*args):
        record = material._hotend_material_history()['h2']
        assert record['state'] == 'mixed'
        assert record['materials'] == [previous, incoming]
        raise RuntimeError('feed interrupted')
    monkeypatch.setattr('wm_material.run_standalone_extrusion_sequence', interrupted)
    with pytest.raises(RuntimeError, match='feed interrupted'):
        material.cmd_FILAMENT_SEQUENCE(sequence_command(material))
    assert material._hotend_material_history()['h2']['state'] == 'mixed'


def test_completed_purge_replaces_history_and_preserves_other_heads(sequence_material, monkeypatch):
    material, _ = sequence_material
    old = {'brand': 'Generic', 'material': 'ABS', 'color': '#ffffff'}
    material._record_hotend_material('h3', old, purged=True)
    monkeypatch.setattr('wm_material.run_standalone_extrusion_sequence', lambda *args: None)
    material.cmd_FILAMENT_SEQUENCE(sequence_command(material))
    history = material._hotend_material_history()
    assert history['h3']['materials'] == [old]
    assert history['h2'] == {'state': 'purged', 'materials': [material._profiles()[0]['h2']],
                             'unknown_residue': False}


def test_unknown_history_is_not_inferred_from_current_profile(service_material):
    material, _, _ = service_material
    assert material._hotend_material_history() == {}
    assert material._filament_plan(2, 'load', 1)['previous_material'] is None
    identity = material._profiles()[0]['h2']
    material._record_hotend_material('h2', identity, purged=False)
    assert material._hotend_material_history()['h2']['unknown_residue'] is True


def test_history_change_invalidates_reviewed_load(sequence_material, monkeypatch):
    material, _ = sequence_material
    cmd = sequence_command(material)
    material._record_hotend_material('h2', {'brand': 'Generic', 'material': 'ABS', 'color': '#ffffff'}, purged=True)
    monkeypatch.setattr('wm_material.run_standalone_extrusion_sequence', lambda *args: pytest.fail('stale review moved'))
    with pytest.raises(ValueError): material.cmd_FILAMENT_SEQUENCE(cmd)


def test_corrupt_history_allows_unknown_plan_and_preserves_original(service_material):
    from pathlib import Path
    material, _, _ = service_material
    path = Path(material.profile_path).with_name('wmp_hotend_materials.json')
    path.write_bytes(b'{broken\xff')
    plan = material._filament_plan(2, 'load', 1)
    assert plan['previous_material'] is None
    assert 'unknown' in plan['transition_note']
    assert plan['history_error']
    assert list(path.parent.glob(path.name + '.invalid-*')) == []
    material._record_hotend_material('h2', material._profiles()[0]['h2'], purged=False)
    assert next(path.parent.glob(path.name + '.invalid-*')).read_bytes() == b'{broken\xff'
    assert material._hotend_material_history()['h2']['unknown_residue'] is True
    material._record_hotend_material('h2', material._profiles()[0]['h2'], purged=True)
    assert material._hotend_material_history()['h2']['state'] == 'purged'


def test_corrupt_history_preservation_failure_retains_bytes_without_blocking(service_material, monkeypatch):
    from pathlib import Path
    material, _, _ = service_material
    path = Path(material.profile_path).with_name('wmp_hotend_materials.json')
    path.write_text('{broken')
    def fail(*args):
        raise OSError('read-only storage')
    monkeypatch.setattr('wm_material.os.link', fail)
    material._record_hotend_material('h2', material._profiles()[0]['h2'], purged=True)
    assert path.read_text() == '{broken'
    assert material._hotend_material_history() == {}


def test_history_write_failure_prevents_feed_and_preserves_old_record(sequence_material, monkeypatch):
    from pathlib import Path
    material, _ = sequence_material
    incoming = dict(material._profiles()[0]['h2'], nozzle_temp_min=230, nozzle_temp_max=270)
    material.cmd_SET_FILAMENT(profile_command(material, PROFILE=json.dumps(incoming).encode().hex()))
    old = {'brand': 'Generic', 'material': 'ABS', 'color': '#ffffff', 'nozzle_temp_min': 240, 'nozzle_temp_max': 260}
    material._record_hotend_material('h2', old, purged=True)
    path = Path(material.profile_path).with_name('wmp_hotend_materials.json')
    original = path.read_bytes()
    cmd = sequence_command(material)
    real_replace = __import__('os').replace
    def fail_history(source, target):
        if str(target) == str(path): raise OSError('disk unavailable')
        return real_replace(source, target)
    monkeypatch.setattr('wm_material.os.replace', fail_history)
    monkeypatch.setattr('wm_material.run_standalone_extrusion_sequence', lambda *args: pytest.fail('feed before history persisted'))
    with pytest.raises(OSError, match='disk unavailable'): material.cmd_FILAMENT_SEQUENCE(cmd)
    assert path.read_bytes() == original
    assert not list(path.parent.glob('.wmp-hotend-*'))


@pytest.mark.parametrize('old,new,expected', [
    ((240, 270, 260), (190, 245, 220), 245),
    ((190, 245, 220), (240, 270, 260), 240),
    ((200, 240, 220), (200, 240, 220), 220),
])
def test_transition_temperature_uses_directional_shared_limit(old, new, expected):
    from wm_material import transition_temperature
    def identity(values):
        return dict(brand='Generic', material='Custom polymer', color='#ffffff',
                    nozzle_temp_min=values[0], nozzle_temp_max=values[1], nozzle_temp=values[2])
    previous = dict(state='purged', materials=[identity(old)], unknown_residue=False)
    assert transition_temperature(identity(new), previous, new[2])[0] == expected


def test_transition_rejects_disjoint_and_missing_ranges():
    from wm_material import transition_temperature
    old = dict(brand='Generic', material='PA', color='#ffffff', nozzle_temp_min=250, nozzle_temp_max=270)
    new = dict(brand='Generic', material='PLA', color='#ffffff', nozzle_temp_min=190, nozzle_temp_max=230)
    previous = dict(state='purged', materials=[old], unknown_residue=False)
    with pytest.raises(ValueError, match='No shared'): transition_temperature(new, previous, 220)
    del old['nozzle_temp_min']
    old['material'] = 'Custom polymer'
    with pytest.raises(ValueError, match='valid nozzle temperature range'): transition_temperature(new, previous, 220)


def test_transition_checks_all_mixed_residue_and_reports_unknown():
    from wm_material import transition_temperature
    new = dict(brand='Generic', material='PETG', color='#ffffff', nozzle_temp_min=220, nozzle_temp_max=260)
    low = dict(new, material='PLA', nozzle_temp_min=190, nozzle_temp_max=235)
    high = dict(new, material='PC', nozzle_temp_min=240, nozzle_temp_max=270)
    previous = dict(state='mixed', materials=[low, high], unknown_residue=False)
    with pytest.raises(ValueError, match='No shared'): transition_temperature(new, previous, 250)
    previous['unknown_residue'] = True
    with pytest.raises(ValueError, match='No shared'): transition_temperature(new, previous, 250)
    target, note = transition_temperature(new, None, 250)
    assert target == 250 and 'unknown' in note


def test_load_plan_binds_transition_target_and_explanation(service_material):
    material, _, _ = service_material
    old = dict(brand='Generic', material='PETG', color='#ffffff', nozzle_temp_min=240, nozzle_temp_max=270, nozzle_temp=260)
    new = dict(brand='Generic', material='PLA', color='#000000', nozzle_temp_min=190, nozzle_temp_max=225, nozzle_temp=220)
    material._record_hotend_material('h2', old, purged=True)
    material.cmd_SET_FILAMENT(profile_command(material, PROFILE=json.dumps(new).encode().hex()))
    plan = material._filament_plan(2, 'load', 1)
    assert plan['target'] == 240
    assert 'Material transition: 240 C' in plan['description']
    assert plan['previous_material']['materials'] == [old]
    # Bounds and history are part of the reviewed token, not an unreviewed override.
    material._record_hotend_material('h2', dict(old, nozzle_temp_min=240, nozzle_temp_max=242), purged=True)
    changed = material._filament_plan(2, 'load', 1)
    assert changed['target'] == 240 and changed['token'] != plan['token']


@pytest.mark.parametrize('incoming,previous,target,expected', [
    ('PLA', 'ABS', 220, 240), ('ABS', 'PLA', 250, 240),
    ('PLA Matte', 'PETG', 220, 240), ('PETG', 'PLA Matte', 250, 220),
    ('PCTG', 'ABS', 260, 240),
])
def test_builtin_transition_ranges(incoming, previous, target, expected):
    from wm_material import transition_temperature
    identity = dict(brand='Generic', material=incoming, color='#ffffff')
    old = dict(identity, material=previous)
    chosen, note = transition_temperature(identity, dict(state='purged', materials=[old], unknown_residue=False), target)
    assert chosen == expected and 'generic' in note


def test_generic_swap_ranges_override_spool_printing_bounds():
    from wm_material import material_temperature_range, transition_temperature
    pla = dict(brand='Specific', material='PLA', color='#ffffff', nozzle_temp_min=195, nozzle_temp_max=225)
    assert material_temperature_range(pla) == (190,240,'generic')
    assert material_temperature_range(dict(pla, nozzle_temp_min=0)) == (190,240,'generic')
    abs_ = dict(brand='Generic', material='ABS', color='#ffffff')
    assert transition_temperature(pla, dict(state='purged', materials=[abs_], unknown_residue=False),220)[0] == 240


def test_every_builtin_has_explicit_range_or_honest_service_point():
    from wm_material import MATERIALS, material_temperature_range
    for name, target in MATERIALS:
        low, high, source = material_temperature_range(dict(brand='Generic',material=name,color='#ffffff'))
        assert low <= target <= high
        if name in ('PET','TPE','Marble','Wood'):
            assert source == 'recipe-only' and low == high == target
        else:
            assert source == 'generic' and low < high


def test_process_loss_during_withdrawal_retains_uncertainty(sequence_material, monkeypatch):
    obj, objects = sequence_material
    from types import SimpleNamespace
    objects['extruder2'] = SimpleNamespace(get_status=lambda now: {'temperature': 250., 'target': 250., 'can_extrude': True})
    obj._set_filament_loaded('h2', True)
    obj._filament_state()._sensor_filament_status = lambda now: {'h2': {'state': 'loaded', 'identity': obj._profiles()[0]['h2']}}
    def process_loss(printer, script):
        assert script.startswith('_TIP_SHAPE_MOVES')
        raise SystemExit('simulated process loss after withdrawal dispatch')
    monkeypatch.setattr('wm_material.run_standalone_extrusion_sequence', process_loss)
    with pytest.raises(SystemExit):
        obj.cmd_FILAMENT_SEQUENCE(sequence_command(obj, 'unload'))
    # A new process loses volatile operation/flag caches; retain the actual
    # on-disk files and the still-present inlet signal from the fixture.
    restarted = WMMaterial.__new__(WMMaterial)
    restarted.__dict__.update(obj.__dict__)
    # The fixture copies machine dependencies, not live feature ownership from
    # the old process. Rebind copied feature instances to this backend.
    for name, feature in list(vars(restarted).items()):
        if getattr(feature, 'material', None) is obj:
            import copy
            replacement = copy.copy(feature)
            replacement.material = restarted
            setattr(restarted, name, replacement)
    restarted.session_id = 'new-process'
    restarted.filament_operation = {}
    restarted._filament_requests = set()
    del restarted._loaded_flags
    restarted._restore_filament_operation()
    state = restarted._loaded_filament_status(1)['h2']['state']
    assert state != 'loaded' or restarted.filament_operation.get('state') == 'unknown', (
        'Process loss discarded the interruption while retaining loaded=true')
    assert restarted.filament_operation['state'] == 'unknown'
    assert state == 'empty'  # Withdrawal revoked the old loaded confirmation.
    assert restarted.filament_operation['phase'] == 'feeding'
    assert restarted.filament_operation['session'] == 'new-process'
    assert restarted.filament_operation['previous_session'] == 'test-session'
    with pytest.raises(ValueError, match='does not report filament'):
        restarted.cmd_FILAMENT_SEQUENCE(FakeCommand(HEAD=2, ACTION='unload', ID='new-attempt', TOKEN='old-plan'))


def test_completed_filament_result_survives_restart_without_dispatch(sequence_material, monkeypatch):
    obj, _ = sequence_material
    calls = []
    monkeypatch.setattr('wm_material.run_standalone_extrusion_sequence', lambda printer, script: calls.append(script))
    obj.cmd_FILAMENT_SEQUENCE(sequence_command(obj))
    assert len(calls) == 2
    obj.filament_operation = {}
    obj.session_id = 'new-session'
    obj._restore_filament_operation()
    assert obj.filament_operation['state'] == 'complete'
    assert obj.filament_operation['session'] == 'new-session'
    assert len(calls) == 2


def test_filament_journal_write_failure_is_not_a_dispatch_prerequisite(sequence_material, monkeypatch):
    obj, _ = sequence_material
    calls = []
    def failed(): raise OSError('disk unavailable')
    monkeypatch.setattr(obj._filament_service(), '_persist_filament_operation', failed)
    monkeypatch.setattr(obj._filament_service(), '_execute_filament', lambda *args: calls.append(args))
    command = sequence_command(obj)
    obj.cmd_FILAMENT_SEQUENCE(command)
    assert len(calls) == 1
    assert obj.filament_operation['persistence_error'] == 'disk unavailable'
    with pytest.raises(ValueError): obj.cmd_FILAMENT_SEQUENCE(command)
    assert len(calls) == 1


@pytest.mark.parametrize('payload', ['broken', '{}', '[]', '{"version":1,"operation":{}}'])
def test_corrupt_filament_journal_is_not_silently_discarded(material, payload):
    from pathlib import Path
    Path(material._filament_service()._filament_operation_path()).write_text(payload)
    material._restore_filament_operation()
    assert material.filament_operation['state'] == 'unknown'
    assert Path(material._filament_service()._filament_operation_path()).read_text() == payload
    material.cmd_SET_FILAMENT(profile_command(material))


def test_filament_journal_checkpoint_does_not_rewrite_unchanged_state(sequence_material, monkeypatch):
    import os
    obj, _ = sequence_material
    obj.filament_operation = dict(id='waiting', session=obj.session_id, head='h2', action='load', state='running')
    calls = []
    original = os.replace
    def replace(source, destination):
        calls.append(destination)
        return original(source, destination)
    monkeypatch.setattr('wm_material.os.replace', replace)
    for _ in range(20):
        obj._filament_checkpoint('inserting')
    assert calls == [obj._filament_service()._filament_operation_path()]


def test_restart_cannot_reuse_old_pause_context(sequence_material):
    obj, _ = sequence_material
    obj.filament_operation = dict(id='paused-load', session=obj.session_id, head='h2',
        action='load', state='running', pause_origin={'file': 'old.gcode'})
    obj._filament_service()._persist_filament_operation()
    obj.session_id = 'restarted'
    obj.filament_operation = {}
    obj._restore_filament_operation()
    assert obj.filament_operation['state'] == 'unknown'
    assert 'pause_origin' not in obj.filament_operation
    assert obj.filament_operation['interrupted_pause_origin'] == {'file': 'old.gcode'}


@pytest.mark.parametrize('interrupt_at', [1, 2])
def test_partial_load_never_persists_ready_before_purge_completes(sequence_material, monkeypatch, interrupt_at):
    material, _ = sequence_material
    calls = []
    def interrupted(printer, script):
        calls.append(script)
        assert material._filament_state()._load_filament_flags().get('h2', False) is False
        if len(calls) == interrupt_at:
            raise SystemExit('process lost')
    monkeypatch.setattr('wm_material.run_standalone_extrusion_sequence', interrupted)
    with pytest.raises(SystemExit):
        material.cmd_FILAMENT_SEQUENCE(sequence_command(material))
    del material._loaded_flags
    assert material._filament_state()._load_filament_flags().get('h2', False) is False
    material.filament_operation = {}
    material.session_id = 'restart'
    material._restore_filament_operation()
    assert material.filament_operation['state'] == 'unknown'
    assert material.filament_operation['phase'] == ('feeding' if interrupt_at == 1 else 'purging')


@pytest.mark.parametrize('writer', ['loaded', 'history'])
def test_filament_state_rename_is_durable_before_dispatch(sequence_material, monkeypatch, writer):
    import os
    import stat
    material, _ = sequence_material
    events = []
    real_replace, real_fsync = os.replace, os.fsync
    def replace(source, target):
        real_replace(source, target)
        events.append(('rename', str(target)))
    def fsync(fd):
        directory = stat.S_ISDIR(os.fstat(fd).st_mode)
        real_fsync(fd)
        events.append(('directory' if directory else 'file', fd))
    monkeypatch.setattr('wm_material.os.replace', replace)
    monkeypatch.setattr('wm_material.os.fsync', fsync)
    if writer == 'loaded':
        material._set_filament_loaded('h2', True)
    else:
        material._record_hotend_material('h2', material._profiles()[0]['h2'], purged=False)
    assert [kind for kind, _ in events] == ['file', 'rename', 'directory']


@pytest.mark.parametrize('action', ['load', 'unload'])
def test_state_directory_flush_failure_preserves_load_write_boundary(sequence_material, monkeypatch, action):
    import os
    import stat
    from types import SimpleNamespace
    material, objects = sequence_material
    if action == 'unload':
        material._set_filament_loaded('h2', True)
        material._filament_state()._sensor_filament_status = lambda now: {'h2': {'state': 'loaded', 'identity': material._profiles()[0]['h2']}}
        objects['extruder2'] = SimpleNamespace(get_status=lambda now: {'temperature':250., 'target':250., 'can_extrude':True})
    command = sequence_command(material, action)
    real_fsync = os.fsync
    def failed_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError('state directory flush failed')
        real_fsync(fd)
    # Isolate the state-file durability boundary; the journal has its own
    # write-failure tests and must not mask reaching this failure point.
    monkeypatch.setattr(material._filament_service(), '_persist_filament_operation', lambda: None)
    monkeypatch.setattr('wm_material.os.fsync', failed_directory)
    feeds = []
    monkeypatch.setattr('wm_material.run_standalone_extrusion_sequence', lambda *args: feeds.append(args))
    if action == 'load':
        # Hotend material history is a physical recipe prerequisite, unlike
        # optional presence metadata. Its failed write still stops extrusion.
        with pytest.raises(OSError, match='state directory flush failed'):
            material.cmd_FILAMENT_SEQUENCE(command)
        assert feeds == []
    else:
        material.cmd_FILAMENT_SEQUENCE(command)
        assert len(feeds) == 1
        assert material._filament_state()._load_filament_flags()['h2'] is False
        assert 'state directory flush failed' in material._filament_presence_error


def test_screen_configuration_excludes_bulk_data_and_tracks_changes(material):
    from types import SimpleNamespace
    settings = {
        'extruder': {'min_temp': 0, 'max_temp': 300, 'nozzle_diameter': .4,
                     'pid_kp': 99, 'sensor_pin': 'private'},
        'extruder1': {'min_temp': 5, 'max_temp': 310, 'nozzle_diameter': .6},
        'gcode_macro HUGE': {'gcode': 'X' * 200000},
    }
    saved = {'box_modify_t0': 3, 'box_modify_t1': 1, 'unrelated': 'X' * 200000}
    objects = {'configfile': SimpleNamespace(get_status=lambda now: {'settings': settings}),
               'save_variables': SimpleNamespace(get_status=lambda now: {'variables': saved})}
    material.printer.lookup_object = lambda name, default=None: objects.get(name, default)
    value = material._screen_configuration_status(1)
    assert value['screen_status_protocol'] == 1
    assert value['physical_mapping'] == [3, 1, None, None]
    assert value['heater_settings']['extruder'] == dict(min_temp=0, max_temp=300, nozzle_diameter=.4)
    assert len(json.dumps(value)) < 500
    saved['box_modify_t0'] = 2
    settings['extruder']['max_temp'] = 280
    updated = material._screen_configuration_status(2)
    assert updated['physical_mapping'][0] == 2
    assert updated['heater_settings']['extruder']['max_temp'] == 280
    assert value['physical_mapping'][0] == 3
    assert value['heater_settings']['extruder']['max_temp'] == 300


def test_screen_configuration_never_invents_missing_or_invalid_settings(material):
    from types import SimpleNamespace
    objects = {'configfile': SimpleNamespace(get_status=lambda now: {'settings': {
        'extruder': {'min_temp': False, 'max_temp': float('nan'), 'nozzle_diameter': '0.4'}}}),
        'save_variables': SimpleNamespace(get_status=lambda now: {'variables': {
            'box_modify_t0': True, 'box_modify_t1': -1, 'box_modify_t2': 4, 'box_modify_t3': '3'}})}
    material.printer.lookup_object = lambda name, default=None: objects.get(name, default)
    value = material._screen_configuration_status(1)
    assert value['heater_settings']['extruder'] == {}
    assert value['physical_mapping'] == [None] * 4
    objects.clear()
    assert material._screen_configuration_status(2) == {
        'screen_status_protocol': 1, 'heater_settings': {}, 'physical_mapping': [None] * 4}


@pytest.mark.parametrize('axes', ['', 'xy', 'xyz'])
@pytest.mark.parametrize('z', [0, 20, 349])
def test_service_preparation_preserves_bed_height_without_z_reference(service_material, axes, z):
    from types import SimpleNamespace
    material, objects, state = service_material
    state['toolhead']['homed_axes'] = axes
    state['toolhead']['position'][2] = z
    state['wmp_recovery']['z_reference_valid'] = False
    calls = []
    def run(script):
        calls.extend(script.splitlines())
        if script == 'G28 X Y\nM400':
            state['toolhead']['homed_axes'] = 'xy'
    objects['gcode'] = SimpleNamespace(run_script_from_command=run)
    material._prepare_service(2, material._service_context(2, 1, allow_homing=True))
    assert calls.count('G28 X Y') == (not axes)
    assert state['toolhead']['position'][2] == z
    assert not state['wmp_recovery']['z_reference_valid']
    assert any(line.startswith('_WMP_XY_TRAVEL X=-13') for line in calls)
    assert any(line.startswith('_WMP_XY_TRAVEL Y=80') for line in calls)
    for line in calls:
        assert not line.startswith(('SET_KINEMATIC_POSITION', 'FORCE_MOVE', 'PROBE'))
        if line.startswith(('G0 ', 'G1 ', 'G28 ')):
            assert not any(word.startswith('Z') for word in line.split()[1:])


def test_save_cooperation_during_owned_procedures_and_calibration():
    from types import SimpleNamespace
    material = WMMaterial.__new__(WMMaterial)
    pauses = []
    reactor = SimpleNamespace(monotonic=lambda: 12.5, pause=pauses.append)
    objects = {}
    material.printer = SimpleNamespace(get_reactor=lambda: reactor,
        lookup_object=lambda name, default=None: objects.get(name, default))
    for state in ('idle', 'complete', 'failed', 'unknown'):
        material.toolhead_operation = {'state': state}
        material.filament_operation = {'state': state}
        material._material_status()._yield_saved_variables()
    assert not pauses
    material.toolhead_operation = {'state': 'running'}
    material._material_status()._yield_saved_variables();assert pauses == [12.5]
    material.toolhead_operation = {'state': 'complete'}
    material.filament_operation = {'state': 'running'}
    material._material_status()._yield_saved_variables();assert pauses == [12.5, 12.5]
    material.filament_operation = {'state': 'complete'}
    calibration = SimpleNamespace(active=False)
    objects['wmp_recovery'] = SimpleNamespace(calibration=calibration)
    material._material_status()._yield_saved_variables();assert len(pauses) == 2
    calibration.active = True
    material._material_status()._yield_saved_variables();assert len(pauses) == 3
    calibration.active = False
    material._material_status()._yield_saved_variables();assert len(pauses) == 3


def test_sunlu_simulated_pla_petg_round_trip_plans(service_material):
    """Exercise requested metadata simulation without heating real PLA as PETG."""
    material, objects, state = service_material
    sensor = state['filament_switch_sensor filament2']
    pla = dict(brand='Sunlu', material='PLA Matte', color='#f5b6cd')
    petg = dict(pla, material='PETG')
    other = dict(brand='Kexcelled', material='PLA Matte', color='#7D8A92')
    material._record_hotend_material('h3', other, purged=True)
    material._record_hotend_material('h2', pla, purged=True)
    for incoming, load_target, unload_target, shaping in (
            (petg, 220, 250, 'petg'), (pla, 240, 220, 'pla')):
        material.cmd_SET_FILAMENT(profile_command(
            material, PROFILE=json.dumps(incoming).encode().hex()))
        load = material._filament_plan(2, 'load', 1)
        assert load['target'] == load_target
        assert load['identity'] == incoming
        assert load['feed_mm'] == 55 and load['purge_mm'] == 50
        assert 'wipe' in load['description']
        # Simulated successful feed/purge and sensor input, not physical evidence.
        material._record_hotend_material('h2', incoming, purged=True)
        sensor['filament_detected'] = True
        material._set_filament_loaded('h2', True)
        unload = material._filament_plan(2, 'unload', 1)
        assert unload['target'] == unload_target
        assert unload['class'] == shaping
        assert unload['identity'] == incoming
        material._set_filament_loaded('h2', False)
        sensor['filament_detected'] = False
        assert material._hotend_material_history()['h2']['materials'] == [incoming]
        assert material._hotend_material_history()['h3']['materials'] == [other]
    assert material.filament_operation == {}  # Only plans were produced.


@pytest.mark.parametrize('old,new,cross', [
    ('PLA', 'PLA Matte', False), ('PLA Silk', 'PLA', False),
    ('PETG', 'PETG Matte', False), ('PLA Matte', 'PETG', True),
    ('PETG', 'PLA Matte', True), ('PETG', 'PCTG', True),
    ('ABS', 'ASA', True), ('PA6', 'PA12', True),
])
def test_material_family_purge_classification(old, new, cross):
    from wm_material import cross_family_purge
    history = dict(materials=[dict(material=old)], unknown_residue=False)
    assert cross_family_purge(dict(material=new), history) is cross


@pytest.mark.parametrize('previous,cross', [
    (None, True), (dict(materials=[], unknown_residue=False), True),
    (dict(materials=[dict(material='PLA')], unknown_residue=True), True),
    (dict(materials=[dict(material='PLA'), dict(material='PETG')]), True),
    (dict(materials=[dict(material='PLA'), dict(material='PLA Matte')]), False),
])
def test_purge_family_unknown_and_mixed_residue(previous, cross):
    from wm_material import cross_family_purge
    assert cross_family_purge(dict(material='PLA'), previous) is cross


def test_cross_material_purge_setting_selects_and_binds_review(service_material):
    material, _, _ = service_material
    material.load_purge_mm = 40
    material.cross_material_purge_mm = 95
    incoming = dict(brand='Sunlu', material='PLA Matte', color='#f5b6cd')
    material.cmd_SET_FILAMENT(profile_command(material, PROFILE=json.dumps(incoming).encode().hex()))
    material._record_hotend_material('h2', dict(incoming, material='PLA'), purged=True)
    same = material._filament_plan(2, 'load', 1)
    assert same['purge_mm'] == 40 and same['purge_source'] == 'same_family'
    material._record_hotend_material('h2', dict(incoming, material='PETG'), purged=True)
    cross = material._filament_plan(2, 'load', 1)
    assert cross['purge_mm'] == 95 and cross['purge_source'] == 'cross_material'
    assert cross['feed_mm'] == same['feed_mm'] == 55
    assert 'purge 95 mm' in cross['description']
    material.cross_material_purge_mm = 110
    changed = material._filament_plan(2, 'load', 1)
    assert changed['purge_mm'] == 110 and changed['token'] != cross['token']

@pytest.mark.parametrize('timing', ['before_pause', 'after_pause'])
def test_other_head_runout_blocks_resume_after_reinsertion(paused_origin_material, timing):
    from copy import deepcopy
    material, objects, state = paused_origin_material
    records = {'h2': {'state': 'loaded'}, 'h3': {'state': 'loaded'}}
    material._filament_state()._sensor_filament_status = lambda now: deepcopy(records)
    material._set_filament_loaded('h2', True)
    material._set_filament_loaded('h3', True)
    if timing == 'before_pause':
        material._pause_origin = None
        state.update(job='printing', paused=False)
    records['h3']['state'] = 'empty'
    material._loaded_filament_status(2)
    material._loaded_filament_status(2.3)
    if timing == 'before_pause':
        state.update(job='paused', paused=True)
        material.cmd_CAPTURE_PAUSE(FakeCommand())
    records['h3']['state'] = 'loaded'  # Reinserted at the inlet, not fed/purged.
    assert material._loaded_filament_status(3)['h3']['state'] == 'empty'
    assert material._paused_filament_status(3)['filament_required'] == ['h2', 'h3']
    with pytest.raises(ValueError, match='Load filament in Head 4'):
        material.cmd_CHECK_RESUME(FakeCommand())
    material._set_filament_loaded('h3', True)  # Successful loading completion.
    material.cmd_CHECK_RESUME(FakeCommand())
    assert state['paused'] and state['job'] == 'paused'


@pytest.mark.parametrize('condition', ['already_empty', 'unknown_sensor', 'idle', 'openace', 'different_file', 'closed_file'])
def test_filament_loss_does_not_attach_unrelated_evidence_to_pause(paused_origin_material, condition):
    import io
    from copy import deepcopy
    material, objects, state = paused_origin_material
    records = {'h2': {'state': 'loaded'}, 'h3': {'state': 'empty'}}
    material._filament_state()._sensor_filament_status = lambda now: deepcopy(records)
    material._set_filament_loaded('h3', condition != 'already_empty')
    if condition == 'unknown_sensor': records['h3']['state'] = 'unknown'
    elif condition == 'idle': state['job'] = 'standby'
    elif condition == 'openace': objects['openace'] = object()
    elif condition == 'closed_file': objects['virtual_sdcard'].current_file.close()
    elif condition == 'different_file':
        material._pause_origin = None
        material._loaded_filament_status(2)
        objects['virtual_sdcard'].current_file = io.StringIO('same name, different open job')
        material.cmd_CAPTURE_PAUSE(FakeCommand())
    material._loaded_filament_status(3)
    assert material._pause_origin.get('filament_required', []) == []

@pytest.mark.parametrize('failure', ['none', 'purge', 'return_lock', 'calibration', 'unrelated'])
@pytest.mark.parametrize('action', ['load', 'unload'])
def test_cross_head_paused_load_returns_origin_without_touching_z(paused_origin_material, monkeypatch, failure, action):
    from copy import deepcopy
    from types import SimpleNamespace
    material, objects, state = paused_origin_material
    profiles, revision = material._profiles()
    profiles['h3'] = dict(profiles['h2'])
    material._material_settings()._profiles = lambda: (deepcopy(profiles), revision)
    material._pause_origin['filament_required'] = ['h3']
    state['variables']['t3_offset'] = [0.3, 0.4, 0.2]
    mounted = {'head': 'h2'}
    material._material_status()._attachment = lambda now: {'state': 'attached', 'head': mounted['head']} if mounted['head'] else {'state': 'empty', 'head': ''}
    material._filament_state()._sensor_filament_status = lambda now: {h: {'state': 'loaded', 'identity': profiles[h]} for h in ('h2', 'h3')}
    material._set_filament_loaded('h2', True)
    material._set_filament_loaded('h3', action == 'unload')
    heaters = {h: {'target': 0, 'temperature': 25, 'can_extrude': True} for h in ('extruder2', 'extruder3')}
    for name, heater in heaters.items(): objects[name] = SimpleNamespace(get_status=lambda now, heater=heater: dict(heater))
    settings = objects['configfile'].get_status(1)['settings']
    settings['extruder3'] = dict(settings['extruder2'])
    objects['configfile'] = SimpleNamespace(get_status=lambda now: {'settings': settings})
    objects['filament_switch_sensor docked2'] = SimpleNamespace(get_status=lambda now: {'filament_detected': True})
    objects['filament_switch_sensor docked3'] = SimpleNamespace(get_status=lambda now: {'filament_detected': True})
    objects['custom_hall'] = SimpleNamespace(get_status=lambda now: {'Raw': 4000 if mounted['head'] else 5000})
    objects['filament_switch_sensor sensor_b'] = SimpleNamespace(get_status=lambda now: {'filament_detected': bool(mounted['head'])})
    calls, feeds = [], []
    def run(script):
        calls.append(script)
        for line in script.splitlines():
            if line.startswith('_UNLOCK_TOOL '): mounted['head'] = ''
            if line.startswith('_LOCK_TOOL '):
                target = int(line.split('T=')[1].split()[0])
                if failure == 'return_lock' and target == 2: raise ValueError('return lock failed')
                mounted['head'] = 'h%d' % target
            if line.startswith('ACTIVATE_EXTRUDER'):
                objects['toolhead'].get_status(1)['extruder'] = line.split('=')[1]
            if line.startswith('SET_HEATER_TEMPERATURE'):
                fields = dict(part.split('=') for part in line.split()[1:])
                heaters[fields['HEATER']].update(target=float(fields['TARGET']), temperature=float(fields['TARGET']))
    objects['gcode'] = SimpleNamespace(run_script_from_command=run)
    def feed(printer, script):
        feeds.append(script)
        if len(feeds) == (2 if action == 'load' else 1):
            if failure == 'purge': raise ValueError('purge failed')
            if failure == 'calibration': state['variables']['t3_offset'] = [1., 1., 1.]
        if failure == 'unrelated':
            state['variables']['t1_offset'] = None
            state['variables']['t1_position'] = None
    monkeypatch.setattr('wm_material.run_standalone_extrusion_sequence', feed)
    before = deepcopy(objects['gcode_move'].saved_states)
    z_before = objects['toolhead'].get_status(1)['position'][2]
    plan = material._filament_plan(3, action, 1)
    assert plan['service']['restore_offset'] == pytest.approx([0.5, 0.3, 0.25])
    assert plan['service']['return_offset'] == [0.2, -0.1, 0.05]
    material._pause_origin.update(serviced=True, ready=False)
    material.filament_operation = {'id': 'paused-service', 'session': material.session_id, 'action': plan['action'], 'state': 'running', 'head': 'h3', 'pause_origin': plan['pause_origin']}
    if failure in ('none', 'unrelated'):
        material._filament_service()._execute_filament(FakeCommand(), 3, action, plan)
        assert mounted['head'] == 'h2'
        assert objects['toolhead'].get_status(1)['extruder'] == 'extruder2'
        assert material._filament_state()._load_filament_flags().get('h3', False) is (action == 'load')
        if action == 'load':
            assert calls.index('WIPE_NOZZLE XY_ONLY=1\nM400') < next(i for i, v in enumerate(calls) if 'ACTIVATE_EXTRUDER EXTRUDER=extruder2' in v)
        assert 'SET_GCODE_OFFSET X=0.20000 Y=-0.10000 Z=0.05000 MOVE=0' in calls
        if action == 'load': material.cmd_CHECK_RESUME(FakeCommand())
        else:
            with pytest.raises(ValueError): material.cmd_CHECK_RESUME(FakeCommand())
    else:
        with pytest.raises(ValueError): material._filament_service()._execute_filament(FakeCommand(), 3, action, plan)
        with pytest.raises(ValueError): material.cmd_CHECK_RESUME(FakeCommand())
        assert not material._filament_state()._load_filament_flags().get('h3', False)
    assert objects['gcode_move'].saved_states == before
    assert objects['toolhead'].get_status(1)['position'][2] == z_before
    assert not any(line.startswith(('G28', 'G1 Z', 'G0 Z', 'RESTORE_GCODE_STATE', 'RESUME')) for script in calls for line in script.splitlines())
    assert heaters['extruder3']['target'] == 0
    assert state['paused'] and state['job'] == 'paused'
    assert 'returning' in [step['phase'] for step in material.filament_operation['steps']]


def test_paused_cross_head_identity_edit_uses_selected_head_not_origin(paused_origin_material):
    from types import SimpleNamespace
    material, objects, state = paused_origin_material
    material._pause_origin['filament_required'] = ['h3']
    material._filament_state()._loaded_filament_status = lambda now: {'h2': {'state': 'loaded'}, 'h3': {'state': 'empty'}}
    objects['extruder3'] = SimpleNamespace(get_status=lambda now: {'temperature': 25, 'target': 0})
    before = material._profiles()[0]['h2'].copy()
    command = profile_command(material, HEAD='3', PAUSE=material._pause_origin['id'])
    material.cmd_SET_FILAMENT(command)
    assert material._profiles()[0]['h3']['material'] == 'PETG'
    assert material._profiles()[0]['h2'] == before
    assert material._attachment(1) == {'state': 'attached', 'head': 'h2'}
    assert state['paused']


@pytest.mark.parametrize('stale', ['new_file', 'new_session'])
@pytest.mark.parametrize('operation', ['failed', 'complete', 'running', 'unknown'])
def test_new_print_pause_is_not_blocked_by_prior_cancelled_service(paused_origin_material, stale, operation):
    import io
    material, objects, state = paused_origin_material
    prior = material._pause_origin
    prior.update(serviced=True, ready=False, filament_required=['h3'])
    material.filament_operation = {'state': operation}
    if stale == 'new_file':
        prior['file'].close()
        objects['virtual_sdcard'].current_file = io.StringIO('new job at the same path')
    else:
        material.session_id = 'new-session'
    if operation == 'running':
        with pytest.raises(ValueError, match='unresolved'):
            material.cmd_CAPTURE_PAUSE(FakeCommand())
        assert material._pause_origin is prior
    else:
        material.cmd_CAPTURE_PAUSE(FakeCommand())
        assert material._pause_origin is not prior
        assert material._pause_origin['file'] is objects['virtual_sdcard'].current_file
        assert material._pause_origin['session'] == material.session_id
        assert material._pause_origin['filament_required'] == []
        assert state['paused'] and state['job'] == 'paused'


# Legacy/public service adapters must enter the same operation state machine.
def test_public_service_load_uses_managed_sequence_once(sequence_material, monkeypatch):
    from types import SimpleNamespace
    material, objects = sequence_material
    objects['gcode'] = SimpleNamespace(create_gcode_command=lambda name, line, args: FakeCommand(**args))
    scripts = []
    monkeypatch.setattr('wm_material.run_standalone_extrusion_sequence', lambda printer, script: scripts.append(script))
    command = FakeCommand(ACTION='load', HEAD='2', ID='public-load')
    material.cmd_FILAMENT_SERVICE(command)
    assert scripts == ['G1 E55 F400', 'G1 E50 F400']
    assert material.filament_operation['head'] == 'h2'
    assert material.filament_operation['id'] == 'public-load'
    assert material.filament_operation['state'] == 'complete'
    assert command.message == 'Filament operation public-load: complete'
    with pytest.raises(ValueError, match='already attempted'):
        material.cmd_FILAMENT_SERVICE(command)
    assert len(scripts) == 2


@pytest.mark.parametrize('arguments', [
    {'T': '2'}, {'HEAD': '-1'}, {'HEAD': '4'}, {'HEAD': 'bad'},
    {'HEAD': '2', 'T': '0'}, {'HEAD': '2', 'TEMP': '220'},
    {'HEAD': '2', 'ACTION': 'extrude'}, {'HEAD': '2', 'ID': 'bad request'},
])
def test_public_service_rejects_ambiguous_or_unsupported_parameters(sequence_material, monkeypatch, arguments):
    from types import SimpleNamespace
    material, objects = sequence_material
    objects['gcode'] = SimpleNamespace(create_gcode_command=lambda name, line, args: FakeCommand(**args))
    monkeypatch.setattr('wm_material.run_standalone_extrusion_sequence', lambda *args: pytest.fail('motion on invalid request'))
    with pytest.raises((ValueError, KeyError)):
        material.cmd_FILAMENT_SERVICE(FakeCommand(**dict({'ACTION': 'load'}, **arguments)))
    assert material.filament_operation == {}


@pytest.mark.parametrize('condition', ['printing', 'from_sd', 'busy', 'attachment'])
def test_public_service_preserves_admission(sequence_material, monkeypatch, condition):
    from types import SimpleNamespace
    material, objects = sequence_material
    objects['gcode'] = SimpleNamespace(create_gcode_command=lambda name, line, args: FakeCommand(**args))
    if condition == 'printing': material.printer.state = 'printing'
    elif condition == 'from_sd': objects['virtual_sdcard'].is_cmd_from_sd = lambda: True
    elif condition in ('unknown', 'busy'):
        material.filament_operation = {'id': 'previous', 'state': 'unknown' if condition == 'unknown' else 'running'}
    else: material._material_status()._attachment = lambda now: {'state': 'unknown'}
    monkeypatch.setattr('wm_material.run_standalone_extrusion_sequence', lambda *args: pytest.fail('motion on refused request'))
    with pytest.raises(ValueError):
        material.cmd_FILAMENT_SERVICE(FakeCommand(ACTION='load', HEAD='2'))


def test_public_service_ace_unload_uses_owner_and_readback(print_material):
    material, objects, _ = ace_unload_fixture(print_material)
    gcode = objects['gcode']
    gcode.create_gcode_command = lambda name, line, args: FakeCommand(**args)
    original = gcode.run_script_from_command
    def unload(script):
        original(script)
        objects['openace'].values['loaded']['h2'] = {'state': 'empty'}
    gcode.run_script_from_command = unload
    command = FakeCommand(ACTION='unload', HEAD='2', ID='public-unload')
    material.cmd_FILAMENT_SERVICE(command)
    assert gcode.scripts == []
    material.printer.get_reactor().callbacks.pop()(1.)
    assert gcode.scripts == ['OPENACE_UNLOAD HEAD=h2']
    assert material.filament_operation['id'] == 'public-unload'
    assert material.filament_operation['state'] == 'complete'


def test_public_service_does_not_choose_an_ace_slot(print_material):
    material, objects, _, _ = openace_start_fixture(print_material)
    material._filament_requests = set()
    material.filament_operation = {}
    material._material_owners()._openace_load_plans = lambda head, now: [{'source': 'ace0:1', 'token': 'some-token'}]
    with pytest.raises(ValueError, match='Select an ACE slot'):
        material.cmd_FILAMENT_SERVICE(FakeCommand(ACTION='load', HEAD='2'))
    assert not objects['gcode'].scripts
    assert material.filament_operation == {}


def recovery_job_record(material):
    from pathlib import Path
    return json.loads((Path(material.profile_path).parent / 'wmp_recovery_job.json').read_text())


def test_print_stages_used_heads_and_exact_file_content(print_material):
    import hashlib
    material, objects, request, path = print_material
    material.cmd_START_PRINT(start_command(request))
    record = recovery_job_record(material)
    assert record['state'] == 'staged'  # Not yet checkpoint/recovery authority.
    assert record['owner'] == 'standalone'
    assert record['required_tools'] == {'0': 2}
    assert record['mapping'] == [2, 1, 2, 3]
    assert set(record['heads']) == {'h2'}  # Empty unused heads are not required.
    assert record['heads']['h2']['source'] == 'external:h2'
    assert record['heads']['h2']['identity'] == material._profiles()[0]['h2']
    assert record['file']['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    # The serialized snapshot is independent of future in-memory/profile edits.
    saved = json.dumps(record, sort_keys=True)
    material.session_id = 'restarted-session'
    assert json.dumps(recovery_job_record(material), sort_keys=True) == saved


def test_new_print_failure_invalidates_old_recovery_material_record(print_material):
    material, objects, request, path = print_material
    material._write_recovery_job({'version': 1, 'state': 'committed', 'id': 'old-job'})
    objects['gcode'].fail_at = 1
    with pytest.raises(ValueError, match='injected failure'):
        material.cmd_START_PRINT(start_command(request))
    record = recovery_job_record(material)
    assert record['state'] == 'invalidated' and record['id'] == request['id']
    assert not any(s.startswith('SDCARD_PRINT_FILE') for s in objects['gcode'].scripts)


def test_recovery_record_write_failure_disables_recovery_not_print(print_material, monkeypatch):
    import wm_material
    material, objects, request, path = print_material
    def failed(*args, **kwargs):
        raise OSError('storage unavailable')
    monkeypatch.setattr(wm_material.tempfile, 'mkstemp', failed)
    material.cmd_START_PRINT(start_command(request))
    assert objects['gcode'].scripts[-1].startswith('SDCARD_PRINT_FILE')
    assert material.print_submission['state'] == 'submitted'
    assert 'storage unavailable' in material._print_recovery_error


@pytest.mark.parametrize('missing', ['source', 'identity'])
def test_staging_unproven_identity_disables_recovery_not_print(print_material, missing):
    material, objects, request, path = print_material
    loaded = material._loaded_filament_status(0)
    loaded['h2'].pop(missing)
    material._filament_state()._loaded_filament_status = lambda now: loaded
    material.cmd_START_PRINT(start_command(request))
    assert recovery_job_record(material)['state'] == 'invalidated'
    assert objects['gcode'].scripts[-1].startswith('SDCARD_PRINT_FILE')
    assert 'source identity' in material._print_recovery_error


def test_openace_submission_cannot_leave_standalone_recovery_authority(print_material):
    material, objects, request, path = openace_start_fixture(print_material)
    material._write_recovery_job({'version': 1, 'state': 'committed', 'owner': 'standalone'})
    material.cmd_START_PRINT(start_command(request))
    record = recovery_job_record(material)
    assert record['state'] == 'owner-required' and record['owner'] == 'openace'
    assert 'heads' not in record


def test_duplicate_print_does_not_replace_staged_job(print_material):
    material, objects, request, path = print_material
    material.cmd_START_PRINT(start_command(request))
    record = recovery_job_record(material)
    with pytest.raises(ValueError, match='already attempted'):
        material.cmd_START_PRINT(start_command(request))
    assert recovery_job_record(material) == record


@pytest.mark.parametrize('drift', ['sensor', 'mapping', 'owner', 'file'])
def test_hashing_yields_and_revalidates_before_dispatch(print_material, drift):
    material, objects, request, path = print_material
    calls = []
    def pause(waketime):
        calls.append(waketime)
        if drift == 'sensor':
            material._filament_state()._loaded_filament_status = lambda now: {'h2': {'state': 'empty'}}
        elif drift == 'mapping':
            objects['save_variables'].values['variables']['box_modify_t0'] = 1
        elif drift == 'owner':
            material.printer.owner = object()
        else:
            path.write_text('replaced during hashing')
        return waketime
    material.printer.pause = pause
    with pytest.raises(ValueError):
        material.cmd_START_PRINT(start_command(request))
    assert calls
    assert recovery_job_record(material)['state'] == 'invalidated'
    assert not any(s.startswith('SDCARD_PRINT_FILE') for s in objects['gcode'].scripts)


@pytest.fixture
def recovery_startup(print_material):
    import copy
    from types import SimpleNamespace
    material, objects, request, path = print_material
    material.printer.command_error = ValueError
    material.cmd_START_PRINT(start_command(request))
    material.printer.state = 'printing'
    sd = objects['virtual_sdcard']
    sd.active = sd.from_sd = True
    variables = objects['save_variables'].values['variables']
    offsets = [[0., 0., float(i)] for i in range(4)]
    variables.update({'t%d_offset' % i: value for i, value in enumerate(offsets)})
    context = {'version': 2, 'tool': 2, 'mesh': 'wmp_print',
               'mapping': [2, 1, 2, 3], 'offsets': copy.deepcopy(offsets),
               'file_hex': path.name.encode().hex()}
    variables['wmp_print_context'] = context
    variables['probe_tool'] = 2
    # Model the retained SAVE_VARIABLE literal parsing for backend-owned context
    # writes; the generic print fixture only handles integer mapping writes.
    original_dispatch = objects['gcode'].run_script_from_command
    def dispatch(script):
        if script.startswith('SAVE_VARIABLE VARIABLE=wmp_print_context '):
            import ast
            import shlex
            objects['gcode'].scripts.append(script)
            fields = dict(item.split('=', 1) for item in shlex.split(script)[1:])
            variables['wmp_print_context'] = ast.literal_eval(fields['VALUE'])
        else:
            original_dispatch(script)
    objects['gcode'].run_script_from_command = dispatch
    objects['bed_mesh'] = SimpleNamespace(
        fade_start=1., fade_end=10., fade_dist=9., fade_target=0., tool_offset=0.,
        get_z_factor=lambda z: 1.,
        get_mesh=lambda: SimpleNamespace(mesh_offsets=[0., 0.], calc_z=lambda x, y: .15),
        get_status=lambda now: {'profile_name': 'wmp_print', 'profiles': {'wmp_print': {}},
            'mesh_min': [0., 0.], 'mesh_max': [300., 300.], 'mesh_matrix': [[.15, .15], [.15, .15]]})
    with path.open('r') as stream:
        sd.current_file = stream
        yield material, objects, request, path


def test_recovery_material_commit_binds_successful_startup_context(recovery_startup):
    material, objects, request, path = recovery_startup
    material.cmd_RECOVERY_JOB_BEGIN(FakeCommand())
    material._print_mesh_persisted = True  # This fixture simulates completed mesh persistence.
    material.cmd_RECOVERY_JOB_COMMIT(FakeCommand())
    record = recovery_job_record(material)
    assert record['state'] == 'committed'
    assert record['context'] == objects['save_variables'].values['variables']['wmp_print_context']
    assert material._pending_recovery_submission is None
    material.cmd_RECOVERY_JOB_CLEAR(FakeCommand())
    assert recovery_job_record(material)['state'] == 'invalidated'


@pytest.mark.parametrize('drift', [
    'session', 'file', 'sensor', 'mapping', 'offset', 'mesh', 'operation',
    'disk_record', 'not_begun', 'not_sd', 'owner'])
def test_recovery_commit_disables_optional_evidence_on_changed_startup(recovery_startup, drift):
    material, objects, request, path = recovery_startup
    if drift != 'not_begun':
        material.cmd_RECOVERY_JOB_BEGIN(FakeCommand())
    variables = objects['save_variables'].values['variables']
    if drift == 'session':
        material.session_id = 'new-session'
    elif drift == 'file':
        path.write_text('different file contents')
    elif drift == 'sensor':
        material._filament_state()._loaded_filament_status = lambda now: {'h2': {'state': 'empty'}}
    elif drift == 'mapping':
        variables['box_modify_t0'] = 0
    elif drift == 'offset':
        del variables['t0_offset']
    elif drift == 'mesh':
        objects['bed_mesh'].get_status = lambda now: {'profile_name': 'default', 'profiles': {'wmp_print': {}}}
    elif drift == 'operation':
        material.filament_operation = {'state': 'running'}
    elif drift == 'disk_record':
        record = recovery_job_record(material)
        record['heads']['h2']['source'] = 'external:h0'
        material._write_recovery_job(record)
    elif drift == 'not_sd':
        objects['virtual_sdcard'].from_sd = False
    elif drift == 'owner':
        material.printer.owner = object()
    material._print_mesh_persisted = True  # Simulated completed mesh persistence.
    command = FakeCommand()
    material.cmd_RECOVERY_JOB_COMMIT(command)
    assert 'Printing can continue' in command.message
    assert recovery_job_record(material)['state'] != 'committed'
    assert material._pending_recovery_submission is None


def test_restart_cannot_promote_previous_session_stage(recovery_startup):
    material, objects, request, path = recovery_startup
    material._pending_recovery_submission = None
    material.session_id = 'new-session'
    material._print_mesh_persisted = True  # This fixture simulates completed mesh persistence.
    material.cmd_RECOVERY_JOB_COMMIT(FakeCommand())
    assert recovery_job_record(material)['state'] == 'staged'
    material.cmd_RECOVERY_JOB_BEGIN(FakeCommand())  # An unrelated direct start.
    assert recovery_job_record(material)['state'] == 'invalidated'


def test_failed_dispatch_cannot_later_commit_its_stage(print_material):
    material, objects, request, path = print_material
    objects['gcode'].fail_at = 10
    with pytest.raises(ValueError):
        material.cmd_START_PRINT(start_command(request))
    assert recovery_job_record(material)['state'] == 'staged'
    assert material._pending_recovery_submission is None


def test_clear_storage_error_does_not_interrupt_cancellation(recovery_startup, monkeypatch):
    material, objects, request, path = recovery_startup
    # The macro clears this before calling the helper.
    objects['save_variables'].values['variables']['wmp_print_context'] = {}
    def fail(record):
        raise OSError('disk failed')
    monkeypatch.setattr(material._recovery_storage(), '_write_recovery_job', fail)
    command = FakeCommand()
    material.cmd_RECOVERY_JOB_CLEAR(command)
    assert 'clear failed' in command.message
    assert material._pending_recovery_submission is None
    assert objects['save_variables'].values['variables']['wmp_print_context'] == {}



@pytest.mark.parametrize('long_line', [False, True])
def test_direct_sd_start_stages_its_actual_file_and_commits_context(recovery_startup, long_line):
    from types import SimpleNamespace as NS
    material, objects, request, path = recovery_startup
    material._pending_recovery_submission = None
    payload = 'START_PRINT INITIAL_TOOL=0\nT0\nG1 X1\n'
    if long_line:
        # Apparent tool commands inside a large comment must not become
        # requirements when the bounded reader crosses a chunk boundary.
        payload += ';' + 'x' * 65535 + 'T3 ' + 'x' * 100000 + '\n'
    path.write_text(payload)
    sd = objects['virtual_sdcard']
    sd.file_position, sd.next_file_position = 0, len('START_PRINT INITIAL_TOOL=0\n')
    objects['gcode_macro START_PRINT'] = NS(get_status=lambda now: {'print_body_ready': False})
    material.cmd_RECOVERY_JOB_BEGIN(FakeCommand())
    stage = recovery_job_record(material)
    assert stage['state'] == 'staged' and stage['id'].startswith('sd_')
    assert stage['file']['path'] == path.name and stage['required_tools'] == {'0': 2}
    import hashlib
    assert stage['file']['sha256'] == hashlib.sha256(payload.encode()).hexdigest()
    assert objects['save_variables'].values['variables']['wmp_print_context'] == {}
    material._print_mesh_persisted = True  # Completed mesh persistence is tested with the real writer separately.
    material.cmd_RECOVERY_JOB_COMMIT(FakeCommand())
    record = recovery_job_record(material)
    assert record['state'] == 'committed' and record['id'] == stage['id']
    assert record['context']['tool'] == 2
    assert record['context']['mapping'] == [2, 1, 2, 3]
    assert record['context']['file_hex'] == path.name.encode().hex()


@pytest.mark.parametrize('stage', ['begin', 'commit'])
def test_optional_context_storage_failure_does_not_abort_print(recovery_startup, stage):
    material, objects, request, path = recovery_startup
    if stage == 'commit':
        material.cmd_RECOVERY_JOB_BEGIN(FakeCommand())
        material._print_mesh_persisted = True
    original = objects['gcode'].run_script_from_command
    def dispatch(script):
        if script.startswith('SAVE_VARIABLE VARIABLE=wmp_print_context '):
            raise ValueError('context storage unavailable')
        original(script)
    objects['gcode'].run_script_from_command = dispatch
    command = FakeCommand()
    getattr(material, 'cmd_RECOVERY_JOB_' + stage.upper())(command)
    assert 'context storage unavailable' in command.message
    assert 'Printing can continue' in command.message
    assert recovery_job_record(material)['state'] == 'invalidated'
    assert material._pending_recovery_submission is None
    assert material.printer.state == 'printing'
    assert objects['virtual_sdcard'].current_file is not None


@pytest.fixture
def committed_recovery(recovery_startup):
    material, objects, request, path = recovery_startup
    material.cmd_RECOVERY_JOB_BEGIN(FakeCommand())
    material._print_mesh_persisted = True  # This fixture simulates completed mesh persistence.
    material.cmd_RECOVERY_JOB_COMMIT(FakeCommand())
    # A restart changes the live session and unloads the active mesh, not the
    # persisted evidence. Unused heads remain outside the material requirements.
    material.session_id = 'after-restart'
    objects['bed_mesh'].get_status = lambda now: {'profile_name': '', 'profiles': {'wmp_print': {}}}
    objects['gcode'].scripts.clear()
    return material, objects, request, path


def test_recovery_evidence_survives_session_change_without_motion(committed_recovery):
    material, objects, request, path = committed_recovery
    evidence = material._recovery_material_evidence(path.name)
    assert evidence['state'] == 'committed'
    assert set(evidence['heads']) == {'h2'}
    assert evidence['session'] != material.session_id
    assert objects['gcode'].scripts == []


@pytest.mark.parametrize('drift', [
    'selected_file', 'sensor', 'owner', 'operation', 'tool_operation',
    'context', 'offset', 'mesh', 'content', 'record_state', 'required_tools',
    'missing_head', 'extra_head', 'boolean_mapping', 'source', 'digest'])
def test_recovery_evidence_rejects_stale_or_malformed_state(committed_recovery, drift):
    import os
    material, objects, request, path = committed_recovery
    selected = path.name
    record = recovery_job_record(material)
    if drift == 'selected_file':
        selected = 'another.gcode'
    elif drift == 'sensor':
        material._filament_state()._loaded_filament_status = lambda now: {'h2': {'state': 'inserted'}}
    elif drift == 'owner':
        material.printer.owner = object()
    elif drift == 'operation':
        material.filament_operation = {'state': 'running'}
    elif drift == 'tool_operation':
        material.toolhead_operation = {'state': 'running'}
    elif drift == 'context':
        objects['save_variables'].values['variables']['wmp_print_context'] = {}
    elif drift == 'offset':
        objects['save_variables'].values['variables']['t2_offset'] = [1., 2., 3.]
    elif drift == 'mesh':
        objects['bed_mesh'].get_status = lambda now: {'profiles': {}}
    elif drift == 'content':
        info = path.stat()
        data = path.read_bytes()
        path.write_bytes(bytes([data[0] ^ 1]) + data[1:])
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
    else:
        if drift == 'record_state': record['state'] = 'staged'
        elif drift == 'required_tools': record['required_tools'] = {'0': 1}
        elif drift == 'missing_head': record['heads'] = {}
        elif drift == 'extra_head': record['heads']['h0'] = record['heads']['h2']
        elif drift == 'boolean_mapping': record['mapping'][1] = True
        elif drift == 'source': record['heads']['h2']['source'] = 'external:h1'
        elif drift == 'digest': record['file']['sha256'] = '0' * 64
        material._write_recovery_job(record)
    with pytest.raises(ValueError):
        material._recovery_material_evidence(selected)
    assert objects['gcode'].scripts == []


@pytest.mark.parametrize('drift', ['sensor', 'owner', 'record', 'context', 'operation'])
def test_recovery_evidence_rechecks_after_hash_yields(committed_recovery, drift):
    material, objects, request, path = committed_recovery
    calls = []
    def pause(waketime):
        calls.append(waketime)
        if drift == 'sensor':
            material._filament_state()._loaded_filament_status = lambda now: {'h2': {'state': 'empty'}}
        elif drift == 'owner':
            material.printer.owner = object()
        elif drift == 'record':
            record = recovery_job_record(material)
            record['id'] = 'replacement-job'
            material._write_recovery_job(record)
        elif drift == 'context':
            objects['save_variables'].values['variables']['wmp_print_context'] = {}
        else:
            material.filament_operation = {'state': 'running'}
        return waketime
    material.printer.pause = pause
    with pytest.raises(ValueError):
        material._recovery_material_evidence(path.name)
    assert calls
    assert objects['gcode'].scripts == []


@pytest.fixture
def bound_recovery(committed_recovery, tmp_path):
    from pathlib import Path
    material, objects, request, path = committed_recovery
    directory = tmp_path / 'native'
    directory.mkdir()
    material.recovery_checkpoint_dir = str(directory)
    checkpoint = directory / 'plr_dataB.ini'
    checkpoint.write_bytes(recovery_checkpoint_payload())
    checkpoint_hash = material._recovery_fingerprint(checkpoint.read_bytes())
    job_hash = material._recovery_fingerprint(Path(material._recovery_job_path()).read_bytes())
    marker = Path(str(checkpoint) + '.wmp-coordinates')
    marker.write_text('WMP-GCODE-XYZ-MATERIAL-2 %s %s\n' % (checkpoint_hash, job_hash))
    return material, objects, path, checkpoint, marker, checkpoint_hash, job_hash


def test_recovery_checkpoint_matches_native_cached_binding(bound_recovery):
    material, objects, path, checkpoint, marker, chash, jhash = bound_recovery
    result = material._recovery_checkpoint_evidence(path.name, checkpoint.name, chash, jhash)
    assert result['record']['state'] == 'committed'
    assert result['checkpoint'] == 'plr_dataB.ini'
    assert result['checkpoint_hash'] == chash and result['job_hash'] == jhash
    assert objects['gcode'].scripts == []


@pytest.mark.parametrize('payload,expected', [
    (b'', 'cbf29ce484222325'), (b'a', 'af63dc4c8601ec8c'),
    (b'foobar', '85944171f73967e8')])
def test_recovery_fingerprint_uses_fnv1a64(material, payload, expected):
    assert material._recovery_fingerprint(payload) == expected


@pytest.mark.parametrize('drift', [
    'checkpoint', 'job', 'legacy_marker', 'extra_marker_field', 'stale_checkpoint_hash',
    'stale_job_hash', 'wrong_selection', 'traversal', 'absolute', 'symlink',
    'fifo', 'oversized', 'empty', 'invalid_hash'])
def test_recovery_checkpoint_refuses_mismatched_evidence(bound_recovery, drift):
    from pathlib import Path
    import os
    material, objects, path, checkpoint, marker, chash, jhash = bound_recovery
    selection = checkpoint.name
    if drift == 'checkpoint': checkpoint.write_text('[plr_data]\nlast_file_pos=99\n')
    elif drift == 'job':
        job = Path(material._recovery_job_path())
        job.write_bytes(job.read_bytes() + b'\n')  # Same JSON, different bound bytes.
    elif drift == 'legacy_marker': marker.write_text('WMP-GCODE-XYZ-1 ' + chash + '\n')
    elif drift == 'extra_marker_field': marker.write_text(marker.read_text() + 'extra\n')
    elif drift == 'stale_checkpoint_hash': chash = '0' * 16
    elif drift == 'stale_job_hash': jhash = '0' * 16
    elif drift == 'wrong_selection': selection = 'plr_dataA.ini'
    elif drift == 'traversal': selection = '../plr_dataB.ini'
    elif drift == 'absolute': selection = str(checkpoint)
    elif drift == 'symlink':
        target = checkpoint.with_suffix('.saved')
        checkpoint.rename(target)
        checkpoint.symlink_to(target)
    elif drift == 'fifo':
        checkpoint.unlink()
        os.mkfifo(checkpoint)
    elif drift == 'oversized': checkpoint.write_bytes(b'x' * 65537)
    elif drift == 'empty': checkpoint.write_bytes(b'')
    else: chash = True
    with pytest.raises((ValueError, OSError)):
        material._recovery_checkpoint_evidence(path.name, selection, chash, jhash)
    assert objects['gcode'].scripts == []


@pytest.mark.parametrize('drift', ['checkpoint', 'marker', 'job_bytes'])
def test_recovery_checkpoint_rechecks_bindings_after_yield(bound_recovery, drift):
    from pathlib import Path
    material, objects, path, checkpoint, marker, chash, jhash = bound_recovery
    calls = []
    def pause(waketime):
        calls.append(waketime)
        target = (checkpoint if drift == 'checkpoint' else marker if drift == 'marker'
                  else Path(material._recovery_job_path()))
        target.write_bytes(target.read_bytes() + b'\n')
        return waketime
    material.printer.pause = pause
    with pytest.raises(ValueError):
        material._recovery_checkpoint_evidence(path.name, checkpoint.name, chash, jhash)
    assert calls and objects['gcode'].scripts == []


def recovery_checkpoint_payload(**overrides):
    fields = dict(absolute_e=0, last_file_pos=3, last_x=165.3, last_y=246.8,
                  last_z=1.04516, last_e=10.1, timestamp=296, print_time=541,
                  last_heater_bed_target=55, last_is_during_T=0,
                  last_leveling_type='adaptive_mesh', last_fan_speed=1.,
                  last_auxiliary_fan_speed=.698039, last_air_fan_speed=0.,
                  last_gcode_move_speed=30000., last_gcode_move_speed_factor=1.,
                  last_gcode_move_extrude_factor=1.)
    fields.update({'last_extruder%d_target' % i: 220 if i == 2 else 0 for i in range(4)})
    fields.update(overrides)
    return ('[plr_data]\n' + ''.join('%s=%s\n' % item for item in fields.items())).encode('ascii')


@pytest.mark.parametrize('key,value', [
    ('last_file_pos', 0), ('last_file_pos', -1), ('last_file_pos', 6),
    ('last_file_pos', '3.0'), ('last_file_pos', 2147483648),
    ('absolute_e', 2), ('last_is_during_T', -1), ('timestamp', 0),
    ('print_time', -1), ('last_x', 'nan'), ('last_e', 'inf'),
    ('last_z', '1e999'), ('last_y', '1 trailing'),
    ('last_gcode_move_speed', 0), ('last_gcode_move_speed_factor', -1),
    ('last_gcode_move_extrude_factor', 0), ('last_fan_speed', 255),
    ('last_auxiliary_fan_speed', -0.1), ('last_air_fan_speed', 1.1),
    ('last_extruder2_target', -1), ('last_heater_bed_target', -1),
    ('last_leveling_type', '""'), ('last_leveling_type', 'unknown')])
def test_recovery_checkpoint_numeric_rejections(material, key, value):
    with pytest.raises(ValueError):
        material._recovery_storage()._recovery_checkpoint_values(recovery_checkpoint_payload(**{key: value}), 6)


@pytest.mark.parametrize('alter', ['duplicate', 'missing', 'defaults', 'section', 'encoding'])
def test_recovery_checkpoint_rejects_malformed_format(material, alter):
    payload = recovery_checkpoint_payload()
    if alter == 'duplicate': payload += b'last_file_pos=4\n'
    elif alter == 'missing': payload = payload.replace(b'last_file_pos=3\n', b'')
    elif alter == 'extra': payload += b'unknown=1\n'
    elif alter == 'defaults': payload = b'[DEFAULT]\nlast_file_pos=3\n' + payload
    elif alter == 'section': payload += b'[other]\nkey=value\n'
    else: payload += b'bad=\xff\n'
    with pytest.raises(ValueError):
        material._recovery_storage()._recovery_checkpoint_values(payload, 6)


def test_recovery_checkpoint_preserves_modes_and_offset_coordinates(material):
    values = material._recovery_storage()._recovery_checkpoint_values(recovery_checkpoint_payload(
        absolute_e=1, last_is_during_T=1, last_x=-2.5, last_e=-12.,
        last_leveling_type='default_mesh'), 6)
    assert values['absolute_e'] == 1 and values['last_is_during_T'] == 1
    assert values['last_x'] == -2.5 and values['last_e'] == -12.


@pytest.mark.parametrize('name', ['plr_dataA.ini', 'plr_dataB.ini'])
def test_recovery_parser_accepts_retained_vendor_checkpoint_format(material, name):
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / 'analysis' /
              'print-validation-20260914T021308Z' / 'power-recovery' / name)
    if not source.exists():
        pytest.skip('retained vendor checkpoint not available')
    # Format compatibility only. Old coordinates/material evidence are not
    # admitted here, and this deliberately does not call recovery preparation.
    result = material._recovery_storage()._recovery_checkpoint_values(source.read_bytes(), 2147483648)
    assert result['last_leveling_type'] == 'adaptive_mesh'
    assert result['last_file_pos'] > 0


@pytest.fixture
def recovery_machine(bound_recovery):
    from types import SimpleNamespace
    material, objects, path, checkpoint, marker, chash, jhash = bound_recovery
    material.printer.state = 'standby'
    material.printer.is_shutdown = lambda: False
    objects['virtual_sdcard'].active = objects['virtual_sdcard'].from_sd = False
    states = {
        'webhooks': {'state': 'ready'},
        'wmp_recovery': {'homing': False, 'calibration_active': False,
                         'calibration_failed': '', 'identification': {'state': 'idle'}},
        'gcode_macro _WMP_RECOVERY_BEGIN': {'active': False},
        'configfile': {'settings': {
            'extruder2': {'min_temp': 0., 'max_temp': 300.},
            'heater_bed': {'min_temp': 0., 'max_temp': 120.}}},
        'extruder2': {'temperature': 25.}, 'heater_bed': {'temperature': 25.},
    }
    for name, state in states.items():
        objects[name] = SimpleNamespace(get_status=lambda now, state=state: state)
    objects['save_variables'].values['variables'].update(fail_flag=0, is_nozzle_setting=0)
    material._material_status()._attachment = lambda now: {'state': 'attached', 'head': 'h2'}
    return bound_recovery, states


def test_recovery_review_ready_idle_machine_without_motion(recovery_machine):
    (material, objects, path, checkpoint, marker, chash, jhash), states = recovery_machine
    result = material._recovery_review_service()._recovery_review(material.session_id, path.name, checkpoint.name, chash, jhash)
    assert result['machine']['attachment'] == {'state': 'attached', 'head': 'h2'}
    assert objects['gcode'].scripts == []


@pytest.mark.parametrize('drift', [
    'session', 'shutdown', 'not_ready', 'printing', 'paused', 'sd_active', 'sd_command',
    'openace', 'afc', 'filament_operation', 'tool_operation',
    'setup', 'homing', 'calibration', 'identification',
    'recovery_active', 'attachment', 'heater_limit', 'missing_limit', 'temperature',
    'temperature_range', 'missing_bed', 'missing_service'])
def test_recovery_review_machine_refusals(recovery_machine, drift):
    (material, objects, path, checkpoint, marker, chash, jhash), states = recovery_machine
    session = material.session_id
    if drift == 'session': session = 'old-session'
    elif drift == 'shutdown': material.printer.is_shutdown = lambda: True
    elif drift == 'not_ready': states['webhooks']['state'] = 'startup'
    elif drift == 'printing': material.printer.state = 'printing'
    elif drift == 'paused': objects['pause_resume'].values['is_paused'] = True
    elif drift == 'sd_active': objects['virtual_sdcard'].active = True
    elif drift == 'sd_command': objects['virtual_sdcard'].from_sd = True
    elif drift == 'openace': material.printer.owner = object()
    elif drift == 'afc': objects['AFC'] = object()
    elif drift == 'filament_operation': material.filament_operation = {'state': 'pending'}
    elif drift == 'tool_operation': material.toolhead_operation = {'state': 'running'}
    elif drift == 'fault': objects['save_variables'].values['variables']['fail_flag'] = -3
    elif drift == 'missing_fault': del objects['save_variables'].values['variables']['fail_flag']
    elif drift == 'setup': objects['save_variables'].values['variables']['is_nozzle_setting'] = 1
    elif drift == 'homing': states['wmp_recovery']['homing'] = True
    elif drift == 'calibration': states['wmp_recovery']['calibration_active'] = True
    elif drift == 'calibration_failed': states['wmp_recovery']['calibration_failed'] = 'failed'
    elif drift == 'identification': states['wmp_recovery']['identification']['state'] = 'running'
    elif drift == 'recovery_active': states['gcode_macro _WMP_RECOVERY_BEGIN']['active'] = True
    elif drift == 'attachment': material._material_status()._attachment = lambda now: {'state': 'unknown', 'head': ''}
    elif drift == 'heater_limit': states['configfile']['settings']['extruder2']['max_temp'] = 200.
    elif drift == 'missing_limit': del states['configfile']['settings']['extruder2']['max_temp']
    elif drift == 'temperature': states['extruder2']['temperature'] = float('nan')
    elif drift == 'temperature_range': states['heater_bed']['temperature'] = 130.
    elif drift == 'missing_bed': del objects['heater_bed']
    else: del objects['wmp_recovery']
    with pytest.raises(ValueError):
        material._recovery_review_service()._recovery_review(session, path.name, checkpoint.name, chash, jhash)
    assert objects['gcode'].scripts == []


@pytest.mark.parametrize('drift', ['session', 'attachment', 'fault', 'shutdown', 'paused'])
def test_recovery_review_rechecks_machine_after_hashing(recovery_machine, drift):
    (material, objects, path, checkpoint, marker, chash, jhash), states = recovery_machine
    calls = []
    def pause(waketime):
        calls.append(waketime)
        if drift == 'session': material.session_id = 'new-session'
        elif drift == 'attachment': material._material_status()._attachment = lambda now: {'state': 'empty', 'head': ''}
        elif drift == 'fault': objects['save_variables'].values['variables']['fail_flag'] = -3
        elif drift == 'shutdown': material.printer.is_shutdown = lambda: True
        else: objects['pause_resume'].values['is_paused'] = True
        return waketime
    material.printer.pause = pause
    with pytest.raises(ValueError):
        material._recovery_review_service()._recovery_review(material.session_id, path.name, checkpoint.name, chash, jhash)
    assert calls and objects['gcode'].scripts == []


def test_interrupted_tool_change_requires_separate_recovery_plan(recovery_machine):
    (material, objects, path, checkpoint, marker, chash, jhash), states = recovery_machine
    checkpoint.write_bytes(recovery_checkpoint_payload(last_is_during_T=1))
    chash = material._recovery_fingerprint(checkpoint.read_bytes())
    marker.write_text('WMP-GCODE-XYZ-MATERIAL-2 %s %s\n' % (chash, jhash))
    with pytest.raises(ValueError, match='Interrupted tool-change'):
        material._recovery_review_service()._recovery_review(material.session_id, path.name, checkpoint.name, chash, jhash)
    assert objects['gcode'].scripts == []


@pytest.fixture
def execution_snapshot_machine(recovery_machine):
    import hashlib
    from types import SimpleNamespace
    (material, objects, path, checkpoint, marker, chash, jhash), states = recovery_machine
    objects['bed_mesh'].get_status = lambda now: {
        'profile_name': 'wmp_print', 'profiles': {'wmp_print': {}},
        'mesh_min': [0., 0.], 'mesh_max': [300., 300.], 'mesh_matrix': [[.15, .15], [.15, .15]]}
    path.write_text('G1 X1\nG1 X2\n')
    record = recovery_job_record(material)
    record['file'].update(size=path.stat().st_size, modified=path.stat().st_mtime,
                          sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    record['context']['tool'] = 1  # Probing reference differs from execution head.
    objects['save_variables'].values['variables']['wmp_print_context']['tool'] = 1
    material._write_recovery_job(record)
    material.printer.state = 'printing'
    sd = objects['virtual_sdcard']
    sd.active = True
    sd.get_status = lambda now: {'file_position': 6}
    sd.get_file_position = lambda: pytest.fail('next_file_position is not a completed boundary')
    objects['gcode'].get_mutex = lambda: SimpleNamespace(test=lambda: False)
    objects['save_variables'].values['variables']['current_extruder'] = 2
    states['toolhead'] = {'extruder': 'extruder2', 'position': [11., 22., .45, 24.]}
    states['extruder2']['target'] = 220.5
    states['heater_bed']['target'] = 55.
    states['fan'] = {'speed': .75}
    states['fan_generic auxiliary_fan'] = {'speed': .5}
    states['print_stats'] = {'state': 'printing', 'total_duration': 541.5, 'print_duration': 500., 'filament_used': 123.}
    states['gcode_macro START_PRINT'] = {'print_body_ready': True}
    states['gcode_move'] = {'gcode_position': [1., 2., .2, 12.],
                          'position': [11., 22., .3, 24.],
                          'homing_origin': [0., 0., .1, 0.],
                          'absolute_coordinates': True, 'absolute_extrude': False,
                          'speed': 300., 'speed_factor': 1., 'extrude_factor': 1.}
    for name in ('toolhead', 'gcode_macro START_PRINT', 'gcode_move', 'fan',
                 'fan_generic auxiliary_fan', 'print_stats'):
        objects[name] = SimpleNamespace(get_status=lambda now, name=name: states[name])
    objects['toolhead'].check_busy = lambda now: (100., 98., True)
    material.printer.pause = lambda when: pytest.fail('snapshot capture must not yield')
    return material, objects, states


def test_execution_snapshot_captures_completed_position_and_head_together(execution_snapshot_machine):
    material, objects, states = execution_snapshot_machine
    result = material._execution_evidence()._recovery_execution_snapshot()
    assert result['file_position'] == 6 and result['head'] == 'h2'
    assert result['mapping'] == [2, 1, 2, 3]
    assert result['source']['source'] == 'external:h2'
    assert result['heater_targets'] == {'extruder2': 220.5, 'heater_bed': 55.}
    assert result['fans'] == {'fan': .75, 'fan_generic auxiliary_fan': .5}
    assert result['total_duration'] == 541.5
    assert result['absolute_extrude'] is False
    assert result['scheduled_print_time'] == 100. and result['observed_print_time'] == 98.
    assert result['gcode_position'] == [1., 2., .2, 12.]
    states['gcode_move']['gcode_position'][0] = 99.
    assert result['gcode_position'][0] == 1.
    assert objects['gcode'].scripts == []


def use_native_tuple_offsets(objects):
    """SAVE_VARIABLE retains Python tuples; durable JSON uses arrays."""
    variables = objects['save_variables'].values['variables']
    for head in range(4):
        variables['t%d_offset' % head] = tuple(variables['t%d_offset' % head])
    variables['wmp_print_context']['offsets'] = [
        variables['t%d_offset' % head] for head in range(4)]


def test_execution_capture_and_publication_accept_native_tuple_offsets(execution_snapshot_machine):
    material, objects, states = execution_snapshot_machine
    use_native_tuple_offsets(objects)
    material._execution_evidence()._queue_recovery_execution()
    objects['toolhead'].check_busy = lambda now: (105., 101., True)
    assert material._execution_evidence()._publish_recovery_execution()
    completed = json.loads(Path(material._recovery_execution_path()).read_text())
    assert completed['state'] == 'completed'
    assert objects['gcode'].scripts == []


def test_recovery_material_accepts_native_tuple_offsets_after_restart(committed_recovery):
    material, objects, request, path = committed_recovery
    use_native_tuple_offsets(objects)
    assert material._recovery_material_evidence(path.name)['state'] == 'committed'
    assert objects['gcode'].scripts == []


def test_recovery_commit_keeps_native_offsets_and_serializes_json_arrays(recovery_startup):
    material, objects, request, path = recovery_startup
    use_native_tuple_offsets(objects)
    material.cmd_RECOVERY_JOB_BEGIN(FakeCommand())
    material._print_mesh_persisted = True  # This fixture simulates completed mesh persistence.
    material.cmd_RECOVERY_JOB_COMMIT(FakeCommand())
    record = recovery_job_record(material)
    variables = objects['save_variables'].values['variables']
    assert isinstance(variables['t0_offset'], tuple)
    assert isinstance(variables['wmp_print_context']['offsets'][0], tuple)
    assert isinstance(record['context']['offsets'][0], list)
    assert material._recovery_material_evidence(path.name) == record


@pytest.mark.parametrize('bad', [None, [], [0., 0.], [0., 0., '0'],
                               [0., 0., True], [0., 0., float('nan')],
                               [0., 0., float('inf')]])
def test_recovery_tuple_normalization_does_not_accept_invalid_offsets(committed_recovery, bad):
    material, objects, request, path = committed_recovery
    use_native_tuple_offsets(objects)
    variables = objects['save_variables'].values['variables']
    variables['wmp_print_context']['offsets'][0] = bad
    with pytest.raises(ValueError, match='offsets'):
        material._recovery_material_evidence(path.name)
    assert objects['gcode'].scripts == []


@pytest.mark.parametrize('change', ['live_offset', 'context_offset', 'mapping', 'tool', 'mesh', 'file_hex'])
def test_recovery_tuple_normalization_still_rejects_context_drift(committed_recovery, change):
    material, objects, request, path = committed_recovery
    use_native_tuple_offsets(objects)
    variables = objects['save_variables'].values['variables']
    context = variables['wmp_print_context']
    if change == 'live_offset': variables['t0_offset'] = (0., 0., .001)
    elif change == 'context_offset': context['offsets'][0] = (0., 0., .001)
    elif change == 'mapping': context['mapping'][0] = 0
    elif change == 'tool': context['tool'] = 0
    elif change == 'mesh': context['mesh'] = 'another'
    else: context['file_hex'] = '00'
    with pytest.raises(ValueError):
        material._recovery_material_evidence(path.name)
    assert objects['gcode'].scripts == []


@pytest.mark.parametrize('drift', [
    'in_command', 'inactive', 'paused', 'startup', 'owner', 'operation', 'fault',
    'mapping', 'attachment', 'extruder', 'saved_head', 'loaded', 'position',
    'coordinate', 'mode', 'speed', 'origin', 'file', 'lookahead', 'motion_clock'])
def test_execution_snapshot_refuses_incoherent_state(execution_snapshot_machine, drift):
    material, objects, states = execution_snapshot_machine
    if drift == 'in_command': objects['virtual_sdcard'].from_sd = True
    elif drift == 'inactive': objects['virtual_sdcard'].active = False
    elif drift == 'paused': objects['pause_resume'].values['is_paused'] = True
    elif drift == 'startup': states['gcode_macro START_PRINT']['print_body_ready'] = False
    elif drift == 'owner': material.printer.owner = object()
    elif drift == 'operation': material.filament_operation = {'state': 'running'}
    elif drift == 'fault': objects['save_variables'].values['variables']['fail_flag'] = -3
    elif drift == 'mapping': objects['save_variables'].values['variables']['box_modify_t0'] = 0
    elif drift == 'attachment': material._material_status()._attachment = lambda now: {'state': 'unknown', 'head': ''}
    elif drift == 'extruder': states['toolhead']['extruder'] = 'extruder'
    elif drift == 'saved_head': objects['save_variables'].values['variables']['current_extruder'] = 0
    elif drift == 'loaded': material._filament_state()._loaded_filament_status = lambda now: {'h2': {'state': 'inserted'}}
    elif drift == 'position': objects['virtual_sdcard'].get_status = lambda now: {'file_position': 0}
    elif drift == 'coordinate': states['gcode_move']['gcode_position'][0] = float('nan')
    elif drift == 'mode': states['gcode_move']['absolute_extrude'] = 1
    elif drift == 'speed': states['gcode_move']['speed'] = 0
    elif drift == 'origin': states['gcode_move']['homing_origin'] = [0., 0.]
    elif drift == 'lookahead': objects['toolhead'].check_busy = lambda now: (100., 98., False)
    elif drift == 'motion_clock': objects['toolhead'].check_busy = lambda now: (float('nan'), 98., True)
    else: objects['virtual_sdcard'].current_file = None
    with pytest.raises(ValueError):
        material._execution_evidence()._recovery_execution_snapshot()
    assert objects['gcode'].scripts == []


def test_execution_publication_waits_without_replacing_pending_snapshot(execution_snapshot_machine):
    import json
    from pathlib import Path
    material, objects, states = execution_snapshot_machine
    assert material._execution_evidence()._queue_recovery_execution() is True
    assert material._execution_evidence()._queue_recovery_execution() is False
    target = Path(material._recovery_execution_path(for_write=True))
    assert material._execution_evidence()._publish_recovery_execution() is False
    assert not target.exists()
    # New parser state must not leak into the older boundary's receipt.
    states['gcode_move']['gcode_position'][0] = 50.
    states['toolhead']['extruder'] = 'extruder1'
    objects['toolhead'].check_busy = lambda now: (105., 100., False)
    assert material._execution_evidence()._publish_recovery_execution() is True
    completed = json.loads(target.read_text())
    assert completed['state'] == 'completed'
    assert completed['head'] == 'h2' and completed['gcode_position'][0] == 1.
    assert completed['scheduled_print_time'] == 100.
    assert completed['completed_print_time'] == 100.
    assert target.stat().st_mode & 0o777 == 0o600
    assert material._execution_evidence()._publish_recovery_execution() is False
    assert objects['gcode'].scripts == []


@pytest.mark.parametrize('drift', [
    'session', 'shutdown', 'owner', 'not_ready', 'paused', 'inactive', 'fault',
    'operation', 'job_bytes', 'context', 'loaded', 'file', 'clock', 'scheduled',
    'invalid_clock', 'rewind'])
def test_execution_publication_discards_changed_pending_evidence(execution_snapshot_machine, drift):
    from pathlib import Path
    material, objects, states = execution_snapshot_machine
    material._execution_evidence()._queue_recovery_execution()
    objects['toolhead'].check_busy = lambda now: (105., 101., True)
    if drift == 'session': material.session_id = 'another-session'
    elif drift == 'shutdown': material.printer.is_shutdown = lambda: True
    elif drift == 'owner': material.printer.owner = object()
    elif drift == 'not_ready': states['webhooks']['state'] = 'shutdown'
    elif drift == 'paused': objects['pause_resume'].values['is_paused'] = True
    elif drift == 'inactive': objects['virtual_sdcard'].active = False
    elif drift == 'fault': objects['save_variables'].values['variables']['fail_flag'] = -3
    elif drift == 'operation': material.toolhead_operation = {'state': 'running'}
    elif drift == 'job_bytes':
        path = Path(material._recovery_job_path())
        path.write_bytes(path.read_bytes() + b'\n')
    elif drift == 'context': objects['save_variables'].values['variables']['wmp_print_context'] = {}
    elif drift == 'loaded': material._filament_state()._loaded_filament_status = lambda now: {'h2': {'state': 'empty'}}
    elif drift == 'file': objects['virtual_sdcard'].current_file = None
    elif drift == 'clock': objects['toolhead'].check_busy = lambda now: (105., 97., True)
    elif drift == 'scheduled': objects['toolhead'].check_busy = lambda now: (99., 101., True)
    elif drift == 'rewind': objects['virtual_sdcard'].get_status = lambda now: {'file_position': 3}
    else: objects['toolhead'].check_busy = lambda now: (105., float('nan'), True)
    with pytest.raises(ValueError):
        material._execution_evidence()._publish_recovery_execution()
    assert material._pending_execution_snapshot is None
    assert not Path(material._recovery_execution_path()).exists()
    assert objects['gcode'].scripts == []


def test_execution_publication_storage_failure_preserves_previous_record(execution_snapshot_machine, monkeypatch):
    from pathlib import Path
    material, objects, states = execution_snapshot_machine
    target = Path(material._recovery_execution_path())
    target.write_bytes(b'previous completed record')
    material._execution_evidence()._queue_recovery_execution()
    objects['toolhead'].check_busy = lambda now: (105., 101., True)
    def fail(source, destination):
        raise OSError('storage unavailable')
    monkeypatch.setattr('wm_material.os.replace', fail)
    with pytest.raises(OSError):
        material._execution_evidence()._publish_recovery_execution()
    assert target.read_bytes() == b'previous completed record'
    assert material._pending_execution_snapshot is None
    assert not list(target.parent.glob('.wmp-recovery-job-*'))


def test_disconnect_discards_pending_execution_snapshot(execution_snapshot_machine):
    material, objects, states = execution_snapshot_machine
    material._execution_evidence()._queue_recovery_execution()
    material._filament_sensors_unavailable()
    assert material._pending_execution_snapshot is None
    assert material._execution_evidence()._publish_recovery_execution() is False


@pytest.mark.parametrize('drift', ['target', 'target_limit', 'bed', 'fan', 'fan_value', 'duration'])
def test_execution_snapshot_requires_coherent_thermal_state(execution_snapshot_machine, drift):
    material, objects, states = execution_snapshot_machine
    if drift == 'target': states['extruder2']['target'] = float('nan')
    elif drift == 'target_limit': states['extruder2']['target'] = 350.
    elif drift == 'bed': del objects['heater_bed']
    elif drift == 'fan': del objects['fan']
    elif drift == 'fan_value': states['fan']['speed'] = 255
    else: states['print_stats']['total_duration'] = -1.
    with pytest.raises(ValueError):
        material._execution_evidence()._recovery_execution_snapshot()
    assert objects['gcode'].scripts == []


def test_execution_publication_preserves_captured_heaters_and_fans(execution_snapshot_machine):
    import json
    from pathlib import Path
    from types import SimpleNamespace
    material, objects, states = execution_snapshot_machine
    objects['fan_generic air_fan'] = SimpleNamespace(get_status=lambda now: {'speed': .2})
    material._execution_evidence()._queue_recovery_execution()
    states['extruder2']['target'] = 0.
    states['fan']['speed'] = 0.
    states['print_stats']['total_duration'] = 600.
    objects['toolhead'].check_busy = lambda now: (105., 101., True)
    assert material._execution_evidence()._publish_recovery_execution()
    result = json.loads(Path(material._recovery_execution_path()).read_text())
    assert result['heater_targets']['extruder2'] == 220.5
    assert result['fans']['fan'] == .75
    assert result['fans']['fan_generic air_fan'] == .2
    assert result['total_duration'] == 541.5


@pytest.fixture
def completed_execution(execution_snapshot_machine):
    material, objects, states = execution_snapshot_machine
    material._execution_evidence()._queue_recovery_execution()
    objects['toolhead'].check_busy = lambda now: (105., 101., True)
    material._execution_evidence()._publish_recovery_execution()
    # Restore may yield for file hashing, unlike synchronous snapshot capture.
    material.printer.pause = lambda when: when
    return material, objects, states


def test_completed_execution_read_survives_restart(completed_execution):
    material, objects, states = completed_execution
    material.session_id = 'restarted-session'
    value = material._read_completed_recovery_execution('part.gcode')
    assert value['head'] == 'h2'
    assert value['session'] != material.session_id
    assert value['heater_targets']['extruder2'] == 220.5
    assert objects['gcode'].scripts == []


@pytest.mark.parametrize('field,value', [
    ('state', 'pending'), ('version', True), ('version', 3), ('session', ''),
    ('print_duration', 600.), ('print_duration', True), ('filament_used', float('inf')),
    ('file_position', 0), ('file_position', True), ('file_position', 12),
    ('gcode_position', [0, 0, 0]), ('homing_origin', [0, 0, 0, 'bad']),
    ('absolute_coordinates', 1), ('absolute_extrude', 'false'),
    ('speed_factor', 0), ('total_duration', -1), ('completed_print_time', 99.),
    ('job_id', 'different-job'), ('job_fingerprint', '0' * 16),
    ('head', 'h1'), ('head', []), ('mapping', [0, 1, 2, 3]),
    ('mapping', [2, True, 2, 3]),
    ('heater_targets', {'heater_bed': 55.}),
    ('fans', {'fan': 255, 'fan_generic auxiliary_fan': .5})])
def test_completed_execution_read_rejects_invalid_evidence(completed_execution, field, value):
    from pathlib import Path
    import json
    material, objects, states = completed_execution
    path = Path(material._recovery_execution_path())
    data = json.loads(path.read_text())
    data[field] = value
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        material._read_completed_recovery_execution('part.gcode')
    assert objects['gcode'].scripts == []


def test_completed_execution_read_rechecks_after_hash_yield(completed_execution):
    from pathlib import Path
    material, objects, states = completed_execution
    path = Path(material._recovery_execution_path())
    def pause(when):
        path.write_bytes(path.read_bytes() + b'\n')
        return when
    material.printer.pause = pause
    with pytest.raises(ValueError, match='changed during'):
        material._read_completed_recovery_execution('part.gcode')


def test_execution_capture_refuses_external_command(execution_snapshot_machine):
    from types import SimpleNamespace
    material, objects, states = execution_snapshot_machine
    objects['gcode'].get_mutex = lambda: SimpleNamespace(test=lambda: True)
    with pytest.raises(ValueError, match='G-code command'):
        material._execution_evidence()._queue_recovery_execution()
    assert getattr(material, '_pending_execution_snapshot', None) is None


def test_execution_sampling_does_not_enumerate_files(execution_snapshot_machine):
    material, objects, states = execution_snapshot_machine
    objects['virtual_sdcard'].get_file_list = lambda *args: pytest.fail('sampling enumerated files')
    assert material._execution_evidence()._queue_recovery_execution()
    objects['toolhead'].check_busy = lambda now: (105., 101., True)
    assert material._execution_evidence()._publish_recovery_execution()


def test_execution_sampler_publishes_once_per_boundary(execution_snapshot_machine, monkeypatch):
    material, objects, states = execution_snapshot_machine
    material._execution_stopped = False
    writes = []
    original = material._write_recovery_json
    def write(path, record):
        writes.append(record)
        original(path, record)
    monkeypatch.setattr(material._recovery_storage(), '_write_recovery_json', write)
    assert material._execution_evidence()._execution_tick(1.) == 2.
    assert material._pending_execution_snapshot is not None
    assert material._execution_evidence()._execution_tick(2.) == 3.
    assert not writes
    objects['toolhead'].check_busy = lambda now: (105., 101., True)
    material._execution_evidence()._execution_tick(3.)
    material._execution_evidence()._execution_tick(4.)
    assert len(writes) == 1
    assert material._pending_execution_snapshot is None


def test_execution_sampler_idle_does_not_read_evidence(execution_snapshot_machine, monkeypatch):
    material, objects, states = execution_snapshot_machine
    material._execution_stopped = False
    objects['virtual_sdcard'].active = False
    monkeypatch.setattr(material._recovery_storage(), '_recovery_read_bytes', lambda *args: pytest.fail('idle evidence read'))
    assert material._execution_evidence()._execution_tick(1.) == 2.


def test_execution_sampler_storage_failure_recovers(execution_snapshot_machine, monkeypatch):
    material, objects, states = execution_snapshot_machine
    material._execution_stopped = False
    material._execution_evidence()._execution_tick(1.)
    objects['toolhead'].check_busy = lambda now: (105., 101., True)
    original = material._write_recovery_json
    def fail(*args):
        raise OSError('storage unavailable')
    monkeypatch.setattr(material._recovery_storage(), '_write_recovery_json', fail)
    assert material._execution_evidence()._execution_tick(2.) == 3.
    assert material._execution_error == 'storage unavailable'
    assert material._pending_execution_snapshot is None
    monkeypatch.setattr(material._recovery_storage(), '_write_recovery_json', original)
    material._execution_evidence()._execution_tick(3.)
    objects['toolhead'].check_busy = lambda now: (106., 106., True)
    material._execution_evidence()._execution_tick(4.)
    assert material._execution_error == ''
    assert material._execution_last_boundary


def test_execution_timer_reuses_handle_and_stops(execution_snapshot_machine):
    material, objects, states = execution_snapshot_machine
    reactor = material.printer.get_reactor()
    registered, updated = [], []
    reactor.NEVER = float('inf')
    def register(callback, when):
        registered.append((callback, when))
        return 'timer-handle'
    reactor.register_timer = register
    reactor.update_timer = lambda handle, when: updated.append((handle, when))
    material._execution_ready()
    material._execution_ready()
    assert len(registered) == 1
    assert updated[0][0] == 'timer-handle'
    material._execution_evidence()._queue_recovery_execution()
    material._execution_stop()
    assert material._pending_execution_snapshot is None
    assert updated[-1] == ('timer-handle', reactor.NEVER)
    assert material._execution_evidence()._execution_tick(1.) == reactor.NEVER


@pytest.fixture
def execution_review_machine(completed_execution):
    from pathlib import Path
    material, objects, states = completed_execution
    objects['wm_material'] = material
    material.printer.state = 'standby'
    states['print_stats']['state'] = 'standby'
    states['toolhead'].update(axis_minimum=[0., 0., 0.], axis_maximum=[300., 300., 300.])
    objects['virtual_sdcard'].active = False
    states['configfile']['settings']['stepper_z'] = {'position_endstop': 300., 'homing_positive_dir': True}
    execution = json.loads(Path(material._recovery_execution_path()).read_text())
    material._write_recovery_json(material._deposition_envelope_path(), {
        'version': 1, 'job_id': execution['job_id'],
        'file_sha256': execution['file']['sha256'], 'max_z': 1.})
    fingerprint = material._recovery_fingerprint(Path(material._recovery_execution_path()).read_bytes())
    return material, objects, states, fingerprint


def test_execution_review_binds_selection_and_current_readiness(execution_review_machine):
    material, objects, states, fingerprint = execution_review_machine
    result = material._recovery_review_service()._recovery_execution_review(material.session_id, 'part.gcode', fingerprint)
    assert result['execution']['head'] == 'h2'
    assert result['execution']['heater_targets']['extruder2'] == 220.5
    assert result['execution_hash'] == fingerprint
    assert objects['gcode'].scripts == []


@pytest.mark.parametrize('drift', ['selection', 'limit', 'fan', 'busy', 'attachment', 'session'])
def test_execution_review_refuses_drift(execution_review_machine, drift):
    material, objects, states, fingerprint = execution_review_machine
    session = material.session_id
    if drift == 'selection':
        fingerprint = '0' * 16
    elif drift == 'limit':
        states['configfile']['settings']['extruder2']['max_temp'] = 210.
    elif drift == 'fan':
        del objects['fan']
    elif drift == 'session':
        session = 'old-session'
    else:
        def change(when):
            if drift == 'busy':
                objects['virtual_sdcard'].active = True
            else:
                material._material_status()._attachment = lambda now: {'state': 'empty'}
            return when
        material.printer.pause = change
    with pytest.raises(ValueError):
        material._recovery_review_service()._recovery_execution_review(session, 'part.gcode', fingerprint)
    assert objects['gcode'].scripts == []


def test_execution_snapshot_preserves_g92_and_mesh_coordinates(execution_snapshot_machine):
    material, objects, states = execution_snapshot_machine
    states['gcode_move']['extrude_factor'] = 1.5
    snapshot = material._execution_evidence()._recovery_execution_snapshot()
    assert snapshot['version'] == 4
    # G92 base differs from homing origin; mesh further transforms machine Z.
    assert snapshot['parser_position'] == [11., 22., .3, 24.]
    assert snapshot['machine_position'] == [11., 22., .45, 24.]
    base = [snapshot['parser_position'][i] - snapshot['gcode_position'][i]
            * (snapshot['extrude_factor'] if i == 3 else 1.) for i in range(4)]
    assert base == pytest.approx([10., 20., .1, 6.])
    assert base != snapshot['homing_origin']


@pytest.mark.parametrize('field', ['parser_position', 'machine_position'])
def test_execution_capture_requires_full_coordinate_evidence(execution_snapshot_machine, field):
    material, objects, states = execution_snapshot_machine
    state = states['gcode_move' if field == 'parser_position' else 'toolhead']
    state['position'] = [0., 0., float('nan'), 0.]
    with pytest.raises(ValueError, match='G-code state'):
        material._execution_evidence()._recovery_execution_snapshot()


@pytest.mark.parametrize('field,value', [('version', 1), ('parser_position', [0., 1.]),
                                         ('machine_position', [0., 0., 'invalid', 0.])])
def test_execution_reader_requires_new_coordinate_schema(completed_execution, field, value):
    from pathlib import Path
    import json
    material, objects, states = completed_execution
    path = Path(material._recovery_execution_path())
    record = json.loads(path.read_text())
    record[field] = value
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        material._read_completed_recovery_execution('part.gcode')


@pytest.mark.parametrize('limits', [None, [0., 0.], [300., 20., 300.], [300., 300., .4],
                                    [300., float('nan'), 300.]])
def test_execution_review_checks_transformed_endpoint(execution_review_machine, limits):
    material, objects, states, fingerprint = execution_review_machine
    states['toolhead']['axis_maximum'] = limits
    with pytest.raises(ValueError, match='travel limits'):
        material._recovery_review_service()._recovery_execution_review(material.session_id, 'part.gcode', fingerprint)
    assert objects['gcode'].scripts == []


def test_recovery_attempt_preserves_history_without_blocking_new_actions(material):
    from pathlib import Path
    material._restore_recovery_attempt()
    assert material._recovery_attempt_status() == {}
    request = dict(id='recover', session=material.session_id, file='part.gcode', execution_hash='a' * 16)
    def interrupted():
        raise RuntimeError('lost acknowledgement')
    with pytest.raises(RuntimeError):
        material._recovery_attempt.run(request, [('prepare', interrupted, lambda: True)])
    assert json.loads(Path(material._recovery_attempt_path()).read_text())['state'] == 'unknown'
    material.session_id = 'new-session'
    material._restore_recovery_attempt()
    assert material._recovery_attempt_status()['request']['session'] == 'test-session'
    assert material._idle_for_filament_settings(1.)
    material.cmd_SET_FILAMENT(profile_command(material))
    material._print_admission(FakeCommand())
    assert not material._recovery_attempt_active()
    visible = material._recovery_attempt_status()
    visible['state'] = 'complete'
    assert material._recovery_lifecycle()._recovery_attempt_unresolved()


def test_recovery_attempt_restore_publishes_unknown_before_admission(material):
    from pathlib import Path
    record = dict(version=1, request=dict(id='recover', session='old', file='part.gcode', execution_hash='a' * 16),
                  state='running', stages=[dict(name='prepare', state='running')], error='')
    Path(material._recovery_attempt_path()).write_text(json.dumps(record))
    material._restore_recovery_attempt()
    assert material._recovery_lifecycle()._recovery_attempt_unresolved()
    assert json.loads(Path(material._recovery_attempt_path()).read_text())['state'] == 'unknown'


def test_corrupt_recovery_attempt_is_diagnostic_without_live_work(material):
    from pathlib import Path
    Path(material._recovery_attempt_path()).write_text('{"version":1,"state":"complete","stages":[]}')
    material._restore_recovery_attempt()
    assert 'journal' in material._recovery_restore_error
    assert material._recovery_lifecycle()._recovery_attempt_unresolved()
    assert material._idle_for_filament_settings(1.)
    material._require_no_recovery_attempt()
    material.cmd_SET_FILAMENT(profile_command(material))


@pytest.fixture
def recovery_reference_machine(execution_review_machine):
    from types import SimpleNamespace
    material, objects, states, fingerprint = execution_review_machine
    review = material._recovery_review_service()._recovery_execution_review(material.session_id, 'part.gcode', fingerprint)
    material._restore_recovery_attempt()
    calls = []
    objects['toolhead'].check_busy = lambda now: (105., 106., True)
    saved_mesh = objects['bed_mesh'].get_mesh()
    states["toolhead"]["axis_maximum"] = [330., 350., 305.]
    states["configfile"]["settings"]["stepper_z"] = {"position_endstop": 300., "homing_positive_dir": True}
    states["toolhead"]["axis_minimum"] = [-20., -10., 0.]
    objects["save_variables"].values["variables"].update(
        {"t%d_position" % i: [i * 75., 330.] for i in range(4)})
    objects['gcode'].get_mutex = lambda: SimpleNamespace(test=lambda: True)
    # Exercise the actual vendor loader/reset/seek during the final private stage.
    import importlib.util
    from pathlib import Path
    from types import MethodType
    source = Path(__file__).resolve().parents[1] / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras/virtual_sdcard.py'
    spec = importlib.util.spec_from_file_location('recovery_chain_sd', source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    sd = objects['virtual_sdcard']
    sd.work_timer = None
    sd.cmd_from_sd = False
    sd.printer = SimpleNamespace(send_event=lambda event: None)
    sd.gcode = objects['gcode']
    sd.print_stats = SimpleNamespace(reset=lambda: states['print_stats'].update(state='standby'),
        set_current_file=lambda name: states['print_stats'].update(filename=name))
    for name in ('_reset_file', '_load_file', 'cmd_M26', 'do_pause', 'get_file_list'):
        setattr(sd, name, MethodType(getattr(module.VirtualSD, name), sd))
    objects['gcode'].create_gcode_command = lambda name, line, args: SimpleNamespace(
        error=lambda message: ValueError(message), respond_raw=lambda message: None,
        get_int=lambda key, **kwargs: int(args[key]))
    parser = [None]
    def parser_command(script):
        if parser[0] is None:
            import importlib.util
            from pathlib import Path
            source = Path(__file__).resolve().parents[1] / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras/gcode_move.py'
            spec = importlib.util.spec_from_file_location('recovery_stage_parser', source)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            p = parser[0] = module.GCodeMove.__new__(module.GCodeMove)
            current = states['gcode_move']
            p.last_position = list(current['position'])
            p.homing_position = list(current['homing_origin'])
            p.speed_factor = current['speed_factor'] / 60.
            p.speed = current['speed'] * p.speed_factor
            p.extrude_factor = current['extrude_factor']
            p.base_position = [p.last_position[i] - current['gcode_position'][i] *
                               (p.extrude_factor if i == 3 else 1.) for i in range(4)]
            p.absolute_coord, p.absolute_extrude = current['absolute_coordinates'], current['absolute_extrude']
            p.Coord = lambda *v: list(v)
            p.printer = SimpleNamespace(quick_stop_flag=False)
            def unchanged(position, speed):
                assert position == states['gcode_move']['position']
            p.move_with_transform = unchanged
        name, *parts = script.split()
        args = dict(token.split('=', 1) if '=' in token else (token[0], token[1:]) for token in parts)
        command = SimpleNamespace(
            get_float=lambda key, default=None, **kwargs: float(args[key]) if key in args else default,
            get_int=lambda key, default=None: int(args[key]) if key in args else default,
            get_command_parameters=lambda: args, error=lambda message: ValueError(message))
        getattr(parser[0], 'cmd_' + name)(command)
        states['gcode_move'] = parser[0].get_status(1.)
    def dispatch(script):
        calls.append(script)
        if any(stage['name'] == 'restore_parser' and stage['state'] == 'running'
               for stage in (material._recovery_attempt.record or {}).get('stages', [])) and not script.startswith('SET_HEATER_TEMPERATURE'):
            parser_command(script)
            return
        if script == '_WMP_RECOVERY_BEGIN':
            states['gcode_macro _WMP_RECOVERY_BEGIN']['active'] = True
            states['gcode_macro START_PRINT']['print_body_ready'] = False
            objects['save_variables'].values['variables']['probe_tool'] = 1
        elif script == '_WMP_HOME_Z_BOTTOM':
            states['wmp_recovery']['z_reference_valid'] = True
            states['toolhead']['homed_axes'] = 'z'
            states['toolhead']['position'][2] = 300.
        elif script == 'G28 X Y\nM400':
            states['toolhead']['homed_axes'] = 'xyz'
        elif script == 'BED_MESH_CLEAR':
            objects['bed_mesh'].get_mesh = lambda: None
            states['gcode_move']['position'] = list(states['toolhead']['position'])
        elif script == 'G90':
            states['gcode_move']['absolute_coordinates'] = True
        elif script == 'M220 S100':
            states['gcode_move']['speed_factor'] = 1.
        elif script == 'M221 S100':
            states['gcode_move']['extrude_factor'] = 1.
        elif script == 'M83':
            states['gcode_move']['absolute_extrude'] = False
        elif script.startswith('G1 Z'):
            states['toolhead']['position'][2] = float(script.split()[1][1:])
            states['gcode_move']['position'] = list(states['toolhead']['position'])
            states['gcode_move']['gcode_position'] = list(states['toolhead']['position'])
        elif script.startswith('G1 E'):
            amount = float(script.split()[1][1:])
            states['toolhead']['position'][3] += amount
            states['gcode_move']['position'][3] += amount
        elif script == 'SET_GCODE_OFFSET X=0 Y=0 Z=0 MOVE=0':
            states['gcode_move']['homing_origin'] = [0., 0., 0., 0.]
        elif script.startswith('G1 X') and script.endswith('\nM400'):
            xy = [float(token[1:]) for token in script.splitlines()[0].split()[1:3]]
            states['toolhead']['position'][:2] = xy
            states['gcode_move']['position'] = list(states['toolhead']['position'])
            states['gcode_move']['gcode_position'] = list(states['toolhead']['position'])
        elif script.startswith('G92 X'):
            values = [float(token[1:]) for token in script.split()[1:]]
            states['gcode_move']['gcode_position'][:3] = values
        elif script == 'BED_MESH_PROFILE_BASE LOAD=wmp_print':
            objects['bed_mesh'].get_mesh = lambda: saved_mesh
            states['gcode_move']['position'] = list(states['toolhead']['position'])
            states['gcode_move']['position'][2] -= .15
            states['gcode_move']['gcode_position'][2] -= .15
        elif script.startswith('BED_MESH_OFFSET '):
            params = dict(token.split('=') for token in script.split()[1:])
            objects['bed_mesh'].tool_offset = float(params['ZFADE'])
        elif script == 'G90\nSET_GCODE_OFFSET X=0 Y=0 Z=0 MOVE=0':
            pass
        elif script.startswith('ACTIVATE_EXTRUDER EXTRUDER=extruder2'):
            states['toolhead']['extruder'] = 'extruder2'
            objects['save_variables'].values['variables']['current_extruder'] = 2
        elif script.startswith('SET_HEATER_TEMPERATURE '):
            params = dict(token.split('=') for token in script.split()[1:])
            states[params['HEATER']]['target'] = float(params['TARGET'])
        elif script.startswith('M99106 S'):
            states['fan']['speed'] = float(script.split('S')[1]) / 255.
        elif script.startswith('SET_FAN_SPEED '):
            params = dict(token.split('=') for token in script.split()[1:])
            states['fan_generic ' + params['FAN']]['speed'] = float(params['SPEED'])
        else:
            pytest.fail('unexpected recovery script: ' + script)
    objects['gcode'].run_script_from_command = dispatch
    clock = [1.]
    material.printer.monotonic = lambda: clock[0]
    def warm(when):
        clock[0] = when
        for name in ('extruder2', 'heater_bed'):
            states[name]['temperature'] = states[name]['target']
            states[name]['can_extrude'] = states[name]['target'] > 0
        return when
    material.printer.pause = warm
    request = dict(id='recover', session=material.session_id, file='part.gcode', execution_hash=fingerprint)
    return material, objects, states, calls, review, request


def test_recovery_reference_stages_use_bottom_z_then_xy(recovery_reference_machine):
    material, objects, states, calls, review, request = recovery_reference_machine
    stages = material._recovery_initial_stages(review)
    result = material._recovery_attempt.run(request, stages)
    assert calls[:3] == ['_WMP_RECOVERY_BEGIN', '_WMP_HOME_Z_BOTTOM', 'G28 X Y\nM400']
    assert calls[3:8] == ['BED_MESH_CLEAR', 'G90', 'M220 S100',
                          'SET_GCODE_OFFSET X=0 Y=0 Z=0 MOVE=0', 'G92 X11 Y22 Z300']
    assert calls[8:10] == ['G90\nSET_GCODE_OFFSET X=0 Y=0 Z=0 MOVE=0',
                          'ACTIVATE_EXTRUDER EXTRUDER=extruder2\nSAVE_VARIABLE VARIABLE=current_extruder VALUE=2']
    assert calls[10] == 'BED_MESH_PROFILE_BASE LOAD=wmp_print'
    assert calls[11] == 'BED_MESH_OFFSET X=0 Y=0 ZFADE=0'
    assert calls[12:16] == ['SET_HEATER_TEMPERATURE HEATER=extruder2 TARGET=220.5',
                         'SET_HEATER_TEMPERATURE HEATER=heater_bed TARGET=55',
                         'M99106 S191.25', 'SET_FAN_SPEED FAN=auxiliary_fan SPEED=0.5']
    assert result['state'] == 'complete'
    assert all(stage['state'] == 'complete' for stage in result['stages'])


def use_native_toolhead_coordinates(objects):
    from collections import namedtuple
    coord = namedtuple("Coord", "x y z e")
    original = objects["toolhead"].get_status
    def native_status(eventtime):
        result = dict(original(eventtime))
        result["position"] = coord(*result["position"])
        return result
    objects["toolhead"].get_status = native_status


def test_recovery_preparation_accepts_native_toolhead_coordinates(recovery_reference_machine):
    material, objects, states, calls, review, request = recovery_reference_machine
    use_native_toolhead_coordinates(objects)
    result = material._recovery_attempt.run(request, material._recovery_initial_stages(review))
    assert result["state"] == "complete", result
    assert all(stage["state"] == "complete" for stage in result["stages"])


def test_recovery_preparation_accepts_native_tuple_calibration(recovery_reference_machine):
    material, objects, states, calls, review, request = recovery_reference_machine
    use_native_tuple_offsets(objects)
    result = material._recovery_attempt.run(request, material._recovery_initial_stages(review))
    assert result['state'] == 'complete'
    assert all(stage['state'] == 'complete' for stage in result['stages'])
    assert calls[:3] == ['_WMP_RECOVERY_BEGIN', '_WMP_HOME_Z_BOTTOM', 'G28 X Y\nM400']


@pytest.mark.parametrize('failure', ['context', 'bottom_z', 'home_xy', 'attachment', 'fault', 'owner', 'session', 'loaded', 'service'])
def test_recovery_reference_failure_stops_later_motion(recovery_reference_machine, failure):
    material, objects, states, calls, review, request = recovery_reference_machine
    stages = material._recovery_initial_stages(review)
    original = objects['gcode'].run_script_from_command
    def dispatch(script):
        if failure == 'context' and script == '_WMP_RECOVERY_BEGIN':
            calls.append(script)
            return
        if failure == 'bottom_z' and script == '_WMP_HOME_Z_BOTTOM':
            calls.append(script)
            return
        if failure == 'home_xy' and script.startswith('G28'):
            calls.append(script)
            return
        original(script)
        if script == '_WMP_RECOVERY_BEGIN':
            if failure == 'attachment':
                material._material_status()._attachment = lambda now: {'state': 'empty'}
            elif failure == 'fault':
                objects['save_variables'].values['variables']['fail_flag'] = -3
            elif failure == 'owner':
                objects['AFC'] = object()
            elif failure == 'session':
                material.session_id = 'restarted'
            elif failure == 'loaded':
                material._filament_state()._loaded_filament_status = lambda now: {}
            elif failure == 'service':
                material.filament_operation = {'state': 'running'}
    objects['gcode'].run_script_from_command = dispatch
    with pytest.raises(ValueError):
        material._recovery_attempt.run(request, stages)
    assert material._recovery_attempt.record['state'] == 'unknown'
    expected = 3 if failure == 'home_xy' else 2 if failure == 'bottom_z' else 1
    assert len(calls) == expected


@pytest.mark.parametrize('ignored', ['SET_HEATER_TEMPERATURE', 'M99106', 'SET_FAN_SPEED'])
def test_recovery_initial_stages_require_target_readback(recovery_reference_machine, ignored):
    material, objects, states, calls, review, request = recovery_reference_machine
    stages = material._recovery_initial_stages(review)
    states['extruder2']['target'] = 0.
    states['heater_bed']['target'] = 0.
    states['fan']['speed'] = states['fan_generic auxiliary_fan']['speed'] = 0.
    original = objects['gcode'].run_script_from_command
    def dispatch(script):
        if script.startswith(ignored):
            calls.append(script)
        else:
            original(script)
    objects['gcode'].run_script_from_command = dispatch
    with pytest.raises(ValueError, match='not confirmed'):
        material._recovery_attempt.run(request, stages)
    assert material._recovery_attempt.record['state'] == 'unknown'
    if ignored == 'SET_HEATER_TEMPERATURE':
        assert not any(call.startswith('M99106') for call in calls)


def test_recovery_target_acceptance_does_not_claim_temperature_ready(recovery_reference_machine):
    material, objects, states, calls, review, request = recovery_reference_machine
    stages = material._recovery_initial_stages(review)
    material._recovery_attempt.run(request, stages[:next(i for i, stage in enumerate(stages) if stage[0] == 'heating')])
    assert states['extruder2']['temperature'] == 25.
    assert states['extruder2']['target'] == 220.5
    assert not any(call.startswith(('M104', 'M109', 'M24')) for call in calls)


def test_recovery_fault_between_heaters_prevents_remaining_targets(recovery_reference_machine):
    material, objects, states, calls, review, request = recovery_reference_machine
    stages = material._recovery_initial_stages(review)
    original = objects['gcode'].run_script_from_command
    def dispatch(script):
        original(script)
        if script.startswith('SET_HEATER_TEMPERATURE HEATER=extruder2'):
            objects['save_variables'].values['variables']['fail_flag'] = -3
    objects['gcode'].run_script_from_command = dispatch
    with pytest.raises(ValueError, match='fault state'):
        material._recovery_attempt.run(request, stages)
    assert not any('HEATER=heater_bed' in call or call.startswith('M99106') for call in calls)
    assert material._recovery_attempt.record['state'] == 'unknown'


def test_recovery_wait_requires_stable_temperatures_and_reports_progress(recovery_reference_machine):
    material, objects, states, calls, review, request = recovery_reference_machine
    material._recovery_attempt.run(request, material._recovery_initial_stages(review))
    assert material.printer.monotonic() >= 3.5
    assert material._recovery_temperatures['extruder2'] == {'temperature': 220.5, 'target': 220.5}
    assert {'name': 'heating', 'state': 'complete'} in material._recovery_attempt.record['stages']


@pytest.mark.parametrize('failure', ['cancel', 'target', 'sensor', 'fault', 'clock'])
def test_recovery_wait_stops_on_changed_state(recovery_reference_machine, failure):
    material, objects, states, calls, review, request = recovery_reference_machine
    cancelled = [False]
    warm = material.printer.pause
    def pause(when):
        warm(when)
        if failure == 'cancel':
            cancelled[0] = True
        elif failure == 'target':
            states['extruder2']['target'] = 210.
        elif failure == 'sensor':
            states['extruder2']['temperature'] = float('nan')
        elif failure == 'fault':
            objects['save_variables'].values['variables']['fail_flag'] = -3
        else:
            material.printer.monotonic = lambda: -1.
        return when
    material.printer.pause = pause
    stages = material._recovery_initial_stages(review, cancelled=lambda: cancelled[0])
    stages.append(('must_not_run', lambda: calls.append('unsafe continuation'), lambda: True))
    with pytest.raises(ValueError):
        material._recovery_attempt.run(request, stages)
    assert material._recovery_attempt.record['state'] == 'unknown'
    assert 'unsafe continuation' not in calls


def test_recovery_wait_timeout_does_not_submit_commands(recovery_reference_machine):
    material, objects, states, calls, review, request = recovery_reference_machine
    clock = [1.]
    material.printer.monotonic = lambda: clock[0]
    material.printer.pause = lambda when: clock.__setitem__(0, when)
    with pytest.raises(ValueError, match='timeout'):
        material._recovery_motion()._wait_recovery_temperatures(review['execution'], lambda: None, lambda: False, timeout=1.)
    assert clock[0] == 2.
    assert calls == []


def test_recovery_wait_restarts_stability_after_temperature_excursion(recovery_reference_machine):
    material, objects, states, calls, review, request = recovery_reference_machine
    warm = material.printer.pause
    def pause(when):
        warm(when)
        if when == 2.5:
            states['extruder2']['temperature'] = 210.
        return when
    material.printer.pause = pause
    material._recovery_motion()._wait_recovery_temperatures(review['execution'], lambda: None, lambda: False)
    assert material.printer.monotonic() == 5.
    assert calls == []


@pytest.mark.parametrize('failure', ['cancel', 'fault', 'heater_off', 'journal'])
def test_recovery_failure_cleans_heaters_without_resolving_outcome(recovery_reference_machine, failure):
    material, objects, states, calls, review, request = recovery_reference_machine
    stopped = [False]
    warm = material.printer.pause
    def pause(when):
        warm(when)
        stopped[0] = True
        if failure == 'fault':
            objects['save_variables'].values['variables']['fail_flag'] = -3
        return when
    material.printer.pause = pause
    original = objects['gcode'].run_script_from_command
    def dispatch(script):
        if failure == 'heater_off' and script == 'SET_HEATER_TEMPERATURE HEATER=extruder2 TARGET=0':
            calls.append(script)
            raise RuntimeError('heater off reply lost')
        original(script)
    objects['gcode'].run_script_from_command = dispatch
    persist = material._recovery_attempt.persist
    def write(record):
        if failure == 'journal' and 'cleanup' in record:
            raise OSError('cleanup receipt disk failed')
        persist(record)
    material._recovery_attempt.persist = write
    cancelled = lambda: stopped[0] and failure != 'fault'
    stages = material._recovery_initial_stages(review, cancelled)
    with pytest.raises(ValueError, match='stopped|fault state'):
        material._run_recovery_stages(request, review, stages, cancelled)
    assert states['heater_bed']['target'] == 0.
    assert material._recovery_lifecycle()._recovery_attempt_unresolved()
    receipt = material._recovery_attempt_status()
    assert receipt['state'] == 'unknown'
    assert receipt['cleanup']['state'] == ('unknown' if failure == 'heater_off' else 'complete')
    if failure != 'heater_off':
        assert states['extruder2']['target'] == 0.
    assert all(call.startswith('SET_HEATER_TEMPERATURE') for call in calls[-2:])
    if failure != 'journal':
        material._restore_recovery_attempt()
        assert material._recovery_lifecycle()._recovery_attempt_unresolved()


def test_recovery_cancel_before_heating_does_not_change_manual_targets(recovery_reference_machine):
    material, objects, states, calls, review, request = recovery_reference_machine
    result = material._run_recovery_stages(request, review, material._recovery_initial_stages(review), lambda: True)
    assert result['state'] == 'stopped'
    assert result['cleanup'] == {'state': 'complete', 'heaters': {}, 'error': ''}
    assert states['extruder2']['target'] == 220.5
    assert calls == []
    assert material._recovery_lifecycle()._recovery_attempt_unresolved()


def test_recovery_cleanup_does_not_command_a_new_owner(recovery_reference_machine):
    material, objects, states, calls, review, request = recovery_reference_machine
    objects['AFC'] = object()
    result = material._recovery_lifecycle()._stop_recovery_heaters(review)
    assert result['state'] == 'unknown'
    assert not any(result['heaters'].values())
    assert calls == []


@pytest.fixture
def recovery_abandon_machine(recovery_reference_machine):
    material, objects, states, calls, review, request = recovery_reference_machine
    material._recovery_attempt.run(request, material._recovery_initial_stages(review), lambda: True)
    states['extruder2']['target'] = states['heater_bed']['target'] = 0.
    states['gcode_macro _WMP_RECOVERY_BEGIN']['active'] = True
    objects['toolhead'].check_busy = lambda now: (105., 106., True)
    def dispatch(script):
        calls.append(script)
        if script == 'M400':
            pass
        elif script == 'SDCARD_RESET_FILE':
            if objects['virtual_sdcard'].current_file is not None:
                objects['virtual_sdcard'].current_file.close()
            objects['virtual_sdcard'].current_file = None
        elif 'MACRO=_WMP_RECOVERY_BEGIN' in script:
            states['gcode_macro _WMP_RECOVERY_BEGIN']['active'] = False
        elif 'MACRO=START_PRINT' in script:
            states['gcode_macro START_PRINT']['print_body_ready'] = False
        elif script.startswith('SAVE_VARIABLE VARIABLE=wmp_print_context'):
            objects['save_variables'].values['variables']['wmp_print_context'] = {}
        else:
            pytest.fail('unexpected abandonment command: ' + script)
    objects['gcode'].run_script_from_command = dispatch
    return material, objects, states, calls, review, request


def test_recovery_abandon_invalidates_job_without_motion(recovery_abandon_machine):
    material, objects, states, calls, review, request = recovery_abandon_machine
    loaded = material._loaded_filament_status(1.)
    result = material._abandon_recovery_attempt(material.session_id, request['id'])
    assert result['state'] == 'abandoned'
    assert result['resolution']['attachment'] == {'state': 'unknown', 'head': ''}
    assert material._read_recovery_job()['reason'] == 'recovery-abandoned'
    assert calls[0:1] == ['SDCARD_RESET_FILE']
    assert not any(call.startswith(('G0', 'G1', 'G28', 'M104', 'M109')) for call in calls)
    assert material._loaded_filament_status(1.) == loaded
    material._restore_recovery_attempt()
    assert not material._recovery_lifecycle()._recovery_attempt_unresolved()
    assert material._recovery_attempt.record['state'] == 'abandoned'
    # Abandoning an owned attempt does not retire raw checkpoints.
    # Do not invent a receipt for that separate confirmation flow.
    assert material._recovery_retirement_result == {}
    assert material._recovery_retirement_store().retirement() is None


def test_recovery_abandon_clears_only_matching_stock_offer(recovery_abandon_machine, tmp_path):
    from types import SimpleNamespace
    material, objects, states, calls, review, request = recovery_abandon_machine
    directory = Path(material.recovery_checkpoint_dir)
    offer = directory / 'plr.ini'
    original = ('[plr_print]\nwas_interrupted=True\nplr_file=' + request['file'] + '\n').encode()
    offer.write_bytes(original)
    checkpoint = directory / 'plr_dataA.ini'
    checkpoint.write_bytes(b'original checkpoint')
    mutex = objects['gcode'].get_mutex
    objects['gcode'].get_mutex = lambda: SimpleNamespace(test=lambda: False)
    assert material._abandon_recovery_attempt(material.session_id, request['id'], review_only=True)['state'] != 'abandoned'
    objects['gcode'].get_mutex = mutex
    assert offer.read_bytes() == original
    result = material._abandon_recovery_attempt(material.session_id, request['id'])
    assert result['state'] == 'abandoned'
    assert offer.read_bytes() == original.replace(b'=True', b'=False')
    assert checkpoint.read_bytes() == b'original checkpoint'
    archived = material._read_archived_recovery_evidence(material._read_recovery_job()['archive'])
    assert archived['offer'] == original


def test_recovery_abandon_offer_write_failure_retains_retry(recovery_abandon_machine, tmp_path):
    material, objects, states, calls, review, request = recovery_abandon_machine
    directory = Path(material.recovery_checkpoint_dir)
    offer = directory / 'plr.ini'
    original = ('[plr_print]\nwas_interrupted=True\nplr_file=' + request['file'] + '\n').encode()
    offer.write_bytes(original)
    clear = material._clear_recovery_offer
    def fail(*args):
        raise OSError('offer write unavailable')
    material._recovery_storage()._clear_recovery_offer = fail
    with pytest.raises(OSError):
        material._abandon_recovery_attempt(material.session_id, request['id'])
    assert material._recovery_attempt.record['state'] == 'unknown'
    assert offer.read_bytes() == original
    archived = material._read_recovery_job()['archive']
    assert material._read_archived_recovery_evidence(archived)['offer'] == original
    material._recovery_storage()._clear_recovery_offer = clear
    assert material._abandon_recovery_attempt(material.session_id, request['id'])['state'] == 'abandoned'
    assert offer.read_bytes() == original.replace(b'=True', b'=False')
    assert material._read_recovery_job()['archive'] == archived


@pytest.mark.parametrize('contents', [
    '[plr_print]\nwas_interrupted=True\nplr_file=another.gcode\n',
    '[plr_print]\nwas_interrupted=maybe\nplr_file=another.gcode\n',
    '[plr_print]\nwas_interrupted=True\nwas_interrupted=False\nplr_file=another.gcode\n',
])
def test_recovery_abandon_preserves_conflicting_stock_offer(recovery_abandon_machine, tmp_path, contents):
    material, objects, states, calls, review, request = recovery_abandon_machine
    directory = Path(material.recovery_checkpoint_dir)
    offer = directory / 'plr.ini'
    offer.write_text(contents)
    before = material._recovery_read_bytes(material._recovery_job_path(), 65536)
    calls.clear()
    with pytest.raises(Exception):
        material._abandon_recovery_attempt(material.session_id, request['id'])
    assert calls == []
    assert offer.read_text() == contents
    assert material._recovery_read_bytes(material._recovery_job_path(), 65536) == before


@pytest.mark.parametrize('drift', ['fault', 'heater', 'attachment', 'motion', 'session', 'id', 'job'])
def test_recovery_abandon_refuses_unresolved_state(recovery_abandon_machine, drift):
    material, objects, states, calls, review, request = recovery_abandon_machine
    session, request_id = material.session_id, request['id']
    if drift == 'fault':
        objects['save_variables'].values['variables']['fail_flag'] = -3
    elif drift == 'heater':
        states['extruder2']['target'] = 220.
    elif drift == 'attachment':
        material._material_status()._attachment = lambda now: {'state': 'unknown'}
    elif drift == 'motion':
        objects['toolhead'].check_busy = lambda now: (105., 100., True)
    elif drift == 'session':
        session = 'old'
    elif drift == 'id':
        request_id = 'another'
    else:
        material._write_recovery_job({'version': 1, 'state': 'committed', 'id': 'another'})
    if drift in ('fault', 'heater', 'attachment', 'motion'):
        result = material._abandon_recovery_attempt(session, request_id)
        assert result['state'] == 'abandoned'
        assert not material._recovery_attempt_active()
        assert 'M400' not in calls
    else:
        with pytest.raises(ValueError):
            material._abandon_recovery_attempt(session, request_id)
        assert calls == []
        assert material._recovery_lifecycle()._recovery_attempt_unresolved()


def test_recovery_abandon_partial_failure_retains_hold(recovery_abandon_machine):
    material, objects, states, calls, review, request = recovery_abandon_machine
    dispatch = objects['gcode'].run_script_from_command
    objects['gcode'].run_script_from_command = lambda script: None if 'MACRO=_WMP_RECOVERY_BEGIN' in script else dispatch(script)
    with pytest.raises(ValueError, match='not confirmed'):
        material._abandon_recovery_attempt(material.session_id, request['id'])
    assert material._recovery_lifecycle()._recovery_attempt_unresolved()
    assert material._read_recovery_job()['state'] == 'invalidated'
    # A fresh explicit retry reconciles only this same abandonment, not PLR motion.
    objects['gcode'].run_script_from_command = dispatch
    result = material._abandon_recovery_attempt(material.session_id, request['id'])
    assert result['state'] == 'abandoned'


def test_recovery_abandon_preserves_another_selected_file(recovery_abandon_machine, tmp_path):
    material, objects, states, calls, review, request = recovery_abandon_machine
    other = tmp_path / 'other.gcode'
    other.write_text('G1 X1\n')
    with other.open() as stream:
        objects['virtual_sdcard'].current_file.close()
        objects['virtual_sdcard'].current_file = stream
        with pytest.raises(ValueError, match='Another file'):
            material._abandon_recovery_attempt(material.session_id, request['id'])
        assert not stream.closed
    assert calls == []
    assert material._recovery_lifecycle()._recovery_attempt_unresolved()


@pytest.fixture
def recovery_head_machine(service_material):
    from types import SimpleNamespace
    material, objects, states = service_material
    states['toolhead']['position'][2] = 300.
    settings = objects['configfile'].get_status(1.)['settings']
    settings['stepper_z'] = {'position_endstop': 300., 'homing_positive_dir': True}
    objects['configfile'].get_status = lambda now: {'settings': settings}
    states['wmp_recovery']['homing'] = False
    saved = states['save_variables']['variables']
    saved.update(fail_flag=0, is_nozzle_setting=0, current_extruder=1)
    states['toolhead']['extruder'] = 'extruder1'
    for name, state in {
        'custom_hall': {'Raw': 4000},
        'filament_switch_sensor sensor_b': {'filament_detected': True},
        **{'filament_switch_sensor docked%d' % i: {'filament_detected': i != 1} for i in range(4)},
    }.items():
        states[name] = state
        objects[name] = SimpleNamespace(get_status=lambda now, state=state: state)
    material._material_status()._attachment = lambda now: type(material)._attachment(material, now)
    calls = []
    def dispatch(script):
        calls.append(script)
        if script.startswith('_UNLOCK_TOOL '):
            states['filament_switch_sensor docked1']['filament_detected'] = True
            states['custom_hall']['Raw'] = 4900
            states['filament_switch_sensor sensor_b']['filament_detected'] = False
            saved['current_extruder'] = 99
        elif script.startswith('_LOCK_TOOL '):
            states['custom_hall']['Raw'] = 4000
            states['filament_switch_sensor sensor_b']['filament_detected'] = True
            states['filament_switch_sensor docked2']['filament_detected'] = False
        elif script.startswith('ACTIVATE_EXTRUDER'):
            states['toolhead']['extruder'] = 'extruder2'
            saved['current_extruder'] = 2
    objects['gcode'] = SimpleNamespace(run_script_from_command=dispatch,
                                      get_mutex=lambda: SimpleNamespace(test=lambda: True))
    material._recovery_motion()._recovery_actuator_stroke = lambda lock, guard: objects['gcode'].run_script_from_command(
        'ECHELON_STEPPER_HOMING STEPPER=trans_stepper PDI=%d\n' % (-125 if lock else 0))
    context = {'positions': [saved['t%d_position' % i] for i in range(4)],
               'attachment': material._attachment(1)}
    return material, objects, states, calls, context


def test_recovery_selects_verified_physical_head_without_stock_retry(recovery_head_machine):
    material, objects, states, calls, context = recovery_head_machine
    assert material._recovery_motion()._recovery_select_head(2, context, lambda: None)
    assert material._attachment(1) == {'state': 'attached', 'head': 'h2'}
    assert calls.count('_UNLOCK_TOOL T=1 SERVICE=1') == 1
    assert calls.count('_LOCK_TOOL T=2 SERVICE=1 RECOVERY=1') == 1
    assert not any(cmd.startswith('_CHECK_CHANGE_TOOL ') for cmd in calls)
    assert not any(line.startswith(('LOCK', 'UNLOCK', '_CHANGE_TOOL', 'G28', 'G1 Z'))
                   for cmd in calls for line in cmd.splitlines())
    assert not any('VARIABLE=fail_flag' in cmd for cmd in calls)
    assert calls[-1].startswith('ACTIVATE_EXTRUDER EXTRUDER=extruder2')


@pytest.mark.parametrize('failure', ['bottom', 'axes', 'calibration', 'fault', 'attachment'])
def test_recovery_head_preconditions_prevent_commands(recovery_head_machine, failure):
    material, objects, states, calls, context = recovery_head_machine
    if failure == 'bottom': states['toolhead']['position'][2] = 349
    elif failure == 'axes': states['toolhead']['homed_axes'] = 'xy'
    elif failure == 'calibration': context['positions'][2] = [999, 330]
    elif failure == 'fault': states['save_variables']['variables']['fail_flag'] = -3
    else: states['custom_hall']['Raw'] = 4900
    with pytest.raises(ValueError):
        material._recovery_motion()._recovery_select_head(2, context, lambda: None)
    assert calls == []


@pytest.mark.parametrize('failure', ['dock', 'mount', 'activation'])
def test_recovery_head_failure_does_not_continue_or_retry(recovery_head_machine, failure):
    material, objects, states, calls, context = recovery_head_machine
    original = objects['gcode'].run_script_from_command
    def dispatch(script):
        if ((failure == 'dock' and script.startswith('_UNLOCK_TOOL ')) or
                (failure == 'mount' and script.startswith('_LOCK_TOOL '))):
            calls.append(script)
            raise ValueError('shared dock/mount verification failed')
        original(script)
        if failure == 'activation' and script.startswith('ACTIVATE_EXTRUDER'):
            states['toolhead']['extruder'] = 'extruder1'
    objects['gcode'].run_script_from_command = dispatch
    with pytest.raises(ValueError):
        material._recovery_motion()._recovery_select_head(2, context, lambda: None)
    expected = {'dock': '_UNLOCK_TOOL', 'mount': '_LOCK_TOOL', 'activation': 'ACTIVATE_EXTRUDER'}[failure]
    assert calls[-1].startswith(expected)
    assert sum(cmd.startswith('_UNLOCK_TOOL ') for cmd in calls) <= 1
    assert sum(cmd.startswith('_LOCK_TOOL ') for cmd in calls) <= 1


@pytest.mark.parametrize('initial', ['same', 'empty'])
def test_recovery_head_selection_same_or_empty_carriage(recovery_head_machine, initial):
    material, objects, states, calls, context = recovery_head_machine
    states['filament_switch_sensor docked1']['filament_detected'] = True
    if initial == 'same':
        states['filament_switch_sensor docked2']['filament_detected'] = False
    else:
        states['custom_hall']['Raw'] = 4900
        states['filament_switch_sensor sensor_b']['filament_detected'] = False
    context['attachment'] = material._attachment(1)
    assert material._recovery_motion()._recovery_select_head(2, context, lambda: None)
    assert not any(cmd.startswith('_UNLOCK_TOOL ') for cmd in calls)
    assert sum(cmd.startswith('_LOCK_TOOL ') for cmd in calls) == (initial == 'empty')
    if initial == 'same':
        assert not any('G1 ' in cmd for cmd in calls)


def test_recovery_fault_while_docking_prevents_unlock(recovery_head_machine):
    material, objects, states, calls, context = recovery_head_machine
    original = objects['gcode'].run_script_from_command
    def dispatch(script):
        original(script)
        if script.startswith('_UNLOCK_TOOL '):
            states['save_variables']['variables']['fail_flag'] = -3
    objects['gcode'].run_script_from_command = dispatch
    with pytest.raises(ValueError, match='fault state changed'):
        material._recovery_motion()._recovery_select_head(2, context, lambda: None)
    assert not any('ECHELON' in cmd for cmd in calls)
    assert states['save_variables']['variables']['fail_flag'] == -3


def test_recovery_runner_reconciles_intended_head_change_before_heating(recovery_reference_machine):
    material, objects, states, calls, review, request = recovery_reference_machine
    attachment = {'state': 'attached', 'head': 'h1'}
    material._material_status()._attachment = lambda now: dict(attachment)
    review['machine']['attachment'] = dict(attachment)
    def select(head, context, guard):
        receipt = material._recovery_attempt.record
        assert receipt['state'] == 'running'
        assert {'name': 'select_head', 'state': 'running'} in receipt['stages']
        assert head == 2 and context['attachment'] == attachment
        assert not any(cmd.startswith('SET_HEATER') for cmd in calls)
        guard()
        attachment.update(state='empty', head='')
        guard()  # Allowed only inside the explicitly owned selection sequence.
        attachment.update(state='attached', head='h2')
        states['toolhead']['extruder'] = 'extruder2'
        objects['save_variables'].values['variables']['current_extruder'] = 2
        guard()
        return True
    material._recovery_motion()._recovery_select_head = select
    material._run_recovery_stages(request, review, material._recovery_initial_stages(review))
    assert material._recovery_attempt.record['state'] == 'complete'
    assert any(cmd.startswith('SET_HEATER') for cmd in calls)


@pytest.mark.parametrize('failure', ['cancel', 'fault', 'unconfirmed', 'exception'])
def test_recovery_selection_failure_blocks_heating_and_retains_attempt(recovery_reference_machine, failure):
    material, objects, states, calls, review, request = recovery_reference_machine
    cancelled = [False]
    def select(head, context, guard):
        if failure == 'cancel': cancelled[0] = True
        elif failure == 'fault': objects['save_variables'].values['variables']['fail_flag'] = -3
        elif failure == 'unconfirmed':
            material._material_status()._attachment = lambda now: {'state': 'unknown', 'head': ''}
            return True
        else:
            raise ValueError('coupling failed')
        guard()
    material._recovery_motion()._recovery_select_head = select
    stages = material._recovery_initial_stages(review, lambda: cancelled[0])
    with pytest.raises(ValueError):
        material._run_recovery_stages(request, review, stages, lambda: cancelled[0])
    assert material._recovery_attempt.record['state'] == 'unknown'
    assert {'name': 'select_head', 'state': 'running'} in material._recovery_attempt.record['stages']
    assert not any(cmd.startswith('SET_HEATER') for cmd in calls)
    assert material._recovery_attempt.record['cleanup'] == {'state': 'complete', 'heaters': {}, 'error': ''}


@pytest.mark.parametrize('drift', ['grid', 'fade', 'offset', 'endpoint', 'inactive'])
def test_recovery_mesh_drift_blocks_heaters(recovery_reference_machine, drift):
    import copy
    material, objects, states, calls, review, request = recovery_reference_machine
    mesh = objects['bed_mesh']
    if drift in ('grid', 'inactive'):
        status = copy.deepcopy(mesh.get_status(1))
        if drift == 'grid': status['mesh_matrix'][0][0] += .01
        else: status['profile_name'] = ''
        mesh.get_status = lambda now: status
    elif drift == 'fade': mesh.fade_target = .01
    elif drift == 'offset':
        original = objects['gcode'].run_script_from_command
        def dispatch(script):
            original(script)
            if script.startswith('BED_MESH_OFFSET '):
                mesh.get_mesh().mesh_offsets = [.01, 0.]  # Offset command did not take effect.
        objects['gcode'].run_script_from_command = dispatch
    else: review['execution']['machine_position'][2] += .01
    with pytest.raises(ValueError, match='mesh'):
        material._run_recovery_stages(request, review, material._recovery_initial_stages(review))
    assert material._recovery_attempt.record['state'] == 'unknown'
    assert not any(cmd.startswith('SET_HEATER') for cmd in calls)


@pytest.mark.parametrize('bad', [[], [[0.]], [[0., 0.], [0.]], [[0., 0.], [0., float('nan')]]])
def test_recovery_snapshot_rejects_invalid_mesh(execution_snapshot_machine, bad):
    material, objects, states = execution_snapshot_machine
    status = dict(objects['bed_mesh'].get_status(1), mesh_matrix=bad)
    objects['bed_mesh'].get_status = lambda now: status
    with pytest.raises(ValueError, match='mesh'):
        material._execution_evidence()._recovery_execution_snapshot()


@pytest.mark.parametrize('fault', ['ignored', 'z', 'e', 'busy', 'cancel'])
def test_recovery_purge_travel_failure_stops_and_cleans_heaters(recovery_reference_machine, fault):
    material, objects, states, calls, review, request = recovery_reference_machine
    cancelled = [False]
    original = objects['gcode'].run_script_from_command
    def dispatch(script):
        moving = script.startswith('G1 X-13 Y')
        if moving and fault == 'ignored': calls.append(script)
        else: original(script)
        if moving:
            if fault == 'z': states['toolhead']['position'][2] -= 1.
            elif fault == 'e': states['toolhead']['position'][3] += 1.
            elif fault == 'busy': objects['toolhead'].check_busy = lambda now: (105., 104., True)
            elif fault == 'cancel': cancelled[0] = True
    objects['gcode'].run_script_from_command = dispatch
    stages = material._recovery_initial_stages(review, lambda: cancelled[0])
    with pytest.raises(ValueError):
        material._run_recovery_stages(request, review, stages, lambda: cancelled[0])
    assert material._recovery_attempt.record['state'] == 'unknown'
    assert sum(cmd.startswith('G1 X-13 Y') for cmd in calls) == 1
    assert states['extruder2']['target'] == states['heater_bed']['target'] == 0.


@pytest.mark.parametrize('points', [[], [[0., 0.], [999., 80.]], [[-13., float('nan')]], [[True, 80.]]])
def test_recovery_xy_validates_entire_route_before_setup(recovery_reference_machine, points):
    material, objects, states, calls, review, request = recovery_reference_machine
    states['toolhead']['position'][2] = 300.
    states['wmp_recovery'].update(z_reference_valid=True, homing=False)
    with pytest.raises(ValueError, match='path exceeds'):
        material._recovery_motion()._recovery_bottom_xy(points, lambda: None)
    assert calls == []


def test_recovery_prime_uses_configured_amount_and_head_limit(recovery_reference_machine):
    material, objects, states, calls, review, request = recovery_reference_machine
    material.recovery_purge_mm = 60.
    states['configfile']['settings']['extruder2']['max_extrude_only_distance'] = 20.
    material._run_recovery_stages(request, review, material._recovery_initial_stages(review))
    assert [cmd for cmd in calls if cmd.startswith('G1 E')] == ['G1 E20 F400\nM400'] * 3
    assert states['toolhead']['position'] == [11., 22., .45, 84.]
    assert {'name': 'prime', 'state': 'complete'} in material._recovery_attempt.record['stages']


@pytest.mark.parametrize('fault', ['cold', 'ignored', 'lost_reply', 'z', 'target', 'cancel'])
def test_recovery_prime_failure_is_not_repeated(recovery_reference_machine, fault):
    material, objects, states, calls, review, request = recovery_reference_machine
    cancelled = [False]
    original = objects['gcode'].run_script_from_command
    def dispatch(script):
        extruding = script.startswith('G1 E')
        if extruding and fault == 'ignored': calls.append(script)
        else: original(script)
        if fault == 'cold' and script == 'G1 X-13 Y80 F12000\nM400':
            states['extruder2']['can_extrude'] = False
        if extruding:
            if fault == 'lost_reply': raise ValueError('lost reply after extrusion')
            if fault == 'z': states['toolhead']['position'][2] -= 1.
            if fault == 'target': states['extruder2']['target'] -= 10.
            if fault == 'cancel': cancelled[0] = True
    objects['gcode'].run_script_from_command = dispatch
    stages = material._recovery_initial_stages(review, lambda: cancelled[0])
    with pytest.raises(ValueError):
        material._run_recovery_stages(request, review, stages, lambda: cancelled[0])
    assert sum(cmd.startswith('G1 E') for cmd in calls) == (0 if fault == 'cold' else 1)
    assert material._recovery_attempt.record['state'] == 'unknown'
    assert states['extruder2']['target'] == states['heater_bed']['target'] == 0.


def test_recovery_wipe_uses_saved_position_and_speed_without_extruding(recovery_reference_machine):
    from types import SimpleNamespace
    material, objects, states, calls, review, request = recovery_reference_machine
    objects['save_variables'].values['variables']['wipe_position'] = [-12., 230.]
    objects['gcode_macro WIPE_NOZZLE'] = SimpleNamespace(get_status=lambda now: {'wipe_speed': 6000.})
    material._run_recovery_stages(request, review, material._recovery_initial_stages(review))
    wipe_moves = [cmd for cmd in calls if cmd.startswith('G1 X-12') and 'F6000' in cmd]
    assert wipe_moves == ['G1 X-12 Y80 F6000\nM400'] + [
        'G1 X-12 Y230 F6000\nM400', 'G1 X-12 Y265 F6000\nM400'] * 4
    assert states['toolhead']['position'] == [11., 22., .45, 74.]
    assert {'name': 'wipe', 'state': 'complete'} in material._recovery_attempt.record['stages']
    assert not any(cmd.startswith('WIPE_NOZZLE') for cmd in calls)


@pytest.mark.parametrize('fault', ['ignored', 'cancel', 'calibration'])
def test_recovery_wipe_failure_retains_prime_and_stops(recovery_reference_machine, fault):
    material, objects, states, calls, review, request = recovery_reference_machine
    original = objects['gcode'].run_script_from_command
    cancelled = [False]
    def dispatch(script):
        wiping = script == 'G1 X-13 Y240 F12000\nM400'
        if wiping and fault == 'ignored': calls.append(script)
        else: original(script)
        if wiping:
            if fault == 'cancel': cancelled[0] = True
            if fault == 'calibration': objects['save_variables'].values['variables']['wipe_position'] = [-12., 240.]
    objects['gcode'].run_script_from_command = dispatch
    with pytest.raises(ValueError):
        material._run_recovery_stages(request, review,
            material._recovery_initial_stages(review, lambda: cancelled[0]), lambda: cancelled[0])
    assert {'name': 'prime', 'state': 'complete'} in material._recovery_attempt.record['stages']
    assert material._recovery_attempt.record['state'] == 'unknown'
    assert states['toolhead']['position'][3] == 74.
    assert not any(cmd == 'G1 X-13 Y275 F12000\nM400' for cmd in calls)
    assert states['extruder2']['target'] == states['heater_bed']['target'] == 0.


@pytest.mark.parametrize('fault', ['ignored', 'xy', 'e', 'busy', 'cancel', 'mesh'])
def test_recovery_return_failure_prevents_continuation(recovery_reference_machine, fault):
    material, objects, states, calls, review, request = recovery_reference_machine
    original = objects['gcode'].run_script_from_command
    cancelled, loads = [False], [0]
    def dispatch(script):
        vertical = script.startswith('G1 Z')
        if vertical and fault == 'ignored': calls.append(script)
        else: original(script)
        if vertical:
            if fault == 'xy': states['toolhead']['position'][0] += 1.
            if fault == 'e': states['toolhead']['position'][3] += 1.
            if fault == 'busy': objects['toolhead'].check_busy = lambda now: (105., 104., True)
            if fault == 'cancel': cancelled[0] = True
        if script == 'BED_MESH_PROFILE_BASE LOAD=wmp_print':
            loads[0] += 1
            if fault == 'mesh' and loads[0] == 2:
                objects['bed_mesh'].fade_target = .01
    objects['gcode'].run_script_from_command = dispatch
    with pytest.raises(ValueError):
        material._run_recovery_stages(request, review,
            material._recovery_initial_stages(review, lambda: cancelled[0]), lambda: cancelled[0])
    assert material._recovery_attempt.record['state'] == 'unknown'
    assert sum(cmd.startswith('G1 Z') for cmd in calls) == 1
    assert sum(cmd.startswith('G1 E') for cmd in calls) == 2
    assert states['extruder2']['target'] == states['heater_bed']['target'] == 0.
    assert not any(cmd.startswith(('M24', 'M9924', 'RESUME')) for cmd in calls)
    assert loads[0] == (2 if fault == 'mesh' else 1)


def test_recovery_return_xy_precedes_vertical_and_mesh(recovery_reference_machine):
    material, objects, states, calls, review, request = recovery_reference_machine
    material._run_recovery_stages(request, review, material._recovery_initial_stages(review))
    vertical = next(i for i, cmd in enumerate(calls) if cmd.startswith('G1 Z'))
    xy = calls.index('G1 X11 Y22 F12000\nM400')
    final_mesh = max(i for i, cmd in enumerate(calls) if cmd == 'BED_MESH_PROFILE_BASE LOAD=wmp_print')
    assert xy < vertical < final_mesh
    assert states['toolhead']['position'][:3] == review['execution']['machine_position'][:3]
    assert states['toolhead']['position'][3] == review['execution']['machine_position'][3] + 50.
    assert [item['name'] for item in material._recovery_attempt.record['stages'][-5:]] == [
        'return_xy', 'return_z', 'return_mesh', 'restore_parser', 'select_file']


@pytest.mark.parametrize('absolute,extrude', [(True, True), (True, False), (False, True), (False, False)])
def test_recovery_chain_restores_parser_after_priming(recovery_reference_machine, absolute, extrude):
    material, objects, states, calls, review, request = recovery_reference_machine
    execution = review['execution']
    execution.update(absolute_coordinates=absolute, absolute_extrude=extrude,
                     speed=12000., speed_factor=.8, extrude_factor=1.5)
    material._run_recovery_stages(request, review, material._recovery_initial_stages(review))
    parser = states['gcode_move']
    for name in ('gcode_position', 'homing_origin', 'speed', 'speed_factor', 'extrude_factor'):
        assert parser[name] == pytest.approx(execution[name])
    assert parser['absolute_coordinates'] is absolute
    assert parser['absolute_extrude'] is extrude
    assert parser['position'][:3] == pytest.approx(execution['parser_position'][:3])
    assert parser['position'][3] == states['toolhead']['position'][3] == 74.
    assert {'name': 'restore_parser', 'state': 'complete'} in material._recovery_attempt.record['stages']
    assert not any(cmd.startswith(('M24', 'M9924', 'RESUME')) for cmd in calls)


@pytest.mark.parametrize('fault', ['ignored', 'cancel', 'stock_fault'])
def test_recovery_parser_stage_failure_preserves_hold(recovery_reference_machine, fault):
    material, objects, states, calls, review, request = recovery_reference_machine
    original = objects['gcode'].run_script_from_command
    cancelled = [False]
    def dispatch(script):
        restoring = any(s['name'] == 'restore_parser' and s['state'] == 'running'
                        for s in material._recovery_attempt.record['stages'])
        if restoring and script.startswith('G92') and fault == 'ignored': calls.append(script)
        else: original(script)
        if restoring and script.startswith('SET_GCODE_OFFSET'):
            if fault == 'cancel': cancelled[0] = True
            if fault == 'stock_fault': objects['save_variables'].values['variables']['fail_flag'] = -3
    objects['gcode'].run_script_from_command = dispatch
    with pytest.raises(ValueError):
        material._run_recovery_stages(request, review,
            material._recovery_initial_stages(review, lambda: cancelled[0]), lambda: cancelled[0])
    assert material._recovery_attempt.record['state'] == 'unknown'
    assert {'name': 'restore_parser', 'state': 'running'} in material._recovery_attempt.record['stages']
    assert states['toolhead']['position'][3] == 74.
    assert states['extruder2']['target'] == states['heater_bed']['target'] == 0.
    if fault != 'ignored': assert not any(cmd.startswith('G1 F') for cmd in calls)


@pytest.mark.parametrize('failure', ['ignored_seek', 'lost_seek_reply', 'owner_after_load'])
def test_recovery_file_stage_failure_retains_attempt_without_start(recovery_reference_machine, failure):
    material, objects, states, calls, review, request = recovery_reference_machine
    sd = objects['virtual_sdcard']
    if failure == 'ignored_seek':
        sd.cmd_M26 = lambda command: None
    elif failure == 'lost_seek_reply':
        original = sd.cmd_M26
        def seek(command):
            original(command)
            raise RuntimeError('lost file seek reply')
        sd.cmd_M26 = seek
    else:
        original = sd._load_file
        def load(*args, **kwargs):
            original(*args, **kwargs)
            objects['AFC'] = object()
        sd._load_file = load
    with pytest.raises((ValueError, RuntimeError)):
        material._run_recovery_stages(request, review, material._recovery_initial_stages(review))
    receipt = material._recovery_attempt.record
    # After manager handoff, preserve the last owned journal rather than
    # rewriting it or cleaning the replacement owner's machine.
    assert receipt['state'] == ('running' if failure == 'owner_after_load' else 'unknown')
    if failure == 'owner_after_load': assert 'cleanup' not in receipt
    assert receipt['stages'][-1] == {'name': 'select_file', 'state': 'running'}
    assert {'name': 'restore_parser', 'state': 'complete'} in receipt['stages']
    assert sd.work_timer is None and not sd.is_active()
    assert not any(command.startswith(('M24', 'M9924', 'SDCARD_PRINT_FILE')) for command in calls)
    assert sum(command.startswith('G1 E25 ') for command in calls) == 2


def test_recovery_file_stage_records_seek_without_starting_worker(recovery_reference_machine):
    material, objects, states, calls, review, request = recovery_reference_machine
    material._run_recovery_stages(request, review, material._recovery_initial_stages(review))
    sd = objects['virtual_sdcard']
    assert material._recovery_attempt.record['stages'][-1] == {'name': 'select_file', 'state': 'complete'}
    assert sd.file_position == sd.current_file.tell() == review['execution']['file_position']
    assert sd.current_file.readline() == 'G1 X2\n'
    assert sd.work_timer is None and not sd.is_active()


@pytest.fixture
def recovery_continuation_machine(recovery_reference_machine):
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace as NS, MethodType
    material, objects, states, calls, review, request = recovery_reference_machine
    objects['toolhead'].lookahead = NS(add_move=lambda move: None)
    base = Path(__file__).resolve().parents[1] / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras'
    def load(name):
        spec = importlib.util.spec_from_file_location('continuation_' + name, base / (name + '.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    stats = load('print_stats').PrintStats.__new__(load('print_stats').PrintStats)
    reactor = material.printer.get_reactor()
    stats.reactor = reactor
    stats.gcode_move = NS(get_status=lambda now: {'position': NS(e=states['toolhead']['position'][3]),
                                                'extrude_factor': states['gcode_move']['extrude_factor']})
    stats.reset()
    objects['print_stats'] = stats
    sd = objects['virtual_sdcard']
    sd.print_stats, sd.reactor = stats, reactor
    sd.on_error_gcode = NS(render=lambda: 'CANCEL_PRINT')
    vendor = load('virtual_sdcard').VirtualSD
    for name in ('is_active', 'is_cmd_from_sd', 'work_handler', 'do_resume', 'do_pause', 'do_cancel'):
        setattr(sd, name, MethodType(getattr(vendor, name), sd))
    reactor.NOW, reactor.NEVER = 0., 1e30
    timers, body = [], []
    def register(callback, when):
        timer = NS(callback=callback, when=when)
        timers.append(timer)
        return timer
    reactor.register_timer = register
    reactor.update_timer = lambda timer, when: setattr(timer, 'when', when)
    reactor.unregister_timer = lambda timer: None
    old_pause = reactor.pause
    reactor.pause = lambda when: old_pause(max(when, reactor.monotonic()))
    mutex = [True]
    gcode = objects['gcode']
    gcode.get_mutex = lambda: NS(test=lambda: mutex[0])
    gcode.error = ValueError
    gcode.respond_raw = lambda message: None
    gcode.run_script = lambda line: body.append(line)
    original = gcode.run_script_from_command
    def dispatch(script):
        if script.startswith('SAVE_VARIABLE VARIABLE=box_modify_'):
            args = dict(token.split('=', 1) for token in script.split()[1:])
            objects['save_variables'].values['variables'][args['VARIABLE']] = int(args['VALUE'])
            calls.append(script)
        elif script.startswith('SET_GCODE_VARIABLE MACRO='):
            args = dict(token.split('=', 1) for token in script.split()[1:])
            states['gcode_macro ' + args['MACRO']][args['VARIABLE']] = args['VALUE'] == 'True'
            calls.append(script)
        else:
            original(script)
    gcode.run_script_from_command = dispatch
    return material, objects, states, calls, review, request, timers, body, mutex


def test_recovery_full_chain_restores_routes_accounting_and_exact_sd_line(recovery_continuation_machine):
    material, objects, states, calls, review, request, timers, body, mutex = recovery_continuation_machine
    saved = objects['save_variables'].values['variables']
    for i in range(4):
        saved['box_modify_t%d' % i] = saved['box_modify_t%d_backup' % i] = i
    stages = material._recovery_initial_stages(review, continue_print=True)
    result = material._run_recovery_stages(request, review, stages)
    assert result['state'] == 'complete'
    assert [s['name'] for s in result['stages'][-3:]] == ['restore_routes', 'accounting', 'start_file']
    assert [saved['box_modify_t%d' % i] for i in range(4)] == review['execution']['mapping']
    assert states['gcode_macro START_PRINT']['print_body_ready'] is True
    assert states['gcode_macro _WMP_RECOVERY_BEGIN']['active'] is False
    assert body == [] and timers[0].when == 0.
    mutex[0] = False
    timers[0].callback(material.printer.monotonic())
    assert body == ['G1 X2']
    stats = objects['print_stats'].get_status(material.printer.monotonic())
    assert stats['state'] == 'complete' and stats['total_duration'] == 541.5
    assert stats['print_duration'] == 500. and stats['filament_used'] == 123.


@pytest.mark.parametrize('ignored', ['box_modify_t0 VALUE=', 'box_modify_t0_backup',
                                    'VARIABLE=active VALUE=False', 'VARIABLE=print_body_ready VALUE=True'])
def test_recovery_route_readback_failure_prevents_worker(recovery_continuation_machine, ignored):
    material, objects, states, calls, review, request, timers, body, mutex = recovery_continuation_machine
    saved = objects['save_variables'].values['variables']
    saved['box_modify_t0'] = saved['box_modify_t0_backup'] = 0
    original = objects['gcode'].run_script_from_command
    objects['gcode'].run_script_from_command = lambda script: None if ignored in script else original(script)
    with pytest.raises(ValueError, match='not confirmed'):
        material._run_recovery_stages(request, review,
            material._recovery_initial_stages(review, continue_print=True))
    assert timers == [] and body == []
    assert material._recovery_attempt.record['state'] == 'unknown'
    assert states['extruder2']['target'] == 0.


@pytest.mark.parametrize('failure', ['activation', 'accounting_reply', 'stop_after_accounting'])
def test_recovery_final_handoff_failure_stops_owned_accounting(recovery_continuation_machine, failure):
    material, objects, states, calls, review, request, timers, body, mutex = recovery_continuation_machine
    reactor = material.printer.get_reactor()
    cancelled = lambda: False
    if failure == 'activation':
        original = reactor.update_timer
        def update(timer, when):
            original(timer, when)
            raise RuntimeError('lost activation reply')
        reactor.update_timer = update
    elif failure == 'accounting_reply':
        original = objects['print_stats'].note_start
        def start():
            original()
            raise RuntimeError('lost accounting reply')
        objects['print_stats'].note_start = start
    else:
        cancelled = lambda: any(stage['name'] == 'accounting' and stage['state'] == 'complete'
            for stage in (material._recovery_attempt.record or {}).get('stages', []))
    stages = material._recovery_initial_stages(review, cancelled, continue_print=True)
    if failure == 'stop_after_accounting':
        material._run_recovery_stages(request, review, stages, cancelled)
    else:
        with pytest.raises(RuntimeError): material._run_recovery_stages(request, review, stages, cancelled)
    assert objects['print_stats'].state == 'cancelled'
    assert objects['virtual_sdcard'].work_timer is None
    assert states['extruder2']['target'] == states['heater_bed']['target'] == 0.
    assert material._recovery_attempt.record['state'] in ('unknown', 'stopped')
    mutex[0] = False
    for timer in timers: timer.callback(reactor.monotonic())
    assert body == []


def test_recovery_accounting_cleanup_does_not_cancel_changed_job(recovery_continuation_machine):
    material, objects, states, calls, review, request, timers, body, mutex = recovery_continuation_machine
    stats = objects['print_stats']
    original = stats.note_start
    def start():
        original()
        stats.filename = 'another-job.gcode'
        raise RuntimeError('context changed during accounting')
    stats.note_start = start
    cancelled = []
    stats.note_cancel = lambda: cancelled.append(True)
    with pytest.raises(RuntimeError):
        material._run_recovery_stages(request, review,
            material._recovery_initial_stages(review, continue_print=True))
    assert cancelled == [] and stats.filename == 'another-job.gcode'
    assert material._recovery_attempt.record['cleanup']['state'] == 'unknown'
    assert timers == [] and body == []


@pytest.mark.parametrize('failure', ['command', 'unexpected'])
def test_recovered_worker_error_never_runs_stock_cancel_motion(recovery_continuation_machine, failure):
    material, objects, states, calls, review, request, timers, body, mutex = recovery_continuation_machine
    sd = objects['virtual_sdcard']
    original_template = sd.on_error_gcode
    def dispatch(line):
        body.append(line)
        if line == 'G1 X2':
            if failure == 'command': raise ValueError('injected command error')
            raise RuntimeError('unexpected dispatch failure')
    objects['gcode'].run_script = dispatch
    material._run_recovery_stages(request, review,
        material._recovery_initial_stages(review, continue_print=True))
    mutex[0] = False
    timers[0].callback(material.printer.monotonic())
    assert body.count('G1 X2') == 1 and 'CANCEL_PRINT' not in body
    assert 'TURN_OFF_HEATERS' in body
    assert sd.on_error_gcode is original_template
    assert sd.file_position == review['execution']['file_position']
    assert material._recovery_attempt.record['state'] == 'unknown'
    assert material._recovery_attempt.record['continuation']['state'] == 'unknown'
    assert material._recovery_lifecycle()._recovery_attempt_unresolved()


def test_recovered_worker_intentional_pause_is_not_dispatch_failure(recovery_continuation_machine):
    material, objects, states, calls, review, request, timers, body, mutex = recovery_continuation_machine
    sd = objects['virtual_sdcard']
    def dispatch(line):
        body.append(line)
        sd.must_pause_work = True
    objects['gcode'].run_script = dispatch
    material._run_recovery_stages(request, review,
        material._recovery_initial_stages(review, continue_print=True))
    mutex[0] = False
    timers[0].callback(material.printer.monotonic())
    assert body == ['G1 X2']
    assert material._recovery_attempt.record['state'] == 'complete'
    assert material._recovery_attempt.record['continuation']['state'] == 'paused'
    assert objects['print_stats'].state == 'paused'


@pytest.fixture
def interrupted_recovery_machine(execution_review_machine):
    from pathlib import Path
    from types import SimpleNamespace
    material, objects, states, fingerprint = execution_review_machine
    path = Path(material._recovery_execution_path())
    execution = json.loads(path.read_text())
    old_session = execution['session']
    receipt = dict(version=1, request=dict(id='recover', session=old_session,
        execution_hash=fingerprint, file='part.gcode'), state='complete',
        stages=[dict(name='start_file', state='complete')], error='',
        checkpoint=dict(job_fingerprint=execution['job_fingerprint'], file_position=execution['file_position']),
        continuation=dict(state='started', file_position=execution['file_position'], error=''))
    material._write_recovery_json(material._recovery_attempt_path(), receipt)
    material.session_id = 'new-session'
    material._restore_recovery_attempt()
    objects['gcode'].get_mutex = lambda: SimpleNamespace(test=lambda: True)
    return material, objects, states, path, execution


@pytest.mark.parametrize('change', ['valid', 'unchanged', 'wrong_session', 'backwards', 'owner', 'busy'])
def test_recovery_restart_reconciliation_requires_new_bound_checkpoint(interrupted_recovery_machine, change):
    material, objects, states, path, execution = interrupted_recovery_machine
    if change != 'unchanged': execution['total_duration'] += 1.
    if change == 'wrong_session': execution['session'] = 'another-session'
    elif change == 'backwards': execution['file_position'] -= 1
    elif change == 'owner': objects['AFC'] = object()
    elif change == 'busy': objects['virtual_sdcard'].active = True
    material._write_recovery_json(str(path), execution)
    fingerprint = material._recovery_fingerprint(path.read_bytes())
    if change == 'valid':
        result = material._reconcile_recovery_continuation(material.session_id, 'recover', fingerprint)
        assert result['state'] == 'complete' and result['continuation']['state'] == 'checkpointed'
        assert not material._recovery_lifecycle()._recovery_attempt_unresolved()
        assert material._read_recovery_job()['state'] == 'committed'
    else:
        with pytest.raises(ValueError):
            material._reconcile_recovery_continuation(material.session_id, 'recover', fingerprint)
        assert material._recovery_lifecycle()._recovery_attempt_unresolved()
    assert objects['gcode'].scripts == []


def test_recovery_reconciliation_detects_journal_change_during_hash(interrupted_recovery_machine):
    material, objects, states, path, execution = interrupted_recovery_machine
    execution['total_duration'] += 1.
    material._write_recovery_json(str(path), execution)
    fingerprint = material._recovery_fingerprint(path.read_bytes())
    def pause(when):
        material._recovery_attempt.record['error'] = 'changed while hashing'
    material.printer.pause = pause
    with pytest.raises(ValueError):
        material._reconcile_recovery_continuation(material.session_id, 'recover', fingerprint)
    assert material._recovery_attempt.record['state'] == 'unknown'
    assert objects['gcode'].scripts == []


@pytest.mark.parametrize('position,allowed', [(300., True), (305., False)])
def test_recovery_xy_uses_endstop_not_axis_maximum(recovery_reference_machine, position, allowed):
    material, objects, states, calls, review, request = recovery_reference_machine
    states['toolhead']['position'][2] = position
    states['toolhead']['homed_axes'] = 'xyz'
    states['wmp_recovery'].update(z_reference_valid=True, homing=False)
    if allowed:
        result = material._recovery_motion()._recovery_bottom_xy([[-13., 80.]], lambda: None)
        assert result[2] == 300.
    else:
        with pytest.raises(ValueError, match='bottom reference'):
            material._recovery_motion()._recovery_bottom_xy([[-13., 80.]], lambda: None)
        assert calls == []


@pytest.mark.parametrize('setting', [None, True, float('nan'), 306., -6.])
def test_recovery_invalid_endstop_refused_before_any_stage(recovery_reference_machine, setting):
    material, objects, states, calls, review, request = recovery_reference_machine
    states['configfile']['settings']['stepper_z']['position_endstop'] = setting
    with pytest.raises(ValueError, match='bottom endstop'):
        material._recovery_initial_stages(review)
    assert calls == []


def test_recovery_endstop_change_during_preparation_stops_chain(recovery_reference_machine):
    material, objects, states, calls, review, request = recovery_reference_machine
    stages = material._recovery_initial_stages(review)
    original = objects['gcode'].run_script_from_command
    def dispatch(script):
        original(script)
        if script == '_WMP_HOME_Z_BOTTOM':
            states['configfile']['settings']['stepper_z']['position_endstop'] = 301.
    objects['gcode'].run_script_from_command = dispatch
    with pytest.raises(ValueError, match='endstop changed'):
        material._run_recovery_stages(request, review, stages)
    assert calls == ['_WMP_RECOVERY_BEGIN', '_WMP_HOME_Z_BOTTOM']


def test_recovery_wrong_bottom_position_prevents_xy_homing(recovery_reference_machine):
    material, objects, states, calls, review, request = recovery_reference_machine
    original = objects['gcode'].run_script_from_command
    def dispatch(script):
        original(script)
        if script == '_WMP_HOME_Z_BOTTOM':
            states['toolhead']['position'][2] = 305.
    objects['gcode'].run_script_from_command = dispatch
    with pytest.raises(ValueError, match='not confirmed: bottom_z'):
        material._run_recovery_stages(request, review, material._recovery_initial_stages(review))
    assert calls == ['_WMP_RECOVERY_BEGIN', '_WMP_HOME_Z_BOTTOM']


def test_deposition_recording_spans_startup_commit_and_stops_on_clear(recovery_startup):
    from types import SimpleNamespace as NS
    import json
    from pathlib import Path
    material, objects, request, path = recovery_startup
    queued = []
    queue = NS(add_move=queued.append)
    objects['toolhead'] = NS(lookahead=queue)
    material.cmd_RECOVERY_JOB_BEGIN(FakeCommand())
    envelope = material._deposition_envelope
    assert envelope.record['job_id'] == request['id']
    queue.add_move(NS(start_pos=[0., 0., .2, 0.], end_pos=[10., 0., .2, 1.], is_kinematic_move=True))
    material._print_mesh_persisted = True  # This fixture simulates completed mesh persistence.
    material.cmd_RECOVERY_JOB_COMMIT(FakeCommand())
    assert material._deposition_envelope is envelope
    assert json.loads(Path(material._deposition_envelope_path()).read_text())['max_z'] == 1.
    material.cmd_RECOVERY_JOB_CLEAR(FakeCommand())
    assert material._deposition_envelope is None
    queue.add_move(NS(start_pos=[0., 0., 200., 0.], end_pos=[10., 0., 200., 1.], is_kinematic_move=True))
    assert len(queued) == 2
    assert json.loads(Path(material._deposition_envelope_path()).read_text())['max_z'] == 1.


@pytest.mark.parametrize('change', ['missing', 'foreign_job', 'foreign_file', 'tall_object'])
def test_recovery_clearance_refuses_unbound_or_tall_envelope(execution_review_machine, change):
    from pathlib import Path
    material, objects, states, fingerprint = execution_review_machine
    path = Path(material._deposition_envelope_path())
    record = json.loads(path.read_text())
    if change == 'missing':
        path.unlink()
    else:
        if change == 'foreign_job':
            record['job_id'] = 'another-job'
        elif change == 'foreign_file':
            record['file_sha256'] = 'f' * 64
        else:
            # Current checkpoint Z is only .45 mm; an earlier sequential object
            # is tall enough to block the bottom route despite that low nozzle.
            record['max_z'] = 295.
        path.write_text(json.dumps(record))
    with pytest.raises(ValueError):
        material._recovery_review_service()._recovery_execution_review(material.session_id, 'part.gcode', fingerprint)
    assert objects['gcode'].scripts == []


def test_recovery_clearance_uses_endstop_and_all_head_offsets(execution_review_machine):
    from pathlib import Path
    material, objects, states, fingerprint = execution_review_machine
    states['toolhead']['axis_maximum'][2] = 305.
    result = material._recovery_review_service()._recovery_execution_review(material.session_id, 'part.gcode', fingerprint)
    clearance = result['deposition']['clearance']
    job = json.loads(Path(material._recovery_job_path()).read_text())
    z_offsets = [row[2] for row in job['context']['offsets']]
    assert clearance['bottom_z'] == 300.
    assert clearance['head_offset_span'] == max(z_offsets) - min(z_offsets)
    assert clearance['available_gap'] == 299. - clearance['head_offset_span']
    material.recovery_clearance_mm = clearance['available_gap'] + .1
    with pytest.raises(ValueError, match='insufficient'):
        material._recovery_review_service()._recovery_execution_review(material.session_id, 'part.gcode', fingerprint)


@pytest.mark.parametrize('change', ['envelope', 'gap'])
def test_recovery_clearance_rechecked_before_first_dispatch(recovery_reference_machine, change):
    from pathlib import Path
    material, objects, states, calls, review, request = recovery_reference_machine
    stages = material._recovery_initial_stages(review)
    if change == 'gap':
        material.recovery_clearance_mm = 11.
    else:
        path = Path(material._deposition_envelope_path())
        record = json.loads(path.read_text())
        record['max_z'] += 1.
        path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match='clearance evidence changed'):
        stages[0][1]()
    assert calls == []


def test_recovery_continuation_preserves_and_extends_prior_deposition(recovery_continuation_machine):
    from pathlib import Path
    from types import SimpleNamespace as NS
    material, objects, states, calls, review, request, timers, body, mutex = recovery_continuation_machine
    path = Path(material._deposition_envelope_path())
    record = json.loads(path.read_text())
    record['max_z'] = 80.
    material._write_recovery_json(str(path), record)
    review['deposition'] = material._recovery_clearance_evidence(review['execution'])
    before = path.read_bytes()
    material._run_recovery_stages(request, review,
        material._recovery_initial_stages(review, continue_print=True))
    assert path.read_bytes() == before  # restoration never initializes an empty envelope
    assert material._deposition_session == material.session_id
    accepted = []
    # Have the actual retained SD worker dispatch through the installed observer.
    def dispatch(line):
        body.append(line)
        for z in (2., 80.2):
            objects['toolhead'].lookahead.add_move(NS(
                start_pos=[0., 0., z, 0.], end_pos=[1., 0., z, 1.], is_kinematic_move=True))
            accepted.append(json.loads(Path(material._deposition_envelope_path()).read_text())['max_z'])
    objects['gcode'].run_script = dispatch
    mutex[0] = False
    timers[0].callback(material.printer.monotonic())
    assert accepted == [80., 81.]
    assert body == ['G1 X2']
    assert material._recovery_attempt.record['continuation']['state'] == 'complete'


def test_recovery_continuation_refuses_unsupported_queue_before_preparation(recovery_continuation_machine):
    material, objects, states, calls, review, request, timers, body, mutex = recovery_continuation_machine
    del objects['toolhead'].lookahead
    with pytest.raises(ValueError, match='supported deposition observer'):
        material._recovery_initial_stages(review, continue_print=True)
    assert calls == [] and timers == [] and body == []


@pytest.mark.parametrize('change', ['replaced_queue', 'cleared_recording', 'failed_recording', 'changed_disk'])
def test_recovery_worker_refuses_lost_deposition_binding(recovery_continuation_machine, change):
    from types import SimpleNamespace as NS
    material, objects, states, calls, review, request, timers, body, mutex = recovery_continuation_machine
    material._run_recovery_stages(request, review,
        material._recovery_initial_stages(review, continue_print=True))
    if change == 'replaced_queue':
        objects['toolhead'].lookahead = NS(add_move=lambda move: None)
    elif change == 'cleared_recording':
        material._deposition_envelope = None
    elif change == 'changed_disk':
        record = dict(material._deposition_envelope.record, max_z=0.)
        material._write_recovery_json(material._deposition_envelope_path(), record)
    else:
        material._deposition_envelope.failed = True
    mutex[0] = False
    timers[0].callback(material.printer.monotonic())
    assert body == ['TURN_OFF_HEATERS']
    result = material._recovery_attempt.record
    assert result['state'] == 'unknown'
    assert 'deposition observer' in result['error']


@pytest.fixture
def native_recovery_request(recovery_continuation_machine, tmp_path):
    from pathlib import Path
    fixture = recovery_continuation_machine
    material, objects, states, calls, review, request, timers, body, mutex = fixture
    # Keep the configured runtime evidence directory established by the fixture.
    directory = Path(material.recovery_checkpoint_dir)
    checkpoint = directory / 'plr_dataB.ini'
    checkpoint.write_bytes(recovery_checkpoint_payload())
    checkpoint_hash = material._recovery_fingerprint(checkpoint.read_bytes())
    job_hash = review['execution']['job_fingerprint']
    Path(str(checkpoint) + '.wmp-coordinates').write_text(
        'WMP-GCODE-XYZ-MATERIAL-2 %s %s\n' % (checkpoint_hash, job_hash))
    native = dict(request, version=1, owner='standalone', checkpoint=checkpoint.name,
                  checkpoint_hash=checkpoint_hash, job_hash=job_hash,
                  deposition_sha256=review['deposition']['sha256'])
    return fixture, native, checkpoint


@pytest.mark.parametrize('native_offsets', [False, True], ids=['json-arrays', 'native-tuples'])
@pytest.mark.parametrize('native_coordinates', [False, True], ids=['list-position', 'native-coord'])
def test_native_recovery_request_runs_owned_chain(native_recovery_request, native_offsets, native_coordinates):
    fixture, request, checkpoint = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    if native_offsets:
        use_native_tuple_offsets(objects)
    if native_coordinates:
        use_native_toolhead_coordinates(objects)
    original_job = Path(material._recovery_job_path()).read_bytes()
    result = material._recovery_review_service()._consume_recovery_request(json.dumps(request).encode().hex())
    assert result['state'] == 'complete'
    assert body == []
    assert Path(material._recovery_job_path()).read_bytes() == original_job
    mutex[0] = False
    timers[0].callback(material.printer.monotonic())
    assert body == ['G1 X2']  # managed completed position, not native last_file_pos=3


@pytest.mark.parametrize('field,value', [
    ('version', True), ('owner', 'openace'), ('session', 'old-session'),
    ('checkpoint', '../plr_dataB.ini'), ('checkpoint_hash', '0' * 16),
    ('job_hash', '0' * 16), ('execution_hash', '0' * 16),
    ('deposition_sha256', '0' * 64), ('file', 'another.gcode'), ('extra', 1)])
def test_native_recovery_request_refuses_stale_or_invalid_selection(native_recovery_request, field, value):
    fixture, request, checkpoint = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    request[field] = value
    with pytest.raises((ValueError, OSError)):
        material._recovery_review_service()._consume_recovery_request(json.dumps(request).encode().hex())
    assert calls == [] and timers == [] and body == []


def test_native_recovery_request_requires_mutex(native_recovery_request):
    fixture, request, checkpoint = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    mutex[0] = False
    with pytest.raises(ValueError, match='command ownership'):
        material._recovery_review_service()._consume_recovery_request(json.dumps(request).encode().hex())
    assert calls == [] and timers == []


def test_native_recovery_selection_rechecked_before_first_command(native_recovery_request):
    fixture, request, checkpoint = native_recovery_request
    material, objects, states, calls, _, _, timers, body, mutex = fixture
    attempt, review = material._recovery_review_service()._recovery_request_review(json.dumps(request).encode().hex())
    stages = material._recovery_initial_stages(review, continue_print=True)
    checkpoint.write_bytes(recovery_checkpoint_payload(last_file_pos=4))
    with pytest.raises(ValueError, match='selection changed'):
        stages[0][1]()
    assert calls == [] and timers == []


def test_native_recovery_request_rejects_duplicate_fields(native_recovery_request):
    fixture, request, checkpoint = native_recovery_request
    material = fixture[0]
    raw = json.dumps(request)[:-1] + ', "owner": "standalone"}'
    with pytest.raises(ValueError, match='Duplicate'):
        material._recovery_review_service()._consume_recovery_request(raw.encode().hex())
    assert fixture[3] == [] and fixture[6] == []


def test_native_recovery_request_duplicate_does_not_repeat_preparation(native_recovery_request):
    fixture, request, checkpoint = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    encoded = json.dumps(request).encode().hex()
    material._recovery_review_service()._consume_recovery_request(encoded)
    before = list(calls)
    with pytest.raises(ValueError):
        material._recovery_review_service()._consume_recovery_request(encoded)
    assert calls == before and len(timers) == 1 and body == []


@pytest.mark.parametrize('history', ['none', 'unknown', 'stopped', 'corrupt'])
def test_recovery_continue_command_returns_preparation_receipt(native_recovery_request, history):
    fixture, request, checkpoint = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    if history == 'corrupt':
        material._recovery_restore_error = 'Old attempt journal is unreadable'
    elif history != 'none':
        material._recovery_attempt.record = dict(version=1,
            request=dict(id='older-attempt', session='old-session', file='part.gcode', execution_hash='a' * 16),
            state=history, stages=[dict(name='prepare', state='pending')], error='Old interrupted attempt')
    assert calls == [] and timers == []
    command = FakeCommand(REQUEST=json.dumps(request).encode().hex())
    material.cmd_RECOVERY_CONTINUE(command)
    result = json.loads(command.message)
    assert result['state'] == 'complete' and result['continuation']['state'] == 'scheduled'
    assert body == [] and len(timers) == 1
    assert material._recovery_command_active is False
    with pytest.raises(ValueError, match='not running'):
        material._handle_recovery_stop(CancelWebRequest(session=material.session_id, id=request['id']))


def test_recovery_stop_endpoint_works_while_command_mutex_held(native_recovery_request):
    fixture, request, checkpoint = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    original = objects['gcode'].run_script_from_command
    stop = CancelWebRequest(session=material.session_id, id=request['id'])
    def dispatch(script):
        original(script)
        if script == '_WMP_RECOVERY_BEGIN':
            assert mutex[0] is True
            material._handle_recovery_stop(stop)
    objects['gcode'].run_script_from_command = dispatch
    command = FakeCommand(REQUEST=json.dumps(request).encode().hex())
    material.cmd_RECOVERY_CONTINUE(command)
    assert stop.response['state'] == 'requested'
    result = json.loads(command.message)
    assert result['state'] == 'stopped'
    assert result['stages'][0]['state'] == 'complete'
    assert all(s['state'] == 'pending' for s in result['stages'][1:])
    assert calls == ['_WMP_RECOVERY_BEGIN'] and timers == [] and body == []


@pytest.mark.parametrize('change', ['session', 'id', 'owner'])
def test_recovery_stop_rejects_other_request_or_owner(native_recovery_request, change):
    fixture, request, checkpoint = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    original = objects['gcode'].run_script_from_command
    def dispatch(script):
        original(script)
        if script != '_WMP_RECOVERY_BEGIN':
            return
        params = dict(session=material.session_id, id=request['id'])
        if change in params:
            params[change] = 'other'
        else:
            objects['AFC'] = object()
        try:
            with pytest.raises(ValueError, match='request or owner changed'):
                material._handle_recovery_stop(CancelWebRequest(**params))
            assert material._recovery_stop_request is None
        finally:
            objects.pop('AFC', None)
        material._handle_recovery_stop(CancelWebRequest(session=material.session_id, id=request['id']))
    objects['gcode'].run_script_from_command = dispatch
    material.cmd_RECOVERY_CONTINUE(FakeCommand(REQUEST=json.dumps(request).encode().hex()))
    assert calls == ['_WMP_RECOVERY_BEGIN'] and timers == []


def test_recovery_stop_during_heating_cleans_heaters_without_purge(native_recovery_request):
    fixture, request, checkpoint = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    reactor = material.printer.get_reactor()
    original = reactor.pause
    stops = []
    def pause(when):
        receipt = material._recovery_attempt.record
        if receipt and any(s['name'] == 'heating' and s['state'] == 'running' for s in receipt['stages']):
            stop = CancelWebRequest(session=material.session_id, id=request['id'])
            material._handle_recovery_stop(stop)
            stops.append(stop.response)
        return original(when)
    reactor.pause = pause
    with pytest.raises(ValueError, match='heating stopped'):
        material.cmd_RECOVERY_CONTINUE(FakeCommand(REQUEST=json.dumps(request).encode().hex()))
    receipt = material._recovery_attempt.record
    assert stops and stops[0]['state'] == 'requested'
    assert receipt['state'] == 'unknown' and receipt['cleanup']['state'] == 'complete'
    assert all(s['state'] == 'pending' for s in receipt['stages'] if s['name'] in ('prime', 'wipe', 'start_file'))
    assert states['extruder2']['target'] == states['heater_bed']['target'] == 0.
    assert timers == [] and body == []
    assert material._recovery_command_active is False


def recovery_review_web_request(request):
    return CancelWebRequest(**{key: request[key] for key in
        ('id', 'session', 'file', 'checkpoint', 'checkpoint_hash', 'job_hash')})


@pytest.mark.parametrize("missing_optional_fan", [False, True])
def test_recovery_review_endpoint_returns_bound_selection_without_commands(native_recovery_request, missing_optional_fan):
    fixture, request, checkpoint = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    mutex[0] = False
    if missing_optional_fan:
        original_review = material._recovery_review_service()._recovery_execution_review
        def with_fan_warning(*args):
            value = original_review(*args)
            value["fan_warnings"] = ["Optional cooling fan is not installed: auxiliary_fan"]
            return value
        material._recovery_review_service()._recovery_execution_review = with_fan_warning
    web = recovery_review_web_request(request)
    material._handle_recovery_review(web)
    result = web.response
    assert result["fan_warnings"] == (["Optional cooling fan is not installed: auxiliary_fan"] if missing_optional_fan else [])
    assert result['request'] == request
    assert json.loads(bytes.fromhex(result['encoded'])) == request
    assert result['execution']['file_position'] == review['execution']['file_position']
    assert calls == [] and timers == [] and body == []
    mutex[0] = True
    material.cmd_RECOVERY_CONTINUE(FakeCommand(REQUEST=result['encoded']))
    assert len(timers) == 1


def test_recovery_review_endpoint_accepts_bound_absolute_native_filename(native_recovery_request):
    import os
    fixture, request, checkpoint = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    mutex[0] = False
    web = recovery_review_web_request(request)
    web.params['file'] = os.path.join(objects['virtual_sdcard'].sdcard_dirname, request['file'])
    material._handle_recovery_review(web)
    assert web.response['request']['file'] == request['file']
    assert calls == [] and timers == []


@pytest.mark.parametrize('change', ['outside', 'busy', 'stale', 'missing_envelope'])
def test_recovery_review_endpoint_refuses_unavailable_selection(native_recovery_request, change):
    from pathlib import Path
    fixture, request, checkpoint = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    mutex[0] = change == 'busy'
    web = recovery_review_web_request(request)
    if change == 'outside': web.params['file'] = '/tmp/another.gcode'
    elif change == 'stale': web.params['session'] = 'old-session'
    elif change == 'missing_envelope': Path(material._deposition_envelope_path()).unlink()
    with pytest.raises(ValueError): material._handle_recovery_review(web)
    assert web.response is None and calls == [] and timers == []


def test_recovery_review_endpoint_rechecks_command_ownership_after_read(native_recovery_request):
    fixture, request, checkpoint = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    mutex[0] = False
    original = material._recovery_review_service()._recovery_request_review
    def changed(encoded):
        result = original(encoded)
        mutex[0] = True
        return result
    material._recovery_review_service()._recovery_request_review = changed
    web = recovery_review_web_request(request)
    with pytest.raises(ValueError, match='started during recovery review'):
        material._handle_recovery_review(web)
    assert web.response is None and calls == [] and timers == []


def test_recovery_command_records_bound_refusal_without_attempt(native_recovery_request):
    fixture, request, checkpoint = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    request['deposition_sha256'] = '0' * 64
    with pytest.raises(ValueError):
        material.cmd_RECOVERY_CONTINUE(FakeCommand(REQUEST=json.dumps(request).encode().hex()))
    result = json.loads(json.dumps(material._recovery_submission))
    assert result['state'] == 'refused' and result['request']['id'] == request['id']
    assert result['message']
    assert material._recovery_attempt.record is None
    assert calls == [] and timers == [] and body == []
    # A repaired payload with the same ticket cannot turn an earlier refusal
    # into an unnoticed successful retry.
    request['deposition_sha256'] = review['deposition']['sha256']
    with pytest.raises(ValueError, match='already attempted'):
        material.cmd_RECOVERY_CONTINUE(FakeCommand(REQUEST=json.dumps(request).encode().hex()))
    assert material._recovery_submission == result and calls == []


def test_recovery_command_duplicate_keeps_attempted_receipt(native_recovery_request):
    import copy
    fixture, request, checkpoint = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    command = FakeCommand(REQUEST=json.dumps(request).encode().hex())
    material.cmd_RECOVERY_CONTINUE(command)
    before = copy.deepcopy(material._recovery_attempt.record)
    submission = copy.deepcopy(material._recovery_submission)
    with pytest.raises(ValueError, match='already attempted'):
        material.cmd_RECOVERY_CONTINUE(command)
    assert material._recovery_attempt.record == before
    assert material._recovery_submission == submission
    assert submission['state'] == 'attempted'


def test_recovery_command_failure_after_dispatch_is_not_a_refusal(native_recovery_request):
    fixture, request, checkpoint = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    original = objects['gcode'].run_script_from_command
    def dispatch(script):
        original(script)
        raise ValueError('lost dispatch acknowledgement')
    objects['gcode'].run_script_from_command = dispatch
    with pytest.raises(ValueError, match='lost dispatch'):
        material.cmd_RECOVERY_CONTINUE(FakeCommand(REQUEST=json.dumps(request).encode().hex()))
    assert material._recovery_submission['state'] == 'attempted'
    assert material._recovery_attempt.record['state'] == 'unknown'
    assert calls == ['_WMP_RECOVERY_BEGIN']


def resolution_request(material, action='abandon', ticket='resolve-1'):
    return material._recovery_review_service()._recovery_resolution_selection(dict(id=ticket,
        attempt_id=material._recovery_attempt.record['request']['id'],
        session=material.session_id, action=action))


def resolution_command(request):
    return FakeCommand(REQUEST=json.dumps(request).encode().hex())


def test_public_recovery_abandon_is_bound_and_not_replayed(recovery_abandon_machine):
    material, objects, states, calls, review, attempt = recovery_abandon_machine
    request = resolution_request(material)
    loaded = material._loaded_filament_status(1.)
    command = resolution_command(request)
    material.cmd_RECOVERY_RESOLVE(command)
    assert material._recovery_resolution['state'] == 'complete'
    assert material._recovery_resolution['request'] == request
    assert json.loads(command.message)['state'] == 'abandoned'
    assert material._loaded_filament_status(1.) == loaded
    before = list(calls)
    with pytest.raises(ValueError, match='already attempted'):
        material.cmd_RECOVERY_RESOLVE(command)
    assert calls == before and material._recovery_resolution['state'] == 'complete'
    assert not any(call.startswith(('G0', 'G1', 'G28', 'M104', 'M109')) for call in calls)


@pytest.mark.parametrize('change', ['session', 'attempt', 'journal', 'execution', 'owner', 'mutex', 'action', 'version'])
def test_public_recovery_resolution_refuses_changed_review(recovery_abandon_machine, change):
    from types import SimpleNamespace
    material, objects, states, calls, review, attempt = recovery_abandon_machine
    request = resolution_request(material)
    if change == 'session': request['session'] = 'old-session'
    elif change == 'attempt': request['attempt_id'] = 'another'
    elif change == 'journal':
        material._recovery_attempt.record['error'] = 'changed'
        material._recovery_attempt.persist(material._recovery_attempt.record)
    elif change == 'execution':
        with open(material._recovery_execution_path(), 'ab') as stream: stream.write(b' ')
    elif change == 'owner': objects['AFC'] = object()
    elif change == 'mutex': objects['gcode'].get_mutex = lambda: SimpleNamespace(test=lambda: False)
    elif change == 'action': request['action'] = 'continue'
    elif change == 'version': request['version'] = True
    with pytest.raises(ValueError): material.cmd_RECOVERY_RESOLVE(resolution_command(request))
    assert calls == []
    assert material._recovery_lifecycle()._recovery_attempt_unresolved()
    assert getattr(material, '_recovery_resolution', {}).get('state', 'refused') == 'refused'


def test_public_recovery_resolution_partial_failure_stays_unknown(recovery_abandon_machine):
    material, objects, states, calls, review, attempt = recovery_abandon_machine
    request = resolution_request(material)
    dispatch = objects['gcode'].run_script_from_command
    objects['gcode'].run_script_from_command = lambda script: None if 'MACRO=_WMP_RECOVERY_BEGIN' in script else dispatch(script)
    with pytest.raises(ValueError, match='not confirmed'):
        material.cmd_RECOVERY_RESOLVE(resolution_command(request))
    assert material._recovery_resolution['state'] == 'unknown'
    assert material._recovery_lifecycle()._recovery_attempt_unresolved()
    before = list(calls)
    with pytest.raises(ValueError, match='already attempted'):
        material.cmd_RECOVERY_RESOLVE(resolution_command(request))
    assert calls == before and material._recovery_resolution['state'] == 'unknown'
    # A new explicit review can finish only the same abandoned job's cleanup.
    objects['gcode'].run_script_from_command = dispatch
    request = resolution_request(material, ticket='resolve-2')
    material.cmd_RECOVERY_RESOLVE(resolution_command(request))
    assert material._recovery_resolution['state'] == 'complete'


def test_public_recovery_reconcile_preserves_job_without_commands(interrupted_recovery_machine):
    material, objects, states, path, execution = interrupted_recovery_machine
    execution['total_duration'] += 1.
    material._write_recovery_json(str(path), execution)
    request = resolution_request(material, action='reconcile')
    material.cmd_RECOVERY_RESOLVE(resolution_command(request))
    assert material._recovery_resolution['state'] == 'complete'
    assert material._recovery_attempt.record['continuation']['state'] == 'checkpointed'
    assert not material._recovery_lifecycle()._recovery_attempt_unresolved()
    assert material._read_recovery_job()['state'] == 'committed'
    assert objects['gcode'].scripts == []


def test_resolution_review_is_explicit_read_only_during_unrelated_command(recovery_abandon_machine):
    from types import SimpleNamespace
    material, objects, states, calls, review, attempt = recovery_abandon_machine
    args = dict(id='resolve-1', attempt_id=attempt['id'], session=material.session_id, action='abandon')
    request = CancelWebRequest(**args)
    material._handle_recovery_resolution_review(request)
    assert request.response['request'] == material._recovery_review_service()._recovery_resolution_selection(args)
    assert calls == [] and not getattr(material, '_recovery_resolution', {})


@pytest.mark.parametrize('payload', ['00', 'ab' * 2049, 'zz', '7', '{}', '{"version":1,"version":1}'])
def test_public_resolution_invalid_payload_has_no_side_effects(recovery_abandon_machine, payload):
    material, objects, states, calls, review, attempt = recovery_abandon_machine
    if payload.startswith('{'): payload = payload.encode().hex()
    with pytest.raises(ValueError): material.cmd_RECOVERY_RESOLVE(FakeCommand(REQUEST=payload))
    assert calls == [] and not getattr(material, '_recovery_resolution', {})


@pytest.mark.parametrize('change', ['heater', 'fault', 'attachment'])
def test_resolution_review_checks_abandon_prerequisites(recovery_abandon_machine, change):
    from types import SimpleNamespace
    material, objects, states, calls, review, attempt = recovery_abandon_machine
    objects['gcode'].get_mutex = lambda: SimpleNamespace(test=lambda: False)
    if change == 'heater': states['extruder2']['target'] = 220.
    elif change == 'fault': objects['save_variables'].values['variables']['fail_flag'] = -3
    else: material._material_status()._attachment = lambda now: {'state': 'unknown'}
    request = CancelWebRequest(id='resolve-1', attempt_id=attempt['id'], session=material.session_id, action='abandon')
    material._handle_recovery_resolution_review(request)
    assert request.response is not None and calls == []
    assert material._recovery_lifecycle()._recovery_attempt_unresolved()


def test_resolution_reconcile_review_does_not_release_hold(interrupted_recovery_machine):
    from types import SimpleNamespace
    material, objects, states, path, execution = interrupted_recovery_machine
    execution['total_duration'] += 1.
    material._write_recovery_json(str(path), execution)
    objects['gcode'].get_mutex = lambda: SimpleNamespace(test=lambda: False)
    request = CancelWebRequest(id='resolve-1', attempt_id='recover', session=material.session_id, action='reconcile')
    before = material._recovery_read_bytes(material._recovery_attempt_path(), 65536)
    material._handle_recovery_resolution_review(request)
    assert request.response['request']['action'] == 'reconcile'
    assert material._recovery_read_bytes(material._recovery_attempt_path(), 65536) == before
    assert material._recovery_lifecycle()._recovery_attempt_unresolved() and objects['gcode'].scripts == []


@pytest.mark.parametrize('version,reason', [
    (1, 'parser/machine coordinates'), (2, 'mesh transform'),
    (3, 'printing-time and filament-use'), (5, 'not supported'),
])
def test_older_execution_schema_explains_gap_and_preserves_record(completed_execution, version, reason):
    from pathlib import Path
    material, objects, states = completed_execution
    path = Path(material._recovery_execution_path())
    saved = json.loads(path.read_text())
    saved['version'] = version
    if version < 4:
        for key in ('print_duration', 'filament_used'): saved.pop(key)
    if version < 3:
        for key in ('mesh_fingerprint', 'mesh_offsets'): saved.pop(key)
    if version < 2:
        for key in ('parser_position', 'machine_position'): saved.pop(key)
    original = json.dumps(saved).encode()
    path.write_bytes(original)
    with pytest.raises(ValueError, match=reason):
        material._read_completed_recovery_execution('part.gcode')
    assert path.read_bytes() == original
    assert objects['gcode'].scripts == []


@pytest.mark.parametrize('payload', [None, b'{broken', b'\xff'])
def test_missing_or_unreadable_execution_has_clear_nonmutating_refusal(completed_execution, payload):
    from pathlib import Path
    material, objects, states = completed_execution
    path = Path(material._recovery_execution_path())
    if payload is None: path.unlink()
    else: path.write_bytes(payload)
    with pytest.raises(ValueError, match='checkpoint was saved|unreadable'):
        material._read_completed_recovery_execution('part.gcode')
    assert (path.read_bytes() if path.exists() else None) == payload
    assert objects['gcode'].scripts == []


@pytest.mark.parametrize('legacy', [False, True])
def test_native_review_explains_legacy_before_missing_clearance(native_recovery_request, legacy):
    from pathlib import Path
    fixture, request, checkpoint = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    path = Path(material._recovery_execution_path())
    if legacy:
        value = json.loads(path.read_text())
        value['version'] = 3
        value.pop('print_duration'); value.pop('filament_used')
        path.write_text(json.dumps(value))
    original = path.read_bytes()
    Path(material._deposition_envelope_path()).unlink()
    mutex[0] = False
    web = recovery_review_web_request(request)
    with pytest.raises(ValueError, match='format 3' if legacy else 'No deposition record or print-start macro proof'):
        material._handle_recovery_review(web)
    assert path.read_bytes() == original
    assert calls == [] and timers == [] and body == [] and web.response is None


def test_recovered_pause_resume_error_retains_managed_cleanup(recovery_continuation_machine):
    material, objects, states, calls, review, request, timers, body, mutex = recovery_continuation_machine
    sd = objects['virtual_sdcard']
    reactor = material.printer.get_reactor()
    material._run_recovery_stages(request, review,
        material._recovery_initial_stages(review, continue_print=True))
    # Pause while the retained vendor worker yields after reading, before it
    # dispatches the first remaining line. Resume must execute that line once.
    old_pause = reactor.pause
    def pause_before_dispatch(when):
        sd.must_pause_work = True
        return old_pause(when)
    reactor.pause = pause_before_dispatch
    mutex[0] = False
    timers[0].callback(reactor.monotonic())
    assert body == [] and objects['print_stats'].state == 'paused'
    assert material._recovery_attempt.record['continuation']['state'] == 'paused'
    reactor.pause = old_pause
    def fail_command(line):
        body.append(line)
        if line == 'G1 X2':
            raise ValueError('command failure after later Resume')
    objects['gcode'].run_script = fail_command
    sd.do_resume()  # Same native entry used by pause_resume and M24.
    timers[-1].callback(reactor.monotonic())
    assert body.count('G1 X2') == 1
    assert 'CANCEL_PRINT' not in body
    assert 'TURN_OFF_HEATERS' in body
    assert material._recovery_attempt.record['continuation']['state'] == 'unknown'


@pytest.fixture
def paused_recovery_worker(recovery_continuation_machine):
    fixture = recovery_continuation_machine
    material, objects, states, calls, review, request, timers, body, mutex = fixture
    sd = objects['virtual_sdcard']
    reactor = material.printer.get_reactor()
    original = sd.work_handler
    material._run_recovery_stages(request, review,
        material._recovery_initial_stages(review, continue_print=True))
    old_pause = reactor.pause
    def pause_before_dispatch(when):
        sd.must_pause_work = True
        return old_pause(when)
    reactor.pause = pause_before_dispatch
    mutex[0] = False
    timers[0].callback(reactor.monotonic())
    reactor.pause = old_pause
    assert body == [] and objects['print_stats'].state == 'paused'
    return fixture, original, pause_before_dispatch


def test_recovered_repeated_resume_keeps_accounting_and_releases_owner(paused_recovery_worker):
    fixture, original, pause_before_dispatch = paused_recovery_worker
    material, objects, states, calls, review, request, timers, body, mutex = fixture
    sd, reactor = objects['virtual_sdcard'], material.printer.get_reactor()
    preparation = list(calls)
    old_pause = reactor.pause
    reactor.pause = pause_before_dispatch
    sd.do_resume()
    timers[-1].callback(reactor.monotonic())
    assert body == [] and material._recovery_attempt.record['continuation']['state'] == 'paused'
    reactor.pause = old_pause
    sd.do_resume()
    timers[-1].callback(reactor.monotonic())
    assert body == ['G1 X2'] and calls == preparation
    assert material._recovery_attempt.record['continuation']['state'] == 'complete'
    assert sd.work_handler is original and material._recovery_paused_worker is None
    stats = objects['print_stats'].get_status(reactor.monotonic())
    assert stats['filament_used'] == 123. and stats['print_duration'] == 500.


@pytest.mark.parametrize('change', ['session', 'owner', 'file', 'journal'])
def test_recovered_resume_rejects_changed_binding_before_dispatch(paused_recovery_worker, change):
    fixture, original, pause_before_dispatch = paused_recovery_worker
    material, objects, states, calls, review, request, timers, body, mutex = fixture
    sd = objects['virtual_sdcard']
    if change == 'session': material.session_id = 'another-session'
    elif change == 'owner': objects['openace'] = object()
    elif change == 'file': objects['print_stats'].filename = 'another.gcode'
    else: material._write_recovery_json(material._recovery_job_path(), {})
    with pytest.raises(ValueError, match='no longer owns|job changed'):
        material.cmd_CHECK_RESUME(FakeCommand())
    sd.do_resume()  # A direct native caller also cannot dispatch the SD body.
    timers[-1].callback(material.printer.monotonic())
    assert 'G1 X2' not in body and 'CANCEL_PRINT' not in body
    assert material._recovery_attempt.record['state'] == 'unknown'


def test_recovered_pause_reset_restores_only_owned_handler(paused_recovery_worker):
    fixture, original, pause_before_dispatch = paused_recovery_worker
    material, objects, states, calls, review, request, timers, body, mutex = fixture
    material._filament_checks = {}
    material._clear_filament_checks()
    assert objects['virtual_sdcard'].work_handler is original
    assert material._recovery_paused_worker is None and body == []


@pytest.fixture
def managed_cancel_cleanup(paused_recovery_worker):
    from types import SimpleNamespace as NS
    fixture, original_worker, _ = paused_recovery_worker
    material, objects, states, calls, review, request, timers, body, mutex = fixture
    sd = objects['virtual_sdcard']
    mutex[0] = True
    pause = {'is_paused': True}
    objects['pause_resume'] = NS(get_status=lambda now: pause)
    names = [name for name in ('heater_bed', 'extruder', 'extruder1', 'extruder2', 'extruder3') if name in states]
    objects['heaters'] = NS(get_all_heaters=lambda: names)
    objects['configfile'] = NS(get_status=lambda now: {'settings': {
        'printer': {'max_velocity': 500, 'max_accel': 10000}, 'idle_timeout': {'timeout': 600}}})
    cleanup = []
    def run(command):
        cleanup.append(command)
        if command == 'TURN_OFF_HEATERS':
            for name in names: states[name]['target'] = 0.
        elif command == '_WMP_PRINT_CONTEXT_CLEAR':
            objects['save_variables'].values['variables']['wmp_print_context'] = {}
            states['gcode_macro _WMP_RECOVERY_BEGIN']['active'] = False
            material.cmd_RECOVERY_JOB_CLEAR(FakeCommand())
        elif command.startswith('SET_GCODE_VARIABLE MACRO=START_PRINT'):
            states['gcode_macro START_PRINT']['print_body_ready'] = False
        elif command == 'CLEAR_PAUSE': pause['is_paused'] = False
        else: assert command.split()[0] in ('M400', 'M107', 'BED_MESH_CLEAR', 'M220', 'RESET_FLOW_EXTRUDER', 'SAVE_VARIABLE', 'SET_VELOCITY_LIMIT', 'SET_IDLE_TIMEOUT', 'M84', '_WMP_CASE_LIGHT_PRINT_END', '_WMP_PRINT_LOWER_BED')
    objects['gcode'].run_script_from_command = run
    binding = {'session': material.session_id, 'file': objects['print_stats'].filename,
               'handle': sd.current_file}
    return fixture, binding, cleanup, original_worker


def test_managed_cancel_cleanup_preserves_evidence_and_lowers_bed(managed_cancel_cleanup):
    fixture, binding, cleanup, original_worker = managed_cancel_cleanup
    material, objects, states, calls, review, request, timers, body, mutex = fixture
    material.filament_operation = {'state': 'unknown', 'id': 'partial-feed'}
    material.toolhead_operation = {'state': 'unknown', 'id': 'partial-dock'}
    before = (dict(material.filament_operation), dict(material.toolhead_operation))
    material._material_status()._attachment = lambda now: pytest.fail('Cancellation must not select a physical motion from attachment')
    phases = []
    result = material._cancellation()._cancel_print_cleanup(binding, lambda name, state="running": phases.append((name, state)))
    assert result['state'] == 'complete'
    assert phases == [('stopping', 'complete')] + [(name, state) for name in material._CANCEL_STAGES[1:] for state in ('running', 'complete')]
    assert cleanup[:5] == ['M400', 'TURN_OFF_HEATERS', '_WMP_PRINT_CONTEXT_CLEAR',
                       'SET_GCODE_VARIABLE MACRO=START_PRINT VARIABLE=print_body_ready VALUE=False', 'CLEAR_PAUSE']
    assert cleanup.index('BED_MESH_CLEAR') < cleanup.index('_WMP_PRINT_LOWER_BED PARK=1')
    assert cleanup[cleanup.index('_WMP_PRINT_LOWER_BED PARK=1') + 1] == 'M400'
    assert binding['handle'].closed and objects['virtual_sdcard'].current_file is None
    assert objects['print_stats'].state == 'cancelled'
    assert objects['print_stats'].filament_used == 123.
    assert objects['pause_resume'].get_status(1)['is_paused'] is False
    assert (material.filament_operation, material.toolhead_operation) == before
    assert objects['virtual_sdcard'].work_handler is original_worker
    assert material._recovery_attempt.record['continuation']['state'] == 'cancelled'


@pytest.mark.parametrize('failure', ['drain', 'heater', 'context', 'body', 'file', 'pause'])
def test_managed_cancel_partial_cleanup_cannot_report_complete(managed_cancel_cleanup, failure):
    fixture, binding, cleanup, original_worker = managed_cancel_cleanup
    material, objects, states, calls, review, request, timers, body, mutex = fixture
    original = objects['gcode'].run_script_from_command
    faulty = {'drain': 'M400', 'heater': 'TURN_OFF_HEATERS', 'context': '_WMP_PRINT_CONTEXT_CLEAR',
              'body': 'SET_GCODE_VARIABLE MACRO=START_PRINT VARIABLE=print_body_ready VALUE=False',
              'pause': 'CLEAR_PAUSE'}.get(failure)
    def run(command):
        if command == faulty:
            cleanup.append(command)
            raise ValueError('injected ' + failure)
        original(command)
    objects['gcode'].run_script_from_command = run
    if failure == 'file':
        def fail_cancel(): raise ValueError('injected file')
        objects['virtual_sdcard'].do_cancel = fail_cancel
    with pytest.raises(ValueError, match='injected'):
        material._cancellation()._cancel_print_cleanup(binding)
    assert objects['pause_resume'].get_status(1)['is_paused'] is (failure == 'pause')
    assert (material._recovery_paused_worker is not None) is (failure == 'pause')
    if failure == 'drain':
        assert cleanup[:2] == ['M400', 'TURN_OFF_HEATERS']
        assert 'M84' not in cleanup
        assert not any(command.startswith('_WMP_PRINT_LOWER_BED') for command in cleanup)
    assert (objects['virtual_sdcard'].current_file is binding['handle']) is (failure == 'file')


@pytest.mark.parametrize('change', ['session', 'owner', 'file', 'mutex', 'active'])
def test_managed_cancel_cleanup_requires_stopped_bound_job(managed_cancel_cleanup, change):
    fixture, binding, cleanup, original_worker = managed_cancel_cleanup
    material, objects, states, calls, review, request, timers, body, mutex = fixture
    if change == 'session': material.session_id = 'new-session'
    elif change == 'owner': objects['openace'] = object()
    elif change == 'file': objects['print_stats'].filename = 'different.gcode'
    elif change == 'mutex': mutex[0] = False
    else: objects['virtual_sdcard'].work_timer = object()
    with pytest.raises(ValueError, match='ownership'):
        material._cancellation()._cancel_print_cleanup(binding)
    assert cleanup == [] and not binding['handle'].closed


@pytest.fixture
def managed_cancel_intent(managed_cancel_cleanup):
    fixture, binding, cleanup, original_worker = managed_cancel_cleanup
    material, objects, states, calls, review, request, timers, body, locked = fixture
    class Mutex:
        def test(self): return locked[0]
        def __enter__(self):
            assert not locked[0]
            locked[0] = True
        def __exit__(self, *args): locked[0] = False
    objects['gcode'].get_mutex = lambda: Mutex()
    return managed_cancel_cleanup


@pytest.fixture
def tracked_cancel_timers(managed_cancel_intent):
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material = fixture[0]
    reactor = material.printer.get_reactor()
    registered = [object()]  # An unrelated timer must survive cancellation.
    original_register = reactor.register_timer
    def register(callback, when):
        timer = original_register(callback, when)
        registered.append(timer)
        return timer
    def unregister(timer):
        registered.remove(timer)
        timer.when = reactor.NEVER
    reactor.register_timer = register
    reactor.unregister_timer = unregister
    return managed_cancel_intent, registered


@pytest.mark.parametrize('exit_path', ['complete', 'superseded', 'terminal', 'owner',
                                     'job', 'cleanup', 'status', 'persist'])
def test_print_cancel_terminal_paths_unregister_timer(tracked_cancel_timers, monkeypatch, exit_path):
    fixture, registered = tracked_cancel_timers
    machine, binding, cleanup, original_worker = fixture
    material, objects, states, calls, review, request, timers, body, locked = machine
    reactor = material.printer.get_reactor()
    material._begin_print_cancel('timer-terminal', binding)
    worker = timers[-1]
    assert len(registered) == 2
    locked[0] = False
    if exit_path == 'superseded': material._print_cancel['id'] = 'newer-request'
    elif exit_path == 'terminal': material._print_cancel['state'] = 'unknown'
    elif exit_path == 'owner': objects['openace'] = object()
    elif exit_path == 'job': objects['print_stats'].filename = 'another.gcode'
    elif exit_path == 'cleanup':
        monkeypatch.setattr(material._cancellation(), '_cancel_print_cleanup', lambda *args: (_ for _ in ()).throw(ValueError('cleanup fault')))
    elif exit_path == 'status':
        monkeypatch.setattr(objects['virtual_sdcard'], 'is_active', lambda: (_ for _ in ()).throw(ValueError('status fault')))
    elif exit_path == 'persist':
        monkeypatch.setattr(material._recovery_storage(), '_write_recovery_json', lambda *args: (_ for _ in ()).throw(OSError('journal fault')))
    assert worker.callback(2.) == reactor.NEVER
    assert len(registered) == 1 and worker not in registered
    if exit_path == 'complete': assert material._print_cancel['state'] == 'complete'
    elif exit_path == 'superseded': assert material._print_cancel['id'] == 'newer-request'
    else: assert material._print_cancel['state'] == 'unknown'
    # A stale direct callback cannot redo cleanup or unregister another timer.
    before = list(cleanup)
    assert worker.callback(3.) == reactor.NEVER
    assert cleanup == before and len(registered) == 1


@pytest.mark.parametrize('wait_for', ['mutex', 'sd', 'sd_command'])
def test_print_cancel_wait_retains_only_live_timer(tracked_cancel_timers, monkeypatch, wait_for):
    fixture, registered = tracked_cancel_timers
    machine, binding, cleanup, original_worker = fixture
    material, objects, states, calls, review, request, timers, body, locked = machine
    material._begin_print_cancel('timer-wait', binding)
    locked[0] = wait_for == 'mutex'
    sd = objects['virtual_sdcard']
    monkeypatch.setattr(sd, 'is_active', lambda: wait_for == 'sd')
    monkeypatch.setattr(sd, 'is_cmd_from_sd', lambda: wait_for == 'sd_command')
    worker = timers[-1]
    for now in (1., 2., 3.):
        assert worker.callback(now) == now + .05
        assert len(registered) == 2 and cleanup == []
    material._print_cancel['state'] = 'unknown'
    assert worker.callback(4.) == material.printer.get_reactor().NEVER
    assert len(registered) == 1


@pytest.mark.parametrize('failure', ['registration', 'missing_handle', 'activation', 'activation_journal'])
def test_print_cancel_timer_setup_failure_preserves_unknown_fence(tracked_cancel_timers, monkeypatch, failure):
    fixture, registered = tracked_cancel_timers
    machine, binding, cleanup, original_worker = fixture
    material, objects, states, calls, review, request, timers, body, locked = machine
    reactor = material.printer.get_reactor()
    if failure == 'registration':
        monkeypatch.setattr(reactor, 'register_timer', lambda *args: (_ for _ in ()).throw(ValueError('registration fault')))
    elif failure == 'missing_handle':
        monkeypatch.setattr(reactor, 'register_timer', lambda *args: None)
    else:
        def activate(timer, when):
            timer.when = when  # Include scheduling before the exception.
            if failure == 'activation_journal':
                monkeypatch.setattr(material._recovery_storage(), '_write_recovery_json', lambda *args: (_ for _ in ()).throw(OSError('journal fault')))
            raise ValueError('activation fault')
        monkeypatch.setattr(reactor, 'update_timer', activate)
    with pytest.raises(ValueError):
        material._begin_print_cancel('timer-setup', binding)
    assert len(registered) == 1 and cleanup == []
    assert material._print_cancel['state'] == 'unknown'
    assert material._cancellation()._print_cancel_unresolved()
    if failure.startswith('activation'):
        assert timers[-1].callback(2.) == reactor.NEVER
        assert len(registered) == 1 and cleanup == []


def test_repeated_resolved_cancellations_do_not_accumulate_timers(tracked_cancel_timers, monkeypatch):
    fixture, registered = tracked_cancel_timers
    machine, binding, cleanup, original_worker = fixture
    material, objects, states, calls, review, request, timers, body, locked = machine
    # Isolate timer lifetime from SD close/reopen; retain actual admission,
    # cancellation receipt persistence, dispatch and terminal handling.
    monkeypatch.setattr(material._cancellation(), '_cancel_print_cleanup', lambda *args: None)
    locked[0] = False
    for number in range(20):
        material._begin_print_cancel('timer-repeat-%d' % number, binding)
        assert len(registered) == 2
        timers[-1].callback(float(number))
        assert material._print_cancel['state'] == 'complete'
        assert len(registered) == 1


def test_print_cancel_intent_fences_queued_work_and_waits_for_owner(managed_cancel_intent):
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material, objects, states, calls, review, request, timers, body, locked = fixture
    material.filament_operation = {'id': 'feed', 'session': material.session_id, 'state': 'running'}
    result = material._begin_print_cancel('cancel-print', binding)
    assert result['state'] == 'pending' and cleanup == []
    assert material.filament_operation['cancel_requested'] is True
    assert objects['virtual_sdcard'].must_pause_work is True
    assert not material._filament_context_valid({'pause_origin': {}}, 1)
    assert not material._idle_for_filament_settings(1)
    with pytest.raises(ValueError, match='cancellation'):
        material.cmd_CHECK_RESUME(FakeCommand())
    worker = timers[-1]
    assert worker.callback(1) == 1.05 and cleanup == []
    locked[0] = False
    assert worker.callback(2) == material.printer.get_reactor().NEVER
    assert material._print_cancel['state'] == 'complete'
    assert not material._cancellation()._print_cancel_unresolved()
    assert material.filament_operation['state'] == 'running'  # Not fabricated as completed.
    before = list(cleanup)
    worker.callback(3)
    with pytest.raises(ValueError, match='already attempted'):
        material._begin_print_cancel('cancel-print', binding)
    assert cleanup == before


@pytest.mark.parametrize('change', ['session', 'owner', 'file'])
def test_print_cancel_intent_does_not_cleanup_replaced_job(managed_cancel_intent, change):
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material, objects, states, calls, review, request, timers, body, locked = fixture
    material._begin_print_cancel('cancel-print', binding)
    if change == 'session': material.session_id = 'new-session'
    elif change == 'owner': objects['AFC'] = object()
    else: objects['print_stats'].filename = 'new.gcode'
    locked[0] = False
    timers[-1].callback(2)
    assert material._print_cancel['state'] == 'unknown' and cleanup == []
    assert material._cancellation()._print_cancel_unresolved()


@pytest.mark.parametrize('state', ['pending', 'unknown', 'complete'])
def test_print_cancel_restore_preserves_record_and_never_schedules(managed_cancel_intent, state):
    from pathlib import Path
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material, objects, states, calls, review, request, timers, body, locked = fixture
    material._begin_print_cancel('cancel-print', binding)
    record = dict(material._print_cancel, state=state)
    material._write_recovery_json(material._cancellation()._print_cancel_path(), record)
    path = Path(material._cancellation()._print_cancel_path())
    original = path.read_bytes()
    count = len(timers)
    material.session_id = 'new-session'
    material._restore_print_cancel()
    assert material._print_cancel['state'] == ('unknown' if state == 'pending' else state)
    assert path.read_bytes() == original and len(timers) == count and cleanup == []


def test_print_cancel_persistence_failure_still_stops_and_schedules(managed_cancel_intent, monkeypatch):
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material, objects, states, calls, review, request, timers, body, locked = fixture
    count = len(timers)
    def fail(path, value):
        assert objects['virtual_sdcard'].must_pause_work
        raise OSError('disk failed')
    monkeypatch.setattr(material._recovery_storage(), '_write_recovery_json', fail)
    material._begin_print_cancel('cancel-print', binding)
    assert len(timers) == count + 1 and cleanup == []
    assert material._print_cancel['state'] == 'pending'
    assert material._print_cancel['persistence_error'] == 'disk failed'


def test_cancel_cleanup_journal_failure_does_not_prevent_file_and_pause_cleanup(managed_cancel_cleanup):
    fixture, binding, cleanup, original_worker = managed_cancel_cleanup
    material, objects, states, calls, review, request, timers, body, mutex = fixture
    def fail_progress(name, state='running'): raise OSError('progress storage failed')
    result = material._cancellation()._cancel_print_cleanup(binding, fail_progress)
    assert result['state'] == 'complete'
    assert any('progress storage failed' in warning for warning in result['warnings'])
    assert cleanup[:2] == ['M400', 'TURN_OFF_HEATERS']
    assert objects['virtual_sdcard'].current_file is None and binding['handle'].closed
    assert objects['pause_resume'].get_status(1)['is_paused'] is False


def test_print_cancel_waits_for_sd_worker_before_cleanup(managed_cancel_intent):
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material, objects, states, calls, review, request, timers, body, locked = fixture
    material._begin_print_cancel('cancel-print', binding)
    locked[0] = False
    sd = objects['virtual_sdcard']
    sd.work_timer = object()
    assert timers[-1].callback(2) == 2.05 and cleanup == []
    sd.work_timer = None
    timers[-1].callback(3)
    assert material._print_cancel['state'] == 'complete'


def test_print_cancel_final_receipt_failure_retains_actual_completion(managed_cancel_intent, monkeypatch):
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material, objects, states, calls, review, request, timers, body, locked = fixture
    material._begin_print_cancel('cancel-print', binding)
    original = material._write_recovery_json
    def fail_complete(path, value):
        if path == material._cancellation()._print_cancel_path() and value.get('state') == 'complete':
            raise OSError('completion storage failed')
        original(path, value)
    monkeypatch.setattr(material._recovery_storage(), '_write_recovery_json', fail_complete)
    locked[0] = False
    timers[-1].callback(2)
    assert binding['handle'].closed and objects['print_stats'].state == 'cancelled'
    assert material._print_cancel['state'] == 'complete' and not material._cancellation()._print_cancel_unresolved()
    assert material._print_cancel['persistence_error'] == 'completion storage failed'
    before = list(cleanup)
    timers[-1].callback(3)
    assert cleanup == before


def print_cancel_review(material, binding, request_id='public-cancel'):
    web = CancelWebRequest(id=request_id, session=material.session_id, file=binding['file'])
    material._handle_print_cancel_review(web)
    return web.response['request']


@pytest.mark.parametrize("job_state", ["printing", "paused", "error"])
def test_public_print_cancel_requires_separate_review_and_confirmation(managed_cancel_intent, job_state):
    from pathlib import Path
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material, objects, states, calls, review, request, timers, body, locked = fixture
    objects["print_stats"].state = job_state
    count = len(timers)
    reviewed = print_cancel_review(material, binding)
    assert print_cancel_review(material, binding) == reviewed
    assert len(timers) == count and cleanup == []
    assert not Path(material._cancellation()._print_cancel_path()).exists()
    assert not material._cancellation()._print_cancel_unresolved()
    confirmation = CancelWebRequest(**reviewed)
    material._handle_print_cancel(confirmation)
    assert confirmation.response['state'] == 'pending'
    assert len(timers) == count + 1 and cleanup == []
    receipt = dict(material._print_cancel)
    with pytest.raises(ValueError, match='already used'):
        material._handle_print_cancel(CancelWebRequest(**reviewed))
    assert material._print_cancel == receipt and len(timers) == count + 1
    locked[0] = False
    timers[-1].callback(material.printer.monotonic())
    assert material._print_cancel['state'] == 'complete'


@pytest.mark.parametrize('field', ['id', 'session', 'file', 'token'])
def test_public_print_cancel_rejects_changed_review_fields(managed_cancel_intent, field):
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material, objects, states, calls, review, request, timers, body, locked = fixture
    reviewed = print_cancel_review(material, binding)
    count = len(timers)
    changed = dict(reviewed, **{field: 'changed'})
    with pytest.raises(ValueError, match='stale, changed'):
        material._handle_print_cancel(CancelWebRequest(**changed))
    assert cleanup == [] and len(timers) == count and not material._cancellation()._print_cancel_unresolved()
    assert material._cancellation()._print_cancel_tickets[reviewed['id']]['used'] is False


@pytest.mark.parametrize('change', ['session', 'owner', 'readiness', 'same_name_new_handle', 'expired'])
def test_public_print_cancel_cannot_transfer_review_to_changed_job(managed_cancel_intent, change):
    import io
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material, objects, states, calls, review, request, timers, body, locked = fixture
    reviewed = print_cancel_review(material, binding)
    count = len(timers)
    if change == 'session': material.session_id = 'new-session'
    elif change == 'owner': objects['openace'] = object()
    elif change == 'readiness': states['webhooks']['state'] = 'shutdown'
    elif change == 'expired': material._cancellation()._print_cancel_tickets[reviewed['id']]['expires'] = 0.
    else: objects['virtual_sdcard'].current_file = io.StringIO('a different print')
    with pytest.raises(ValueError):
        material._handle_print_cancel(CancelWebRequest(**reviewed))
    assert cleanup == [] and len(timers) == count and not material._cancellation()._print_cancel_unresolved()


def test_public_print_cancel_lost_reply_preserves_receipt_without_resubmission(managed_cancel_intent):
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material, objects, states, calls, review, request, timers, body, locked = fixture
    reviewed = print_cancel_review(material, binding)
    class LostReply(CancelWebRequest):
        def send(self, value): raise OSError('reply disconnected')
    with pytest.raises(ValueError, match='reply disconnected'):
        material._handle_print_cancel(LostReply(**reviewed))
    receipt = dict(material._print_cancel)
    count = len(timers)
    with pytest.raises(ValueError, match='already used'):
        material._handle_print_cancel(CancelWebRequest(**reviewed))
    assert material._print_cancel == receipt and len(timers) == count and cleanup == []


@pytest.fixture
def interrupted_print_cancel(managed_cancel_intent):
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material, objects, states, calls, review, request, timers, body, locked = fixture
    material._begin_print_cancel('cancel-print', binding)
    material._print_cancel.update(state='unknown', message='interrupted')
    material._write_recovery_json(material._cancellation()._print_cancel_path(), material._print_cancel)
    locked[0] = False
    return managed_cancel_intent


def cancel_resolution_review(material, request_id='resolve-cancel'):
    web = CancelWebRequest(id=request_id, session=material.session_id, cancel_id='cancel-print')
    material._handle_print_cancel_resolution_review(web)
    return web.response['request']


def confirm_cancel_resolution(material, request):
    return material.cmd_RESOLVE_PRINT_CANCEL(FakeCommand(REQUEST=json.dumps(request).encode().hex()))


def test_cancel_resolution_finishes_original_open_file_only_after_confirmation(interrupted_print_cancel):
    from pathlib import Path
    fixture, binding, cleanup, original_worker = interrupted_print_cancel
    material, objects, states, calls, review, request, timers, body, locked = fixture
    original = Path(material._cancellation()._print_cancel_path()).read_bytes()
    reviewed = cancel_resolution_review(material)
    assert reviewed['action'] == 'finish_cleanup'
    assert cleanup == [] and Path(material._cancellation()._print_cancel_path()).read_bytes() == original
    locked[0] = True
    confirm_cancel_resolution(material, reviewed)
    assert binding['handle'].closed and objects['print_stats'].state == 'cancelled'
    assert material._print_cancel_resolution['state'] == 'complete'
    assert material._print_cancel['state'] == 'complete'
    before = list(cleanup)
    with pytest.raises(ValueError, match='already used'):
        confirm_cancel_resolution(material, reviewed)
    assert cleanup == before and material._print_cancel_resolution['state'] == 'complete'


def test_cancel_resolution_acknowledges_finished_cleanup_without_commands(managed_cancel_intent):
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material, objects, states, calls, review, request, timers, body, locked = fixture
    material._begin_print_cancel('cancel-print', binding)
    locked[0] = False
    timers[-1].callback(2)
    material._print_cancel.update(state='unknown')
    material._write_recovery_json(material._cancellation()._print_cancel_path(), material._print_cancel)
    material.session_id = 'after-restart'
    material._restore_print_cancel()
    cleanup.clear()
    reviewed = cancel_resolution_review(material)
    assert reviewed['action'] == 'acknowledge_complete'
    locked[0] = True
    confirm_cancel_resolution(material, reviewed)
    assert cleanup == [] and material._print_cancel['state'] == 'complete'
    assert material._command_generation == 3  # Intent, completion, explicit resolution.


def test_cancel_resolution_explicitly_discards_remaining_saved_job(interrupted_print_cancel):
    fixture, binding, cleanup, original_worker = interrupted_print_cancel
    material, objects, states, calls, review, request, timers, body, locked = fixture
    objects['virtual_sdcard'].do_cancel()
    material.session_id = 'after-restart'
    material._restore_print_cancel()
    reviewed = cancel_resolution_review(material)
    assert reviewed['action'] == 'discard_saved_job' and reviewed['job_id']
    assert material._read_recovery_job()['state'] == 'committed' and cleanup == []
    locked[0] = True
    confirm_cancel_resolution(material, reviewed)
    assert material._read_recovery_job()['state'] == 'invalidated'
    assert material._print_cancel['state'] == 'complete'
    assert cleanup[0:2] == ['M400', 'TURN_OFF_HEATERS']


@pytest.mark.parametrize('change', ['restart_open_file', 'new_handle', 'other_saved_job'])
def test_cancel_resolution_refuses_unidentified_job(interrupted_print_cancel, change):
    import io
    fixture, binding, cleanup, original_worker = interrupted_print_cancel
    material, objects, states, calls, review, request, timers, body, locked = fixture
    if change == 'restart_open_file':
        material.session_id = 'after-restart'
        material._restore_print_cancel()
    elif change == 'new_handle': objects['virtual_sdcard'].current_file = io.StringIO('new job same filename')
    else:
        job = material._read_recovery_job()
        job['file']['path'] = 'different.gcode'
        material._write_recovery_job(job)
    with pytest.raises(ValueError): cancel_resolution_review(material)
    assert cleanup == [] and material._print_cancel['state'] == 'unknown'


@pytest.mark.parametrize('change', ['heater', 'job', 'receipt', 'owner', 'session'])
def test_cancel_resolution_rechecks_evidence_before_cleanup(interrupted_print_cancel, change):
    fixture, binding, cleanup, original_worker = interrupted_print_cancel
    material, objects, states, calls, review, request, timers, body, locked = fixture
    reviewed = cancel_resolution_review(material)
    if change == 'heater': states['extruder2']['target'] += 1
    elif change == 'job':
        job = material._read_recovery_job()
        job['id'] = 'replacement-job'
        material._write_recovery_job(job)
    elif change == 'receipt':
        material._print_cancel['message'] = 'changed result'
        material._write_recovery_json(material._cancellation()._print_cancel_path(), material._print_cancel)
    elif change == 'owner': objects['openace'] = object()
    else: material.session_id = 'new-session'
    locked[0] = True
    with pytest.raises(ValueError): confirm_cancel_resolution(material, reviewed)
    assert cleanup == [] and material._print_cancel['state'] == 'unknown'


def test_cancel_resolution_failure_keeps_result_but_finishes_independent_cleanup(interrupted_print_cancel):
    fixture, binding, cleanup, original_worker = interrupted_print_cancel
    material, objects, states, calls, review, request, timers, body, locked = fixture
    reviewed = cancel_resolution_review(material)
    original = objects['gcode'].run_script_from_command
    def fail_drain(command):
        if command == 'M400': raise ValueError('drain failed')
        original(command)
    objects['gcode'].run_script_from_command = fail_drain
    locked[0] = True
    with pytest.raises(ValueError, match='drain failed'): confirm_cancel_resolution(material, reviewed)
    assert material._print_cancel_resolution['state'] == 'unknown'
    assert material._cancellation()._print_cancel_unresolved() and binding['handle'].closed
    objects['gcode'].run_script_from_command = original
    locked[0] = False
    fresh = cancel_resolution_review(material, 'resolve-again')
    locked[0] = True
    confirm_cancel_resolution(material, fresh)
    assert material._print_cancel['state'] == 'complete'


def test_cancel_resolution_finishes_idle_heater_and_pause_cleanup(managed_cancel_intent):
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material, objects, states, calls, review, request, timers, body, locked = fixture
    material._begin_print_cancel('cancel-print', binding)
    locked[0] = False
    timers[-1].callback(2)
    material._print_cancel.update(state='unknown')
    material._write_recovery_json(material._cancellation()._print_cancel_path(), material._print_cancel)
    objects['pause_resume'].get_status(1)['is_paused'] = True
    states['extruder2']['target'] = 100.
    cleanup.clear()
    reviewed = cancel_resolution_review(material)
    assert reviewed['action'] == 'finish_idle_cleanup'
    locked[0] = True
    confirm_cancel_resolution(material, reviewed)
    assert states['extruder2']['target'] == 0
    assert objects['pause_resume'].get_status(1)['is_paused'] is False
    assert material._print_cancel['state'] == 'complete'
    assert not any(command.startswith('_WMP_PRINT_LOWER_BED') for command in cleanup)


@pytest.mark.parametrize('encoded', ['zz', '00', '5b5d', '7b226964223a5b5d7d'])
def test_cancel_resolution_malformed_input_is_command_error(interrupted_print_cancel, encoded):
    fixture, binding, cleanup, original_worker = interrupted_print_cancel
    material = fixture[0]
    class CommandError(Exception): pass
    command = FakeCommand(REQUEST=encoded)
    command.error = CommandError
    with pytest.raises(CommandError): material.cmd_RESOLVE_PRINT_CANCEL(command)
    assert cleanup == [] and material._print_cancel['state'] == 'unknown'


def test_cancel_resolution_expired_review_does_not_clear_hold(interrupted_print_cancel):
    fixture, binding, cleanup, original_worker = interrupted_print_cancel
    material = fixture[0]
    reviewed = cancel_resolution_review(material)
    material._cancellation()._print_cancel_resolution_tickets[reviewed['id']]['expires'] = 0.
    fixture[-1][0] = True
    with pytest.raises(ValueError, match='stale'): confirm_cancel_resolution(material, reviewed)
    assert cleanup == [] and material._cancellation()._print_cancel_unresolved()


def test_cancel_resolution_lost_response_does_not_replace_completed_receipt(interrupted_print_cancel):
    fixture, binding, cleanup, original_worker = interrupted_print_cancel
    material = fixture[0]
    reviewed = cancel_resolution_review(material)
    fixture[-1][0] = True
    command = FakeCommand(REQUEST=json.dumps(reviewed).encode().hex())
    def lose_reply(message): raise OSError('reply lost')
    command.respond_info = lose_reply
    with pytest.raises(OSError, match='reply lost'):
        material.cmd_RESOLVE_PRINT_CANCEL(command)
    assert material._print_cancel['state'] == 'complete'
    assert material._print_cancel_resolution['state'] == 'complete'
    assert material._recovery_attempt.record['continuation']['state'] == 'cancelled'


def test_cancel_generation_retires_toolhead_callback_after_hold_cleared(toolhead_material):
    material, objects, state, scripts, callbacks = toolhead_material
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material))
    material._command_generation = 1
    material._print_cancel = {'state': 'complete'}
    callbacks.pop()(1)
    assert scripts == []
    assert material.toolhead_operation['state'] == 'refused'
    assert 'invalidated' in material.toolhead_operation['message']


def test_cancel_generation_invalidates_filament_review_after_hold_cleared(sequence_material, monkeypatch):
    material, objects = sequence_material
    command = sequence_command(material)
    material._command_generation = 1
    material._print_cancel = {'state': 'complete'}
    monkeypatch.setattr('wm_material.run_standalone_extrusion_sequence', lambda *args: pytest.fail('retired feed dispatched'))
    with pytest.raises(ValueError, match='changed'):
        material.cmd_FILAMENT_SEQUENCE(command)
    assert material.filament_operation['state'] == 'refused'


def test_cancel_generation_survives_cleanup_and_invalidates_old_context(managed_cancel_intent):
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material, objects, states, calls, review, request, timers, body, locked = fixture
    old = getattr(material, '_command_generation', 0)
    material._begin_print_cancel('cancel-generation', binding)
    assert material._command_generation == old + 1
    locked[0] = False
    timers[-1].callback(2)
    assert material._print_cancel['state'] == 'complete'
    assert not material._filament_context_valid({'command_generation': old}, 2)
    # Requests captured while cancellation was pending are retired too.
    assert material._command_generation == old + 2
    assert not material._filament_context_valid({'command_generation': old + 1}, 2)
    # A new request is not permanently poisoned by the retired generations.
    material._material_settings()._idle_for_filament_settings = lambda now: True
    assert material._filament_context_valid({'command_generation': old + 2}, 2)


@pytest.mark.parametrize('change', ['none', 'generation', 'session', 'pending', 'unknown', 'owner'])
def test_command_generation_stops_remaining_vendor_rpc_script(material, change):
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace
    from contextlib import nullcontext
    path = Path(__file__).resolve().parents[1] / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/gcode.py'
    spec = importlib.util.spec_from_file_location('generation_vendor_gcode', path)
    vendor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vendor)
    dispatcher = vendor.GCodeDispatch.__new__(vendor.GCodeDispatch)
    events = []
    dispatcher.printer = SimpleNamespace(quick_stop_flag=False, send_event=events.append,
        invoke_shutdown=lambda message: pytest.fail(message))
    dispatcher.mutex = nullcontext()
    dispatcher._respond_error = events.append
    dispatcher.respond_info = lambda *args, **kwargs: None
    dispatcher.gcode_handlers = {
        'WMP_CHECK_COMMAND_GENERATION': lambda command: material.cmd_CHECK_COMMAND_GENERATION(dispatcher._get_extended_params(command)),
        'M104': lambda command: events.append('heat-dispatched'),
        'G1': lambda command: events.append('motion-dispatched')}
    script = 'WMP_CHECK_COMMAND_GENERATION SESSION=%s GENERATION=0\nM104 S220\nG1 E10' % material.session_id
    if change == 'generation': material._command_generation = 1
    elif change == 'session': material.session_id = 'new-session'
    elif change in ('pending', 'unknown'): material._print_cancel = {'state': change}
    elif change == 'owner': material.printer.owner = object()
    if change in ('none', 'unknown'):
        dispatcher.run_script(script)
        assert events == ['heat-dispatched', 'motion-dispatched']
    else:
        with pytest.raises(vendor.CommandError): dispatcher.run_script(script)
        assert 'heat-dispatched' not in events and 'motion-dispatched' not in events


def test_cancel_stages_keep_failed_drain_when_heater_cleanup_completes(managed_cancel_intent):
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material, objects, states, calls, review, request, timers, body, locked = fixture
    original = objects['gcode'].run_script_from_command
    def fail_drain(command):
        if command == 'M400': raise ValueError('drain interrupted')
        original(command)
    objects['gcode'].run_script_from_command = fail_drain
    material._begin_print_cancel('stage-failure', binding)
    locked[0] = False
    timers[-1].callback(2)
    stages = {s['name']: s['state'] for s in material._print_cancel['stages']}
    assert stages == {'stopping': 'complete', 'draining': 'failed', 'cooling': 'complete',
                      'invalidating': 'complete', 'cancelling': 'complete', 'clearing_pause': 'complete'}
    assert material._print_cancel['state'] == 'unknown'
    assert binding['handle'].closed


@pytest.mark.parametrize('version', [1, 2])
def test_cancel_stage_restore_preserves_bytes_and_does_not_invent_completion(managed_cancel_intent, version):
    from pathlib import Path
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material = fixture[0]
    material._begin_print_cancel('stage-restore', binding)
    record = material._print_cancel
    if version == 1:
        record['version'] = 1
        del record['stages']
        material._write_recovery_json(material._cancellation()._print_cancel_path(), record)
    path = Path(material._cancellation()._print_cancel_path())
    before = path.read_bytes()
    material._restore_print_cancel()
    assert path.read_bytes() == before and cleanup == []
    assert material._print_cancel['state'] == 'unknown'
    if version == 1: assert 'stages' not in material._print_cancel
    else:
        assert material._print_cancel['stages'][0]['state'] == 'unknown'
        assert all(s['state'] == 'pending' for s in material._print_cancel['stages'][1:])


@pytest.mark.parametrize('change', ['missing', 'reordered', 'state', 'duplicate'])
def test_cancel_stage_restore_refuses_corrupt_progress(managed_cancel_intent, change):
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material = fixture[0]
    material._begin_print_cancel('bad-stages', binding)
    record = material._print_cancel
    if change == 'missing': del record['stages']
    elif change == 'reordered': record['stages'].reverse()
    elif change == 'state': record['stages'][0]['state'] = 'guessed'
    else: record['stages'][1] = record['stages'][0]
    material._write_recovery_json(material._cancellation()._print_cancel_path(), record)
    material._restore_print_cancel()
    assert material._cancellation()._print_cancel_unresolved()
    assert 'unreadable' in material._print_cancel['message']
    assert cleanup == []

@pytest.fixture
def legacy_cancel_routes(managed_cancel_intent):
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material, objects, states, calls, review, request, timers, body, locked = fixture
    gcode = objects['gcode']
    forwarded = []
    handlers = {'CANCEL_PRINT': lambda command: forwarded.append('stock-cancel')}
    def register(name, callback, **kwargs):
        old = handlers.pop(name, None)
        if callback is not None: handlers[name] = callback
        return old
    gcode.register_command = register
    gcode.run_script = lambda script: forwarded.append(script)
    gcode.error = ValueError
    material._cancel_routes_ready()
    return fixture, binding, cleanup, handlers, forwarded


@pytest.mark.parametrize('script', ['CANCEL_PRINT', 'cancel_print ; stop', 'N17cancel_print',
    'M400\nCANCEL_PRINT\nG28', 'CANCEL_PRINT\nCANCEL_PRINT', 'CANCEL_PRINT OTHER=1'])
def test_legacy_cancel_records_intent_before_mutex_without_batch_side_effects(legacy_cancel_routes, script):
    fixture, binding, cleanup, handlers, forwarded = legacy_cancel_routes
    material, objects, states, calls, review, request, timers, body, locked = fixture
    assert locked[0]  # A service owns commands; original run_script would wait.
    material.filament_operation = {'state': 'running', 'session': material.session_id}
    objects['gcode'].run_script(script)
    assert forwarded == [] and cleanup == []
    assert material._print_cancel['state'] == 'pending'
    assert material._cancellation()._print_cancel_live_binding['handle'] is binding['handle']
    assert material.filament_operation['cancel_requested'] is True
    assert objects['virtual_sdcard'].must_pause_work
    objects['gcode'].run_script(script)  # Same live job coalesces without another worker.
    assert forwarded == []
    locked[0] = False
    timers[-1].callback(1.)
    assert material._print_cancel['state'] == 'complete'
    assert objects['print_stats'].state == 'cancelled'
    assert 'G28' not in cleanup


@pytest.mark.parametrize('script', ['M25', '; CANCEL_PRINT', 'RESPOND MSG="CANCEL_PRINT"',
    'SET_GCODE_VARIABLE MACRO=CANCEL_PRINT VARIABLE=x VALUE=1', 'CANCEL_PRINT1', 'MY_CANCEL_PRINT'])
def test_legacy_cancel_does_not_intercept_other_commands(legacy_cancel_routes, script):
    fixture, binding, cleanup, handlers, forwarded = legacy_cancel_routes
    material, objects, *unused = fixture
    objects['gcode'].run_script(script)
    assert len(forwarded) == 1
    if material._script_command_names(script):
        assert forwarded[0].endswith('\n' + script)
        assert forwarded[0].startswith('WMP_CHECK_SCRIPT_GENERATION ')
    else:
        assert forwarded == [script]
    assert not getattr(material, '_print_cancel', {})


def test_nested_cancel_stops_before_unwinding_and_other_owner_keeps_route(legacy_cancel_routes):
    fixture, binding, cleanup, handlers, forwarded = legacy_cancel_routes
    material, objects, *unused = fixture
    with pytest.raises(ValueError, match='remaining macro commands retired'):
        handlers['CANCEL_PRINT'](FakeCommand())
    assert forwarded == [] and cleanup == []
    objects['openace'] = object()
    objects['gcode'].run_script('M400\nCANCEL_PRINT\nG28')
    handlers['CANCEL_PRINT'](FakeCommand())
    assert forwarded == ['M400\nCANCEL_PRINT\nG28', 'stock-cancel']
    original = objects['gcode'].run_script
    material._cancel_routes_ready()
    assert objects['gcode'].run_script is original


def test_standard_remote_cancel_uses_independent_managed_ingress(legacy_cancel_routes):
    import ast
    from pathlib import Path
    from types import SimpleNamespace
    fixture, binding, cleanup, handlers, forwarded = legacy_cancel_routes
    material, objects, *unused = fixture
    path = Path(__file__).resolve().parents[1] / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras/pause_resume.py'
    cls = next(node for node in ast.parse(path.read_text()).body if isinstance(node, ast.ClassDef))
    method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == '_handle_cancel_request')
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), namespace)
    namespace['_handle_cancel_request'](SimpleNamespace(gcode=objects['gcode']), object())
    assert material._print_cancel['state'] == 'pending' and forwarded == [] and cleanup == []


def test_sd_cancel_ingress_waits_for_dispatch_exit_before_cleanup(legacy_cancel_routes):
    fixture, binding, cleanup, handlers, forwarded = legacy_cancel_routes
    material, objects, states, calls, review, request, timers, body, locked = fixture
    sd = objects['virtual_sdcard']
    sd.cmd_from_sd = True
    objects['gcode'].run_script('CANCEL_PRINT')
    locked[0] = False
    assert timers[-1].callback(1.) == 1.05 and cleanup == []
    sd.cmd_from_sd = False
    objects['print_stats'].state = 'error'  # The SD error handler finishes its stack.
    timers[-1].callback(2.)
    assert material._print_cancel['state'] == 'complete' and forwarded == []

@pytest.fixture
def guarded_legacy_dispatch(managed_cancel_intent):
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material, objects, states, calls, review, request, timers, body, locked = fixture
    path = Path(__file__).resolve().parents[1] / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/gcode.py'
    spec = importlib.util.spec_from_file_location('legacy_queue_vendor_gcode', path)
    vendor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(vendor)
    dispatcher = vendor.GCodeDispatch.__new__(vendor.GCodeDispatch)
    events, waiting = [], [None]
    class Mutex:
        def test(self): return locked[0]
        def __enter__(self):
            callback, waiting[0] = waiting[0], None
            if callback: callback()
            locked[0] = True
        def __exit__(self, *args): locked[0] = False
    dispatcher.printer = SimpleNamespace(quick_stop_flag=False, send_event=events.append,
        invoke_shutdown=lambda message: pytest.fail(message))
    dispatcher.mutex = Mutex()
    dispatcher._respond_error = events.append
    dispatcher.respond_info = lambda *args, **kwargs: None
    dispatcher.gcode_handlers = dispatcher.ready_gcode_handlers = {
        'CANCEL_PRINT': lambda command: events.append('stock-cancel'),
        'WMP_CHECK_SCRIPT_GENERATION': lambda command: material.cmd_CHECK_SCRIPT_GENERATION(dispatcher._get_extended_params(command)),
        'WMP_RESOLVE_PRINT_CANCEL': lambda command: events.append('resolution'),
        'TURN_OFF_HEATERS': lambda command: events.append('heaters-off'),
        'M112': lambda command: events.append('emergency-stop'),
        'M104': lambda command: events.append('heat'),
        'G1': lambda command: events.append('move')}
    dispatcher.base_gcode_handlers, dispatcher.gcode_help = {}, {}
    dispatcher.is_printer_ready = True
    dispatcher.run_script_from_command = objects['gcode'].run_script_from_command
    objects['gcode'] = dispatcher
    material._cancel_routes_ready()
    return fixture, dispatcher, events, waiting, vendor


@pytest.mark.parametrize('command', ['RESTART', 'FIRMWARE_RESTART'])
@pytest.mark.parametrize('ready', [False, True])
def test_explicit_shutdown_restart_isolated_from_cancel_hold(guarded_legacy_dispatch, command, ready):
    fixture, dispatcher, events, waiting, vendor = guarded_legacy_dispatch
    material = fixture[0]
    material._print_cancel = {'state': 'unknown', 'id': 'keep-evidence'}
    dispatcher.is_printer_ready = ready
    dispatcher.gcode_handlers[command] = lambda gcmd: events.append('restart-request')
    dispatcher.run_script(command.lower() + ' ; explicit recovery')
    assert events == ['restart-request']
    assert material._print_cancel == {'state': 'unknown', 'id': 'keep-evidence'}


def test_shutdown_restart_batch_cannot_bypass_cancel_hold(guarded_legacy_dispatch):
    fixture, dispatcher, events, waiting, vendor = guarded_legacy_dispatch
    material = fixture[0]
    material._print_cancel = {'state': 'pending'}
    dispatcher.is_printer_ready = False
    dispatcher.gcode_handlers['RESTART'] = lambda gcmd: events.append('restart-request')
    with pytest.raises(vendor.CommandError, match='invalidated'):
        dispatcher.run_script('RESTART\nG1 X10')
    assert 'restart-request' not in events and 'move' not in events


@pytest.mark.parametrize('change', ['cancel_pending', 'cancel_complete', 'session', 'owner'])
def test_legacy_batch_queued_before_cancel_cannot_run_after_mutex_wait(guarded_legacy_dispatch, change):
    fixture, dispatcher, events, waiting, vendor = guarded_legacy_dispatch
    material, objects, states, calls, review, request, timers, body, locked = fixture
    def after_wait():
        if change == 'session': material.session_id = 'new-session'
        elif change == 'owner': objects['openace'] = object()
        else:
            locked[0] = False
            dispatcher.run_script('CANCEL_PRINT')
            assert material._print_cancel['state'] == 'pending'
            if change == 'cancel_complete':
                timers[-1].callback(2.)
                assert material._print_cancel['state'] == 'complete'
    waiting[0] = after_wait
    with pytest.raises(vendor.CommandError): dispatcher.run_script('M104 S220\nG1 X10')
    assert 'heat' not in events and 'move' not in events and 'stock-cancel' not in events


@pytest.mark.parametrize('state', ['pending', 'unknown'])
@pytest.mark.parametrize('script', ['M104 S220\nG1 X10', 'TURN_OFF_HEATERS\nG1 X10',
    'WMP_RESOLVE_PRINT_CANCEL REQUEST=abcd\nM104 S220'])
def test_cancel_hold_rejects_entire_non_resolution_batch(guarded_legacy_dispatch, state, script):
    fixture, dispatcher, events, waiting, vendor = guarded_legacy_dispatch
    material, *unused = fixture
    material._print_cancel = {'state': state}
    if state == 'pending':
        with pytest.raises(vendor.CommandError): dispatcher.run_script(script)
        assert not set(events).intersection({'heat', 'move', 'resolution', 'heaters-off'})
    else:
        dispatcher.run_script(script)
        assert 'move' in events or 'heat' in events


@pytest.mark.parametrize('script,event', [('TURN_OFF_HEATERS', 'heaters-off'),
    ('; reviewed cleanup\nWMP_RESOLVE_PRINT_CANCEL REQUEST=abcd', 'resolution'), ('M112', 'emergency-stop')])
def test_cancel_hold_keeps_scoped_cleanup_and_emergency_available(guarded_legacy_dispatch, script, event):
    fixture, dispatcher, events, waiting, vendor = guarded_legacy_dispatch
    material, *unused = fixture
    material._print_cancel = {'state': 'unknown'}
    dispatcher.run_script(script)
    assert events == [event]


def test_script_queued_during_hold_is_retired_even_if_hold_clears_before_dispatch(guarded_legacy_dispatch):
    fixture, dispatcher, events, waiting, vendor = guarded_legacy_dispatch
    material, *unused = fixture
    material._command_generation = 1
    material._print_cancel = {'state': 'pending'}
    def complete():
        material._command_generation = 2
        material._print_cancel = {'state': 'complete'}
    waiting[0] = complete
    with pytest.raises(vendor.CommandError): dispatcher.run_script('M104 S220\nG1 X10')
    assert 'heat' not in events and 'move' not in events
    events.clear()
    dispatcher.run_script('M104 S220\nG1 X10')  # Fresh command after cleanup.
    assert events == ['heat', 'move']


def test_cancel_during_first_command_retires_remaining_script_lines(guarded_legacy_dispatch):
    fixture, dispatcher, events, waiting, vendor = guarded_legacy_dispatch
    material, *unused = fixture
    def heated(command):
        events.append('accepted-heat-finished')
        material._command_generation = 1
        material._print_cancel = {'state': 'pending'}
    dispatcher.gcode_handlers['M104'] = heated
    with pytest.raises(vendor.CommandError): dispatcher.run_script('M104 S220\n; next command must not run\nG1 X10')
    assert 'accepted-heat-finished' in events and 'move' not in events


def test_recovery_abandon_archives_original_bytes_before_invalidating(recovery_abandon_machine):
    material, objects, states, calls, review, request = recovery_abandon_machine
    job = Path(material._recovery_job_path()).read_bytes()
    execution = Path(material._recovery_execution_path()).read_bytes()
    write_job = material._write_recovery_job
    def invalidate(record):
        archive = Path(material.profile_path).parent / ('wmp_recovery_archive_' + record['archive'] + '.json')
        saved = json.loads(archive.read_bytes())
        assert saved == {'version': 1, 'records': {'job': job.hex(), 'execution': execution.hex()}}
        assert Path(material._recovery_job_path()).read_bytes() == job
        write_job(record)
    material._recovery_storage()._write_recovery_job = invalidate
    material._abandon_recovery_attempt(material.session_id, request['id'])
    assert Path(material._recovery_execution_path()).read_bytes() == execution


def test_recovery_archive_failure_allows_explicit_discard_with_warning(recovery_abandon_machine, monkeypatch):
    material, objects, states, calls, review, request = recovery_abandon_machine
    job = Path(material._recovery_job_path()).read_bytes()
    def fail(*args):
        raise OSError('archive storage unavailable')
    monkeypatch.setattr(os, 'link', fail)
    result = material._abandon_recovery_attempt(material.session_id, request['id'])
    assert result['state'] == 'abandoned'
    assert result['archive_warning'] == 'archive storage unavailable'
    marker = json.loads(Path(material._recovery_job_path()).read_text())
    assert marker['state'] == 'invalidated' and 'archive' not in marker
    assert 'M400' not in calls
    assert not material._recovery_attempt_active()
    assert not list(Path(material.profile_path).parent.glob('.wmp-recovery-archive-*'))


def test_recovery_archive_is_idempotent_and_never_overwrites(recovery_abandon_machine):
    material, objects, states, calls, review, request = recovery_abandon_machine
    evidence = {'job': b'original job\n', 'execution': b'original execution\n'}
    digest = material._archive_recovery_evidence(evidence)
    path = Path(material.profile_path).parent / ('wmp_recovery_archive_' + digest + '.json')
    inode = path.stat().st_ino
    assert material._archive_recovery_evidence(evidence) == digest
    assert path.stat().st_ino == inode
    path.write_bytes(b'conflicting archive')
    with pytest.raises(ValueError, match='conflicts'):
        material._archive_recovery_evidence(evidence)
    assert path.read_bytes() == b'conflicting archive'


def test_recovery_abandon_rechecks_execution_after_archive(recovery_abandon_machine):
    material, objects, states, calls, review, request = recovery_abandon_machine
    job = Path(material._recovery_job_path()).read_bytes()
    archive = material._archive_recovery_evidence
    def changed(evidence):
        digest = archive(evidence)
        Path(material._recovery_execution_path()).write_bytes(b'another checkpoint')
        return digest
    material._recovery_storage()._archive_recovery_evidence = changed
    with pytest.raises(ValueError, match='changed during archival'):
        material._abandon_recovery_attempt(material.session_id, request['id'])
    assert Path(material._recovery_job_path()).read_bytes() == job
    assert calls == []
    assert material._recovery_lifecycle()._recovery_attempt_unresolved()


def test_recovery_archive_rejects_symlink_without_touching_target(recovery_abandon_machine, tmp_path):
    material, objects, states, calls, review, request = recovery_abandon_machine
    evidence = {'job': b'job', 'execution': b'execution'}
    digest = material._archive_recovery_evidence(evidence)
    path = Path(material.profile_path).parent / ('wmp_recovery_archive_' + digest + '.json')
    target = tmp_path / 'unrelated'
    target.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(target)
    original = target.read_bytes()
    with pytest.raises(OSError):
        material._archive_recovery_evidence(evidence)
    assert path.is_symlink() and target.read_bytes() == original


def test_recovery_archive_directory_sync_failure_precedes_invalidation(recovery_abandon_machine, monkeypatch):
    import stat
    material, objects, states, calls, review, request = recovery_abandon_machine
    original = Path(material._recovery_job_path()).read_bytes()
    sync = os.fsync
    def fail_directory(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError('directory sync failed')
        sync(fd)
    monkeypatch.setattr(os, 'fsync', fail_directory)
    with pytest.raises(OSError, match='directory sync failed'):
        material._abandon_recovery_attempt(material.session_id, request['id'])
    assert json.loads(Path(material._recovery_job_path()).read_bytes())['state'] == 'invalidated'
    assert calls == []
    assert material._recovery_lifecycle()._recovery_attempt_unresolved()


def test_recovery_abandon_retry_rejects_archive_from_another_job(recovery_abandon_machine):
    material, objects, states, calls, review, request = recovery_abandon_machine
    dispatch = objects['gcode'].run_script_from_command
    objects['gcode'].run_script_from_command = lambda script: None if 'MACRO=_WMP_RECOVERY_BEGIN' in script else dispatch(script)
    with pytest.raises(ValueError, match='not confirmed'):
        material._abandon_recovery_attempt(material.session_id, request['id'])
    marker = material._read_recovery_job()
    other = material._archive_recovery_evidence({'job': b'other job', 'execution': b'other execution'})
    marker['archive'] = other
    material._write_recovery_job(marker)
    calls.clear()
    objects['gcode'].run_script_from_command = dispatch
    with pytest.raises(ValueError, match='Another job owns'):
        material._abandon_recovery_attempt(material.session_id, request['id'])
    assert calls == []
    assert material._recovery_lifecycle()._recovery_attempt_unresolved()


@pytest.fixture
def archived_partial_recovery(recovery_abandon_machine):
    material, objects, states, calls, review, request = recovery_abandon_machine
    dispatch = objects['gcode'].run_script_from_command
    objects['gcode'].run_script_from_command = lambda script: None if 'MACRO=_WMP_RECOVERY_BEGIN' in script else dispatch(script)
    with pytest.raises(ValueError, match='not confirmed'):
        material._abandon_recovery_attempt(material.session_id, request['id'])
    objects['gcode'].run_script_from_command = dispatch
    calls.clear()
    return recovery_abandon_machine


@pytest.mark.parametrize('damage', ['missing', 'changed'])
def test_archive_problem_does_not_veto_read_only_resolution_review(archived_partial_recovery, damage):
    from types import SimpleNamespace
    material, objects, states, calls, review, attempt = archived_partial_recovery
    marker = material._read_recovery_job()
    archive = Path(material.profile_path).parent / ('wmp_recovery_archive_' + marker['archive'] + '.json')
    if damage == 'missing': archive.unlink()
    elif damage == 'changed': archive.write_bytes(b'changed original')
    before = Path(material._recovery_job_path()).read_bytes()
    objects['gcode'].get_mutex = lambda: SimpleNamespace(test=lambda: False)
    request = CancelWebRequest(id='review-archive', attempt_id=attempt['id'], session=material.session_id, action='abandon')
    material._handle_recovery_resolution_review(request)
    assert request.response is not None and calls == []
    assert Path(material._recovery_job_path()).read_bytes() == before
    assert material._recovery_lifecycle()._recovery_attempt_unresolved()


def test_archive_removed_during_cleanup_reports_warning_without_stranding_exit(archived_partial_recovery):
    material, objects, states, calls, review, attempt = archived_partial_recovery
    marker = material._read_recovery_job()
    archive = Path(material.profile_path).parent / ('wmp_recovery_archive_' + marker['archive'] + '.json')
    dispatch = objects['gcode'].run_script_from_command
    def remove_after_reset(script):
        dispatch(script)
        if script == 'SDCARD_RESET_FILE': archive.unlink()
    objects['gcode'].run_script_from_command = remove_after_reset
    result = material._abandon_recovery_attempt(material.session_id, attempt['id'])
    assert result['state'] == 'abandoned' and 'archive_warning' in result
    assert not material._recovery_attempt_active()
    assert states['gcode_macro _WMP_RECOVERY_BEGIN']['active'] is False
    assert 'M400' not in calls


def legacy_abandon_marker(material):
    marker = material._read_recovery_job()
    archive = Path(material.profile_path).parent / ('wmp_recovery_archive_' + marker.pop('archive') + '.json')
    execution = json.loads(material._read_archived_recovery_evidence(archive.stem.removeprefix('wmp_recovery_archive_'))['execution'])
    material._recovery_attempt._save(checkpoint={
        'job_fingerprint': execution['job_fingerprint'], 'file_position': execution['file_position']})
    archive.unlink()  # Model a pre-archive cleanup: original job is unavailable.
    material._write_recovery_job(marker)
    return Path(material._recovery_job_path()).read_bytes()


def test_legacy_abandon_preserves_remaining_evidence_and_requires_confirmation(archived_partial_recovery):
    from types import SimpleNamespace
    material, objects, states, calls, review, attempt = archived_partial_recovery
    original_marker = legacy_abandon_marker(material)
    execution = Path(material._recovery_execution_path()).read_bytes()
    loaded = material._loaded_filament_status(1.)
    objects['gcode'].get_mutex = lambda: SimpleNamespace(test=lambda: False)
    request = CancelWebRequest(id='legacy-abandon', attempt_id=attempt['id'], session=material.session_id, action='abandon')
    material._handle_recovery_resolution_review(request)
    assert calls == [] and material._recovery_lifecycle()._recovery_attempt_unresolved()
    assert not list(Path(material.profile_path).parent.glob('wmp_recovery_archive_*.json'))
    assert Path(material._recovery_job_path()).read_bytes() == original_marker
    objects['gcode'].get_mutex = lambda: SimpleNamespace(test=lambda: True)
    material.cmd_RECOVERY_RESOLVE(resolution_command(request.response['request']))
    assert material._recovery_resolution['state'] == 'complete'
    assert not material._recovery_lifecycle()._recovery_attempt_unresolved()
    marker = material._read_recovery_job()
    evidence = material._read_archived_recovery_evidence(marker['archive'])
    assert evidence == {'job': original_marker, 'execution': execution}
    assert json.loads(evidence['job'])['state'] == 'invalidated'  # Never recreated as committed.
    assert material._loaded_filament_status(1.) == loaded
    assert calls == ['SDCARD_RESET_FILE',
                     'SET_GCODE_VARIABLE MACRO=_WMP_RECOVERY_BEGIN VARIABLE=active VALUE=False',
                     'SET_GCODE_VARIABLE MACRO=START_PRINT VARIABLE=print_body_ready VALUE=False',
                     'SAVE_VARIABLE VARIABLE=wmp_print_context VALUE="{}"']


@pytest.mark.parametrize('damage', ['checkpoint', 'missing-checkpoint', 'marker-fields', 'execution'])
def test_legacy_abandon_requires_existing_attempt_binding(archived_partial_recovery, damage):
    material, objects, states, calls, review, attempt = archived_partial_recovery
    legacy_abandon_marker(material)
    if damage == 'checkpoint':
        material._recovery_attempt.record['checkpoint']['job_fingerprint'] = '0' * 16
    elif damage == 'missing-checkpoint':
        material._recovery_attempt.record.pop('checkpoint')
    elif damage == 'marker-fields':
        marker = material._read_recovery_job();marker['unrecognized'] = True
        material._write_recovery_job(marker)
    else:
        Path(material._recovery_execution_path()).write_bytes(b'{}')
    before = Path(material._recovery_job_path()).read_bytes()
    with pytest.raises(ValueError, match='Another job owns'):
        material._abandon_recovery_attempt(material.session_id, attempt['id'])
    assert calls == [] and material._recovery_lifecycle()._recovery_attempt_unresolved()
    assert Path(material._recovery_job_path()).read_bytes() == before
    assert not list(Path(material.profile_path).parent.glob('wmp_recovery_archive_*.json'))


@pytest.mark.parametrize('phase', ['pending', 'running', 'scheduled', 'started'])
def test_startup_archives_exact_attempt_before_interruption_rewrite(material, phase):
    import hashlib
    record = dict(version=1, request=dict(id='recover', session='old', file='part.gcode', execution_hash='a' * 16),
                  state=phase if phase in ('pending', 'running') else 'complete',
                  stages=[dict(name='prepare', state=phase if phase in ('pending', 'running') else 'complete')], error='')
    if phase in ('scheduled', 'started'):
        record.update(continuation=dict(state=phase, file_position=100, error=''),
                      checkpoint=dict(job_fingerprint='b' * 16, file_position=100))
    original = (json.dumps(record, indent=3) + '\n').encode()
    path = Path(material._recovery_attempt_path());path.write_bytes(original)
    archive = path.parent / ('wmp_recovery_attempt_original_' + hashlib.sha256(original).hexdigest() + '.json')
    write = material._write_recovery_json
    def checked_write(destination, value):
        assert archive.read_bytes() == original
        assert path.read_bytes() == original
        write(destination, value)
    material._recovery_storage()._write_recovery_json = checked_write
    material._restore_recovery_attempt()
    assert material._recovery_lifecycle()._recovery_attempt_unresolved()
    assert json.loads(path.read_bytes())['state'] == 'unknown'
    assert archive.read_bytes() == original
    inode = archive.stat().st_ino
    material._recovery_storage()._write_recovery_json = write
    material._restore_recovery_attempt()  # already unknown: no further rewrite/archive
    assert archive.stat().st_ino == inode
    assert len(list(path.parent.glob('wmp_recovery_attempt_original_*'))) == 1


@pytest.mark.parametrize('failure', ['link', 'conflict', 'changed', 'publication'])
def test_startup_archive_failure_does_not_overwrite_attempt(material, monkeypatch, failure):
    import hashlib
    original = json.dumps(dict(version=1, request=dict(id='recover', session='old', file='part.gcode', execution_hash='a' * 16),
        state='running', stages=[dict(name='prepare', state='running')], error='')).encode()
    path = Path(material._recovery_attempt_path());path.write_bytes(original)
    archive = path.parent / ('wmp_recovery_attempt_original_' + hashlib.sha256(original).hexdigest() + '.json')
    changed = b'newer external evidence'
    if failure == 'link':
        def fail(*args): raise OSError('archive unavailable')
        monkeypatch.setattr(os, 'link', fail)
    elif failure == 'conflict':
        archive.write_bytes(b'conflicting archive')
    elif failure == 'publication':
        def fail(*args): raise OSError('attempt publication unavailable')
        material._recovery_storage()._write_recovery_json = fail
    else:
        preserve = material._recovery_lifecycle()._preserve_recovery_attempt_original
        def replace(payload):
            preserve(payload)
            path.write_bytes(changed)
        material._recovery_lifecycle()._preserve_recovery_attempt_original = replace
    material._restore_recovery_attempt()
    assert material._recovery_lifecycle()._recovery_attempt_unresolved()
    assert material._recovery_attempt_status() == {}
    material._require_no_recovery_attempt()
    assert material._idle_for_filament_settings(0)
    assert path.read_bytes() == (changed if failure == 'changed' else original)
    if failure == 'conflict': assert archive.read_bytes() == b'conflicting archive'
    assert not list(path.parent.glob('.wmp-recovery-attempt-original-*'))


@pytest.fixture
def retirement_machine(recovery_machine):
    from types import SimpleNamespace
    fixture, states = recovery_machine
    material, objects, *_ = fixture
    locked = [False]
    objects['gcode'].get_mutex = lambda: SimpleNamespace(test=lambda: locked[0])
    objects['toolhead'] = SimpleNamespace(check_busy=lambda now: (1., 1., True))
    for name in ('extruder', 'extruder1', 'extruder2', 'extruder3', 'heater_bed'):
        objects[name] = SimpleNamespace(get_status=lambda now: {'target': 0})
    return material, objects, states, locked


def test_retirement_public_review_confirm_preserves_and_blocks(retirement_machine):
    material, objects, states, locked = retirement_machine
    store = material._recovery_retirement_store()
    before, raw = store.snapshot()
    web = CancelWebRequest(session=material.session_id, id='retire-1')
    material._handle_recovery_retirement_review(web)
    request = web.response['request']
    assert web.response['file'] == 'part.gcode'
    assert store.retirement() is None and objects['gcode'].scripts == []
    locked[0] = True
    material.cmd_RETIRE_RECOVERY(resolution_command(request))
    assert material._recovery_retirement_result['state'] == 'complete'
    assert store.snapshot() == (before, raw)
    assert objects['gcode'].scripts == []
    with pytest.raises(ValueError, match='explicitly discarded'):
        material._read_completed_recovery_execution('part.gcode')
    with pytest.raises(ValueError, match='explicitly discarded'):
        material._recovery_review_service()._recovery_review(material.session_id, 'part.gcode', '', '', '')
    material.cmd_RETIRE_RECOVERY(resolution_command(request))
    assert material._recovery_retirement_result['state'] == 'complete'


@pytest.mark.parametrize('malformed_job', [False, True])
def test_retirement_public_confirmation_clears_reviewed_native_offer(retirement_machine, malformed_job):
    material, objects, _, locked = retirement_machine
    store = material._recovery_retirement_store()
    offer = Path(store.files['offer'][0])
    offer.write_bytes(b'[plr_print]\nwas_interrupted=True\nplr_file=part.gcode\n')
    if malformed_job:
        Path(store.files['job'][0]).write_bytes(b'{unreadable job')
    before = offer.read_bytes()
    web = CancelWebRequest(session=material.session_id, id='retire-offer')
    material._handle_recovery_retirement_review(web)
    assert offer.read_bytes() == before
    locked[0] = True
    material.cmd_RETIRE_RECOVERY(resolution_command(web.response['request']))
    assert material._recovery_retirement_result['state'] == 'complete'
    assert material._recovery_retirement_result['version'] == 2
    assert offer.read_bytes() == before.replace(b'True', b'False')
    result = CancelWebRequest(session=material.session_id, id='retire-offer')
    material._handle_recovery_retirement_result(result)
    assert result.response['result']['state'] == 'complete'
    material._restore_recovery_attempt()
    assert material._recovery_retirement_result['state'] == 'complete'
    assert objects['gcode'].scripts == []


@pytest.mark.parametrize('change', ['session', 'heater', 'motion', 'owner', 'paused', 'files'])
def test_retirement_refuses_changed_review_without_commands(retirement_machine, change):
    from types import SimpleNamespace
    from pathlib import Path
    material, objects, states, locked = retirement_machine
    web = CancelWebRequest(session=material.session_id, id='retire-1')
    material._handle_recovery_retirement_review(web)
    if change == 'session': material.session_id = 'replacement'
    elif change == 'heater': objects['extruder2'] = SimpleNamespace(get_status=lambda now: {'target': 220})
    elif change == 'motion': objects['toolhead'].check_busy = lambda now: (2., 1., False)
    elif change == 'owner': objects['openace'] = object()
    elif change == 'paused': material.printer.state = 'paused'
    else: Path(material._recovery_execution_path()).write_text('{changed')
    locked[0] = True
    if change in ('heater', 'motion'):
        material.cmd_RETIRE_RECOVERY(resolution_command(web.response['request']))
        assert material._recovery_retirement_result['state'] == 'complete'
    else:
        with pytest.raises(ValueError):
            material.cmd_RETIRE_RECOVERY(resolution_command(web.response['request']))
        assert material._recovery_retirement_store().retirement() is None
    assert objects['gcode'].scripts == []


@pytest.mark.parametrize('state', ['absent', 'complete', 'superseded', 'corrupt', 'wrong_id', 'old_session'])
def test_retirement_explicit_readback_without_replay(retirement_machine, state):
    material, objects, _, locked = retirement_machine
    store = material._recovery_retirement_store()
    if state != 'absent':
        web = CancelWebRequest(session=material.session_id, id='retire-1')
        material._handle_recovery_retirement_review(web)
        locked[0] = True
        material.cmd_RETIRE_RECOVERY(resolution_command(web.response['request']))
        locked[0] = False
    # Simulate a new plugin session: readback must use durable evidence, not RAM.
    material.session_id = 'restarted-session'
    material._recovery_retirement_result = {}
    if state == 'superseded':
        Path(material._recovery_execution_path()).write_bytes(b'new evidence')
    elif state == 'corrupt':
        Path(store.receipt_path).write_bytes(b'{broken')
    before = {p.name: p.read_bytes() for p in Path(material.profile_path).parent.iterdir() if p.is_file()}
    request = CancelWebRequest(session='old-session' if state == 'old_session' else material.session_id,
                               id='another-request' if state == 'wrong_id' else 'retire-1')
    if state in ('corrupt', 'old_session'):
        with pytest.raises(ValueError):
            material._handle_recovery_retirement_result(request)
    else:
        material._handle_recovery_retirement_result(request)
        assert request.response['result']['state'] == (state if state in ('complete', 'superseded') else 'unknown')
        assert request.response['session'] == material.session_id
    assert before == {p.name: p.read_bytes() for p in Path(material.profile_path).parent.iterdir() if p.is_file()}
    assert objects['gcode'].scripts == []


@pytest.mark.parametrize('raw', [b'{broken', b'', b'{}', b'[]', b'null', b'\xff'])
def test_invalid_attempt_is_diagnostic_and_can_be_explicitly_discarded(retirement_machine, raw):
    material, objects, _, locked = retirement_machine
    path = Path(material._recovery_attempt_path())
    path.write_bytes(raw)
    material._restore_recovery_attempt()
    assert material._recovery_restore_error and material._recovery_lifecycle()._recovery_attempt_unresolved()
    assert material._idle_for_filament_settings(0)
    material._recovery_review_service()._recovery_machine_state(material.session_id)
    assert path.read_bytes() == raw
    review = CancelWebRequest(session=material.session_id, id='discard-invalid')
    material._handle_recovery_retirement_review(review)
    locked[0] = True
    material.cmd_RETIRE_RECOVERY(resolution_command(review.response['request']))
    assert not material._recovery_restore_error and not material._recovery_lifecycle()._recovery_attempt_unresolved()
    assert path.read_bytes() == raw and objects['gcode'].scripts == []
    # Restart and subsequent job publication must not resurrect this attempt.
    material._restore_recovery_attempt()
    assert not material._recovery_lifecycle()._recovery_attempt_unresolved()
    Path(material._recovery_job_path()).write_bytes(b'new job')
    material._restore_recovery_attempt()
    assert not material._recovery_lifecycle()._recovery_attempt_unresolved()
    assert material._recovery_retirement_result['state'] == 'superseded'
    assert material._recovery_retirement_store().retirement()['matches'] is False
    # A replacement bad attempt remains visible, even if its bytes happen to match.
    replacement = path.with_suffix('.replacement')
    replacement.write_bytes(raw)
    replacement.replace(path)
    material._restore_recovery_attempt()
    assert material._recovery_restore_error and material._recovery_lifecycle()._recovery_attempt_unresolved()


def test_damaged_retirement_receipt_does_not_block_startup_commands(retirement_machine):
    material, objects, _, _ = retirement_machine
    Path(material._recovery_retirement_store().receipt_path).write_bytes(b'{broken')
    material._restore_recovery_attempt()
    assert material._recovery_restore_error and material._recovery_lifecycle()._recovery_attempt_unresolved()
    assert material._idle_for_filament_settings(0)
    assert objects['gcode'].scripts == []


def test_execution_sampler_distinguishes_busy_commands_from_unscheduled_motion(execution_snapshot_machine):
    """Continuous printing can expose no capturable boundary to the timer.

    Preserve both refusal reasons without flushing lookahead or presenting a
    queued parser position as completed physical execution.
    """
    from types import SimpleNamespace
    material, objects, states = execution_snapshot_machine
    material._execution_stopped = False
    busy = [True]
    objects['gcode'].get_mutex = lambda: SimpleNamespace(test=lambda: busy[0])
    for now in (1., 2., 3.):
        assert material._execution_evidence()._execution_tick(now) == now + 1.
        assert material._execution_state == 'command_busy'
        assert getattr(material, '_pending_execution_snapshot', None) is None
    busy[0] = False
    objects['toolhead'].check_busy = lambda now: (105., 101., False)
    material._execution_evidence()._execution_tick(4.)
    assert material._execution_state == 'refused'
    assert material._execution_error == 'Checkpoint motion has not reached a scheduled boundary'
    assert material._pending_execution_snapshot is None
    objects['toolhead'].check_busy = lambda now: (105., 101., True)
    material._execution_evidence()._execution_tick(5.)
    assert material._execution_state == 'waiting_motion' and material._execution_error == ''
    objects['toolhead'].check_busy = lambda now: (106., 106., True)
    material._execution_evidence()._execution_tick(6.)
    assert material._execution_last_boundary is not None


@pytest.fixture
def execution_queued_boundary(execution_snapshot_machine):
    from types import SimpleNamespace as NS
    material, objects, states = execution_snapshot_machine
    sd = objects['virtual_sdcard']
    sd.from_sd = True
    sd.file_position, sd.next_file_position = 0, 6
    sd.get_status = lambda now: {'file_position': sd.file_position}
    material._execution_stopped = False
    tail = NS(timing_callbacks=[], is_kinematic_move=False, axes_d=[0, 0, 0, 0],
              accel_t=1., cruise_t=2., decel_t=1.)
    queue = NS(get_last=lambda: tail)
    objects['toolhead'].lookahead = queue
    objects['toolhead'].check_busy = lambda now: (100., 98., False)
    return material, objects, states, tail


def test_execution_completed_sd_boundary_waits_for_retained_move_timing(execution_queued_boundary):
    import ast
    from pathlib import Path
    from types import SimpleNamespace as NS
    material, objects, states, tail = execution_queued_boundary
    boundary = material._execution_sd_boundary()
    assert boundary is not None
    material._execution_command_completed(boundary)
    candidate = material._pending_execution_snapshot
    assert candidate['file_position'] == 6  # Successful command, before SD increments its cursor.
    assert candidate['scheduled_print_time'] is None
    assert not material._execution_evidence()._publish_recovery_execution()
    assert len(tail.timing_callbacks) == 1
    states['gcode_move']['gcode_position'][0] = 99.
    # Run the retained scheduling method; it invokes callbacks at move end.
    path = Path(__file__).resolve().parents[1] / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/toolhead.py'
    tree = ast.parse(path.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ToolHead')
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_process_moves')
    namespace = {}
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
    scheduler = NS(special_queuing_state='', print_time=100., kin_flush_delay=0.,
        note_mcu_movequeue_activity=lambda *args, **kwargs: None,
        _advance_move_time=lambda when: None)
    namespace['_process_moves'](scheduler, [tail])
    assert candidate['scheduled_print_time'] == 104.
    assert candidate['gcode_position'][0] == 1.  # Later parser state never overwrites captured state.
    sd = objects['virtual_sdcard']; sd.file_position = 6; sd.from_sd = False
    objects['toolhead'].check_busy = lambda now: (106., 103., False)
    assert not material._execution_evidence()._publish_recovery_execution()
    objects['toolhead'].check_busy = lambda now: (106., 104., False)
    assert material._execution_evidence()._publish_recovery_execution()
    assert material._pending_execution_snapshot is None
    tail.timing_callbacks[0](107.)  # A late duplicate cannot alter published evidence.
    assert candidate['scheduled_print_time'] == 104.
    assert objects['gcode'].scripts == []


@pytest.mark.parametrize('drift', ['session', 'stop', 'replacement', 'invalid-clock'])
def test_execution_tail_callback_cannot_revive_invalid_candidate(execution_queued_boundary, drift):
    material, objects, states, tail = execution_queued_boundary
    material._execution_command_completed(material._execution_sd_boundary())
    old = material._pending_execution_snapshot
    if drift == 'session': material.session_id = 'new-session'
    elif drift == 'stop': material._execution_stop()
    elif drift == 'replacement': material._pending_execution_snapshot = dict(old)
    tail.timing_callbacks[0](float('nan') if drift == 'invalid-clock' else 104.)
    assert old['scheduled_print_time'] is None
    if drift == 'invalid-clock':
        assert material._pending_execution_snapshot is None
        assert material._execution_error == 'Invalid recovery move scheduling time'


@pytest.mark.parametrize('drift', ['file', 'position', 'next', 'session', 'busy'])
def test_execution_successful_command_still_requires_original_sd_binding(execution_queued_boundary, drift):
    from types import SimpleNamespace
    material, objects, states, tail = execution_queued_boundary
    boundary = material._execution_sd_boundary()
    sd = objects['virtual_sdcard']
    if drift == 'file': sd.current_file = SimpleNamespace(closed=False)
    elif drift == 'position': sd.file_position = 1
    elif drift == 'next': sd.next_file_position = 7
    elif drift == 'session': material.session_id = 'new'
    else: objects['gcode'].get_mutex = lambda: SimpleNamespace(test=lambda: True)
    material._execution_command_completed(boundary)
    assert material._pending_execution_snapshot is None
    assert tail.timing_callbacks == []


@pytest.mark.parametrize('fails', [False, True])
def test_sd_observer_runs_only_after_retained_script_success(legacy_cancel_routes, fails):
    import ast
    from pathlib import Path
    fixture, binding, cleanup, handlers, forwarded = legacy_cancel_routes
    material, objects, states, calls, review, request, timers, body, locked = fixture
    # Reinstall around the retained dispatcher, not the earlier fixture stub.
    gcode = objects['gcode']
    path = Path(__file__).resolve().parents[1] / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/gcode.py'
    cls = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.ClassDef) and n.name == 'GCodeDispatch')
    method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'run_script')
    namespace = {}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), 'exec'), namespace)
    events = []
    locked[0] = False
    gcode.mutex = gcode.get_mutex()
    def process(lines, need_ack):
        assert locked[0]
        events.append('dispatch')
        if fails: raise ValueError('command failed')
    gcode._process_commands = process
    gcode.run_script = lambda script: namespace['run_script'](gcode, script)
    del material._cancel_script_wrapper
    material._cancel_routes_ready()
    token = object()
    material._execution_evidence()._execution_sd_boundary = lambda: token
    def observe(boundary):
        assert boundary is token and not locked[0]
        events.append('completed')
    material._execution_evidence()._execution_command_completed = observe
    if fails:
        with pytest.raises(ValueError, match='command failed'): gcode.run_script('G1 X10')
    else: gcode.run_script('G1 X10')
    assert events == (['dispatch'] if fails else ['dispatch', 'completed'])


@pytest.mark.parametrize('terminal', ['complete', 'stopped'])
@pytest.mark.parametrize('fault', ['before_write', 'after_write', 'persistent'])
def test_filament_terminal_write_failure_preserves_actual_outcome(service_material, monkeypatch, terminal, fault):
    material, objects, state = service_material
    material.filament_operation = dict(id='terminal-write', session=material.session_id,
        head='h2', action='load', state='running', phase='feeding')
    material._filament_service()._persist_filament_operation()
    persist = material._filament_service()._persist_filament_operation
    effects = []
    def finish(*args):
        effects.append('effect')
        material.filament_operation.update(state='complete' if terminal == 'complete' else 'failed',
            phase='stopped', recovered=terminal == 'stopped')
    monkeypatch.setattr(material._filament_service(), '_execute_filament_impl', finish)
    def fail_write():
        if fault == 'after_write': persist()
        raise OSError('terminal storage failure')
    monkeypatch.setattr(material._filament_service(), '_persist_filament_operation', fail_write)
    material._filament_service()._execute_filament(FakeCommand(), 2, 'load', {})
    assert material.filament_operation['state'] == ('complete' if terminal == 'complete' else 'failed')
    assert material.filament_operation['persistence_error'] == 'terminal storage failure'
    assert effects == ['effect']
    material.cmd_SET_FILAMENT(profile_command(material))
    material.filament_operation = {}
    material._restore_filament_operation()
    assert not material._material_operation_active('filament_operation')
    assert effects == ['effect']  # Startup never replays an uncertain receipt.


@pytest.mark.parametrize('action', ['take', 'dock'])
@pytest.mark.parametrize('point', ['queued', 'moving', 'terminal'])
def test_toolhead_journal_survives_process_loss(toolhead_material, action, point):
    material, objects, state, scripts, callbacks = toolhead_material
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material, ACTION=action))
    if point == 'moving':
        def interrupted(script):
            scripts.append(script)
            if script.startswith(('_CHANGE_TOOL', 'PARK_CURRENT_TOOL')):
                raise KeyboardInterrupt('process loss')
        objects['gcode'].run_script_from_command = interrupted
        with pytest.raises(KeyboardInterrupt): callbacks.pop()(1)
    elif point == 'terminal':
        if action == 'dock':
            # Dispatch must see the original mounted head; change after motion.
            def run(script):
                scripts.append(script)
                if script == 'PARK_CURRENT_TOOL':
                    material._material_status()._attachment = lambda now: {'state': 'empty', 'head': ''}
            material._material_status()._attachment = lambda now: {'state': 'attached', 'head': 'h2'}
            objects['gcode'].run_script_from_command = run
        callbacks.pop()(1)
    before = list(scripts)
    material.toolhead_operation = {}
    material._toolhead_requests = set()
    material.session_id = 'new-process'
    material._restore_toolhead_operation()
    assert scripts == before
    assert material.toolhead_operation['state'] == ('complete' if point == 'terminal' else 'unknown')
    assert material.toolhead_operation['previous_session'] == 'test-session'
    assert material.toolhead_operation['session'] == 'new-process'
    if point != 'terminal':
        material.cmd_TOOLHEAD_ACTION(toolhead_command(material, ID='replacement'))
        assert scripts == before  # User requested a new attempt; no inline replay.
        assert material.toolhead_operation['id'] == 'replacement'
        assert material.toolhead_operation['state'] == 'running'


@pytest.mark.parametrize('stage', ['intent', 'completion', 'recovery'])
@pytest.mark.parametrize('fault', ['before', 'after', 'persistent'])
def test_toolhead_journal_failure_preserves_actual_outcome(toolhead_material, monkeypatch, stage, fault):
    material, objects, state, scripts, callbacks = toolhead_material
    persist = material._toolheads()._persist_toolhead_operation
    if stage != 'intent':
        material.cmd_TOOLHEAD_ACTION(toolhead_command(material))
    if stage == 'recovery':
        callbacks.pop()  # Model an interrupted prior process, with no live callback.
        state['save_variables']['variables'].update(fail_flag=0, is_nozzle_setting=0)
        material.toolhead_operation['state'] = 'unknown'
        persist()
    def broken():
        if fault == 'after': persist()
        raise OSError('storage failed')
    monkeypatch.setattr(material._toolheads(), '_persist_toolhead_operation', broken)
    if stage == 'intent':
        material.cmd_TOOLHEAD_ACTION(toolhead_command(material))
        assert not scripts and len(callbacks) == 1
        with pytest.raises(ValueError): material.cmd_TOOLHEAD_ACTION(toolhead_command(material, ID='competing'))
        callbacks.pop()(1)
    elif stage == 'completion': callbacks.pop()(1)
    else: material.cmd_RECOVER_TOOLHEAD(FakeCommand(ID='take-1', SESSION=material.session_id, HEAD='2'))
    assert material.toolhead_operation['state'] == ('failed' if stage == 'recovery' else 'complete')
    assert material.toolhead_operation['persistence_error'] == 'storage failed'
    assert scripts.count('_CHANGE_TOOL T=2') == (0 if stage == 'recovery' else 1)
    before = list(scripts)
    with pytest.raises(ValueError, match='already attempted'):
        material.cmd_TOOLHEAD_ACTION(toolhead_command(material))
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material, ID='replacement'))
    assert scripts == before and len(callbacks) == 1


@pytest.mark.parametrize('payload', ['{', '[]', '{"version":2,"operation":{}}',
                                   '{"version":1,"operation":null}', ' ' * 131073])
def test_toolhead_journal_corruption_is_not_an_empty_result(toolhead_material, payload):
    material, objects, state, scripts, callbacks = toolhead_material
    Path(material._toolheads()._toolhead_operation_path()).write_text(payload)
    material._restore_toolhead_operation()
    assert material.toolhead_operation['state'] == 'unknown'
    assert Path(material._toolheads()._toolhead_operation_path()).read_text() == payload
    assert not scripts and not callbacks
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material))
    callbacks.pop()(1)
    assert material.toolhead_operation['state'] == 'complete'


def test_reconciled_toolhead_result_survives_restart(interrupted_toolhead):
    material, objects, state, scripts, command = interrupted_toolhead
    material._toolheads()._persist_toolhead_operation()
    material.cmd_RECOVER_TOOLHEAD(command)
    assert scripts == ['M400']
    material.toolhead_operation = {}
    material.session_id = 'after-reconcile'
    material._restore_toolhead_operation()
    assert material.toolhead_operation['state'] == 'failed'
    assert material.toolhead_operation['recovered'] is True
    assert material.toolhead_operation['recovery_attachment'] == {'state': 'attached', 'head': 'h2'}
    assert scripts == ['M400']


@pytest.mark.parametrize('kind', [1, 2, 3, 99, 'missing', 'empty', 'corrupt'])
def test_incompatible_execution_public_retirement_preserves_evidence(completed_execution, retirement_machine, kind):
    material, objects, states, locked = retirement_machine
    material.printer.state = "standby"
    states["print_stats"]["state"] = "standby"
    objects["virtual_sdcard"].active = False
    store = material._recovery_retirement_store()
    path = Path(material._recovery_execution_path())
    if isinstance(kind, int):
        # Construct the historical omissions, not just a changed version number.
        saved = json.loads(path.read_text())
        saved['version'] = kind
        if kind < 4:
            for key in ('print_duration', 'filament_used'): saved.pop(key, None)
        if kind < 3:
            for key in ('mesh_fingerprint', 'mesh_offsets'): saved.pop(key, None)
        if kind < 2:
            for key in ('parser_position', 'machine_position'): saved.pop(key, None)
        path.write_text(json.dumps(saved))
    elif kind == 'missing': path.unlink()
    else: path.write_bytes(b'' if kind == 'empty' else b'{invalid\xff')
    offer = Path(store.files['offer'][0])
    offer.write_bytes(b'[plr_print]\nwas_interrupted=True\nplr_file=part.gcode\n')
    original_manifest, original_bytes = store.snapshot()
    with pytest.raises(ValueError): material._read_completed_recovery_execution('part.gcode')
    web = CancelWebRequest(session=material.session_id, id='retire-incompatible')
    material._handle_recovery_retirement_review(web)
    assert store.snapshot() == (original_manifest, original_bytes)
    assert not objects['gcode'].scripts
    locked[0] = True
    material.cmd_RETIRE_RECOVERY(resolution_command(web.response['request']))
    receipt = store.retirement()
    assert receipt['matches'] is True
    archive = json.loads((Path(store.directory) / ('wmp_recovery_retirement_archive_' + receipt['archive'] + '.json')).read_text())
    archived = {key: None if value is None else bytes.fromhex(value) for key, value in archive['records'].items()}
    assert archived == original_bytes
    current = store.snapshot()[1]
    assert {k:v for k,v in current.items() if k != 'offer'} == {k:v for k,v in original_bytes.items() if k != 'offer'}
    assert current['offer'] == original_bytes['offer'].replace(b'True', b'False')
    material.session_id = 'after-incompatible-discard'
    material._restore_recovery_attempt()
    assert material._recovery_retirement_result['state'] == 'complete'
    with pytest.raises(ValueError, match='explicitly discarded'):
        material._read_completed_recovery_execution('part.gcode')
    assert not objects['gcode'].scripts


@pytest.mark.parametrize('failure', ['before_write', 'after_write', 'persistent'])
def test_public_reconcile_persistence_failure_keeps_attempt_unresolved(interrupted_recovery_machine, failure):
    import copy
    material, objects, states, path, execution = interrupted_recovery_machine
    execution['total_duration'] += 1.
    material._write_recovery_json(str(path), execution)
    request = resolution_request(material, action='reconcile')
    runner = material._recovery_attempt
    original = copy.deepcopy(runner.record)
    persist = runner.persist
    writes = []
    def failing(record):
        writes.append(copy.deepcopy(record))
        if len(writes) == 1 or failure == 'persistent':
            if failure == 'after_write':
                persist(record)
            raise OSError('reconciliation storage failure')
        persist(record)
    runner.persist = failing
    with pytest.raises(ValueError, match='reconciliation storage failure'):
        material.cmd_RECOVERY_RESOLVE(resolution_command(request))
    assert material._recovery_resolution['state'] == 'unknown'
    assert runner.record == original
    assert material._recovery_lifecycle()._recovery_attempt_unresolved()
    assert objects['gcode'].scripts == []
    runner.persist = persist
    material._restore_recovery_attempt()
    assert material._recovery_lifecycle()._recovery_attempt_unresolved()


@pytest.mark.parametrize('outcome', ['complete', 'paused', 'cancelled'])
@pytest.mark.parametrize('failure', ['before_write', 'after_write', 'persistent'])
def test_recovered_worker_terminal_write_failure_retains_hold(recovery_continuation_machine, failure, outcome):
    material, objects, states, calls, review, request, timers, body, mutex = recovery_continuation_machine
    material._run_recovery_stages(request, review,
        material._recovery_initial_stages(review, continue_print=True))
    if outcome != 'complete':
        def dispatch(line):
            body.append(line)
            if outcome == 'paused':
                objects['virtual_sdcard'].do_pause()
            else:
                objects['virtual_sdcard'].do_cancel()
        objects['gcode'].run_script = dispatch
    runner = material._recovery_attempt
    persist = runner.persist
    failed = []
    def fail_terminal(record):
        terminal = record.get('continuation', {}).get('state') == outcome
        if terminal or failure == 'persistent' and failed:
            failed.append(True)
            if failure == 'after_write': persist(record)
            raise OSError('worker terminal storage failure')
        persist(record)
    runner.persist = fail_terminal
    mutex[0] = False
    with pytest.raises(OSError, match='worker terminal storage failure'):
        timers[0].callback(material.printer.monotonic())
    assert body == ['G1 X2']
    assert material._recovery_lifecycle()._recovery_attempt_unresolved()
    assert runner.record['state'] == 'unknown'
    runner.persist = persist
    material._restore_recovery_attempt()
    assert material._recovery_lifecycle()._recovery_attempt_unresolved()


@pytest.mark.parametrize('failure', ['before_write', 'after_write', 'persistent'])
def test_public_discard_terminal_storage_failure_preserves_archive_and_hold(recovery_abandon_machine, failure):
    from pathlib import Path
    material, objects, states, calls, review, attempt = recovery_abandon_machine
    original_job = Path(material._recovery_job_path()).read_bytes()
    original_execution = Path(material._recovery_execution_path()).read_bytes()
    request = resolution_request(material)
    runner = material._recovery_attempt
    persist = runner.persist
    failed = []
    def fail_terminal(record):
        if record['state'] == 'abandoned' or failure == 'persistent' and failed:
            failed.append(True)
            if failure == 'after_write': persist(record)
            raise OSError('discard terminal storage failure')
        persist(record)
    runner.persist = fail_terminal
    with pytest.raises(ValueError, match='discard terminal storage failure'):
        material.cmd_RECOVERY_RESOLVE(resolution_command(request))
    assert material._recovery_resolution['state'] == 'unknown'
    assert material._recovery_lifecycle()._recovery_attempt_unresolved()
    marker = json.loads(Path(material._recovery_job_path()).read_text())
    assert marker['state'] == 'invalidated'
    archives = list(Path(material.profile_path).parent.glob('wmp_recovery_archive_*.json'))
    assert len(archives) == 1
    archive_bytes = archives[0].read_bytes()
    records = json.loads(archive_bytes)['records']
    assert bytes.fromhex(records['job']) == original_job
    assert bytes.fromhex(records['execution']) == original_execution
    assert not any(call.startswith(('G0', 'G1', 'G28', 'M104', 'M109')) for call in calls)
    runner.persist = persist
    material._restore_recovery_attempt()
    assert material._recovery_lifecycle()._recovery_attempt_unresolved()
    # Storage recovery permits a fresh explicit discard, not automatic cleanup.
    material.cmd_RECOVERY_RESOLVE(resolution_command(resolution_request(material, ticket='retry-discard')))
    assert not material._recovery_lifecycle()._recovery_attempt_unresolved()
    assert archives[0].read_bytes() == archive_bytes


def test_afc_owner_refuses_standalone_print_before_submission(print_material):
    material, objects, request, path = print_material
    objects['AFC'] = object()
    with pytest.raises(ValueError, match='ownership changed'):
        material.cmd_START_PRINT(start_command(request))
    assert objects['gcode'].scripts == []
    assert material.print_submission['state'] == 'refused'


@pytest.mark.parametrize('action', ['edit', 'confirm'])
def test_afc_owner_preserves_standalone_filament_metadata(filament_check, action):
    material, sensor, command = filament_check
    before = Path(material.profile_path).read_bytes()
    original = material.printer.lookup_object
    material.printer.lookup_object = lambda name, default=None: object() if name == 'AFC' else original(name, default)
    with pytest.raises(ValueError, match='owns filament'):
        if action == 'edit':
            material.cmd_SET_FILAMENT(profile_command(material))
        else:
            material.cmd_CONFIRM_FILAMENT(command)
    assert Path(material.profile_path).read_bytes() == before
    assert not material._filament_checks


def test_afc_cannot_reuse_standalone_pause_for_resume_or_editor(paused_origin_material):
    import copy
    material, objects, state = paused_origin_material
    saved = copy.deepcopy(objects['gcode_move'].saved_states)
    objects['AFC'] = object()
    assert material._paused_filament_status(1).get('available') is not True
    with pytest.raises(ValueError, match='owns paused filament'):
        material.cmd_CHECK_RESUME(FakeCommand())
    assert state['paused'] is True and state['job'] == 'paused'
    assert objects['gcode_move'].saved_states == saved

@pytest.mark.parametrize('queued_change', [None, 'head', 'cleared', 'paused', 'disabled'])
@pytest.mark.parametrize('sensor_name', ['filament0', 'path_0'])
@pytest.mark.parametrize('job,paused,head,expected', [
    ('standby', False, 'h0', False), ('complete', False, 'h0', False),
    ('cancelled', False, 'h0', False), ('paused', True, 'h0', False),
    ('printing', False, 'h1', False), ('printing', False, 'h0', True),
    ('printing', False, 'unknown', False), ('standby', False, 'unknown', False),
    ('paused', True, 'unknown', False),
])
def test_vendor_runout_notification_only_for_active_required_head(sensor_name, job, paused, head, expected, queued_change):
    import importlib.util
    from pathlib import Path
    from types import SimpleNamespace
    from wm_material import WMMaterial
    path = Path(__file__).resolve().parents[1] / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras/filament_switch_sensor.py'
    if not path.exists():
        pytest.skip('local vendor analysis source is not distributed')
    spec = importlib.util.spec_from_file_location('vendor_runout_notification', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    errors, callbacks, pauses, scripts, info = [], [], [], [], []
    reactor = SimpleNamespace(monotonic=lambda: 10., NEVER=float('inf'), register_callback=callbacks.append, pause=lambda until: None)
    objects = {'print_stats': SimpleNamespace(get_status=lambda now: {'state': job}),
               'pause_resume': SimpleNamespace(get_status=lambda now: {'is_paused': paused}, send_pause_command=lambda: pauses.append('pause'))}
    printer = SimpleNamespace(lookup_object=lambda name, default=None: objects.get(name, default),
                              get_reactor=lambda: reactor)
    helper = module.RunoutHelper.__new__(module.RunoutHelper)
    helper.name, helper.printer, helper.reactor = sensor_name, printer, reactor
    helper.gcode = SimpleNamespace(_respond_error=errors.append, run_script=scripts.append, respond_info=info.append)
    objects['gcode'] = helper.gcode
    helper.runout_pause, helper.pause_delay, helper.event_delay = sensor_name.startswith("path_"), .5, 3.
    helper.filament_present, helper.sensor_enabled = True, True
    helper.min_event_systime = 0.
    helper.insert_gcode, helper.runout_gcode = None, SimpleNamespace(render=lambda: "")
    objects['filament_switch_sensor ' + sensor_name] = SimpleNamespace(runout_helper=helper)
    material = WMMaterial.__new__(WMMaterial)
    material.printer = printer
    material._material_status()._attachment = lambda now: ({'state': 'unknown', 'head': ''} if head == 'unknown'
                                       else {'state': 'attached', 'head': head})
    material._filament_state()._guard_filament_notifications()
    wrapper = helper._respond_runout_error
    material._filament_state()._guard_filament_notifications()
    assert helper._respond_runout_error is wrapper
    helper.note_filament_present(False)
    assert helper.filament_present is False
    assert errors == []
    assert bool(info) is (expected or (job == 'printing' and head == 'unknown'))
    if info and head == 'unknown':
        assert sensor_name in info[0] and 'attached head is unknown' in info[0]
    # Existing event dispatch remains intact; its macro owns pause admission.
    assert len(callbacks) == (1 if job == 'printing' else 0)
    helper.note_filament_present(False)
    assert errors == []
    assert len(info) == int(expected or (job == 'printing' and head == 'unknown'))

    if queued_change == 'head':
        material._material_status()._attachment = lambda now: {'state': 'attached', 'head': 'h3'}
    elif queued_change == 'cleared': helper.filament_present = True
    elif queued_change == 'disabled': helper.sensor_enabled = False
    elif queued_change == 'paused':
        objects['pause_resume'].get_status = lambda now: {'is_paused': True}
    for callback in callbacks:
        callback(10.)
    assert bool(pauses) is (expected and sensor_name.startswith('path_') and queued_change is None)
    assert any(script.startswith('PAUSE\n') for script in scripts) is bool(pauses)
    if callbacks:
        assert helper.min_event_systime == 13.  # suppressed callbacks must not stay locked at NEVER


@pytest.mark.parametrize('enabled,present,blocked', [
    (True, False, True), (True, None, True), (True, True, False),
    (False, False, False),
])
def test_resume_requires_active_head_path_clear(paused_origin_material, enabled, present, blocked):
    from types import SimpleNamespace
    material, objects, state = paused_origin_material
    material._filament_state()._loaded_filament_status = lambda now: {'h2': {'state': 'loaded'}}
    objects['filament_switch_sensor path_2'] = SimpleNamespace(
        get_status=lambda now: {'enabled': enabled, 'filament_detected': present})
    objects['filament_switch_sensor path_1'] = SimpleNamespace(
        get_status=lambda now: {'enabled': True, 'filament_detected': False})
    if blocked:
        with pytest.raises(ValueError, match='Untangle filament for Head 3'):
            material.cmd_CHECK_RESUME(FakeCommand())
    else:
        material.cmd_CHECK_RESUME(FakeCommand())
    assert state['paused'] is True and state['job'] == 'paused'


def test_stock_ini_profiles_follow_mapping_and_preserve_on_save(material, tmp_path):
    from types import SimpleNamespace
    material.ini_path = str(tmp_path / 'tmt1.ini')
    Path(material.ini_path).write_text('[slot]\nmaterial0=3\ncolor0=14\nmaterial1=0\ncolor1=0\n')
    original = material.printer.lookup_object
    material.printer.lookup_object = lambda name, default=None: SimpleNamespace(get_status=lambda now: {'variables': {'box_modify_t0': 2, 'box_modify_t1': 0}}) if name == 'save_variables' else original(name, default)
    profiles, revision = material._profiles()
    assert profiles['h2'] == {'brand': 'Generic', 'material': 'PETG', 'color': '#cd001a'}
    assert profiles['h0']['material'] == 'PLA'
    profiles['h2']['brand'] = 'Example'
    material.cmd_SET_FILAMENT(FakeCommand(HEAD=2, EXPECT=revision, PROFILE=json.dumps(profiles['h2']).encode().hex()))
    Path(material.ini_path).write_text('[slot]\nmaterial0=2\ncolor0=0\n')
    saved, _ = material._profiles()
    assert saved == profiles


def test_stock_ini_changes_invalidate_revision_and_ambiguous_heads_are_omitted(material, tmp_path):
    from types import SimpleNamespace
    material.ini_path = str(tmp_path / 'tmt1.ini')
    ini = Path(material.ini_path)
    ini.write_text('[slot]\nmaterial0=3\ncolor0=14\n')
    _, before = material._profiles()
    ini.write_text('[slot]\nmaterial0=0\ncolor0=14\n')
    assert material._profiles()[1] != before
    ini.write_text('[slot]\nmaterial0=3\ncolor0=14\nmaterial1=0\ncolor1=0\nmaterial2=0\ncolor2=18\n')
    original = material.printer.lookup_object
    material.printer.lookup_object = lambda name, default=None: SimpleNamespace(get_status=lambda now: {'variables': {'box_modify_t0': 0, 'box_modify_t1': 0}}) if name == 'save_variables' else original(name, default)
    assert material._profiles()[0] == {}


def test_confirm_existing_filament_persists_without_motion(filament_check):
    material, sensor, _ = filament_check
    material._set_filament_loaded('h2', False)
    _, revision = material._profiles()
    material.cmd_CONFIRM_FILAMENT(FakeCommand(HEAD=2, STATE='loaded', SESSION=material.session_id, EXPECT=revision))
    del material._loaded_flags
    assert material._loaded_filament_status(1)['h2']['state'] == 'loaded'


def test_stock_ini_preserves_exact_orca_colour(material, tmp_path):
    material.ini_path = str(tmp_path / 'tmt1.ini')
    Path(material.ini_path).write_text(SAMPLE)
    profiles, _ = material._profiles()
    assert profiles['h0']['color'] == '#8ED8F8'
    assert profiles['h1']['color'] == '#FF0000'
    assert 'h2' not in profiles and 'h3' not in profiles


@pytest.mark.parametrize('present', [True, False])
def test_first_install_adopts_stock_presence_once(material, tmp_path, present):
    from types import SimpleNamespace
    material.ini_path = str(tmp_path / 'tmt1.ini')
    Path(material.ini_path).write_text('[slot]\nmaterial2=3\ncolor2=14\n')
    sensor = {'filament_detected': present, 'enabled': True}
    original = material.printer.lookup_object
    material.printer.lookup_object = lambda name, default=None: SimpleNamespace(get_status=lambda now: sensor) if name == 'filament_switch_sensor filament2' else original(name, default)
    material._filament_sensors_ready_at = 2
    assert material._loaded_filament_status(1)['h2']['state'] == 'unknown'
    assert not (tmp_path / 'wmp_filament_loaded.json').exists()
    first = material._loaded_filament_status(2)['h2']
    assert first['state'] == ('loaded' if present else 'empty')
    assert (tmp_path / 'wmp_filament_loaded.json').exists()
    if present:
        assert first['identity']['material'] == 'PETG'
    sensor['filament_detected'] = False
    assert material._loaded_filament_status(3)['h2']['state'] == 'empty'
    assert material._loaded_filament_status(3.3)['h2']['state'] == 'empty'  # sustained absence
    sensor['filament_detected'] = True
    del material._loaded_flags
    assert material._loaded_filament_status(4)['h2']['state'] == 'empty'


@pytest.mark.parametrize('blocker', ['saved_identity', 'saved_empty', 'corrupt_presence', 'busy', 'printing', 'openace'])
def test_stock_adoption_preserves_existing_authority(material, tmp_path, blocker):
    from types import SimpleNamespace
    material.ini_path = str(tmp_path / 'tmt1.ini')
    Path(material.ini_path).write_text('[slot]\nmaterial2=3\ncolor2=14\n')
    original = material.printer.lookup_object
    material.printer.lookup_object = lambda name, default=None: SimpleNamespace(get_status=lambda now: {'filament_detected': True, 'enabled': True}) if name == 'filament_switch_sensor filament2' else original(name, default)
    if blocker == 'saved_identity':
        Path(material.profile_path).write_text('{}')
    elif blocker in ('saved_empty', 'corrupt_presence'):
        (tmp_path / 'wmp_filament_loaded.json').write_text('{"h2": false}' if blocker == 'saved_empty' else 'invalid')
    elif blocker == 'busy':
        material.filament_operation = {'state': 'unknown'}
    elif blocker == 'printing':
        material.printer.state = 'printing'
    else:
        material.printer.owner = object()
    assert material._loaded_filament_status(1)['h2']['state'] == 'empty'


def test_invalid_stock_ini_does_not_adopt_loaded_state(material, tmp_path):
    material.ini_path = str(tmp_path / 'tmt1.ini')
    Path(material.ini_path).write_text('[slot]\nmaterial2=3\nmaterial2=0\ncolor2=14\n')
    with pytest.raises(ValueError, match='Invalid stock filament settings'):
        material._profiles()
    assert material._loaded_filament_status(1)['h2']['state'] == 'unknown'
    assert not (tmp_path / 'wmp_filament_loaded.json').exists()


def test_status_publication_reuses_loaded_profiles_and_commands_reload(service_material, tmp_path, monkeypatch):
    import builtins
    import os
    material, objects, state = service_material
    material.ini_path = str(tmp_path / 'tmt1.ini')
    Path(material.ini_path).write_text('[slot]\nmaterial0=0\n')
    material._mtime, material._slots, material.print_submission = None, {}, {}
    reads = []
    original_open = builtins.open
    def tracked(path, *args, **kwargs):
        if str(path) == material.profile_path:
            reads.append(path)
        return original_open(path, *args, **kwargs)
    monkeypatch.setattr(builtins, 'open', tracked)
    expected = material._material_status()._status_snapshot(1.)
    assert len(reads) > 1
    reads.clear()
    observed = material.get_status(1.)
    material._lane_data(1.)
    assert observed == expected
    assert len(reads) == 0
    assert material._status_observation_cache is None
    # Polling does not reload the profile. Explicit command admission still
    # reloads it, including external edits preserving length and timestamps.
    before = os.stat(material.profile_path)
    content = Path(material.profile_path).read_text()
    assert 'Generic' in content
    Path(material.profile_path).write_text(content.replace('Generic', 'Changed'))
    os.utime(material.profile_path, ns=(before.st_atime_ns, before.st_mtime_ns))
    reads.clear()
    assert material.get_status(2.)['identity_revision'] == observed['identity_revision']
    assert len(reads) == 0
    assert material._profiles()[0]['h2']['brand'] == 'Changed'
    assert len(reads) == 1
    changed = material.get_status(3.)
    assert len(reads) == 1
    assert changed['identity_revision'] != observed['identity_revision']
    assert changed['identities']['h2']['brand'] == 'Changed'
    # A supported save publishes its result without waiting for another read.
    material.cmd_SET_FILAMENT(profile_command(material, EXPECT=changed['identity_revision']))
    reads.clear()
    saved = material.get_status(4.)
    assert saved['identities']['h2']['brand'] == 'Generic'
    assert len(reads) == 0


def test_status_observation_cache_is_isolated_and_cleared_on_exception(material, monkeypatch):
    material.cmd_SET_FILAMENT(profile_command(material))
    def fail(eventtime):
        first = material._profiles()
        first[0]['h2']['brand'] = 'local draft'
        assert material._profiles()[0]['h2']['brand'] != 'local draft'
        raise RuntimeError('publication failed')
    monkeypatch.setattr(material._material_status(), '_status_snapshot', fail)
    with pytest.raises(RuntimeError, match='publication failed'):
        material.get_status(1.)
    assert material._status_observation_cache is None
    assert material._profiles()[0]['h2']['brand'] != 'local draft'


def test_status_observation_cache_restores_outer_publication(material, monkeypatch):
    outer = []
    def nested(eventtime):
        if eventtime == 1.:
            outer.append(material._status_observation_cache)
            assert material.get_status(2.) == {'nested': True}
            assert material._status_observation_cache is outer[0]
        else:
            assert material._status_observation_cache is not outer[0]
        return {'nested': True}
    monkeypatch.setattr(material._material_status(), '_status_snapshot', nested)
    assert material.get_status(1.) == {'nested': True}
    assert material._status_observation_cache is None


@pytest.mark.parametrize('valid_colour', [False, True])
def test_legacy_status_without_profile_does_not_accumulate_parsers(service_material, tmp_path, monkeypatch, valid_colour):
    import gc
    import wm_material
    material, objects, state = service_material
    Path(material.profile_path).unlink(missing_ok=True)
    (tmp_path / 'wmp_filament_loaded.json').unlink(missing_ok=True)
    material.ini_path = str(tmp_path / 'tmt1.ini')
    rows = ''.join('material%d=0\n' % i + ('color%d=1\n' % i if valid_colour else '')
                   for i in range(4))
    Path(material.ini_path).write_text('[slot]\n' + rows)
    material._mtime, material._slots, material.print_submission = None, {}, {}
    material._material_settings()._status_profiles_snapshot = None
    parser_type = wm_material.configparser.ConfigParser
    created = []
    def counted(*args, **kwargs):
        created.append(1)
        return parser_type(*args, **kwargs)
    monkeypatch.setattr(wm_material.configparser, 'ConfigParser', counted)
    material.get_status(0.)
    assert created
    created.clear()
    gc.collect()
    baseline = sum(type(obj) is parser_type for obj in gc.get_objects())
    enabled = gc.isenabled()
    gc.disable()  # Vendor Klipper collects only when its reactor has idle time.
    try:
        for tick in range(100):
            material.get_status(float(tick + 1))
            material._lane_data(float(tick + 1))
        assert not created
        assert sum(type(obj) is parser_type for obj in gc.get_objects()) == baseline
    finally:
        gc.collect()
        if enabled:
            gc.enable()


@pytest.mark.parametrize('owner', ['openace', 'AFC'])
def test_alternate_owner_direct_pause_helpers_without_standalone_context(paused_origin_material, owner):
    material, objects, state = paused_origin_material
    material._pause_origin = None
    objects[owner] = object()
    from types import SimpleNamespace
    objects['gcode'] = SimpleNamespace(scripts=[])
    objects['gcode'].run_script_from_command = objects['gcode'].scripts.append
    before = list(objects['gcode'].scripts)
    material.cmd_CAPTURE_PAUSE(FakeCommand())
    material.cmd_CHECK_RESUME(FakeCommand())
    assert material._pause_origin is None
    assert objects['gcode'].scripts == before
    with pytest.raises(ValueError, match='owns paused filament'):
        material.cmd_RESTORE_RESUME_E(FakeCommand())
    assert objects['gcode'].scripts == before


@pytest.mark.parametrize('owner', ['openace', 'AFC'])
@pytest.mark.parametrize('entry', ['cmd_CAPTURE_PAUSE', 'cmd_CHECK_RESUME', 'cmd_RESTORE_RESUME_E'])
def test_pause_owner_handover_never_erases_or_reuses_standalone_context(paused_origin_material, owner, entry):
    material, objects, state = paused_origin_material
    origin = material._pause_origin
    from types import SimpleNamespace
    objects['gcode'] = SimpleNamespace(scripts=[])
    objects['gcode'].run_script_from_command = objects['gcode'].scripts.append
    before = list(objects['gcode'].scripts)
    objects[owner] = object()
    with pytest.raises(ValueError, match='owns paused filament'):
        getattr(material, entry)(FakeCommand())
    assert material._pause_origin is origin
    assert state['paused'] is True
    assert objects['gcode'].scripts == before


@pytest.mark.parametrize('change', ['session', 'openace', 'AFC'])
def test_resume_recheck_after_heating_rejects_changed_owner_or_session(paused_origin_material, change):
    material, objects, state = paused_origin_material
    material._filament_state()._loaded_filament_status = lambda now: {'h2': {'state': 'loaded'}}
    material.cmd_CHECK_RESUME(FakeCommand())
    origin = material._pause_origin
    if change == 'session':
        material.session_id = 'replacement-session'
    else:
        objects[change] = object()
    from types import SimpleNamespace
    objects['gcode'] = SimpleNamespace(scripts=[])
    objects['gcode'].run_script_from_command = objects['gcode'].scripts.append
    before = list(objects['gcode'].scripts)
    with pytest.raises(ValueError, match='Pause context|owns paused filament'):
        material.cmd_CHECK_RESUME(FakeCommand())
    assert material._pause_origin is origin
    assert state['paused'] is True
    assert objects['gcode'].scripts == before


@pytest.mark.parametrize('owner', ['openace', 'AFC'])
def test_alternate_owner_resume_does_not_bypass_unresolved_recovery(paused_origin_material, owner):
    material, objects, state = paused_origin_material
    material._pause_origin = None
    objects[owner] = object()
    def unresolved():
        raise ValueError('Resolve the recovery attempt first')
    material._recovery_lifecycle()._require_no_recovery_attempt = unresolved
    with pytest.raises(ValueError, match='Resolve the recovery attempt'):
        material.cmd_CHECK_RESUME(FakeCommand())
    assert state['paused'] is True


@pytest.mark.parametrize('runout_enabled', [True, False])
def test_paused_operator_check_survives_polling_and_admits_resume(paused_origin_material, runout_enabled, tmp_path):
    from types import SimpleNamespace
    material, objects, state = paused_origin_material
    calls = []
    objects['gcode'] = SimpleNamespace(run_script_from_command=calls.append)
    objects['filament_switch_sensor filament2'] = SimpleNamespace(
        get_status=lambda now: {'enabled': runout_enabled, 'filament_detected': True})
    material._set_filament_loaded('h2', False)
    material._pause_origin['filament_required'] = ['h2']
    material.filament_operation = {'state': 'unknown', 'id': 'old-failed-attempt'}
    with pytest.raises(ValueError, match='Load filament'):
        material.cmd_CHECK_RESUME(FakeCommand())
    material.ini_path = str(tmp_path / 'tmt1.ini')
    Path(material.ini_path).write_text('[slot]\nmaterial2=3\n')
    material._mtime, material._slots, material.print_submission = None, {}, {}
    status = material.get_status(1.)
    assert status['filament_check_protocol'] == 1
    command = FakeCommand(HEAD=2, STATE='loaded', SESSION=status['session_id'],
                          EXPECT=status['identity_revision'])
    material.cmd_CONFIRM_FILAMENT(command)
    for now in (1, 2, 3):
        assert material._filament_status(now)['h2']['state'] == 'loaded'
        assert material._loaded_filament_status(now)['h2']['state'] == 'loaded'
    material.cmd_CHECK_RESUME(FakeCommand())
    assert calls == []  # No homing, heating, extrusion, or automatic resume.
    assert state['paused'] is True


@pytest.mark.parametrize('change', ['head', 'file', 'session', 'identity', 'running', 'sensor', 'worker', 'cancel', 'recovery', 'identification'])
def test_paused_operator_check_rejects_current_conflicts(paused_origin_material, change):
    import io
    from types import SimpleNamespace
    material, objects, state = paused_origin_material
    objects['filament_switch_sensor filament2'] = SimpleNamespace(
        get_status=lambda now: {'filament_detected': change != 'sensor'})
    command = FakeCommand(HEAD=1 if change == 'head' else 2, STATE='loaded',
                          SESSION='old' if change == 'session' else material.session_id,
                          EXPECT='old' if change == 'identity' else material._profiles()[1])
    if change == 'file': objects['virtual_sdcard'].current_file = io.StringIO('replacement')
    if change == 'running': material.filament_operation = {'state': 'running'}
    if change == 'worker': state['active'] = True
    if change == 'cancel': material._print_cancel = {'state': 'pending'}
    if change == 'recovery': material._recovery_attempt = SimpleNamespace(busy=True, record=None)
    if change == 'identification':
        objects['wmp_recovery'] = SimpleNamespace(get_status=lambda now: {'identification': {'state': 'running'}})
    material._set_filament_loaded('h2', False)
    with pytest.raises(ValueError):
        material.cmd_CONFIRM_FILAMENT(command)
    assert material._filament_checks == {}
    assert material._filament_state()._load_filament_flags().get('h2', False) is False


@pytest.mark.parametrize('operation', ['toolhead', 'filament'])
@pytest.mark.parametrize('payload', [b'{invalid', b'[]', b'\xff'])
def test_invalid_operation_journal_is_diagnostic_not_startup_or_edit_lock(material, operation, payload):
    feature = material._toolheads() if operation == 'toolhead' else material._filament_service()
    path = getattr(feature, '_' + operation + '_operation_path')()
    Path(path).write_bytes(payload)
    getattr(material, '_restore_' + operation + '_operation')()
    assert getattr(material, operation + '_operation')['state'] == 'unknown'
    material.cmd_SET_FILAMENT(profile_command(material))
    assert material._profiles()[0]['h2']['material'] == 'PETG'
    assert Path(path).read_bytes() == payload  # Inspection never destroys history.


@pytest.mark.parametrize('history', ['cancel', 'recovery', 'corrupt_recovery'])
def test_history_does_not_block_new_metadata_or_print_admission(material, history):
    from types import SimpleNamespace
    if history == 'cancel': material._print_cancel = {'state': 'unknown'}
    elif history == 'recovery':
        material._recovery_attempt = SimpleNamespace(busy=False, record={'state': 'unknown'})
    else: material._recovery_restore_error = 'Saved journal is unreadable'
    material.cmd_SET_FILAMENT(profile_command(material))
    assert material._print_admission(FakeCommand()) is material.printer


@pytest.mark.parametrize('active', ['cancel', 'recovery', 'queued_recovery'])
def test_live_work_still_blocks_new_metadata_and_print(material, active):
    from types import SimpleNamespace
    if active == 'cancel': material._print_cancel = {'state': 'pending'}
    elif active == 'recovery': material._recovery_attempt = SimpleNamespace(busy=True, record=None)
    else: material._recovery_pending_worker = {'armed': False}
    with pytest.raises(ValueError): material.cmd_SET_FILAMENT(profile_command(material))
    with pytest.raises(ValueError): material._print_admission(FakeCommand())


def test_stopped_error_allows_metadata_and_print_but_not_live_worker(material):
    material.printer.state = 'error'
    material.cmd_SET_FILAMENT(profile_command(material))
    assert material._print_admission(FakeCommand()) is material.printer
    material.printer.sd_active = True
    with pytest.raises(ValueError):
        material.cmd_SET_FILAMENT(profile_command(material, PROFILE=json.dumps(dict(material._profiles()[0]["h2"], material="PLA")).encode().hex()))
    with pytest.raises(ValueError): material._print_admission(FakeCommand())
    material.printer.sd_active = False
    material.printer.paused = True
    with pytest.raises(ValueError): material._print_admission(FakeCommand())


def test_fresh_filament_attempt_rechecks_current_state_without_replaying_history(sequence_material, monkeypatch):
    material, objects = sequence_material
    material.filament_operation = {'id': 'old', 'state': 'unknown'}
    calls = []
    monkeypatch.setattr('wm_material.run_standalone_extrusion_sequence', lambda printer, script: calls.append(script))
    request = sequence_command(material)
    material.cmd_FILAMENT_SEQUENCE(request)
    assert calls == ['G1 E55 F400', 'G1 E50 F400']
    assert material.filament_operation['state'] == 'complete'
    with pytest.raises(ValueError, match='already attempted'):
        material.cmd_FILAMENT_SEQUENCE(request)
    assert len(calls) == 2


def test_filament_result_storage_warning_is_not_repeated_at_every_checkpoint(sequence_material, monkeypatch, caplog):
    material, objects = sequence_material
    material.filament_operation = {'id': 'test', 'state': 'running'}
    def fail(): raise OSError('storage unavailable')
    monkeypatch.setattr(material._filament_service(), '_persist_filament_operation', fail)
    for _ in range(5): material._filament_checkpoint('inserting')
    assert material.filament_operation['state'] == 'running'
    assert material.filament_operation['persistence_error'] == 'storage unavailable'
    assert len([r for r in caplog.records if r.message == 'Unable to persist filament result']) == 1
    material.filament_operation['cancel_requested'] = True
    from wm_material import FilamentCancelled
    with pytest.raises(FilamentCancelled): material._filament_checkpoint('inserting')


@pytest.mark.parametrize('history', ['tool', 'filament', 'cancel', 'recovery', 'corrupt_recovery'])
def test_stopped_error_print_submission_ignores_history_and_dispatches_once(print_material, history):
    from types import SimpleNamespace
    material, objects, request, path = print_material
    material.printer.state = 'error'
    if history == 'tool': material.toolhead_operation = {'state': 'unknown'}
    elif history == 'filament': material.filament_operation = {'state': 'unknown'}
    elif history == 'cancel': material._print_cancel = {'state': 'unknown'}
    elif history == 'recovery': material._recovery_attempt = SimpleNamespace(busy=False, record={'state': 'unknown'})
    else: material._recovery_restore_error = 'Unreadable old recovery result'
    command = start_command(request)
    material.cmd_START_PRINT(command)
    assert material.print_submission['state'] == 'submitted'
    assert objects['gcode'].scripts.count('SDCARD_PRINT_FILE FILENAME="part.gcode"') == 1
    with pytest.raises(ValueError, match='already attempted'):
        material.cmd_START_PRINT(command)
    assert objects['gcode'].scripts.count('SDCARD_PRINT_FILE FILENAME="part.gcode"') == 1


@pytest.mark.parametrize('operation', ['filament_operation', 'toolhead_operation'])
def test_new_print_cannot_overtake_queued_material_work(print_material, operation):
    material, objects, request, path = print_material
    setattr(material, operation, {'state': 'running', 'id': 'queued'})
    with pytest.raises(ValueError, match='running'):
        material.cmd_START_PRINT(start_command(request))
    assert objects['gcode'].scripts == []
    assert material.print_submission['state'] == 'refused'
@pytest.mark.parametrize('attribute,value,detail', [
    ('state', 'printing', "print_stats.state='printing'"),
    ('paused', True, 'pause_resume.is_paused=True'),
    ('sd_active', True, 'virtual_sdcard.is_active=True'),
    ('from_sd', True, 'virtual_sdcard.is_cmd_from_sd=True'),
])
def test_idle_admission_diagnostic_names_predicate_without_poll_logging(material, attribute, value, detail, caplog):
    setattr(material.printer, attribute, value)
    assert material._idle_for_filament_settings(1) is False
    assert material._idle_settings_refusal == detail
    assert not caplog.records
    with pytest.raises(ValueError) as error:
        material._toolheads()._toolhead_context(2, "take", 1)
    assert detail in str(error.value)
    setattr(material.printer, attribute, 'standby' if attribute == 'state' else False)
    assert material._idle_for_filament_settings(1) is True
    assert material._idle_settings_refusal == ''

@pytest.mark.parametrize('change,detail', [
    ('session', 'printer session changed'),
    ('owner', 'openace owner is present'),
    ('handle', 'virtual_sdcard file handle changed'),
])
def test_cancel_admission_reports_exact_binding_failure_without_starting(managed_cancel_intent, change, detail):
    fixture, binding, cleanup, original_worker = managed_cancel_intent
    material, objects, states, calls, review, request, timers, body, locked = fixture
    before = list(calls)
    if change == 'session': binding = dict(binding, session='old-session')
    elif change == 'owner': objects['openace'] = object()
    else: objects['virtual_sdcard'].current_file = object()
    with pytest.raises(ValueError) as error:
        material._begin_print_cancel('diagnostic-refusal', binding)
    assert detail in str(error.value)
    assert calls == before and not cleanup

@pytest.mark.parametrize('action', ['scan', 'review'])
@pytest.mark.parametrize('paused', [False, True])
def test_profile_reads_do_not_require_machine_idle(material, monkeypatch, action, paused):
    from types import SimpleNamespace as NS
    material.printer.state = 'paused' if paused else 'printing'
    material.printer.paused, material.printer.sd_active = paused, True
    material._profile_import_busy = False
    workers, callbacks, reads = [], [], []
    material._profile_importer = NS(
        scan=lambda: reads.append('scan') or {'state': 'scanned'},
        review=lambda token: reads.append('review') or {'state': 'reviewed'})
    material.printer.register_async_callback = callbacks.append
    monkeypatch.setattr('wm_material.threading.Thread', lambda target, **kw: NS(start=lambda: workers.append(target)))
    material.cmd_PROFILE_IMPORT(FakeCommand(ACTION=action, ID='read-profile', FILE='a' * 64))
    workers.pop()(); callbacks.pop()(1)
    assert reads == [action] and not material._profile_import_busy
    assert material.printer.sd_active and material.printer.paused is paused
    with pytest.raises(ValueError, match='Profile import save requires an idle printer'):
        material.cmd_PROFILE_IMPORT(FakeCommand(ACTION='save', ID='write-profile', TOKEN='b' * 48))
    assert not workers


def test_public_abandon_archive_failure_is_warning_and_allows_fresh_action(recovery_abandon_machine, monkeypatch):
    material, objects, states, calls, review, attempt = recovery_abandon_machine
    def fail(*args): raise OSError('archive unavailable')
    monkeypatch.setattr(material._recovery_storage(), '_archive_recovery_evidence', fail)
    states['extruder2']['target'] = 160.
    objects['save_variables'].values['variables']['fail_flag'] = -3
    request = resolution_request(material)
    material.cmd_RECOVERY_RESOLVE(resolution_command(request))
    assert material._recovery_resolution['state'] == 'complete'
    assert 'archive unavailable' in material._recovery_resolution['message']
    assert not material._recovery_attempt_active()
    material._require_no_recovery_attempt()
    assert states['extruder2']['target'] == 160.
    assert 'M400' not in calls


def test_abandon_without_archive_can_retry_partial_metadata_cleanup(recovery_abandon_machine, monkeypatch):
    material, objects, states, calls, review, attempt = recovery_abandon_machine
    def fail(*args): raise OSError('archive unavailable')
    monkeypatch.setattr(material._recovery_storage(), '_archive_recovery_evidence', fail)
    dispatch = objects['gcode'].run_script_from_command
    objects['gcode'].run_script_from_command = lambda script: None if 'MACRO=_WMP_RECOVERY_BEGIN' in script else dispatch(script)
    with pytest.raises(ValueError, match='not confirmed'):
        material._abandon_recovery_attempt(material.session_id, attempt['id'])
    assert not material._recovery_attempt_active()
    objects['gcode'].run_script_from_command = dispatch
    result = material._abandon_recovery_attempt(material.session_id, attempt['id'])
    assert result['state'] == 'abandoned'


def test_abandon_retry_missing_diagnostic_archive_keeps_current_binding(recovery_abandon_machine):
    material, objects, states, calls, review, attempt = recovery_abandon_machine
    dispatch = objects['gcode'].run_script_from_command
    objects['gcode'].run_script_from_command = lambda script: None if 'MACRO=_WMP_RECOVERY_BEGIN' in script else dispatch(script)
    with pytest.raises(ValueError, match='not confirmed'):
        material._abandon_recovery_attempt(material.session_id, attempt['id'])
    for path in Path(material.profile_path).parent.glob('wmp_recovery_archive_*.json'):
        path.write_bytes(b'corrupt archive')
    objects['gcode'].run_script_from_command = dispatch
    result = material._abandon_recovery_attempt(material.session_id, attempt['id'])
    assert result['state'] == 'abandoned' and 'archive_warning' in result
    assert not material._recovery_attempt_active()


def test_recovery_discard_review_during_print_does_not_authorize_cleanup(recovery_abandon_machine):
    material, objects, states, calls, review, attempt = recovery_abandon_machine
    objects['virtual_sdcard'].is_active = lambda: True
    request = CancelWebRequest(id='review-live-print', attempt_id=attempt['id'], session=material.session_id, action='abandon')
    material._handle_recovery_resolution_review(request)
    assert request.response is not None and not calls
    with pytest.raises(ValueError, match='print or pause'):
        material.cmd_RECOVERY_RESOLVE(resolution_command(request.response['request']))
    assert not calls


def test_retirement_review_during_unrelated_command_does_not_authorize_print_cleanup(retirement_machine):
    material, objects, states, locked = retirement_machine
    locked[0] = True
    objects['virtual_sdcard'].is_active = lambda: True
    request = CancelWebRequest(session=material.session_id, id='review-live-print')
    material._handle_recovery_retirement_review(request)
    assert request.response is not None and not objects['gcode'].scripts
    with pytest.raises(ValueError, match='Finish or cancel'):
        material.cmd_RETIRE_RECOVERY(resolution_command(request.response['request']))
    assert not objects['gcode'].scripts


def test_execution_sampler_retires_previous_checkpoint_after_resume_mapping_edit(execution_snapshot_machine):
    material, objects, states = execution_snapshot_machine
    assert material._execution_evidence()._queue_recovery_execution()
    objects['toolhead'].check_busy = lambda now: (105., 101., True)
    assert material._execution_evidence()._publish_recovery_execution()
    execution = Path(material._recovery_execution_path())
    assert execution.exists()
    objects['save_variables'].values['variables']['box_modify_t0_backup'] = 1
    material._execution_stopped = False
    material._execution_evidence()._execution_tick(3.)
    assert material._read_recovery_job()['state'] == 'invalidated'
    assert not execution.exists()
    assert states['print_stats']['state'] == 'printing'
    assert objects['gcode'].scripts == []


def test_invalid_profile_entry_preserved_by_unrelated_save(material):
    from pathlib import Path
    path = Path(material.profile_path)
    bad = {'h0': {'material': 'PLA'}, 'future': {'untouched': [1, None]}}
    good = {'brand': 'Generic', 'material': 'PLA', 'color': '#ffffff'}
    raw = dict(bad, h2=good)
    path.write_text(json.dumps(raw))
    profiles, revision = material._profiles()
    assert profiles == {'h2': good}
    assert set(material._profile_entry_errors) == set(bad)
    command = profile_command(material)
    material.cmd_SET_FILAMENT(command)
    saved = json.loads(path.read_text())
    assert all(saved[key] == value for key, value in bad.items())
    assert saved['h2']['material'] == 'PETG'
    assert material._profiles()[0] == {'h2': saved['h2']}
    assert material._profiles()[1] != revision


def test_invalid_profile_entry_change_invalidates_save(material):
    from pathlib import Path
    path = Path(material.profile_path)
    path.write_text(json.dumps({'h0': {'bad': 1}}))
    command = profile_command(material)
    path.write_text(json.dumps({'h0': {'bad': 2}}))
    with pytest.raises(ValueError, match='changed'):
        material.cmd_SET_FILAMENT(command)
    assert json.loads(path.read_text()) == {'h0': {'bad': 2}}


def test_explicit_profile_repair_replaces_only_selected_invalid_entry(material):
    from pathlib import Path
    path = Path(material.profile_path)
    path.write_text(json.dumps({'h2': {'bad': True}, 'h1': {'keep': 'invalid'}}))
    material.cmd_SET_FILAMENT(profile_command(material))
    raw = json.loads(path.read_text())
    assert raw['h1'] == {'keep': 'invalid'}
    assert raw['h2']['material'] == 'PETG'
    assert set(material._profile_entry_errors) == {'h1'}


def test_partial_profiles_status_reports_errors_without_disabling_valid_edits(material):
    from pathlib import Path
    path = Path(material.profile_path)
    path.write_text(json.dumps({'h0': {'bad': True}}))
    material._material_status()._refresh = lambda: None
    material._mtime = 1
    material._slots = {}
    material.ini_path = '/unused/test.ini'
    material.print_submission = {}
    material.filament_operation = {}
    material._material_status()._attachment = lambda now: {'state': 'unknown', 'head': ''}
    material._filament_state()._filament_status = lambda now: {}
    status = material.get_status(1)
    assert status['identity_writable'] is True
    assert 'h0' in status['identity_entry_errors']
    assert 'entry preserved' in status['identity_error']



def test_load_completes_from_corrupt_history_without_fabricating_old_material(sequence_material, monkeypatch):
    from pathlib import Path
    material, _ = sequence_material
    path = Path(material.profile_path).with_name('wmp_hotend_materials.json')
    path.write_text('{broken')
    moves = []
    monkeypatch.setattr('wm_material.run_standalone_extrusion_sequence', lambda printer, script: moves.append(script))
    material.cmd_FILAMENT_SEQUENCE(sequence_command(material))
    assert moves and material.filament_operation['state'] == 'complete'
    assert next(path.parent.glob(path.name + '.invalid-*')).read_text() == '{broken'
    assert material._hotend_material_history()['h2'] == {
        'state': 'purged', 'materials': [material._profiles()[0]['h2']], 'unknown_residue': False}


@pytest.mark.parametrize('kind', ['filament', 'toolhead'])
def test_material_sequences_survive_more_than_1024_refused_attempts(toolhead_material, kind, monkeypatch):
    material, objects, state, scripts, callbacks = toolhead_material
    command = material.cmd_FILAMENT_SEQUENCE if kind == 'filament' else material.cmd_TOOLHEAD_ACTION
    legacy = material._filament_requests if kind == 'filament' else material._toolhead_requests
    legacy.update('legacy-%d' % i for i in range(1024))
    for number in range(1, 1027):
        args = dict(ID=kind + '_' + str(number), SEQUENCE=str(number), SESSION=material.session_id,
                    HEAD='2', ACTION='take' if kind == 'toolhead' else 'load', ATTACHED='none', TOKEN='stale')
        with pytest.raises(ValueError, match='changed'):
            command(FakeCommand(**args))
    assert getattr(material, '_' + kind + '_request_sequence') == 1026
    assert len(legacy) == 1024
    assert not scripts and not callbacks
    with pytest.raises(ValueError, match='already attempted'):
        command(FakeCommand(**args))
    if kind == 'toolhead':
        material.cmd_TOOLHEAD_ACTION(toolhead_command(material, ID='toolhead_1030', SEQUENCE='1030'))
        callbacks.pop()(1)
        assert material.toolhead_operation['state'] == 'complete'
        assert '_CHANGE_TOOL T=2' in scripts
    else:
        material.cmd_FILAMENT_SEQUENCE(sequence_command(material, ID='filament_1030', SEQUENCE='1030', SESSION=material.session_id))
        assert material.filament_operation['state'] == 'running'
        assert callbacks  # Actual service scheduled exactly once after fresh review.
    assert getattr(material, '_' + kind + '_request_sequence') == 1030
    args['SEQUENCE'], args['ID'] = '1029', kind + '_1029'
    with pytest.raises(ValueError, match='superseded'):
        command(FakeCommand(**args))


@pytest.mark.parametrize('kind', ['filament', 'toolhead'])
@pytest.mark.parametrize('defect', ['old_session', 'missing_session', 'wrong_id', 'missing_sequence', 'zero', 'overflow'])
def test_material_sequence_binding_refuses_before_consumption(toolhead_material, kind, defect):
    material, objects, state, scripts, callbacks = toolhead_material
    args = dict(ID=kind + '_1', SEQUENCE='1', SESSION=material.session_id, HEAD='2', ACTION='take', ATTACHED='h2')
    if defect == 'old_session': args['SESSION'] = 'old'
    elif defect == 'missing_session': args.pop('SESSION')
    elif defect == 'wrong_id': args['ID'] = 'legacy-id'
    elif defect == 'missing_sequence': args.pop('SEQUENCE')
    elif defect == 'zero': args['SEQUENCE'] = '0'
    elif defect == 'overflow': args['SEQUENCE'] = '9223372036854775808'
    command = material.cmd_FILAMENT_SEQUENCE if kind == 'filament' else material.cmd_TOOLHEAD_ACTION
    with pytest.raises((ValueError, KeyError)):
        command(FakeCommand(**args))
    assert getattr(material, '_' + kind + '_request_sequence', 0) == 0
    assert not scripts and not callbacks


@pytest.mark.parametrize('kind', ['filament', 'toolhead'])
def test_material_sequence_consumed_before_current_busy_refusal(toolhead_material, kind):
    material, objects, state, scripts, callbacks = toolhead_material
    material.toolhead_operation = {'state': 'running'}
    args = dict(ID=kind + '_7', SEQUENCE='7', SESSION=material.session_id, HEAD='2', ACTION='take', ATTACHED='h2')
    command = material.cmd_FILAMENT_SEQUENCE if kind == 'filament' else material.cmd_TOOLHEAD_ACTION
    with pytest.raises(ValueError, match='unresolved'):
        command(FakeCommand(**args))
    material.toolhead_operation = {}
    with pytest.raises(ValueError, match='already attempted'):
        command(FakeCommand(**args))
    assert not scripts and not callbacks


def test_public_service_generates_sequenced_request_after_legacy_limit(sequence_material, monkeypatch):
    from types import SimpleNamespace
    material, objects = sequence_material
    objects['gcode'] = SimpleNamespace(create_gcode_command=lambda name, line, args: FakeCommand(**args))
    material._filament_requests.update('legacy-%d' % i for i in range(1024))
    scripts = []
    monkeypatch.setattr('wm_material.run_standalone_extrusion_sequence', lambda printer, script: scripts.append(script))
    material.cmd_FILAMENT_SERVICE(FakeCommand(ACTION='load', HEAD='2'))
    assert scripts == ['G1 E55 F400', 'G1 E50 F400']
    assert material.filament_operation['id'] == 'filament_1'
    assert material.filament_operation['state'] == 'complete'
    assert len(material._filament_requests) == 1024
    assert material._filament_request_sequence == 1


@pytest.mark.parametrize('kind', ['filament', 'toolhead'])
def test_legacy_material_request_limit_has_current_action_exit(toolhead_material, kind):
    material, _, _, scripts, callbacks = toolhead_material
    legacy = material._filament_requests if kind == 'filament' else material._toolhead_requests
    legacy.update('legacy-%d' % i for i in range(1024))
    command = material.cmd_FILAMENT_SEQUENCE if kind == 'filament' else material.cmd_TOOLHEAD_ACTION
    with pytest.raises(ValueError, match='Legacy .* request limit reached; use the current touchscreen'):
        command(toolhead_command(material))
    assert not scripts and not callbacks

# Modern recovery reviews issue bounded, session-scoped operation tickets.
def ticket_command(request, ticket):
    return FakeCommand(REQUEST=json.dumps(request).encode().hex(), TICKET=ticket['token'])


@pytest.mark.parametrize('persisted_prior_attempt', [False, True])
def test_recovery_ticket_review_repeat_and_real_continue(native_recovery_request, persisted_prior_attempt):
    fixture, request, checkpoint = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    if persisted_prior_attempt:
        material._recovery_attempt.run(dict(id='wmp2rc_1', session='previous-printer-session',
            execution_hash=request['execution_hash'], file=request['file']),
            [('prepare', lambda: None, lambda: True)])
        material._restore_recovery_attempt()
        assert material._recovery_attempt.record['request']['id'] == 'wmp2rc_1'
    mutex[0] = False
    web = recovery_review_web_request(request); web.params['ticket_protocol'] = '1'
    material._handle_recovery_review(web); first = json.loads(json.dumps(web.response))
    material._handle_recovery_review(web)
    assert web.response == first and first['request']['id'] == 'wmp2rc_' + first['ticket']['sequence']
    assert first['ticket']['selection_id'] == request['id'] and calls == timers == body == []
    mutex[0] = True
    material.cmd_RECOVERY_CONTINUE(ticket_command(first['request'], first['ticket']))
    assert len(timers) == 1
    before = list(calls)
    for command in [ticket_command(first['request'], first['ticket']), FakeCommand(REQUEST=first['encoded'])]:
        with pytest.raises(ValueError, match='ticket|TICKET'):
            material.cmd_RECOVERY_CONTINUE(command)
    assert len(timers) == 1 and calls == before


def test_recovery_ticket_continue_1100_and_refusal_consumption(native_recovery_request):
    material = native_recovery_request[0][0]; base = native_recovery_request[1]
    invoked = []
    material._recovery_review_service()._consume_recovery_request = lambda encoded, cancelled: invoked.append(encoded) or {}
    first = None
    for index in range(1100):
        selected = dict(base, id='selection-' + str(index))
        request, ticket = material._recovery_review_service()._issue_recovery_ticket('continue', selected)
        if first is None: first = request, ticket
        material.cmd_RECOVERY_CONTINUE(ticket_command(request, ticket))
        assert len(material._recovery_tickets['continue']['slots']) == 0
    assert len(invoked) == 1100 and not getattr(material, '_recovery_command_ids', set())
    with pytest.raises(ValueError, match='consumed|superseded'):
        material.cmd_RECOVERY_CONTINUE(ticket_command(*first))
    request, ticket = material._recovery_review_service()._issue_recovery_ticket('continue', dict(base, id='semantic-refusal'))
    def refuse(*args): raise ValueError('current sensor admission refused')
    material._recovery_review_service()._consume_recovery_request = refuse
    with pytest.raises(ValueError, match='sensor admission'):
        material.cmd_RECOVERY_CONTINUE(ticket_command(request, ticket))
    with pytest.raises(ValueError, match='consumed|superseded'):
        material.cmd_RECOVERY_CONTINUE(ticket_command(request, ticket))
    assert len(invoked) == 1100


def test_recovery_ticket_unconfirmed_reads_and_tamper(native_recovery_request):
    material = native_recovery_request[0][0]; base = native_recovery_request[1]
    old = material._recovery_review_service()._issue_recovery_ticket('continue', dict(base, id='old'))
    for index in range(1100):
        current = material._recovery_review_service()._issue_recovery_ticket('continue', dict(base, id='read-' + str(index)))
        assert len(material._recovery_tickets['continue']['slots']) == 1
    request, ticket = current
    assert not getattr(material, '_recovery_command_active', False)
    with pytest.raises(ValueError, match='consumed|superseded'):
        material._recovery_review_service()._consume_recovery_ticket('continue', old[0], ticket_command(*old))
    for changed in [dict(request, file='other.gcode'), dict(request, id='wmp2rc_99999'),
                    dict(request, session='old-session'), dict(request, id='legacy')]:
        with pytest.raises(ValueError):
            material._recovery_review_service()._consume_recovery_ticket('continue', changed, ticket_command(changed, ticket))
    with pytest.raises(ValueError):
        material._recovery_review_service()._consume_recovery_ticket('continue', request, ticket_command(request, dict(ticket, token='0'*64)))
    assert material._recovery_review_service()._consume_recovery_ticket('continue', request, ticket_command(request, ticket))
    material.session_id = 'new-session'
    with pytest.raises(ValueError, match='session'):
        material._recovery_review_service()._consume_recovery_ticket('continue', request, ticket_command(request, ticket))
    assert material._recovery_review_service()._recovery_ticket_state()['continue']['slots'] == {}


def test_recovery_resolution_ticket_1100_and_choice_pairs(recovery_abandon_machine):
    material, objects, states, calls, review, attempt = recovery_abandon_machine
    template = resolution_request(material)
    invoked = []
    material._recovery_review_service()._recovery_resolution_selection = lambda identity: dict(template, **identity)
    material._recovery_lifecycle()._abandon_recovery_attempt = lambda *args, **kwargs: invoked.append(args) or {}
    for index in range(1100):
        request, ticket = material._recovery_review_service()._issue_recovery_ticket('resolve', dict(template, id='resolve-' + str(index)))
        material.cmd_RECOVERY_RESOLVE(ticket_command(request, ticket))
        assert len(material._recovery_tickets['resolve']['slots']) == 0
    assert len(invoked) == 1100 and not getattr(material, '_recovery_resolution_ids', set())
    # Reading both alternatives does not choose one or reserve the machine.
    reconcile = material._recovery_review_service()._issue_recovery_ticket('resolve', dict(template, id='use-new', action='reconcile'))
    abandon = material._recovery_review_service()._issue_recovery_ticket('resolve', dict(template, id='discard'))
    assert len(material._recovery_tickets['resolve']['slots']) == 2 and len(invoked) == 1100
    material.cmd_RECOVERY_RESOLVE(ticket_command(*abandon))
    with pytest.raises(ValueError, match='consumed|superseded'):
        material.cmd_RECOVERY_RESOLVE(ticket_command(*reconcile))
    with pytest.raises(ValueError, match='TICKET'):
        material.cmd_RECOVERY_RESOLVE(resolution_command(abandon[0]))
    assert len(invoked) == 1101 and calls == []
    request, ticket = material._recovery_review_service()._issue_recovery_ticket('resolve', dict(template, id='failed-resolution'))
    def fail(*args, **kwargs): raise ValueError('resolution dispatch failed')
    material._recovery_lifecycle()._abandon_recovery_attempt = fail
    with pytest.raises(ValueError, match='dispatch failed'):
        material.cmd_RECOVERY_RESOLVE(ticket_command(request, ticket))
    assert material._recovery_resolution['state'] == 'unknown'
    with pytest.raises(ValueError, match='consumed|superseded'):
        material.cmd_RECOVERY_RESOLVE(ticket_command(request, ticket))


def test_recovery_resolution_review_ticket_is_read_only(recovery_abandon_machine):
    material, objects, states, calls, review, attempt = recovery_abandon_machine
    web = CancelWebRequest(id='read-only', attempt_id=attempt['id'], session=material.session_id,
                           action='abandon', ticket_protocol='1')
    material._handle_recovery_resolution_review(web); first = json.loads(json.dumps(web.response))
    material._handle_recovery_resolution_review(web)
    assert first == web.response and first['request']['id'] == 'wmp2rr_' + first['ticket']['sequence']
    assert first['ticket']['selection_id'] == 'read-only'
    assert calls == [] and not getattr(material, '_recovery_resolution', {})


def test_checkpoint_additive_fields_preserve_required_semantics(material):
    payload = recovery_checkpoint_payload()
    expected = material._recovery_storage()._recovery_checkpoint_values(payload, 6)
    assert material._recovery_storage()._recovery_checkpoint_values(payload + b'vendor_future_field=anything\n', 6) == expected
    with pytest.raises(ValueError, match='Malformed'):
        material._recovery_storage()._recovery_checkpoint_values(payload + b'vendor_future_field=a\nvendor_future_field=b\n', 6)


def test_additive_checkpoint_bytes_still_require_new_bound_marker(bound_recovery):
    material, objects, path, checkpoint, marker, chash, jhash = bound_recovery
    checkpoint.write_bytes(checkpoint.read_bytes() + b'vendor_future_field=1\n')
    with pytest.raises(ValueError):
        material._recovery_checkpoint_evidence(path.name, checkpoint.name, chash, jhash)


def test_checkpoint_capture_allows_absent_optional_auxiliary(execution_snapshot_machine):
    material, objects, states = execution_snapshot_machine
    objects.pop('fan_generic auxiliary_fan')
    snapshot = material._execution_evidence()._recovery_execution_snapshot()
    assert snapshot['fans'] == {'fan': .75}
    assert snapshot['heater_targets'] == {'extruder2': 220.5, 'heater_bed': 55.}


def test_recovery_optional_fan_absent_review_and_restore_notice(recovery_reference_machine, caplog):
    material, objects, states, calls, review, request = recovery_reference_machine
    objects.pop('fan_generic auxiliary_fan')
    original = material._recovery_read_bytes(material._recovery_execution_path(), 65536)
    refreshed = material._recovery_review_service()._recovery_execution_review(material.session_id, 'part.gcode', review['execution_hash'])
    assert refreshed['fan_warnings'] and 'auxiliary_fan' in refreshed['fan_warnings'][0]
    result = material._recovery_attempt.run(request, material._recovery_initial_stages(refreshed))
    assert result['state'] == 'complete'
    assert not any('SET_FAN_SPEED FAN=auxiliary_fan' in command for command in calls)
    assert any('M99106' in command for command in calls)
    assert any('HEATER=extruder2 TARGET=220.5' in command for command in calls)
    assert any('HEATER=heater_bed TARGET=55' in command for command in calls)
    assert 'restoration skipped: fan_generic auxiliary_fan' in caplog.text
    assert material._recovery_read_bytes(material._recovery_execution_path(), 65536) == original


def test_recovery_optional_fan_disappears_after_review_is_reported(recovery_reference_machine, caplog):
    material, objects, states, calls, review, request = recovery_reference_machine
    stages = material._recovery_initial_stages(review)
    objects.pop('fan_generic auxiliary_fan')
    assert material._recovery_attempt.run(request, stages)['state'] == 'complete'
    assert 'restoration skipped' in caplog.text


def test_recovery_missing_main_fan_still_refuses(recovery_reference_machine):
    material, objects, states, calls, review, request = recovery_reference_machine
    objects.pop('fan')
    with pytest.raises(ValueError, match='Required part-cooling'):
        material._recovery_review_service()._recovery_execution_review(material.session_id, 'part.gcode', review['execution_hash'])
    assert calls == []


def test_new_checkpoint_without_optional_fan_remains_readable(execution_snapshot_machine):
    material, objects, states = execution_snapshot_machine
    objects.pop('fan_generic auxiliary_fan')
    assert material._execution_evidence()._queue_recovery_execution()
    objects['toolhead'].check_busy = lambda now: (100., 100., False)
    assert material._execution_evidence()._publish_recovery_execution()
    material.printer.pause = lambda when: when
    assert material._read_completed_recovery_execution('part.gcode')['fans'] == {'fan': .75}


@pytest.mark.parametrize('entry', ['timer', 'completed_sd'])
def test_sampler_batch_reuses_loaded_missing_profile_without_parser_churn(execution_queued_boundary, monkeypatch, entry):
    import builtins
    import gc
    import wm_material
    material, objects, states, tail = execution_queued_boundary
    Path(material.profile_path).unlink(missing_ok=True)
    material.ini_path = str(Path(material.profile_path).with_name('tmt1.ini'))
    Path(material.ini_path).write_text('[slot]\n' + ''.join(
        'material%d=0\ncolor%d=0\n' % (i,i) for i in range(4)))
    material._material_settings()._status_profiles_snapshot = None
    # Warm the missing-profile legacy projection exactly once, as startup does.
    profiles, revision = material._profiles()
    job = recovery_job_record(material)
    job['heads']['h2']['identity'] = profiles['h2']
    sd = objects['virtual_sdcard']
    path = Path(sd.current_file.name)
    path.write_text('G1 X1\n' * 100)
    import hashlib
    job['file'].update(size=path.stat().st_size, modified=path.stat().st_mtime,
                       sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    material._write_recovery_job(job)
    if entry == 'timer':
        objects['virtual_sdcard'].from_sd = False
        objects['virtual_sdcard'].file_position = 6
    parser_type = wm_material.configparser.ConfigParser
    opens, parsers = [], []
    real_open = builtins.open
    def opened(path, *args, **kwargs):
        if str(path) in (material.profile_path, material.ini_path): opens.append(str(path))
        return real_open(path,*args,**kwargs)
    def parser(*args, **kwargs):
        parsers.append(1)
        return parser_type(*args,**kwargs)
    monkeypatch.setattr(builtins, 'open', opened)
    monkeypatch.setattr(wm_material.configparser, 'ConfigParser', parser)
    clock=[100.]
    material.printer.get_reactor().monotonic=lambda: clock[0]
    objects['toolhead'].check_busy=lambda now: (clock[0], clock[0], False)
    published=[]
    original_write=material._write_recovery_json
    def write(path,record):
        if path==material._recovery_execution_path(for_write=True): published.append(json.loads(json.dumps(record)))
        return original_write(path,record)
    monkeypatch.setattr(material._recovery_storage(),'_write_recovery_json',write)
    def sample():
        if entry=='timer': material._execution_evidence()._execution_tick(clock[0])
        else: material._execution_command_completed(material._execution_sd_boundary())
    gc.collect()
    before=sum(type(obj) is parser_type for obj in gc.get_objects())
    enabled=gc.isenabled();gc.disable()
    try:
        for tick in range(20):
            clock[0]+=2.
            if getattr(material, '_pending_execution_snapshot', None) is None:
                if entry=='timer': sd.file_position=6*(tick+1)
                sample()
            candidate=material._pending_execution_snapshot
            assert candidate is not None and candidate['scheduled_print_time'] is None
            assert len(published)==tick  # Not durable while still unscheduled.
            tail.timing_callbacks[-1](clock[0]+4.)
            clock[0]+=5.
            sd.file_position=candidate['file_position']
            sd.next_file_position=sd.file_position+6
            sample()
            assert not material._execution_error
            assert len(published)==tick+1
            assert published[-1]['file_position']==6*(tick+1)
            assert published[-1]['completed_print_time']>=published[-1]['scheduled_print_time']
        assert len(set(row['file_position'] for row in published))==20
        durable=json.loads(Path(material._recovery_execution_path()).read_text())
        assert durable==published[-1] and durable['state']=='completed'
        assert not opens and not parsers
        assert sum(type(obj) is parser_type for obj in gc.get_objects())==before
        assert material._status_observation_cache is None
    finally:
        gc.collect()
        if enabled: gc.enable()
    # Command admission remains fresh, including externally changed legacy data.
    profiles, revision = material._profiles()
    assert opens and parsers
    changed = dict(profiles['h2'], color='#123456')
    material.cmd_SET_FILAMENT(FakeCommand(HEAD=2, EXPECT=revision,
        PROFILE=json.dumps(changed).encode().hex()))
    observed=[]
    previous_loaded=material._loaded_filament_status
    def loaded(now):
        result=previous_loaded(now)
        observed.append(result['h2']['identity']['color'])
        return result
    monkeypatch.setattr(material._filament_state(),'_loaded_filament_status',loaded)
    opens.clear();parsers.clear()
    material._pending_execution_snapshot=None
    clock[0]+=2.
    if entry=='timer': material._execution_evidence()._execution_tick(clock[0])
    else: material._execution_command_completed(material._execution_sd_boundary())
    assert not material._execution_error
    assert observed and set(observed)=={'#123456'}
    assert not opens and not parsers


@pytest.mark.parametrize('entry', ['timer', 'completed_sd'])
def test_sampler_observation_scope_restores_even_when_publication_fails(execution_queued_boundary, monkeypatch, entry):
    material, objects, states, tail = execution_queued_boundary
    previous={('outer',): 'untouched'}
    material._status_observation_cache=previous
    def fail():
        assert material._status_observation_cache is not previous
        raise ValueError('publication failed')
    monkeypatch.setattr(material._execution_evidence(),'_publish_recovery_execution',fail)
    if entry=='timer': material._execution_evidence()._execution_tick(1.)
    else: material._execution_command_completed(material._execution_sd_boundary())
    assert material._status_observation_cache is previous
    assert material._execution_error=='publication failed'


def test_runtime_evidence_reads_interrupted_legacy_without_migration(completed_execution,tmp_path):
    material, objects, states=completed_execution
    old=Path(material._recovery_execution_path())
    payload=old.read_bytes()
    legacy=Path(material.profile_path).parent/'wmp_recovery_execution.json'
    if old!=legacy: old.replace(legacy)
    runtime=tmp_path/'runtime-native';runtime.mkdir()
    material.recovery_checkpoint_dir=str(runtime)
    before=legacy.stat()
    assert material._recovery_execution_path()==str(legacy)
    assert material._read_completed_recovery_execution('part.gcode')['state']=='completed'
    assert legacy.read_bytes()==payload and legacy.stat()==before
    assert not list(runtime.iterdir())
    # New writes leave archived legacy bytes alone and become read authority.
    record=json.loads(payload)
    material._write_recovery_json(material._recovery_execution_path(for_write=True),record)
    assert Path(material._recovery_execution_path()).parent==runtime
    assert legacy.read_bytes()==payload
    record['job_fingerprint']='wrong-job'
    material._write_recovery_json(material._recovery_execution_path(for_write=True),record)
    with pytest.raises(ValueError,match='different job'):
        material._read_completed_recovery_execution('part.gcode')


@pytest.mark.parametrize('fail_job_write',[False,True])
def test_runtime_invalidation_deletes_both_generations_and_syncs_directories(material,tmp_path,monkeypatch,fail_job_write):
    import errno
    import os
    config=Path(material.profile_path).parent
    runtime=tmp_path/'runtime-native';runtime.mkdir()
    material.recovery_checkpoint_dir=str(runtime)
    paths=[folder/name for folder in (config,runtime) for name in
           ('wmp_recovery_execution.json','wmp_recovery_envelope.json')]
    for path in paths:path.write_bytes(b'old authority')
    if fail_job_write:
        monkeypatch.setattr(material._recovery_storage(),'_write_recovery_job',lambda value:(_ for _ in ()).throw(OSError(errno.ENOSPC,'full disk')))
    synced=[];real_sync=os.fsync
    def sync(fd):
        synced.append(os.readlink('/proc/self/fd/%d'%fd));return real_sync(fd)
    monkeypatch.setattr(os,'fsync',sync)
    material._disable_print_recovery('qualification invalidation')
    assert not any(path.exists() for path in paths)
    assert str(config) in synced and str(runtime) in synced
    with pytest.raises(ValueError,match='No managed execution'):
        material._recovery_execution_bytes()
    assert material._print_recovery_error=='qualification invalidation'


def test_runtime_first_publication_failure_preserves_legacy_without_partial_authority(completed_execution,tmp_path,monkeypatch):
    import os
    material,objects,states=completed_execution
    original=Path(material._recovery_execution_path()).read_bytes()
    legacy=Path(material.profile_path).parent/'wmp_recovery_execution.json'
    legacy.write_bytes(original)
    runtime=tmp_path/'runtime-native';runtime.mkdir()
    material.recovery_checkpoint_dir=str(runtime)
    monkeypatch.setattr(os,'replace',lambda *args:(_ for _ in ()).throw(OSError('publication failed')))
    with pytest.raises(OSError,match='publication failed'):
        material._write_recovery_json(material._recovery_execution_path(for_write=True),json.loads(original))
    assert not list(runtime.iterdir())
    assert material._recovery_execution_bytes()==original
    assert legacy.read_bytes()==original



def test_runtime_post_replace_sync_failure_never_selects_older_legacy(completed_execution,tmp_path,monkeypatch):
    import os
    import stat
    material,objects,states=completed_execution
    old=Path(material._recovery_execution_path()).read_bytes()
    legacy=Path(material.profile_path).parent/'wmp_recovery_execution.json'
    legacy.write_bytes(old)
    runtime=tmp_path/'runtime-native';runtime.mkdir()
    material.recovery_checkpoint_dir=str(runtime)
    record=json.loads(old);record['file_position']+=1
    real_sync=os.fsync
    def sync(fd):
        if stat.S_ISDIR(os.fstat(fd).st_mode): raise OSError('directory sync failed')
        return real_sync(fd)
    monkeypatch.setattr(os,'fsync',sync)
    with pytest.raises(OSError,match='directory sync failed'):
        material._write_recovery_json(material._recovery_execution_path(for_write=True),record)
    assert Path(material._recovery_execution_path()).parent==runtime
    assert json.loads(material._recovery_execution_bytes())==record
    assert legacy.read_bytes()==old


@pytest.mark.parametrize('failure',['none','legacy_unlink','legacy_sync'])
def test_runtime_invalidation_durable_fallback_barrier(material,tmp_path,monkeypatch,failure):
    import os
    config=Path(material.profile_path).parent
    runtime=tmp_path/'runtime-native';runtime.mkdir()
    material.recovery_checkpoint_dir=str(runtime)
    names=('wmp_recovery_execution.json','wmp_recovery_envelope.json')
    for name in names:
        (config/name).write_bytes(b'legacy')
        (runtime/name).write_bytes(b'runtime')
    monkeypatch.setattr(material._recovery_storage(),'_write_recovery_job',lambda value:(_ for _ in ()).throw(OSError('full disk')))
    trace=[];actual_unlink=os.unlink;actual_sync=os.fsync
    def unlink(path):
        path=str(path);trace.append(('unlink',path))
        if failure=='legacy_unlink' and path==str(config/names[0]):raise OSError('legacy delete failed')
        if Path(path).parent==runtime:
            assert ('synced',str(config)) in trace
            assert not (config/Path(path).name).exists()
        return actual_unlink(path)
    def sync(fd):
        path=os.readlink('/proc/self/fd/%d'%fd)
        trace.append(('sync',path))
        if failure=='legacy_sync' and path==str(config):raise OSError('legacy sync failed')
        actual_sync(fd);trace.append(('synced',path))
    monkeypatch.setattr(os,'unlink',unlink);monkeypatch.setattr(os,'fsync',sync)
    material._disable_print_recovery('test failure')
    if failure=='none':
        assert not any((folder/name).exists() for folder in (config,runtime) for name in names)
    else:
        assert (runtime/names[0]).read_bytes()==b'runtime'
        assert material._recovery_execution_path()==str(runtime/names[0])
        assert 'legacy' in material._recovery_invalidation_error
        if failure=='legacy_sync':
            assert (runtime/names[1]).read_bytes()==b'runtime'
    assert trace.index(('sync',str(config))) < trace.index(('sync',str(runtime)))


@pytest.mark.parametrize('kind', ['continue', 'resolve'])
@pytest.mark.parametrize('prior_id', ['session_bound', 'legacy_counter'])
def test_recovery_ticket_ids_do_not_repeat_after_session_restart(material, kind, prior_id):
    from wm_material import RecoveryAttempt
    calls, records = [], []
    selection = dict(id='screen-selection', session=material.session_id,
                     execution_hash='a' * 16, file='part.gcode')
    if kind == 'resolve':
        selection['action'] = 'abandon'
    first, first_ticket = material._recovery_review_service()._issue_recovery_ticket(kind, selection)
    assert material._recovery_review_service()._consume_recovery_ticket(kind, first, ticket_command(first, first_ticket))
    # Exercise the durable attempt's actual ID-only replay check, not just
    # uniqueness of two strings. A restarted worker retains this journal.
    attempt_request = {key: first[key] for key in ('id', 'session', 'execution_hash', 'file')}
    if prior_id == 'legacy_counter':
        attempt_request['id'] = 'wmp2rc_1' if kind == 'continue' else 'wmp2rr_1'
    runner = RecoveryAttempt(records.append)
    runner.run(attempt_request, [('prepare', lambda: calls.append('old'), lambda: True)])
    restored = RecoveryAttempt(records.append, runner.record)
    material.session_id = 'new-printer-session'
    second, second_ticket = material._recovery_review_service()._issue_recovery_ticket(kind, dict(selection, session=material.session_id))
    assert first_ticket['sequence'] != second_ticket['sequence']
    prefix = 'wmp2rc_' if kind == 'continue' else 'wmp2rr_'
    for operation, ticket in ((first, first_ticket), (second, second_ticket)):
        assert operation['id'] == prefix + ticket['sequence']
        assert ticket['sequence'].isascii() and ticket['sequence'].isdigit()
        assert ticket['sequence'][0] != '0'
    assert first['id'] != second['id']
    assert len(first['id']) <= 64 and len(second['id']) <= 64
    with pytest.raises(ValueError, match='session'):
        material._recovery_review_service()._consume_recovery_ticket(kind, first, ticket_command(first, first_ticket))
    assert material._recovery_review_service()._consume_recovery_ticket(kind, second, ticket_command(second, second_ticket))
    next_request = {key: second[key] for key in ('id', 'session', 'execution_hash', 'file')}
    assert restored.run(next_request, [('prepare', lambda: calls.append('new'), lambda: True)])['state'] == 'complete'
    with pytest.raises(ValueError, match='already attempted'):
        restored.run(next_request, [('prepare', lambda: calls.append('replay'), lambda: True)])
    with pytest.raises(ValueError, match='consumed|superseded'):
        material._recovery_review_service()._consume_recovery_ticket(kind, second, ticket_command(second, second_ticket))
    assert calls == ['old', 'new']


def test_recovery_ticket_response_passes_native_wire_validator(material, tmp_path):
    import shutil
    import subprocess
    compiler = shutil.which('g++')
    if compiler is None:
        pytest.skip('Native wire-contract check requires g++')
    root = Path(__file__).resolve().parents[1]
    source = tmp_path / 'recovery_ticket_contract.cpp'
    binary = tmp_path / 'recovery_ticket_contract'
    source.write_text('''#include "recovery_request.hpp"
#include <iostream>
int main() {
    wmp_ui::Json cases; std::cin >> cases;
    for (const auto& item : cases) {
        std::cout << wmp_ui::recovery_ticket_suffix(item.at("request"),
            item.at("ticket"), "selection", item.at("prefix").get<std::string>().c_str()) << "\\n";
    }
}
''')
    subprocess.run([compiler, '-std=c++17', '-I' + str(root / 'client-preload/unified-ui'),
        '-I' + str(root / 'client-preload/openace-compat/screen1113/source/vendor'),
        str(source), '-o', str(binary)], check=True, capture_output=True, text=True)
    cases = []
    for session in ('old-session', 'new-session'):
        material.session_id = session
        for kind, prefix in (('continue', 'wmp2rc_'), ('resolve', 'wmp2rr_')):
            selection = dict(id='selection', session=session, action='abandon')
            request, ticket = material._recovery_review_service()._issue_recovery_ticket(kind, selection)
            cases.append(dict(request=request, ticket=ticket, prefix=prefix))
    result = subprocess.run([str(binary)], input=json.dumps(cases), check=True,
                            capture_output=True, text=True)
    assert result.stdout.splitlines() == [' TICKET=' + case['ticket']['token'] for case in cases]


@pytest.fixture
def fault_service_material(paused_origin_material):
    from types import SimpleNamespace
    material, objects, state = paused_origin_material
    scripts = []
    objects['gcode'] = SimpleNamespace(scripts=scripts, run_script_from_command=scripts.append)
    material.printer.is_shutdown = lambda: False
    objects['pause_resume'].is_paused = True
    state['variables'].update({'box_modify_t%d' % i: i for i in range(4)})
    objects['gcode_move'].saved_states.clear()  # No fabricated stock pause states.
    material._pause_origin = None
    material._toolchange_pause = {
        'state': 'paused', 'session': material.session_id,
        'handle': objects['virtual_sdcard'].current_file, 'start': 120, 'end': 123,
        'target': 3, 'logical': 'T3', 'stage': 'coupling', 'message': 'test pickup fault',
        'mapping': [0, 1, 2, 3], 'logical_e': 42., 'service_required': set(),
        'context': {'position': [20, 30, 5], 'absolute': True, 'absolute_e': False}}
    return material, objects, state


def test_fault_service_origin_is_real_attachment_without_fake_pause_states(fault_service_material):
    material, objects, state = fault_service_material
    before = json.loads(json.dumps(material._toolchange_pause['context']))
    plan = material._filament_plan(2, 'load', 1)
    assert plan['pause_origin']['head'] == 'h2'
    assert plan['service']['restore_offset'] == [0.2, -0.1, 0.05]
    assert material._pause_origin['kind'] == 'toolchange'
    assert 'states' not in material._pause_origin
    assert objects['gcode_move'].saved_states == {}
    assert material._toolchange_pause['context'] == before
    assert objects['gcode'].scripts == []
    assert material._paused_filament_status(1)['available']


@pytest.mark.parametrize('change', ['empty', 'unknown', 'motor', 'file', 'cursor', 'mapping', 'moving', 'running', 'unhomed'])
def test_fault_service_current_binding_refuses_concrete_invalid_state(fault_service_material, change):
    import io
    material, objects, state = fault_service_material
    if change in ('empty', 'unknown'):
        material._material_status()._attachment = lambda now: {'state': change, 'head': ''}
    elif change == 'motor': objects['toolhead'].get_status(1)['extruder'] = 'extruder'
    elif change == 'file': objects['virtual_sdcard'].current_file = io.StringIO('different')
    elif change == 'cursor': objects['virtual_sdcard'].file_position += 1
    elif change == 'mapping': state['variables']['box_modify_t0'] = 3
    elif change == 'moving': state['active'] = True
    elif change == 'running': state['job'] = 'printing'
    elif change == 'unhomed': objects['toolhead'].get_status(1)['homed_axes'] = 'xy'
    with pytest.raises(ValueError): material._filament_plan(2, 'load', 1)
    assert objects['gcode'].scripts == []


@pytest.mark.parametrize('history', ['unknown', 'failed', 'refused', 'complete'])
def test_fault_service_history_does_not_disable_new_load(fault_service_material, history):
    material, objects, state = fault_service_material
    material.filament_operation = {'state': history}
    material.toolhead_operation = {'state': history}
    assert material._filament_plan(2, 'load', 1)['head'] == 'h2'
    available, reason = material._toolchange_repair()._fault_manual_toolhead(1)
    assert available and not reason


def test_fault_take_dock_exception_is_not_general_paused_permission(fault_service_material):
    material, objects, state = fault_service_material
    objects['gcode_macro _CHANGE_TOOL'] = objects['gcode_macro PARK_CURRENT_TOOL'] = object()
    assert material._toolheads()._toolhead_context(2, 'dock', 1, fresh=True)['head'] == 'h2'
    assert material._toolheads()._toolhead_context(3, 'take', 1, fresh=True)['head'] == 'h2'
    saved_origin = dict(material._toolchange_pause['context'])
    assert material._toolchange_pause['context'] == saved_origin
    material._toolchange_pause = None
    with pytest.raises(ValueError, match='idle printer'):
        material._toolheads()._toolhead_context(3, 'take', 1, fresh=True)


def test_fault_load_actual_completion_keeps_print_origin_and_marks_required(fault_service_material, monkeypatch):
    from types import SimpleNamespace
    material, objects, state = fault_service_material
    sensor = objects['filament_switch_sensor filament2'].get_status(1)
    sensor['filament_detected'] = False
    material._set_filament_loaded('h2', False)
    plan = material._filament_plan(2, 'load', 1)
    record = material._toolchange_pause
    original = dict(record['context'])
    material.filament_operation = {'id': 'paused-service', 'session': material.session_id, 'action': plan['action'], 'state': 'running', 'head': 'h2', 'pause_origin': plan['pause_origin']}
    heater = {'temperature': 250, 'target': 0, 'can_extrude': True}
    objects['extruder2'] = SimpleNamespace(get_status=lambda now: dict(heater))
    calls = []
    def run(script):
        calls.append(script)
        if 'TARGET=' in script:
            heater['target'] = heater['temperature'] = float(script.split('TARGET=')[1])
    objects['gcode'] = SimpleNamespace(run_script_from_command=run)
    sensor['filament_detected'] = True
    monkeypatch.setattr('wm_material.run_standalone_extrusion_sequence', lambda printer, script: None)
    material._filament_service()._execute_filament(FakeCommand(), 2, 'load', plan)
    assert material.filament_operation['state'] == 'complete'
    assert record['service_required'] == {'h2'} and record['context'] == original
    assert objects['gcode_move'].saved_states == {}
    material._toolchange_repair()._check_fault_service_complete(record, 1)
    # Exercise the real unload/load execution entrypoints in the same fault
    # pause. A successful unload is not permission to resume without material.
    unload = material._filament_plan(2, 'unload', 1)
    material.filament_operation = {'id': 'paused-service', 'session': material.session_id, 'action': unload['action'], 'state': 'running', 'head': 'h2', 'pause_origin': unload['pause_origin']}
    material._filament_service()._execute_filament(FakeCommand(), 2, 'unload', unload)
    with pytest.raises(ValueError, match='Load or check filament in Head 3'):
        material._toolchange_repair()._check_fault_service_complete(record, 1)
    reload = material._filament_plan(2, 'load', 1)
    material.filament_operation = {'id': 'paused-service', 'session': material.session_id, 'action': reload['action'], 'state': 'running', 'head': 'h2', 'pause_origin': reload['pause_origin']}
    material._filament_service()._execute_filament(FakeCommand(), 2, 'load', reload)
    material._toolchange_repair()._check_fault_service_complete(record, 1)
    assert record['context'] == original and record['logical_e'] == 42.
    assert objects['gcode_move'].saved_states == {}

@pytest.fixture
def ordinary_pause_toolhead(paused_origin_material):
    from types import SimpleNamespace
    from contextlib import nullcontext
    import copy
    material, objects, state = paused_origin_material
    material._toolhead_requests = set()
    material.toolhead_operation = {}
    callbacks, scripts = [], []
    physical = {'state': 'attached', 'head': 'h2'}
    offset = [.2, -.1, .05]
    material._material_status()._attachment = lambda now: dict(physical)
    objects['gcode_macro _CHANGE_TOOL'] = object()
    objects['gcode_macro PARK_CURRENT_TOOL'] = object()
    material.printer.is_shutdown = lambda: False
    material.printer.register_callback = callbacks.append
    objects['filament_switch_sensor filament2'].get_status = lambda now: {'filament_detected': True}
    def run(line):
        scripts.append(line)
        if line == 'PARK_CURRENT_TOOL':
            physical.update(state='empty', head=''); offset[:] = [0, 0, 0]
        elif line == '_CHANGE_TOOL T=2':
            physical.update(state='attached', head='h2'); offset[:] = [.4, .5, .6]
        elif line.startswith('SET_GCODE_OFFSET '):
            values=dict(word.split('=') for word in line.split()[1:])
            assert values['MOVE']=='0'
            offset[:] = [float(values[k]) for k in ('X','Y','Z')]
    objects['gcode'] = SimpleNamespace(get_mutex=nullcontext, run_script_from_command=run)
    return material, objects, state, physical, offset, callbacks, scripts


def test_ordinary_paused_dock_take_preserves_origin_and_offset(ordinary_pause_toolhead):
    import copy
    material, objects, state, physical, offset, callbacks, scripts = ordinary_pause_toolhead
    original = copy.deepcopy(objects['gcode_move'].saved_states)
    origin = material._pause_origin
    assert material._ordinary_paused_toolhead_status(1)['actions']==['dock']
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material, ACTION='dock', ID='paused-dock'))
    assert scripts==[]
    callbacks.pop()(1)
    assert material.toolhead_operation['state']=='complete'
    assert material._ordinary_paused_toolhead_status(1)['actions']==['take']
    with pytest.raises(ValueError, match='Mount the original'):
        material.cmd_CHECK_RESUME(FakeCommand())
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material, ATTACHED='none', ID='paused-take'))
    callbacks.pop()(1)
    assert material.toolhead_operation['state']=='complete'
    assert offset==[.2,-.1,.05]
    assert scripts.count('PARK_CURRENT_TOOL')==1 and scripts.count('_CHANGE_TOOL T=2')==1
    assert objects['gcode_move'].saved_states==original
    assert material._pause_origin is origin
    assert not origin.get('serviced',False)
    material._paused_service()._retire_changed_print_recovery=lambda *args: None
    material.cmd_CHECK_RESUME(FakeCommand())


@pytest.mark.parametrize('change', ['head','cursor','active','homing','reference','service','session','new_origin'])
def test_ordinary_paused_toolhead_revalidates_before_motion(ordinary_pause_toolhead, change):
    material, objects, state, physical, offset, callbacks, scripts = ordinary_pause_toolhead
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material, ACTION='dock', ID='paused-dock'))
    if change=='head':physical['head']='h3'
    elif change=='cursor':objects['virtual_sdcard'].file_position+=1
    elif change=='active':state['active']=True
    elif change=='homing':objects['toolhead'].get_status(1)['homed_axes']='xy'
    elif change=='reference':objects['wmp_recovery'].get_status(1)['z_reference_valid']=False
    elif change=='service':material.filament_operation={'state':'running','session':material.session_id}
    elif change=='session':material.session_id='new'
    elif change=='new_origin':material._pause_origin=dict(material._pause_origin)
    callbacks.pop()(1)
    assert material.toolhead_operation['state']=='refused'
    assert scripts==[]


def test_ordinary_paused_toolhead_wrong_head_and_failed_pickup_retry(ordinary_pause_toolhead):
    material, objects, state, physical, offset, callbacks, scripts = ordinary_pause_toolhead
    physical.update(state='empty',head='')
    with pytest.raises(ValueError):
        material.cmd_TOOLHEAD_ACTION(toolhead_command(material, HEAD='3',ATTACHED='none',ID='wrong'))
    realrun=objects['gcode'].run_script_from_command
    def failed(line):
        if line=='_CHANGE_TOOL T=2':raise ValueError('pickup failed before attachment')
        realrun(line)
    objects['gcode'].run_script_from_command=failed
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material,ATTACHED='none',ID='failed'))
    callbacks.pop()(1)
    assert material.toolhead_operation['state']=='unknown'
    assert material._ordinary_paused_toolhead_status(1)['actions']==['take']
    objects['gcode'].run_script_from_command=realrun
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material,ATTACHED='none',ID='retry'))
    callbacks.pop()(1)
    assert material.toolhead_operation['state']=='complete'
    assert offset==[.2,-.1,.05]


def test_toolhead_switch_reports_old_head_docking_before_mount(toolhead_material):
    material, objects, state, scripts, callbacks = toolhead_material
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material, HEAD='3'))
    assert [step['label'] for step in material.toolhead_operation['steps']] == [
        'Check head attachment', 'Dock Head 3', 'Mount Head 4', 'Verify attachment sensors']
    phases = []
    def run(script):
        scripts.append(script)
        if script == '_CHANGE_TOOL T=3':
            phases.append(material.toolhead_operation['phase'])
            material.cmd_TOOLHEAD_PROGRESS(FakeCommand(T='3', PHASE='docking'))
            phases.append(material.toolhead_operation['phase'])
            assert material.toolhead_operation['message'] == 'Docking Head 3...'
            material.cmd_TOOLHEAD_PROGRESS(FakeCommand(T='3', PHASE='moving'))
            phases.append(material.toolhead_operation['phase'])
            assert material.toolhead_operation['message'] == 'Mounting Head 4...'
            material._material_status()._attachment = lambda now: {'state': 'attached', 'head': 'h3'}
    objects['gcode'].run_script_from_command = run
    callbacks.pop()(1)
    assert phases == ['docking', 'docking', 'moving']
    assert material.toolhead_operation['state'] == 'complete'


@pytest.mark.parametrize('attachment', [{'state': 'empty', 'head': ''}, {'state': 'attached', 'head': 'h2'}])
def test_toolhead_take_without_switch_omits_docking_step(toolhead_material, attachment):
    material, objects, state, scripts, callbacks = toolhead_material
    material._material_status()._attachment = lambda now: attachment
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material, ATTACHED=attachment['head'] or 'none'))
    assert [step['phase'] for step in material.toolhead_operation['steps']] == ['checking', 'moving', 'verifying']


@pytest.mark.parametrize('updates', [{'T': '1', 'PHASE': 'moving'}, {'T': '3', 'PHASE': 'invalid'}])
def test_toolhead_progress_notification_cannot_change_other_operation(toolhead_material, updates):
    material, objects, state, scripts, callbacks = toolhead_material
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material, HEAD='3'))
    before = dict(material.toolhead_operation)
    material.cmd_TOOLHEAD_PROGRESS(FakeCommand(**updates))
    assert material.toolhead_operation == before and scripts == []
    material.toolhead_operation['state'] = 'complete'
    before = dict(material.toolhead_operation)
    material.cmd_TOOLHEAD_PROGRESS(FakeCommand(T='3', PHASE='moving'))
    assert material.toolhead_operation == before and scripts == []


def test_nozzle_save_applies_live_only_after_persistence(material, tmp_path):
    from types import SimpleNamespace
    from wmp_nozzles import NozzleSettings
    import math
    cfg, ini = tmp_path/'printer.cfg', tmp_path/'tmt1.ini'
    cfg.write_text('[extruder2]\nnozzle_diameter: 0.4\n')
    ini.write_text('[nozzle]\ntype2=0\n')
    material._nozzles = NozzleSettings(cfg, ini)
    extruder = SimpleNamespace(nozzle_diameter=.4, filament_area=math.pi*.875**2,
        max_extrude_ratio=5000., max_e_velocity=200., max_e_accel=10000.)
    settings = {'extruder2': {'nozzle_diameter': .4}}
    explicit = {'extruder2': dict.fromkeys(('max_extrude_cross_section',
        'max_extrude_only_velocity', 'max_extrude_only_accel'), 'configured')}
    flushes = []
    def flush():
        assert '0.6' in cfg.read_text()  # File commit precedes runtime application.
        flushes.append(1)
    original = material.printer.lookup_object
    objects = {'extruder2': extruder,
        'toolhead': SimpleNamespace(flush_step_generation=flush),
        'configfile': SimpleNamespace(get_status=lambda now: {'settings':settings, 'config':explicit})}
    material.printer.lookup_object = lambda name, default=None: objects.get(name, original(name, default))
    state = material._nozzle_status(1)
    cmd = FakeCommand(HEAD=2, DIAMETER='0.6', MATERIAL=1,
        EXPECT=state['nozzle_revision'], SESSION='test-session', ID='live-nozzle')
    material.cmd_SET_NOZZLE(cmd)
    current = material._nozzle_status(1)['nozzles']['h2']
    assert current['active_diameter'] == .6 and not current['restart_required']
    assert current['live_update_supported'] and not current['apply_pending'] and not current['apply_error']
    assert (extruder.max_extrude_ratio, extruder.max_e_velocity, extruder.max_e_accel) == (5000.,200.,10000.)
    assert settings['extruder2']['nozzle_diameter'] == .4 and flushes == [1]
    # A stale save fails without changing live geometry.
    cmd.args['DIAMETER'] = '0.8'
    with pytest.raises(ValueError, match='changed'):
        material.cmd_SET_NOZZLE(cmd)
    assert extruder.nozzle_diameter == .6 and flushes == [1]


@pytest.mark.parametrize('attachment,needs_home,expected', [
    ({'state':'attached','head':'h2'},False,['Position Head 3']),
    ({'state':'attached','head':'h0'},True,['Home X/Y','Dock Head 1','Mount Head 3','Position Head 3']),
    ({'state':'empty','head':''},False,['Mount Head 3','Position Head 3']),
])
def test_filament_progress_lists_existing_service_moves(attachment, needs_home, expected):
    from wmp_filament_planning import service_progress_steps
    steps = service_progress_steps(2, {'attachment':attachment, 'needs_home':needs_home})
    assert [label for _,label in steps] == expected

def test_progress_details_do_not_require_extra_motion_context():
    from wmp_filament_planning import service_progress_steps
    assert service_progress_steps(2,{}) == [('preparing','Position Head 3')]

@pytest.mark.parametrize('axes,z_valid,action,homing', [('xy',False,'take',True),('',False,'dock',True),('xyz',True,'take',False)])
def test_toolhead_progress_reports_stock_homing_only_when_needed(toolhead_material,axes,z_valid,action,homing):
    material,objects,state,scripts,callbacks=toolhead_material
    state['toolhead']['homed_axes']=axes
    state['wmp_recovery']['z_reference_valid']=z_valid
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material,ACTION=action))
    assert ('homing' in [step['phase'] for step in material.toolhead_operation['steps']]) is homing
    if homing:
        material.cmd_TOOLHEAD_PROGRESS(FakeCommand(T='2',PHASE='homing'))
        assert material.toolhead_operation['phase']=='homing'
        assert material.toolhead_operation['message']=='Homing axes...'
    assert scripts == []


def test_toolhead_dispatch_does_not_claim_mount_before_required_homing(toolhead_material):
    material, objects, state, scripts, callbacks = toolhead_material
    state['toolhead']['homed_axes'] = ''
    state['wmp_recovery']['z_reference_valid'] = False
    observed = []
    original = objects['gcode'].run_script_from_command
    def run(command):
        if command.startswith('_CHANGE_TOOL '):
            observed.append(material.toolhead_operation['phase'])
        return original(command)
    objects['gcode'].run_script_from_command = run
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material, ACTION='take'))
    callbacks.pop()(1)
    assert observed == ['homing']


def test_service_shared_pickup_checks_result_without_print_finalization(service_material):
    from types import SimpleNamespace
    material, objects, state = service_material
    material._material_status()._attachment = lambda now: {'state': 'empty', 'head': ''}
    calls = []
    objects['gcode'] = SimpleNamespace(run_script_from_command=calls.append)
    context = material._service_context(2, 1)
    material._prepare_service(2, context)
    assert '_LOCK_TOOL T=2 SERVICE=1' in calls
    assert not any(command.startswith('_CHECK_CHANGE_TOOL ') for command in calls)
    assert not any('MOVE=1' in command for command in calls)


@pytest.mark.parametrize('returning', [False, True])
@pytest.mark.parametrize('needs_home', [False, True])
def test_service_progress_follows_physical_commands_without_jumping_ahead(service_material, returning, needs_home):
    from types import SimpleNamespace
    from wmp_filament_planning import service_progress_steps
    material, objects, state = service_material
    material._material_status()._attachment = lambda now: {'state': 'attached', 'head': 'h0'}
    state['toolhead']['homed_axes'] = 'z' if needs_home else 'xyz'
    context = material._service_context(2, 1, allow_homing=True)
    phase_name = 'returning' if returning else 'preparing'
    planned = [phase for phase, _ in service_progress_steps(2, context, phase_name)]
    observed = []
    prefix = 'return_' if returning else ''
    def run(command):
        phase = material.filament_operation['phase']
        observed.append(planned.index(phase))
        if command.startswith('G28'):
            assert phase == prefix + 'homing'
            state['toolhead']['homed_axes'] = 'xyz'
        elif command.startswith('_UNLOCK_TOOL'):
            assert phase == prefix + 'docking'
        elif command.startswith('_LOCK_TOOL'):
            assert phase == prefix + 'mounting'
        elif command.startswith('_WMP_XY_TRAVEL X=-13'):
            assert phase == phase_name
    objects['gcode'] = SimpleNamespace(run_script_from_command=run)
    material._prepare_service(2, context, phase_name=phase_name)
    assert observed == sorted(observed)


@pytest.mark.parametrize('fault', [-1, -2, -5])
def test_service_shared_pickup_failure_cannot_proceed_to_heating(service_material, fault):
    from types import SimpleNamespace
    material, objects, state = service_material
    material._material_status()._attachment = lambda now: {'state': 'empty', 'head': ''}
    calls = []
    def run(command):
        calls.append(command)
        if command.startswith('_LOCK_TOOL '):state['save_variables']['variables']['fail_flag'] = fault
    objects['gcode'] = SimpleNamespace(run_script_from_command=run)
    context = material._service_context(2, 1)
    with pytest.raises(ValueError, match='current fail_flag=%d' % fault):
        material._prepare_service(2, context)
    assert calls[-1] == '_LOCK_TOOL T=2 SERVICE=1'


def test_lane_projection_reuses_rows_until_presence_or_profile_changes(filament_check):
    material, sensor, _ = filament_check
    rows = material._lane_data(1.)
    assert material._lane_data(2.) is rows
    material.cmd_SET_FILAMENT(profile_command(material, PROFILE=json.dumps({'brand':'Updated','material':'PETG','color':'#ab1234'}).encode().hex()))
    updated = material._lane_data(3.)
    assert updated is not rows and updated['wmplus_tool_2']['brand'] == 'Updated'
    sensor.detected = False
    empty = material._lane_data(4.)
    assert empty is not updated and empty['wmplus_tool_2']['loaded'] is False


def test_runout_ownership_requires_all_guarded_sensors_and_standalone():
    from types import SimpleNamespace
    from wmp_filament_state import FilamentState
    owners = {}
    state = FilamentState.__new__(FilamentState)
    state.material = SimpleNamespace(printer=SimpleNamespace(
        lookup_object=lambda name, default=None: owners.get(name, default)))
    assert not state._runout_owned()
    names = {'filament%d' % n for n in range(4)} | {'path_%d' % n for n in range(4)}
    for missing in names:
        state._guarded_filament_notifications = names - {missing}
        assert not state._runout_owned()
    state._guarded_filament_notifications = names
    assert state._runout_owned()
    for owner in ('openace', 'AFC'):
        owners[owner] = object()
        assert not state._runout_owned()
        owners.clear()


@pytest.mark.parametrize('phase', ['homing', 'docking', 'mounting', 'positioning'])
def test_filament_cancel_between_service_stages_preserves_head_frame(service_material, phase):
    from types import SimpleNamespace
    from wmp_filament_types import FilamentCancelled
    from wmp_stop_points import check_operation_boundary
    material, objects, state = service_material
    objects['wm_material'] = material
    attachment = {'state':'attached','head':'h0'}
    material._material_status()._attachment = lambda now:dict(attachment)
    state['toolhead']['homed_axes'] = '' if phase=='homing' else 'xyz'
    state['save_variables']['variables'].update(current_extruder=0, fail_flag=0,
                                               t2_offset=[.3,.2,.1])
    heater={'temperature':25,'target':0,'can_extrude':False}
    objects['extruder2']=SimpleNamespace(get_status=lambda now:dict(heater))
    plan=material._filament_plan(2,'load',1)
    material.filament_operation=dict(id='cancel-test',session=material.session_id,head='h2',action='load',state='running')
    calls=[];frame=[0.,0.,0.]
    def cancel():material._handle_filament_cancel(cancellation_request(material))
    def run(script):
        calls.append(script)
        if script.startswith('G28 X Y'):
            if phase=='homing':
                cancel()
                check_operation_boundary(material.printer,'after Y homing')
                pytest.fail('homing proceeded to X after Cancel')
            state['toolhead']['homed_axes']='xyz'
        elif script.startswith('_UNLOCK_TOOL '):
            attachment.update(state='empty',head='')
            state['save_variables']['variables']['current_extruder']=99
            if phase=='docking':cancel()
        elif script.startswith('_LOCK_TOOL '):
            attachment.update(state='attached',head='h2')
            if phase=='mounting':cancel()
        elif script.startswith('_WMP_XY_TRAVEL X=-13'):
            if phase=='positioning':cancel()
        for line in script.splitlines():
            if line.startswith('SET_HEATER_TEMPERATURE '):heater['target']=float(line.split('TARGET=')[1])
            elif line.startswith('SET_GCODE_OFFSET '):
                args=dict(word.split('=') for word in line.split()[1:])
                assert args['MOVE']=='0'
                frame[:]=[float(args[key]) for key in ('X','Y','Z')]
            elif line.startswith('ACTIVATE_EXTRUDER '):state['toolhead']['extruder']='extruder2'
            elif line.startswith('SAVE_VARIABLE VARIABLE=current_extruder '):state['save_variables']['variables']['current_extruder']=int(line.split('VALUE=')[1])
    objects['gcode']=SimpleNamespace(run_script_from_command=run)
    with pytest.raises(FilamentCancelled):
        material._filament_service()._execute_filament(FakeCommand(),2,'load',plan)
    operation=material.filament_operation
    assert operation['state']=='failed' and operation['cancelled'] is True
    assert calls[-2:] == ['M400','SET_HEATER_TEMPERATURE HEATER=extruder2 TARGET=0']
    assert heater['target']==0 and material._filament_service()._boundary_scope is None
    if phase=='homing':
        assert calls[0]=='G28 X Y\nM400' and not any('_LOCK_TOOL' in line or '_UNLOCK_TOOL' in line for line in calls)
    elif phase=='docking':
        assert state['save_variables']['variables']['current_extruder']==99 and attachment['state']=='empty'
        assert not any('_LOCK_TOOL' in line for line in calls)
    else:
        assert state['save_variables']['variables']['current_extruder']==2 and attachment['head']=='h2'
        assert state['toolhead']['extruder']=='extruder2' and frame==[.3,.2,.1]
        if phase=='mounting':assert not any('_WMP_XY_TRAVEL' in line for line in calls)


def test_filament_stop_boundary_ignores_foreign_reactor_actor(service_material):
    from types import SimpleNamespace
    from wmp_filament_types import FilamentCancelled
    from wmp_stop_points import check_operation_boundary
    material,objects,state=service_material
    objects['wm_material']=material
    service=material._filament_service();actor=[object()]
    service._current_actor=lambda:actor[0]
    material.filament_operation=dict(id='cancel-test',session=material.session_id,head='h2',state='running',action='load')
    def execute(*args):
        material._handle_filament_cancel(cancellation_request(material))
        command=actor[0];actor[0]=object()
        check_operation_boundary(material.printer,'after Y homing')
        assert 'cancel_phase' not in material.filament_operation
        actor[0]=command
        check_operation_boundary(material.printer,'after Y homing')
        pytest.fail('command actor failed to stop')
    service._execute_filament_impl=execute
    with pytest.raises(FilamentCancelled,match='after Y homing'):
        service._execute_filament(FakeCommand(),2,'load',{})
    assert service._boundary_scope is None


def test_replaced_filament_owner_receives_no_old_cleanup_commands(service_material):
    from types import SimpleNamespace
    from wmp_stop_points import check_operation_boundary
    material,objects,state=service_material
    objects['wm_material']=material
    state['toolhead']['homed_axes']=''
    material.filament_operation=dict(id='cancel-test',session=material.session_id,head='h2',state='running',action='load')
    plan=material._filament_plan(2,'load',1)
    replacement=dict(id='replacement',session=material.session_id,head='h1',state='running',action='load')
    calls=[]
    def run(script):
        calls.append(script)
        material.filament_operation=dict(replacement)
        check_operation_boundary(material.printer,'after Y homing')
    objects['gcode']=SimpleNamespace(run_script_from_command=run)
    with pytest.raises(ValueError,match='owner changed'):
        material._filament_service()._execute_filament(FakeCommand(),2,'load',plan)
    assert calls==['G28 X Y\nM400']
    assert material.filament_operation==replacement


@pytest.mark.parametrize('stage,code',[('docking',-3),('mounting',-2)])
def test_filament_owned_tool_fault_keeps_cooldown_but_not_cancel_outcome(service_material,stage,code):
    from types import SimpleNamespace
    material,objects,state=service_material
    material._command_generation=0
    material._material_status()._attachment=lambda now:{'state':'attached','head':'h0'}
    heater={'temperature':25,'target':0,'can_extrude':False}
    objects['extruder2']=SimpleNamespace(get_status=lambda now:dict(heater))
    plan=material._filament_plan(2,'load',1)
    material.filament_operation=dict(id='cancel-test',session=material.session_id,head='h2',state='running',action='load')
    calls=[]
    def run(script):
        calls.append(script)
        if script.startswith('SET_HEATER_TEMPERATURE '):heater['target']=float(script.split('TARGET=')[1])
        selected=script.startswith('_UNLOCK_TOOL ') if stage=='docking' else script.startswith('_LOCK_TOOL ')
        if selected:
            material._handle_filament_cancel(cancellation_request(material))
            state['save_variables']['variables']['fail_flag']=code
            material._command_generation+=1
            error=ValueError('coupling fault remains primary')
            error.wmp_toolchange_fault=(code,'coupling_stroke')
            raise error
    objects['gcode']=SimpleNamespace(run_script_from_command=run)
    with pytest.raises(ValueError,match='coupling fault remains primary'):
        material._filament_service()._execute_filament(FakeCommand(),2,'load',plan)
    assert material.filament_operation['state']=='failed'
    assert material.filament_operation['cancelled'] is False and heater['target']==0
    assert state['save_variables']['variables']['fail_flag']==code
    assert calls[-2:]==['M400','SET_HEATER_TEMPERATURE HEATER=extruder2 TARGET=0']


def test_filament_replacement_during_cleanup_wait_keeps_new_target(service_material):
    from types import SimpleNamespace
    from wmp_filament_types import FilamentCancelled
    material,objects,state=service_material
    heater={'temperature':25,'target':0,'can_extrude':False}
    objects['extruder2']=SimpleNamespace(get_status=lambda now:dict(heater))
    plan=material._filament_plan(2,'load',1)
    material.filament_operation=dict(id='cancel-test',session=material.session_id,head='h2',state='running',action='load')
    replacement=dict(id='replacement',session=material.session_id,head='h1',state='running',action='load')
    calls=[]
    def prepare(head,context):
        heater['target']=250
        material._handle_filament_cancel(cancellation_request(material))
        material._filament_checkpoint('preparing')
    material._filament_planning()._prepare_service=prepare
    def run(script):
        calls.append(script)
        assert script=='M400'
        material.filament_operation=dict(replacement)
        heater['target']=222
    objects['gcode']=SimpleNamespace(run_script_from_command=run)
    with pytest.raises(FilamentCancelled):
        material._filament_service()._execute_filament(FakeCommand(),2,'load',plan)
    assert calls==['M400'] and heater['target']==222
    assert material.filament_operation==replacement


def test_nested_filament_stop_uses_stock_command_error_without_shutdown(service_material):
    import importlib.util
    from types import SimpleNamespace
    from wmp_stop_points import check_operation_boundary
    path=Path(__file__).resolve().parents[1]/'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/gcode.py'
    if not path.is_file():pytest.skip('retained stock dispatcher required')
    spec=importlib.util.spec_from_file_location('stock_filament_stop_dispatch',path)
    vendor=importlib.util.module_from_spec(spec);spec.loader.exec_module(vendor)
    material,objects,state=service_material
    objects['wm_material']=material
    material.printer.command_error=vendor.CommandError;material.printer.quick_stop_flag=False
    material.printer.invoke_shutdown=lambda message:pytest.fail('normal Cancel shut down: '+message)
    events=[];material.printer.send_event=lambda name:events.append(name)
    state['toolhead']['homed_axes']=''
    plan=material._filament_plan(2,'load',1)
    material.filament_operation=dict(id='cancel-test',session=material.session_id,head='h2',state='running',action='load')
    dispatcher=vendor.GCodeDispatch.__new__(vendor.GCodeDispatch)
    dispatcher.printer=material.printer
    dispatcher.respond_info=dispatcher.respond_raw=dispatcher._respond_error=lambda message:None
    dispatcher.gcode_handlers={'_WMP_FILAMENT_BOUNDARY':lambda command:check_operation_boundary(material.printer,'after Y homing')}
    dispatcher.cmd_default=lambda command:pytest.fail('unexpected nested command')
    heater={'target':0,'temperature':25,'can_extrude':False};calls=[]
    objects['extruder2']=SimpleNamespace(get_status=lambda now:dict(heater))
    def run(script):
        calls.append(script)
        if script.startswith('G28'):
            material._handle_filament_cancel(cancellation_request(material))
            dispatcher.run_script_from_command('_WMP_FILAMENT_BOUNDARY')
            pytest.fail('continued beyond nested stop')
        if script.startswith('SET_HEATER_TEMPERATURE '):heater['target']=float(script.split('TARGET=')[1])
    objects['gcode']=SimpleNamespace(run_script_from_command=run)
    with pytest.raises(vendor.CommandError,match='Filament operation cancelled; stopped after Y homing'):
        material._filament_service()._execute_filament(FakeCommand(),2,'load',plan)
    assert events==['gcode:command_error']
    assert material.filament_operation['cancelled'] is True and material.filament_operation['state']=='failed'
    assert calls[-2:]==['M400','SET_HEATER_TEMPERATURE HEATER=extruder2 TARGET=0']


# Standalone tool service uses the same macro/homing stop points as filament
# service, but owns neither a heater change nor an automatic cancellation park.
def toolhead_cancel_request(material, **updates):
    op = material.toolhead_operation
    params = {key: op[key] for key in ('id', 'session', 'head', 'action')}
    params.update(updates)
    return CancelWebRequest(**params)


def test_toolhead_cancel_before_callback_never_moves(toolhead_material):
    material, objects, state, scripts, callbacks = toolhead_material
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material))
    request = toolhead_cancel_request(material)
    material._handle_toolhead_cancel(request)
    assert request.response['state'] == 'requested' and scripts == []
    callbacks.pop()(1.)
    assert scripts == []
    assert material.toolhead_operation['state'] == 'refused'
    assert material.toolhead_operation['cancelled'] is True
    assert material.toolhead_operation['cancel_cleanup'] == 'not_started'


@pytest.mark.parametrize('defect', ['id', 'session', 'head', 'action', 'generation', 'owner', 'terminal'])
def test_toolhead_cancel_rejects_changed_binding(toolhead_material, defect):
    material, objects, state, scripts, callbacks = toolhead_material
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material))
    request = toolhead_cancel_request(material, **({defect: 'wrong'} if defect in ('id', 'session', 'head', 'action') else {}))
    if defect == 'generation': material._command_generation = getattr(material, '_command_generation', 0) + 1
    if defect == 'owner': objects['openace'] = object()
    if defect == 'terminal': material.toolhead_operation['state'] = 'complete'
    with pytest.raises(ValueError): material._handle_toolhead_cancel(request)
    assert not material.toolhead_operation.get('cancel_requested') and scripts == []


@pytest.mark.parametrize('action', ['take', 'dock'])
@pytest.mark.parametrize('phase', ['after X homing', 'after tool docking', 'before tool wiping'])
def test_toolhead_cancel_shared_boundary_holds_without_additional_motion(toolhead_material, action, phase):
    from wmp_stop_points import check_operation_boundary
    material, objects, state, scripts, callbacks = toolhead_material
    objects['wm_material'] = material
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material, ACTION=action))
    def run(line):
        scripts.append(line)
        if line.startswith(('_CHANGE_TOOL ', 'PARK_CURRENT_TOOL')):
            material._handle_toolhead_cancel(toolhead_cancel_request(material))
            check_operation_boundary(material.printer, phase)
            scripts.append('UNREACHABLE NEXT MOTION')
    objects['gcode'].run_script_from_command = run
    callbacks.pop()(1.)
    op = material.toolhead_operation
    assert op['state'] == 'unknown' and op['cancelled'] is True
    assert op['cancel_phase'] == phase and op['cancel_cleanup'] == 'held'
    assert scripts[-1] == 'M400' and 'UNREACHABLE NEXT MOTION' not in scripts
    assert not any(line.startswith(('G0', 'G1', 'M84', 'SET_HEATER_TEMPERATURE')) for line in scripts)
    with pytest.raises(ValueError): material._handle_toolhead_cancel(toolhead_cancel_request(material))


def test_toolhead_cancel_foreign_actor_does_not_unwind(toolhead_material, monkeypatch):
    material, objects, state, scripts, callbacks = toolhead_material
    service = material._toolheads()
    actor, foreign = object(), object()
    current = [actor]
    monkeypatch.setattr(service, '_current_actor', lambda: current[0])
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material))
    def run(line):
        scripts.append(line)
        if line.startswith('_CHANGE_TOOL '):
            material._handle_toolhead_cancel(toolhead_cancel_request(material))
            current[0] = foreign
            assert service.wait_owner() is None
            service.check_operation_boundary('foreign callback')
            current[0] = actor
            assert service.wait_owner() is service
            service.check_operation_boundary('after mount')
    objects['gcode'].run_script_from_command = run
    callbacks.pop()(1.)
    assert material.toolhead_operation['cancel_phase'] == 'after mount'


@pytest.mark.parametrize('change', ['replacement', 'session', 'generation', 'owner'])
def test_toolhead_cancel_loses_cleanup_authority_on_context_change(toolhead_material, change):
    material, objects, state, scripts, callbacks = toolhead_material
    service = material._toolheads()
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material))
    original = material.toolhead_operation
    def run(line):
        scripts.append(line)
        if line.startswith('_CHANGE_TOOL '):
            material._handle_toolhead_cancel(toolhead_cancel_request(material))
            if change == 'replacement': material.toolhead_operation = {'id': 'new', 'state': 'running'}
            if change == 'session': material.session_id = 'new'
            if change == 'generation': material._command_generation = getattr(material, '_command_generation', 0) + 1
            if change == 'owner': objects['AFC'] = object()
            service.check_operation_boundary('after mount')
    objects['gcode'].run_script_from_command = run
    callbacks.pop()(1.)
    assert 'M400' not in scripts
    assert not original.get('cancelled')
    if change == 'replacement': assert material.toolhead_operation == {'id': 'new', 'state': 'running'}
    else: assert material.toolhead_operation['state'] == 'unknown'


def test_toolhead_cancel_preserves_real_sensor_fault(toolhead_material):
    material, objects, state, scripts, callbacks = toolhead_material
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material))
    def run(line):
        scripts.append(line)
        if line.startswith('_CHANGE_TOOL '):
            material._handle_toolhead_cancel(toolhead_cancel_request(material))
            state['save_variables']['variables']['fail_flag'] = -2
            material._toolheads().check_operation_boundary('after mount')
    objects['gcode'].run_script_from_command = run
    callbacks.pop()(1.)
    assert material.toolhead_operation['state'] == 'unknown'
    assert not material.toolhead_operation.get('cancelled')
    assert 'fault' in material.toolhead_operation['message']
    assert 'M400' not in scripts


@pytest.mark.parametrize('change', ['generation', 'fault'])
def test_toolhead_cancel_rechecks_authority_after_draining(toolhead_material, change):
    material, objects, state, scripts, callbacks = toolhead_material
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material))
    generation = getattr(material, '_command_generation', 0)
    def run(line):
        scripts.append(line)
        if line.startswith('_CHANGE_TOOL '):
            material._handle_toolhead_cancel(toolhead_cancel_request(material))
            material._toolheads().check_operation_boundary('after mount')
        if line == 'M400':
            if change == 'generation': material._command_generation = generation + 1
            else: state['save_variables']['variables']['fail_flag'] = -2
    objects['gcode'].run_script_from_command = run
    callbacks.pop()(1.)
    assert scripts[-1] == 'M400'
    assert material.toolhead_operation['state'] == 'unknown'
    assert not material.toolhead_operation.get('cancelled')
    if change == 'generation': assert material._command_generation == generation + 1


def test_nested_toolhead_cancel_uses_stock_command_error_without_shutdown(toolhead_material):
    import importlib.util
    from wmp_stop_points import check_operation_boundary
    path = Path(__file__).resolve().parents[1] / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/gcode.py'
    if not path.is_file(): pytest.skip('retained stock dispatcher required')
    spec = importlib.util.spec_from_file_location('stock_toolhead_stop_dispatch', path)
    vendor = importlib.util.module_from_spec(spec);spec.loader.exec_module(vendor)
    material, objects, state, scripts, callbacks = toolhead_material
    objects['wm_material'] = material
    material.printer.command_error = vendor.CommandError
    material.printer.quick_stop_flag = False
    material.printer.invoke_shutdown = lambda message: pytest.fail('normal Cancel shut down: ' + message)
    events = [];material.printer.send_event = lambda name: events.append(name)
    dispatcher = vendor.GCodeDispatch.__new__(vendor.GCodeDispatch)
    dispatcher.printer = material.printer
    dispatcher.respond_info = dispatcher.respond_raw = dispatcher._respond_error = lambda message: None
    dispatcher.gcode_handlers = {'_BOUNDARY': lambda command: check_operation_boundary(material.printer, 'after tool docking')}
    dispatcher.cmd_default = lambda command: pytest.fail('unexpected command')
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material))
    def run(line):
        scripts.append(line)
        if line.startswith('_CHANGE_TOOL '):
            material._handle_toolhead_cancel(toolhead_cancel_request(material))
            dispatcher.run_script_from_command('_BOUNDARY')
            pytest.fail('continued after stop')
    objects['gcode'].run_script_from_command = run
    callbacks.pop()(1.)
    assert events == ['gcode:command_error']
    assert material.toolhead_operation['cancelled'] is True and scripts[-1] == 'M400'


@pytest.mark.parametrize('change', ['cancel', 'owner'])
def test_toolhead_cancel_breaks_owned_heater_wait_without_changing_target(toolhead_material, change):
    from types import SimpleNamespace
    material, objects, state, scripts, callbacks = toolhead_material
    polls = []
    heater = SimpleNamespace(name='extruder2', get_name=lambda: 'extruder2', check_busy=lambda now: True)
    objects['heaters'] = SimpleNamespace(_wait_for_temperature=lambda heater: pytest.fail('used unmanaged wait'), _get_temp=lambda now: 'T:100 /220')
    objects['gcode'].register_command = lambda *args, **kwargs: None
    objects['gcode'].respond_raw = lambda message: None
    objects['toolhead'].get_last_move_time = lambda: 0
    material.printer.get_start_args = lambda: {}
    material.printer.quick_stop_flag = False
    def pause(now):
        polls.append(now)
        if change == 'cancel': material._handle_toolhead_cancel(toolhead_cancel_request(material))
        else: objects['AFC'] = object()
        return now
    material.printer.pause = pause
    material._install_wait_wrappers()
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material))
    def run(line):
        scripts.append(line)
        if line.startswith('_CHANGE_TOOL '): objects['heaters']._wait_for_temperature(heater)
    objects['gcode'].run_script_from_command = run
    callbacks.pop()(1.)
    assert len(polls) == 1
    assert not any(line.startswith(('SET_HEATER_TEMPERATURE', 'M104', 'M109')) for line in scripts)
    assert material.toolhead_operation['state'] == 'unknown'
    if change == 'cancel':
        assert material.toolhead_operation['cancelled'] is True
        assert material.toolhead_operation['cancel_phase'] == 'during heater wait'
        assert scripts[-1] == 'M400'
    else:
        assert not material.toolhead_operation.get('cancelled')
        assert 'M400' not in scripts


def test_toolhead_cancel_rechecks_owner_after_cleanup_mutex_acquisition(toolhead_material):
    from contextlib import contextmanager
    material, objects, state, scripts, callbacks = toolhead_material
    acquisitions = []
    @contextmanager
    def mutex():
        acquisitions.append(True)
        if len(acquisitions) == 2:
            material._command_generation = getattr(material, '_command_generation', 0) + 1
        yield
    objects['gcode'].get_mutex = mutex
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material))
    def run(line):
        scripts.append(line)
        if line.startswith('_CHANGE_TOOL '):
            material._handle_toolhead_cancel(toolhead_cancel_request(material))
            material._toolheads().check_operation_boundary('after mount')
    objects['gcode'].run_script_from_command = run
    callbacks.pop()(1.)
    assert len(acquisitions) == 2 and 'M400' not in scripts
    assert not material.toolhead_operation.get('cancelled')
    assert material.toolhead_operation['state'] == 'unknown'


def test_recovery_nested_xy_stop_does_not_continue_into_the_next_axis(native_recovery_request):
    from wmp_stop_points import check_operation_boundary
    fixture, request, _ = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    objects['wm_material'] = material
    dispatch = objects['gcode'].run_script_from_command
    def run(script):
        if script == 'G28 X Y\nM400':
            material._handle_recovery_stop(CancelWebRequest(session=material.session_id, id=request['id']))
            check_operation_boundary(material.printer, 'after Y homing')
            calls.append('unexpected next X home')
        dispatch(script)
    objects['gcode'].run_script_from_command = run
    with pytest.raises(ValueError, match='Recovery preparation stopped'):
        material.cmd_RECOVERY_CONTINUE(FakeCommand(REQUEST=json.dumps(request).encode().hex()))
    assert 'unexpected next X home' not in calls and timers == [] and body == []
    record = material._recovery_attempt.record
    assert record['state'] == 'unknown' and record['cleanup']['state'] == 'complete'
    before = list(calls)
    material._restore_recovery_attempt()
    assert material._recovery_attempt.record['state'] == 'unknown'
    assert 'after Y homing' in material._recovery_attempt.record['error']
    assert calls == before and timers == [] and body == []



@pytest.mark.parametrize('stop_axis', [1, 0])
@pytest.mark.parametrize('handoff', [False, True])
def test_recovery_stop_between_native_axes_preserves_bottom_reference_and_motors(native_recovery_request, stop_axis, handoff):
    import importlib.util
    from types import SimpleNamespace as NS
    from wmp_xy_homing import XYHoming
    source = Path(__file__).resolve().parents[1]/'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/extras/homing.py'
    spec = importlib.util.spec_from_file_location('plr_cancel_native_home', source)
    native = importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
    fixture, request, _ = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    axes, waits = [], []
    rails = [NS(get_name=lambda: 'stepper_x', get_homing_info=lambda: NS(positive_dir=True)),
             NS(get_name=lambda: 'stepper_y', get_homing_info=lambda: NS(positive_dir=False))]
    def home(state):
        axes.append(state.get_axes())
        if state.get_axes() == [stop_axis]:
            if handoff: objects['wm_material'] = object()
            else: material._handle_recovery_stop(CancelWebRequest(session=material.session_id, id=request['id']))
    kin = NS(rails=rails, home=home, limits=[(0,300), (0,300)])
    objects['toolhead'].get_kinematics = lambda: kin
    objects['toolhead'].wait_moves = lambda: waits.append('wait')
    objects['stepper_enable'] = NS(motor_off=lambda: pytest.fail('normal Recovery Stop disabled motors'))
    printer = material.printer;printer.command_error = ValueError
    homing = native.PrinterHoming.__new__(native.PrinterHoming);homing.printer = printer
    objects['homing'] = homing
    objects['gcode'].register_command = lambda *args, **kwargs: None
    objects['gcode'].create_gcode_command = lambda name, text, params: NS(get=lambda key, default=None: params.get(key, default))
    xy = XYHoming(printer)
    dispatch = objects['gcode'].run_script_from_command
    def run(script):
        if script == 'G28 X Y\nM400': xy._home(NS(error=ValueError, respond_info=lambda message: None), native.Homing, native.HomingMove)
        else: dispatch(script)
    objects['gcode'].run_script_from_command = run
    error = 'XY homing interrupted' if handoff else 'Recovery preparation stopped after ' + ('Y' if stop_axis == 1 else 'X')
    with pytest.raises(ValueError, match=error):
        material.cmd_RECOVERY_CONTINUE(FakeCommand(REQUEST=json.dumps(request).encode().hex()))
    assert axes == ([[1]] if stop_axis == 1 else [[1], [0]])
    assert len(waits) == len(axes) and kin.limits[1] == (1., -1.)
    assert states['toolhead']['position'][2] == 300. and timers == [] and body == []
    receipt = material._recovery_attempt.record
    if handoff:
        assert receipt['state'] == 'running' and 'cleanup' not in receipt
    else:
        assert receipt['state'] == 'unknown' and receipt['cleanup']['state'] == 'complete'
    assert all(s['state'] == 'pending' for s in receipt['stages'] if s['name'] in ('select_head', 'heating', 'prime', 'start_file'))


def test_recovery_boundary_stop_ignores_foreign_callback_but_accepts_its_intent(native_recovery_request, monkeypatch):
    from wmp_stop_points import check_operation_boundary
    fixture, request, _ = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    service = material._recovery_lifecycle()
    actor = [object()];monkeypatch.setattr(service, '_current_actor', lambda: actor[0])
    dispatch = objects['gcode'].run_script_from_command
    def run(script):
        if script == 'G28 X Y\nM400':
            owner = actor[0];actor[0] = object()
            material._handle_recovery_stop(CancelWebRequest(session=material.session_id, id=request['id']))
            check_operation_boundary(material.printer, 'foreign callback')
            assert service._execution_scope['cancel_phase'] == ''
            actor[0] = owner
            check_operation_boundary(material.printer, 'after Y homing')
            pytest.fail('owned homing did not observe Stop')
        dispatch(script)
    objects['gcode'].run_script_from_command = run
    with pytest.raises(ValueError, match='Recovery preparation stopped'):
        material.cmd_RECOVERY_CONTINUE(FakeCommand(REQUEST=json.dumps(request).encode().hex()))
    assert 'after Y homing' in material._recovery_attempt.record['error']
    assert timers == [] and body == []


@pytest.mark.parametrize('change', ['generation', 'session', 'material', 'runner', 'record', 'manager', 'review', 'worker'])
def test_recovery_lost_boundary_owner_never_cleans_or_rewrites_replacement(native_recovery_request, change):
    import copy
    from wm_material import RecoveryAttempt
    from types import SimpleNamespace as NS
    from wmp_stop_points import check_operation_boundary
    fixture, request, _ = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    service = material._recovery_lifecycle()
    dispatch = objects['gcode'].run_script_from_command
    changed, replacement = [], []
    def run(script):
        if script == 'G28 X Y\nM400':
            material._handle_recovery_stop(CancelWebRequest(session=material.session_id, id=request['id']))
            old = material._recovery_attempt
            if change == 'generation': material._command_generation = getattr(material, '_command_generation', 0) + 1
            elif change == 'session': material.session_id = 'new-session'
            elif change == 'material': objects['wm_material'] = object()
            elif change == 'runner':
                new = RecoveryAttempt(lambda value: pytest.fail('old owner wrote new runner'))
                new.record = dict(version=1, request=dict(old.record['request'], id='new'), state='running', stages=[], error='new')
                material._recovery_attempt = new;replacement.append((new, copy.deepcopy(new.record)))
            elif change == 'record':
                new = copy.deepcopy(old.record);new['request']['id'] = 'replacement'
                old.record = new;replacement.append((old, copy.deepcopy(new)))
            elif change == 'manager': objects['AFC'] = object()
            elif change == 'review': material._plr_review_component = NS(_recovery_pending_worker=None)
            else:
                pending = {'armed': False, 'timer': object(), 'sd': objects['virtual_sdcard'], 'session': material.session_id,
                           'request': dict(old.record['request'], id='new-worker')}
                material._recovery_pending_worker = pending;changed.append(pending)
            boundary = len(calls)
            try:
                if change == 'material': service.check_operation_boundary('after Y homing')
                else: check_operation_boundary(material.printer, 'after Y homing')
            finally: changed.append(boundary)
            pytest.fail('recovery continued after owner change')
        dispatch(script)
    objects['gcode'].run_script_from_command = run
    with pytest.raises(ValueError, match='ownership changed'):
        material.cmd_RECOVERY_CONTINUE(FakeCommand(REQUEST=json.dumps(request).encode().hex()))
    assert len(calls) == changed[-1] and timers == [] and body == []
    if replacement:
        runner, before = replacement[0]
        assert runner.record == before
    if change == 'worker': assert material._recovery_pending_worker is changed[0]


def test_recovery_fault_takes_precedence_over_stop_at_nested_boundary(native_recovery_request):
    from wmp_stop_points import check_operation_boundary
    fixture, request, _ = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    dispatch = objects['gcode'].run_script_from_command
    def run(script):
        if script == 'G28 X Y\nM400':
            material._handle_recovery_stop(CancelWebRequest(session=material.session_id, id=request['id']))
            objects['save_variables'].values['variables']['fail_flag'] = -3
            check_operation_boundary(material.printer, 'after Y homing')
        dispatch(script)
    objects['gcode'].run_script_from_command = run
    with pytest.raises(ValueError, match='printer fault'):
        material.cmd_RECOVERY_CONTINUE(FakeCommand(REQUEST=json.dumps(request).encode().hex()))
    assert 'Recovery preparation stopped' not in material._recovery_attempt.record['error']
    assert timers == [] and body == []


def test_old_recovery_cleanup_cannot_disarm_replacement_worker(native_recovery_request):
    fixture, request, _ = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    reactor = material.printer.get_reactor()
    original = reactor.unregister_timer
    replacement = []
    def replace(timer):
        original(timer)
        pending = {'armed': True, 'timer': object(), 'sd': objects['virtual_sdcard'], 'session': material.session_id,
                   'request': dict(material._recovery_attempt.record['request'], id='replacement')}
        replacement.append(pending)
        material._recovery_pending_worker = pending
        objects['virtual_sdcard'].work_timer = pending['timer']
    reactor.unregister_timer = replace
    def activation(request): raise RuntimeError('activation failed')
    material._recovery_worker()._recovery_activate_worker = activation
    with pytest.raises(ValueError, match='activation failed'):
        material.cmd_RECOVERY_CONTINUE(FakeCommand(REQUEST=json.dumps(request).encode().hex()))
    assert len(replacement) == 1 and material._recovery_pending_worker is replacement[0]
    assert replacement[0]['armed'] is True and objects['virtual_sdcard'].work_timer is replacement[0]['timer']
    assert not any('TARGET=0' in script for script in calls)
    assert states['extruder2']['target'] == 220.5 and states['heater_bed']['target'] == 55.
    assert body == []


def test_recovery_submission_handoff_is_not_rewritten_by_old_command(native_recovery_request):
    from wmp_stop_points import check_operation_boundary
    fixture, request, _ = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    dispatch = objects['gcode'].run_script_from_command
    replacement = {'request': {'id': 'new-submission'}, 'state': 'new', 'message': 'new result'}
    def run(script):
        if script == 'G28 X Y\nM400':
            material._recovery_submission = replacement
            material._recovery_stop_request = {'id': 'new-stop'}
            check_operation_boundary(material.printer, 'after Y homing')
        dispatch(script)
    objects['gcode'].run_script_from_command = run
    with pytest.raises(ValueError, match='ownership changed'):
        material.cmd_RECOVERY_CONTINUE(FakeCommand(REQUEST=json.dumps(request).encode().hex()))
    assert material._recovery_submission is replacement and replacement['message'] == 'new result'
    assert material._recovery_stop_request == {'id': 'new-stop'} and material._recovery_command_active is True
    assert timers == [] and body == []


def test_reviewed_recovery_ticket_can_stop_before_continue_is_dispatched(native_recovery_request):
    fixture, selection, _ = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    mutex[0] = False
    web = recovery_review_web_request(selection);web.params['ticket_protocol'] = '1'
    material._handle_recovery_review(web)
    issued, ticket = web.response['request'], web.response['ticket']
    prior = material._recovery_attempt.record
    journal = Path(material._recovery_attempt_path())
    before = journal.read_bytes() if journal.exists() else None
    stop = CancelWebRequest(session=material.session_id, id=issued['id'], ticket=ticket['token'])
    material._handle_recovery_stop(stop)
    assert stop.response['state'] == 'requested' and calls == [] and timers == []
    mutex[0] = True
    command = ticket_command(issued, ticket)
    material.cmd_RECOVERY_CONTINUE(command)
    assert json.loads(command.message)['before_execution'] is True
    assert material._recovery_submission['state'] == 'cancelled'
    assert material._recovery_attempt.record is prior
    assert (journal.read_bytes() if journal.exists() else None) == before
    assert calls == [] and timers == [] and body == []
    with pytest.raises(ValueError, match='consumed|superseded'):
        material.cmd_RECOVERY_CONTINUE(ticket_command(issued, ticket))
    assert calls == []


@pytest.mark.parametrize('changed', ['token', 'missing_token', 'session', 'id', 'superseded'])
def test_early_recovery_stop_rejects_other_ticket(native_recovery_request, changed):
    fixture, selection, _ = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    mutex[0] = False
    web = recovery_review_web_request(selection)
    web.params['ticket_protocol'] = '1'
    material._handle_recovery_review(web)
    request, ticket = web.response['request'], web.response['ticket']
    args = dict(session=material.session_id, id=request['id'], ticket=ticket['token'])
    if changed == 'token': args['ticket'] = '0' * 64
    if changed == 'missing_token': args.pop('ticket')
    if changed == 'session': args['session'] = 'other-session'
    if changed == 'id': args['id'] = 'other-request'
    if changed == 'superseded':
        newer = recovery_review_web_request(dict(selection, id='new-selection'))
        newer.params['ticket_protocol'] = '1'
        material._handle_recovery_review(newer)
    with pytest.raises(ValueError):
        material._handle_recovery_stop(CancelWebRequest(**args))
    assert not any(slot.get('cancel_requested') for slot in
                   material._recovery_tickets['continue']['slots'].values())
    assert calls == [] and timers == [] and body == []


def test_recovery_stop_during_consumed_ticket_review_prevents_admission(native_recovery_request):
    fixture, selection, _ = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    mutex[0] = False
    web = recovery_review_web_request(selection)
    web.params['ticket_protocol'] = '1'
    material._handle_recovery_review(web)
    request, ticket = web.response['request'], web.response['ticket']
    controller = material._recovery_review_service()
    original = controller._recovery_request_review
    prior = material._recovery_attempt.record
    def reviewing(encoded):
        result = original(encoded)
        for _ in range(2):
            material._handle_recovery_stop(CancelWebRequest(
                session=material.session_id, id=request['id'], ticket=ticket['token']))
        return result
    controller._recovery_request_review = reviewing
    def unexpected_admission(*args):
        pytest.fail('Cancelled review must not begin physical admission')
    material._begin_explicit_physical_action = unexpected_admission
    mutex[0] = True
    command = ticket_command(request, ticket)
    material.cmd_RECOVERY_CONTINUE(command)
    assert json.loads(command.message)['before_execution'] is True
    assert material._recovery_submission['state'] == 'cancelled'
    assert material._recovery_attempt.record is prior
    assert calls == [] and timers == [] and body == []
    with pytest.raises(ValueError):
        material._handle_recovery_stop(CancelWebRequest(
            session=material.session_id, id=request['id'], ticket=ticket['token']))


def test_repeated_early_stop_retains_only_current_ticket_and_allows_new_selection(native_recovery_request):
    fixture, selection, _ = native_recovery_request
    material, objects, states, calls, review, _, timers, body, mutex = fixture
    mutex[0] = False
    def issue(selected):
        web = recovery_review_web_request(selected)
        web.params['ticket_protocol'] = '1'
        material._handle_recovery_review(web)
        return web.response['request'], web.response['ticket']
    request, ticket = issue(selection)
    for _ in range(2):
        material._handle_recovery_stop(CancelWebRequest(
            session=material.session_id, id=request['id'], ticket=ticket['token']))
    assert issue(selection) == (request, ticket)
    assert material._recovery_tickets['continue']['slots']['continue']['cancel_requested'] is True
    newer, newer_ticket = issue(dict(selection, id='explicit-retry'))
    slots = material._recovery_tickets['continue']['slots']
    assert len(slots) == 1 and not slots['continue'].get('cancel_requested')
    with pytest.raises(ValueError):
        material._handle_recovery_stop(CancelWebRequest(
            session=material.session_id, id=request['id'], ticket=ticket['token']))
    consumed = []
    material._recovery_review_service()._consume_recovery_request = lambda encoded, cancelled: consumed.append(cancelled()) or {}
    mutex[0] = True
    material.cmd_RECOVERY_CONTINUE(ticket_command(newer, newer_ticket))
    assert consumed == [False]
    assert material._recovery_tickets['continue']['slots'] == {}
    assert calls == [] and timers == [] and body == []


def _confirmed_released_transient(objects, variables, events):
    from types import SimpleNamespace as NS
    variables.update(changing_tool=1, fail_flag=0, thr_number=4)
    status = {'custom_hall': {'Raw': 5000},
              'filament_switch_sensor sensor_b': {'filament_detected': False},
              **{'filament_switch_sensor docked%d' % n: {'filament_detected': True} for n in range(4)}}
    for name, value in status.items():
        objects[name] = NS(get_status=lambda now, value=value: value)
    objects['toolhead'].wait_moves = lambda: events.append('drain-toolchange')


def test_toolhead_cancel_clears_transient_after_verified_release(toolhead_material):
    from wmp_stop_points import check_operation_boundary
    material, objects, state, scripts, callbacks = toolhead_material
    objects['wm_material'] = material
    material.cmd_TOOLHEAD_ACTION(toolhead_command(material, ACTION='dock'))
    variables = state['save_variables']['variables']
    def run(line):
        scripts.append(line)
        if line == 'PARK_CURRENT_TOOL':
            _confirmed_released_transient(objects, variables, scripts)
            variables['current_extruder'] = 99
            material._handle_toolhead_cancel(toolhead_cancel_request(material))
            check_operation_boundary(material.printer, 'after verified tool docking')
        elif line == 'SAVE_VARIABLE VARIABLE=changing_tool VALUE=0':
            variables['changing_tool'] = 0
    objects['gcode'].run_script_from_command = run
    callbacks.pop()(1.)
    assert material.toolhead_operation['cancelled']
    assert material.toolhead_operation['toolchange_cleanup'] == 'cleared'
    assert variables['changing_tool'] == 0
    assert scripts[-3:] == ['M400', 'drain-toolchange', 'SAVE_VARIABLE VARIABLE=changing_tool VALUE=0']


def test_print_cancel_clears_transient_before_other_housekeeping(managed_cancel_cleanup):
    fixture, binding, cleanup, _ = managed_cancel_cleanup
    material, objects, states, *_ = fixture
    variables = objects['save_variables'].values['variables']
    _confirmed_released_transient(objects, variables, cleanup)
    run = objects['gcode'].run_script_from_command
    def record(command):
        run(command)
        if command == 'SAVE_VARIABLE VARIABLE=changing_tool VALUE=0': variables['changing_tool'] = 0
    objects['gcode'].run_script_from_command = record
    result = material._cancellation()._cancel_print_cleanup(binding)
    assert result['state'] == 'complete' and variables['changing_tool'] == 0
    assert cleanup.index('drain-toolchange') < cleanup.index('SAVE_VARIABLE VARIABLE=changing_tool VALUE=0') < cleanup.index('TURN_OFF_HEATERS')


def test_filament_cancel_clears_transient_without_feeding(service_material):
    from types import SimpleNamespace as NS
    from wmp_filament_types import FilamentCancelled
    from wmp_stop_points import check_operation_boundary
    material, objects, state = service_material
    objects['wm_material'] = material
    material.printer.is_shutdown = lambda: False
    variables, calls = state['save_variables']['variables'], []
    variables.update(current_extruder=2, fail_flag=0)
    heater = {'temperature': 25, 'target': 0, 'can_extrude': False}
    objects['extruder2'] = NS(get_status=lambda now: dict(heater))
    plan = material._filament_plan(2, 'load', 1)
    material.filament_operation = dict(id='transient', session=material.session_id, head='h2', action='load', state='running')
    def prepare(head, context):
        _confirmed_released_transient(objects, variables, calls)
        variables['current_extruder'] = 99
        material._handle_filament_cancel(cancellation_request(material, id='transient'))
        check_operation_boundary(material.printer, 'after verified tool docking')
    material._filament_planning()._prepare_service = prepare
    def run(command):
        calls.append(command)
        if command == 'SAVE_VARIABLE VARIABLE=changing_tool VALUE=0': variables['changing_tool'] = 0
        elif command.startswith('SET_HEATER_TEMPERATURE'): heater['target'] = float(command.split('TARGET=')[1])
    objects['gcode'] = NS(run_script_from_command=run)
    with pytest.raises(FilamentCancelled): material._filament_service()._execute_filament(FakeCommand(), 2, 'load', plan)
    assert material.filament_operation['state'] == 'failed', material.filament_operation
    assert material.filament_operation['toolchange_cleanup'] == 'cleared'
    assert variables['changing_tool'] == 0 and heater['target'] == 0
    assert all(not command.startswith(('G1', 'G0')) for command in calls)


@pytest.mark.parametrize('appearance',['standard','translucent','gradient','co-extrusion'])
def test_filament_appearance_persists_as_cosmetic_metadata(material, appearance):
    identity={'brand':'Generic','material':'PETG','color':'#ab1234','appearance':appearance,'nozzle_temp':250}
    material.cmd_SET_FILAMENT(profile_command(material,PROFILE=json.dumps(identity).encode().hex()))
    assert material._profiles()[0]['h2']==identity
    from wmp_material_settings import MaterialSettings
    without=dict(identity);without.pop('appearance')
    assert MaterialSettings._filament_recipe(identity)==MaterialSettings._filament_recipe(without)
    # Label-only appearance edits are not a physical spool/recipe change.
    current={'state':'loaded','source':'external:h2','identity':identity}
    previous=dict(current,identity=without)
    assert MaterialSettings._loaded_source_matches(current,previous)


@pytest.mark.parametrize('appearance',['rainbow','',None,True,{},['standard']])
def test_filament_appearance_rejects_invalid_values_without_overwriting(material, appearance):
    material.cmd_SET_FILAMENT(profile_command(material))
    before=material._profiles()
    identity=dict(before[0]['h2'],appearance=appearance)
    with pytest.raises(ValueError,match='appearance'):
        material.cmd_SET_FILAMENT(profile_command(material,PROFILE=json.dumps(identity).encode().hex()))
    assert material._profiles()==before


@pytest.mark.parametrize('change', [None, 'same-file-reset', 'pending-start', 'recovery', 'active-sd'])
def test_clear_cancelled_checks_current_generation_and_is_one_shot(change):
    from contextlib import nullcontext
    from types import SimpleNamespace as NS
    from wmp_print_cancel import PrintCancellation

    stats = NS(filename='same.gcode', state='cancelled')
    sd = NS(current_file=None, is_active=lambda: change == 'active-sd', is_cmd_from_sd=lambda: False)
    pause = NS(get_status=lambda _: {'is_paused': False})
    calls = []
    def run(command):
        calls.append(command)
        cancellation.note_sd_reset()
        stats.filename, stats.state = '', 'standby'
    ports = dict(gcode=NS(get_mutex=nullcontext, run_script_from_command=run),
                 print_stats=stats, virtual_sdcard=sd, pause_resume=pause,
                 webhooks=NS(get_status=lambda _: {'state': 'ready'}))
    printer = NS(lookup_object=lambda name, default=None: ports.get(name, default),
                 is_shutdown=lambda: False,
                 get_reactor=lambda: NS(monotonic=lambda: 1.))
    material = NS(printer=printer, session_id='helper',
                  print_submission={'state': 'pending'} if change == 'pending-start' else {},
                  _recovery_lifecycle=lambda: NS(_recovery_attempt_unresolved=lambda: change == 'recovery'))
    cancellation = PrintCancellation(material)
    cancellation._print_cancel = dict(session='helper', id='cancelled', file='same.gcode', state='complete')
    cancellation._clearable_cancel = ('cancelled', 0)
    if change == 'same-file-reset':
        cancellation.note_sd_reset()
    request = CancelWebRequest(session='helper', id='cancelled')
    if change:
        with pytest.raises(ValueError):
            cancellation._handle_clear_cancelled(request)
        assert calls == []
    else:
        cancellation._handle_clear_cancelled(request)
        assert request.response == dict(state='complete', id='cancelled')
        with pytest.raises(ValueError, match='job changed'):
            cancellation._handle_clear_cancelled(request)
        assert calls == ['SDCARD_RESET_FILE']
