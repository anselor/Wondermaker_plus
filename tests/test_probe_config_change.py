"""Probe offset ownership using the retained configfile.set implementation."""
import configparser
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
import pytest

ROOT = Path(__file__).resolve().parents[1]

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def config():
    path = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/configfile.py'
    if not path.exists(): pytest.skip('retained configfile required')
    vendor = load('retained_configfile', path)
    cfg = vendor.PrinterConfig.__new__(vendor.PrinterConfig)
    cfg.autosave = NS(fileconfig=configparser.RawConfigParser())
    cfg.status_save_pending = {}
    cfg.save_config_pending = False
    return cfg


@pytest.fixture
def change():
    return load('probe_pending_owner', ROOT / 'klipper_extras/wmp_recovery.py').ProbeConfigChange


@pytest.mark.parametrize('existing', [False, True])
def test_discard_restores_old_offset_and_preserves_other_new_changes(config, change, existing):
    if existing:
        config.autosave.fileconfig.add_section('probe')
        config.autosave.fileconfig.set('probe','z_offset','1.250')
    owned = change(config,'probe')
    config.set('probe','z_offset','1.500'); owned.capture()
    config.set('extruder','pid_kp','25')
    config.set('probe','speed','5')
    with pytest.raises(ValueError, match='Other pending'): owned.admit_save()
    owned.discard()
    assert config.status_save_pending == {'extruder':{'pid_kp':'25'},'probe':{'speed':'5'}}
    assert config.autosave.fileconfig.has_option('probe','z_offset') is existing
    if existing: assert config.autosave.fileconfig.get('probe','z_offset') == '1.250'
    assert config.save_config_pending


def test_only_owned_pending_offset_can_save_and_can_be_discarded(config, change):
    owned = change(config,'probe')
    config.set('probe','z_offset','1.500'); owned.capture(); owned.admit_save()
    owned.discard()
    assert config.status_save_pending == {} and not config.save_config_pending
    assert not config.autosave.fileconfig.has_section('probe')
    with pytest.raises(ValueError): owned.admit_save()


def test_preexisting_offset_change_is_restored_not_saved(config, change):
    config.set('probe','z_offset','1.100')
    owned = change(config,'probe')
    config.set('probe','z_offset','1.500'); owned.capture()
    with pytest.raises(ValueError, match='Other pending'): owned.admit_save()
    owned.discard()
    assert config.status_save_pending == {'probe':{'z_offset':'1.100'}}
    assert config.autosave.fileconfig.get('probe','z_offset') == '1.100'


def test_concurrent_offset_edit_is_not_overwritten(config, change):
    owned = change(config,'probe')
    config.set('probe','z_offset','1.500'); owned.capture()
    config.set('probe','z_offset','2.000')
    for action in (owned.discard, owned.admit_save):
        with pytest.raises(ValueError, match='changed'): action()
    assert config.autosave.fileconfig.get('probe','z_offset') == '2.000'
    assert config.status_save_pending == {'probe':{'z_offset':'2.000'}}


def conflict(config, change):
    owned = change(config, 'probe')
    config.set('probe', 'z_offset', '1.500'); owned.capture()
    config.set('probe', 'z_offset', '2.000')
    return owned


@pytest.mark.parametrize('mutation', ['pending', 'parser', 'defaults', 'flag'])
def test_keep_review_binds_all_pending_configuration(config, change, mutation):
    owned = conflict(config, change)
    review = owned.conflict_review()['review']
    if mutation == 'pending': config.status_save_pending['extruder'] = {'pid_kp':'25'}
    elif mutation == 'parser': config.autosave.fileconfig.set('probe', 'speed', '5')
    elif mutation == 'defaults': config.autosave.fileconfig['DEFAULT']['speed'] = '5'
    else: config.save_config_pending = False
    with pytest.raises(ValueError, match='review it again'): owned.keep(review)
    assert not owned.discarded
    assert config.autosave.fileconfig.get('probe', 'z_offset') == '2.000'


@pytest.mark.parametrize('bad', ['nan', 'inf', 'unknown', None, 2.0, 'missing', 'mismatch'])
def test_inconsistent_conflict_does_not_offer_keep(config, change, bad):
    owned = conflict(config, change)
    if bad == 'missing': config.autosave.fileconfig.remove_section('probe')
    elif bad == 'mismatch': config.autosave.fileconfig.set('probe', 'z_offset', '3.000')
    else: config.status_save_pending['probe']['z_offset'] = bad
    assert owned.conflict_review() is None
    with pytest.raises(ValueError): owned.keep('0' * 64)
    assert not owned.discarded


def test_keep_retires_ownership_without_mutating_pending_config(config, change):
    import copy
    owned = conflict(config, change)
    before = copy.deepcopy(config.status_save_pending)
    review = owned.conflict_review()
    assert review['accepted_offset'] == '1.500' and review['current_offset'] == '2.000'
    with pytest.raises(ValueError): owned.admit_discard()
    assert config.status_save_pending == before
    owned.keep(review['review'])
    assert config.status_save_pending == before and config.save_config_pending
    assert config.autosave.fileconfig.get('probe', 'z_offset') == '2.000'
    assert owned.conflict_review() is None
    for action in (owned.discard, owned.admit_save, lambda: owned.keep(review['review'])):
        with pytest.raises(ValueError): action()


def test_retained_save_requests_restart_only_after_persisting_offset(config, tmp_path):
    path = tmp_path / 'printer.cfg'
    original = '[printer]\nkinematics = cartesian\n'
    path.write_text(original)
    restarts = []
    def restart(kind):
        regular, autosave = config._find_autosave_data(path.read_text())
        saved = config._build_config_wrapper(autosave, str(path)).fileconfig
        assert saved.get('probe', 'z_offset') == '1.500'
        assert 'kinematics = cartesian' in regular
        assert any(p.read_text() == original for p in tmp_path.glob('printer-*.cfg'))
        restarts.append(kind)
    gcode = NS(error=ValueError, request_restart=restart)
    config.printer = NS(get_start_args=lambda: {'config_file':str(path)},
                        lookup_object=lambda name: gcode)
    config.set('probe', 'z_offset', '1.500')
    config.cmd_SAVE_CONFIG(NS())
    assert restarts == ['firmware_restart']


@pytest.mark.parametrize('matching', [True, False])
@pytest.mark.parametrize('repaired', [False, True])
def test_ready_restores_save_review_without_replay(config, tmp_path, matching, monkeypatch, repaired):
    module = load('probe_restore_owner', ROOT / 'klipper_extras/wmp_recovery.py')
    path = tmp_path / 'printer.cfg'
    path.write_text('[printer]\nkinematics = cartesian\n')
    handlers, commands = {}, []
    gcode = NS(error=ValueError, request_restart=lambda kind: None,
               register_command=lambda *a, **k: None,
               run_script_from_command=commands.append)
    printer = NS(get_start_args=lambda: {'config_file':str(path)},
                 lookup_object=lambda name, default=None: {'configfile':config,'gcode':gcode,
                     'wm_material':NS(_restart_requested=lambda *a, **k: None)}.get(name, default),
                 register_event_handler=lambda event, callback: handlers.setdefault(event, callback))
    config.printer = printer
    config.set('probe', 'z_offset', '1.500')
    config.cmd_SAVE_CONFIG(NS())
    config.status_save_pending = {}
    config.status_raw_config = {'probe': {'z_offset': '1.500' if matching else '2.000'}}
    record = dict(version=1, session='a'*32, request='b'*32, config_path=str(path),
                  section='probe', offset='1.500', autosave={'probe':{'z_offset':'1.500'}}, before_sha256='c'*64)
    store = module.ProbeSaveRecord(str(tmp_path / 'wmp_probe_save.json')); store.create(record)
    calibration = NS(printer=printer, gcode=gcode, session='d'*32, active=False, failure='', _check=lambda _: None)
    editor = module.ProbeEditorCommands(calibration)
    original_evidence = Path(store.path).read_bytes()
    if repaired: Path(store.path).write_bytes(b'corrupt evidence')
    handlers['klippy:ready']()
    if repaired:
        assert not editor.busy() and editor.save_review is None
        assert Path(store.path).read_bytes() == b'corrupt evidence'
        Path(store.path).write_bytes(original_evidence)
        assert editor.save_review is None  # Repair alone does not acknowledge or refresh.
    assert editor.state == 'save_review' and not editor.busy()
    if not repaired: assert editor.save_review['configuration_matches'] is matching
    assert editor.get_status()['save_review_required']
    assert commands == [] and store.read() == record
    def command(action, token='', session='d'*32, sequence=None):
        fields = dict(SESSION=session, REQUEST=editor.request, ACTION=action, REVIEW=token,
                      SEQ=str(editor.save_review_sequence + 1 if sequence is None else sequence))
        return NS(get=lambda key, default: fields.get(key, default), error=ValueError)
    # Startup observation alone cannot acknowledge anything.
    with pytest.raises(ValueError): editor.cmd_save_review(command('ACK', editor.save_review['token'] if editor.save_review else 'e'*64))
    assert editor.get_status()['save_review_result']['state'] == 'refused'
    review_command = command('REVIEW')
    editor.cmd_save_review(review_command)
    review_receipt = editor.get_status()['save_review_result']
    assert review_receipt == dict(session='d'*32, request=editor.request, sequence=2,
                                 action='REVIEW', state='complete', error='')
    editor.cmd_save_review(review_command)
    assert editor.get_status()['save_review_result'] == review_receipt
    with pytest.raises(ValueError):
        editor.cmd_save_review(command('ACK', sequence=2))
    assert editor.get_status()['save_review_result'] == review_receipt
    token = editor.get_status()['save_review']['token']
    if repaired:
        replacement = dict(record, request='f'*32)
        other = module.ProbeSaveRecord(str(tmp_path / 'other-evidence.json'))
        other.create(replacement)
        Path(store.path).write_bytes(Path(other.path).read_bytes())
        with pytest.raises(ValueError, match='evidence changed'):
            editor.cmd_save_review(command('REVIEW'))
        assert not editor.busy() and editor.restored_save_request == record['request']
        Path(store.path).write_bytes(original_evidence)
    with pytest.raises(ValueError): editor.cmd_save_review(command('ACK', token, session='old'))
    config.status_save_pending = {'probe':{'z_offset':'2.000'}}
    with pytest.raises(ValueError): editor.cmd_save_review(command('ACK', token))
    assert not editor.busy() and not store.acknowledged(record)
    config.status_save_pending = {}
    if matching:
        original_acknowledge = module.ProbeSaveRecord.acknowledge
        attempts = []
        def uncertain_acknowledge(self, *args):
            attempts.append(args)
            original_acknowledge(self, *args)
            raise OSError('lost acknowledgement after durable write')
        monkeypatch.setattr(module.ProbeSaveRecord, 'acknowledge', uncertain_acknowledge)
        uncertain = command('ACK', token)
        with pytest.raises(OSError): editor.cmd_save_review(uncertain)
        unknown = editor.get_status()['save_review_result']
        assert unknown['state'] == 'unknown' and not editor.busy()
        editor.cmd_save_review(uncertain)
        assert len(attempts) == 1 and editor.get_status()['save_review_result'] == unknown
        monkeypatch.setattr(module.ProbeSaveRecord, 'acknowledge', original_acknowledge)
        # A fresh explicit action may reconcile the durable marker; no automatic retry.
        editor.cmd_save_review(command('REVIEW'))
        ack = command('ACK', token)
        editor.cmd_save_review(ack)
        receipt = editor.get_status()['save_review_result']
        editor.cmd_save_review(ack)
        assert editor.get_status()['save_review_result'] == receipt
        assert receipt['state'] == 'complete'
        assert editor.state == 'save_acknowledged' and not editor.busy()
        assert store.acknowledged(record) and store.read() == record
        restarted = module.ProbeEditorCommands(calibration)
        restarted._restore_save_evidence()
        assert restarted.state == 'save_acknowledged' and not restarted.busy()
    else:
        with pytest.raises(ValueError): editor.cmd_save_review(command('ACK', token))
        assert not editor.busy() and not store.acknowledged(record)
        # Loaded and saved current offset must agree before offering retention.
        editor.cmd_save_review(command('REVIEW'))
        assert not editor.get_status()['save_review']['retainable']
        with pytest.raises(ValueError):
            editor.cmd_save_review(command('RETAIN', editor.save_review['token']))
        path.write_text(path.read_text().replace('1.500', '2.000'))
        original_config = path.read_bytes()
        editor.cmd_save_review(command('REVIEW'))
        review = editor.get_status()['save_review']
        assert review['retainable'] and review['loaded_offset'] == '2.000'
        retain = command('RETAIN', review['token'])
        editor.cmd_save_review(retain); editor.cmd_save_review(retain)
        assert editor.state == 'save_acknowledged' and not editor.busy()
        assert path.read_bytes() == original_config and store.acknowledged(record)
        restarted = module.ProbeEditorCommands(calibration); restarted._restore_save_evidence()
        assert not restarted.busy()
    assert commands == [] and store.read() == record


@pytest.fixture
def guarded_config(config, tmp_path, monkeypatch):
    """Real retained writer behind WM+ admission; every file is disposable."""
    monkeypatch.syspath_prepend(str(ROOT / 'klipper_extras'))
    from wm_material import WMMaterial
    path = tmp_path / 'printer.cfg'
    path.write_text('[printer]\nkinematics = cartesian\n')
    handlers = {'SAVE_CONFIG': config.cmd_SAVE_CONFIG,
                'SAVE_CONFIG_NO_RESTART': config.cmd_SAVE_CONFIG_NO_RESTART}
    def register(name, callback):
        if callback is None:
            return handlers.pop(name, None)
        assert name not in handlers
        handlers[name] = callback
    restarts = []
    gcode = NS(register_command=register, error=ValueError, quick_stop_flag=False,
               request_restart=lambda kind: restarts.append(kind))
    state = {'print_stats': {'state': 'standby'}, 'pause_resume': {'is_paused': False}}
    objects = {'gcode': gcode, 'virtual_sdcard': NS(current_file=None,
        is_active=lambda: False, is_cmd_from_sd=lambda: False)}
    def lookup(name, default=None):
        if name in objects: return objects[name]
        return NS(get_status=lambda now: state[name]) if name in state else default
    printer = NS(lookup_object=lookup, get_reactor=lambda: NS(monotonic=lambda: 1),
                 get_start_args=lambda: {'config_file': str(path)},
                 command_error=ValueError, config_error=ValueError, is_shutdown=lambda: False)
    config.printer = printer
    config.set('probe', 'z_offset', '1.500')
    material = WMMaterial.__new__(WMMaterial)
    material.printer = printer
    material._print_cancel = {}
    material._recovery_attempt = None
    material.filament_operation = {}
    material.toolhead_operation = {}
    material._config_save_routes_ready()
    return NS(config=config, path=path, handlers=handlers, material=material,
              gcode=gcode, objects=objects, state=state, restarts=restarts)


@pytest.mark.parametrize('hold', ['printing', 'paused', 'filament', 'tool', 'cancel',
                                 'recovery', 'calibration', 'unknown', 'quick-stop'])
def test_restarting_config_save_refuses_before_any_file_write(guarded_config, hold):
    import copy
    v = guarded_config
    if hold == 'printing': v.state['print_stats']['state'] = 'printing'
    elif hold == 'paused': v.state['pause_resume']['is_paused'] = True
    elif hold == 'filament': v.material.filament_operation = {'state': 'running'}
    elif hold == 'tool': v.material.toolhead_operation = {'state': 'running'}
    elif hold == 'cancel': v.material._print_cancel = {'state': 'pending'}
    elif hold == 'recovery': v.material._recovery_attempt = NS(busy=True, record={'state':'running'})
    elif hold == 'calibration': v.state['wmp_recovery'] = {'calibration_active':True}
    elif hold == 'unknown': del v.state['pause_resume']
    else: v.gcode.quick_stop_flag = True
    before = {p.name:p.read_bytes() for p in v.path.parent.iterdir()}
    pending = copy.deepcopy(v.config.status_save_pending)
    with pytest.raises(ValueError): v.handlers['SAVE_CONFIG'](NS(error=ValueError))
    assert {p.name:p.read_bytes() for p in v.path.parent.iterdir()} == before
    assert v.config.status_save_pending == pending
    assert v.config.save_config_pending and v.restarts == []


@pytest.mark.parametrize('command', ['SAVE_CONFIG', 'SAVE_CONFIG_NO_RESTART'])
@pytest.mark.parametrize('context', ['idle', 'managed-calibration', 'openace', 'AFC'])
def test_admitted_config_save_keeps_original_writer(guarded_config, command, context):
    v = guarded_config
    if context == 'managed-calibration':
        v.objects['wmp_recovery'] = NS(get_status=lambda now: {'calibration_active':True},
            calibration=NS(active=True, _saving=True, failure=''))
    elif context in ('openace', 'AFC'):
        v.objects[context] = object()
        v.state['print_stats']['state'] = 'printing'  # Existing owner's policy stays intact.
    original = v.path.read_bytes()
    v.handlers[command](NS(error=ValueError))
    assert '#*# z_offset = 1.500' in v.path.read_text()
    assert next(v.path.parent.glob('printer-*.cfg')).read_bytes() == original
    assert v.restarts == (['firmware_restart'] if command == 'SAVE_CONFIG' else [])


def test_config_save_ready_registration_is_idempotent(guarded_config):
    v = guarded_config
    before = dict(v.handlers)
    v.material._config_save_routes_ready()
    assert v.handlers == before


@pytest.mark.parametrize('missing', ['SAVE_CONFIG', 'SAVE_CONFIG_NO_RESTART'])
def test_config_save_registration_requires_primary_but_optional_vendor_alias(guarded_config, missing):
    v = guarded_config
    v.handlers.clear()
    v.handlers.update(v.material._config_save_handlers)
    del v.material._config_save_handlers
    v.handlers.pop(missing)
    before = dict(v.handlers)
    if missing == 'SAVE_CONFIG':
        with pytest.raises(ValueError, match='requires SAVE_CONFIG'):
            v.material._config_save_routes_ready()
        assert v.handlers == before
    else:
        v.material._config_save_routes_ready()
        assert set(v.handlers) == {'SAVE_CONFIG'}
        v.handlers['SAVE_CONFIG'](NS(error=ValueError))
        assert v.restarts == ['firmware_restart']


@pytest.mark.parametrize('held', [False, True])
def test_config_save_guard_through_retained_dispatcher(guarded_config, held):
    v = guarded_config
    vendor = load('config_guard_dispatch', ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy/gcode.py')
    dispatch = vendor.GCodeDispatch.__new__(vendor.GCodeDispatch)
    dispatch.printer = v.material.printer
    v.material.printer.command_error = vendor.CommandError
    dispatch.ready_gcode_handlers = {}
    dispatch.base_gcode_handlers = {}
    dispatch.gcode_handlers = dispatch.ready_gcode_handlers
    dispatch.gcode_help = {}
    dispatch.respond_info = dispatch.respond_raw = lambda *args: None
    dispatch.request_restart = v.gcode.request_restart
    dispatch.register_command('SAVE_CONFIG', v.config.cmd_SAVE_CONFIG, desc='Save configuration')
    v.objects['gcode'] = dispatch
    del v.material._config_save_handlers
    v.material._config_save_routes_ready()
    before = v.path.read_bytes()
    command = vendor.GCodeCommand(dispatch, 'SAVE_CONFIG', 'SAVE_CONFIG', {}, False)
    if held:
        v.material.toolhead_operation = {'state':'running'}
        with pytest.raises(vendor.CommandError, match='toolhead_operation.state=running'): dispatch.ready_gcode_handlers['SAVE_CONFIG'](command)
        assert v.path.read_bytes() == before and not v.restarts
    else:
        dispatch.ready_gcode_handlers['SAVE_CONFIG'](command)
        assert '#*# z_offset = 1.500' in v.path.read_text()
        assert v.restarts == ['firmware_restart']
    assert dispatch.get_command_help()['SAVE_CONFIG'] == 'Save configuration'


# Real START_PRINT dispatch and failed publications are exercised in
# test_stock_sd_mesh_save.py and test_print_mesh_intent.py. Explicit mesh-only
# save intent replaces the old inferred one-shot SD-line ticket.

@pytest.mark.parametrize('activity', ['printing', 'paused', 'filament', 'tool',
                                     'cancel', 'recovery', 'calibration'])
def test_explicit_no_restart_save_is_whole_set_intent(guarded_config, activity):
    v = guarded_config
    if activity == 'printing': v.state['print_stats']['state'] = 'printing'
    elif activity == 'paused': v.state['pause_resume']['is_paused'] = True
    elif activity == 'filament': v.material.filament_operation = {'state': 'running'}
    elif activity == 'tool': v.material.toolhead_operation = {'state': 'running'}
    elif activity == 'cancel': v.material._print_cancel = {'state': 'pending'}
    elif activity == 'recovery': v.material._recovery_attempt = NS(busy=True, record={'state': 'running'})
    elif activity == 'calibration': v.state['wmp_recovery'] = {'calibration_active': True}
    v.config.set('extruder', 'pid_kp', '25')
    before = v.path.read_bytes()
    v.handlers['SAVE_CONFIG_NO_RESTART'](NS(error=ValueError))
    assert '#*# z_offset = 1.500' in v.path.read_text()
    assert '#*# pid_kp = 25' in v.path.read_text()
    assert next(v.path.parent.glob('printer-*.cfg')).read_bytes() == before
    assert not v.restarts


@pytest.mark.parametrize('command', ['SAVE_CONFIG', 'SAVE_CONFIG_NO_RESTART'])
@pytest.mark.parametrize('stop', ['shutdown', 'quick-stop'])
def test_config_writers_preserve_shutdown_stop_before_writes(guarded_config, command, stop):
    v = guarded_config
    if stop == 'shutdown': v.material.printer.is_shutdown = lambda: True
    else: v.gcode.quick_stop_flag = True
    before = {p.name: p.read_bytes() for p in v.path.parent.iterdir()}
    with pytest.raises(ValueError, match='Configuration save stopped'):
        v.handlers[command](NS(error=ValueError))
    assert {p.name: p.read_bytes() for p in v.path.parent.iterdir()} == before
    assert not v.restarts


def test_consecutive_explicit_mesh_saves_replace_retained_pending_mesh(guarded_config):
    v = guarded_config
    v.config.status_save_pending = {}
    v.config.autosave.fileconfig.remove_section('probe')
    v.objects['configfile'] = v.config
    v.state['bed_mesh'] = {'profile_name': 'wmp_print'}
    v.state['print_stats']['state'] = 'printing'
    messages = []
    for points in ('0.1, 0.2\n0.3, 0.4', '0.5, 0.6\n0.7, 0.8'):
        v.config.set('bed_mesh wmp_print', 'points', points)
        v.material.cmd_SAVE_PRINT_MESH(NS(respond_info=messages.append))
        assert v.material._print_mesh_persisted
        _, autosave = v.config._find_autosave_data(v.path.read_text())
        parsed = v.config._build_config_wrapper(autosave, str(v.path))
        assert parsed.fileconfig.get('bed_mesh wmp_print', 'points').strip() == points
        assert set(v.config.status_save_pending) == {'bed_mesh wmp_print'}
    assert not messages and not v.restarts


@pytest.mark.parametrize('fault, reason', [('wrong-mesh', "active mesh is 'default'"),
                                          ('empty-mesh', 'settings are empty')])
def test_explicit_mesh_save_skips_unusable_mesh_without_aborting(guarded_config, fault, reason):
    v = guarded_config
    v.config.status_save_pending = {}
    v.config.autosave.fileconfig.remove_section('probe')
    v.config.set('bed_mesh wmp_print', 'points', '0.1, 0.2')
    v.objects['configfile'] = v.config
    v.state['bed_mesh'] = {'profile_name': 'default' if fault == 'wrong-mesh' else 'wmp_print'}
    if fault == 'empty-mesh': v.config.status_save_pending['bed_mesh wmp_print'] = {}
    before = v.path.read_bytes()
    messages = []
    v.material.cmd_SAVE_PRINT_MESH(NS(respond_info=messages.append))
    assert not v.material._print_mesh_persisted
    assert reason in messages[0] and 'Printing can continue' in messages[0]
    assert v.path.read_bytes() == before and not v.restarts


@pytest.mark.parametrize('action', ['scan', 'review'])
def test_read_only_profile_import_does_not_block_explicit_mesh_save(guarded_config, action):
    v = guarded_config
    v.config.status_save_pending = {}
    v.config.autosave.fileconfig.remove_section('probe')
    v.objects['configfile'] = v.config
    v.state['bed_mesh'] = {'profile_name': 'wmp_print'}
    v.material._profile_import_busy = True
    v.material.profile_import = {'action': action, 'state': 'busy'}
    v.config.set('bed_mesh wmp_print', 'points', '0.1, 0.2')
    v.material.cmd_SAVE_PRINT_MESH(NS(respond_info=lambda message: pytest.fail(message)))
    assert '#*# [bed_mesh wmp_print]' in v.path.read_text()
    assert not v.restarts


@pytest.mark.parametrize('action', ['scan', 'review'])
def test_read_only_profile_import_does_not_block_restart(guarded_config, action):
    v = guarded_config
    v.material._profile_import_busy = True
    v.material.profile_import = {'action': action, 'state': 'busy'}
    v.material._restart_requested(None)
