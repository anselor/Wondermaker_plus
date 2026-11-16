"""The installer requires loaded protocols, not just correct files on disk."""
import json
from types import SimpleNamespace

import pytest
from test_deploy import deploy
from components import preload


def status():
    return {
        'wm_material': dict({name:1 for name in preload.BACKEND_PROTOCOLS},
                            session_id='fresh-session',
                            # No legacy INI is needed for protocol acceptance.
                            available=False,
                            filament_presence={'h%d'%n:{'state':'unknown'} for n in range(4)},
                            filament_loaded={'h%d'%n:{'state':'empty'} for n in range(4)}),
        'wmp_recovery': {'identification': {'protocol':2}, 'z_reference_valid':False, 'homing':False,
                         'calibration_active':False, 'calibration_failed':'',
                         'calibration_ticket_protocol':1, 'calibration_next_ticket':'1',
                         'calibration_checkpoint':'', 'calibration_session':'calibration-session',
                         'probe_editor': {'protocol':1, 'stop_protocol':1, 'save_review_protocol':2,
                                          'session':'calibration-session', 'binding_valid':True,
                                          'save_review_required':False, 'save_review_confirmable':False,
                                          'save_review_sequence':0}},
        'gcode': {'commands': {name:{} for name in preload.BACKEND_COMMANDS}},
    }


def check(value):
    paths=[]
    def api(path):
        paths.append(path)
        return json.dumps({'result':{'status':value}})
    preload._verify_running_backend(SimpleNamespace(moonraker=api, DeployError=deploy.DeployError))
    assert paths==['/printer/objects/query?wm_material&wmp_recovery&gcode']


def test_current_standalone_backend_passes_without_moving_or_requiring_homing():
    check(status())


@pytest.mark.parametrize('protocol', preload.BACKEND_PROTOCOLS)
@pytest.mark.parametrize('version', [None, 0, 2, True])
def test_unsupported_or_missing_protocol_rejected(protocol, version):
    value=status()
    value['wm_material'][protocol]=version
    with pytest.raises(deploy.DeployError, match=protocol):
        check(value)


@pytest.mark.parametrize('command', preload.BACKEND_COMMANDS)
def test_each_required_command_must_be_loaded(command):
    value=status()
    del value['gcode']['commands'][command]
    with pytest.raises(deploy.DeployError, match=command):
        check(value)


@pytest.mark.parametrize('obj', ['wm_material', 'wmp_recovery', 'gcode'])
def test_missing_runtime_object_rejected(obj):
    value=status()
    del value[obj]
    with pytest.raises(deploy.DeployError):
        check(value)


@pytest.mark.parametrize('field', ['filament_presence', 'filament_loaded'])
def test_missing_head_status_rejected(field):
    value=status()
    del value['wm_material'][field]['h3']
    with pytest.raises(deploy.DeployError, match='four-head'):
        check(value)


def test_missing_recovery_contract_rejected():
    value=status()
    value['wmp_recovery']={}
    with pytest.raises(deploy.DeployError, match='wmp_recovery.calibration_ticket_protocol'):
        check(value)


@pytest.mark.parametrize('key,value', [
    ('calibration_checkpoint', None), ('calibration_checkpoint', 1),
    ('calibration_session', None), ('calibration_session', ''),
    ('calibration_session', 1), ('calibration_active', None),
    ('calibration_active', 0), ('calibration_failed', None),
    ('calibration_failed', False),
    ('calibration_ticket_protocol', None), ('calibration_ticket_protocol', True),
    ('calibration_ticket_protocol', 2), ('calibration_next_ticket', None),
    ('calibration_next_ticket', 1), ('calibration_next_ticket', '0'),
    ('calibration_next_ticket', '01'), ('calibration_next_ticket', '1.0'),
    ('calibration_next_ticket', '١'), ('calibration_next_ticket', '1' * 257),
])
def test_calibration_status_contract_required(key, value):
    current = status()
    current['wmp_recovery'][key] = value
    with pytest.raises(deploy.DeployError, match='calibration'):
        check(current)


@pytest.mark.parametrize('missing', [
    'recovery_review_protocol', 'recovery_continue_protocol',
    'recovery_stop_protocol', 'recovery_resolution_protocol',
    'WMP_RECOVERY_CONTINUE', 'WMP_RECOVERY_RESOLVE',
])
def test_screen_recovery_contract_cannot_accept_older_helper(missing):
    current = status()
    if missing.startswith('WMP_'):
        current['gcode']['commands'].pop(missing, None)
    else:
        current['wm_material'].pop(missing, None)
    with pytest.raises(deploy.DeployError, match=missing):
        check(current)


@pytest.mark.parametrize('field,version', [('protocol',1), ('stop_protocol',1), ('save_review_protocol',2)])
@pytest.mark.parametrize('bad', [None, False, True, '2', 0, 3])
def test_probe_editor_protocol_must_be_loaded(field, version, bad):
    current = status()
    current['wmp_recovery']['probe_editor'][field] = bad
    with pytest.raises(deploy.DeployError, match='probe_editor.' + field):
        check(current)


def test_legacy_unsequenced_save_review_protocol_rejected():
    current = status()
    current['wmp_recovery']['probe_editor']['save_review_protocol'] = 1
    with pytest.raises(deploy.DeployError, match='save_review_protocol'):
        check(current)


@pytest.mark.parametrize('editor', [None, {}, [], 'unsupported'])
def test_missing_editor_status_rejected(editor):
    current = status()
    current['wmp_recovery']['probe_editor'] = editor
    with pytest.raises(deploy.DeployError, match='probe_editor'):
        check(current)


@pytest.mark.parametrize('field,bad', [
    ('session', 'old'), ('session', None),
    ('save_review_sequence', -1), ('save_review_sequence', 1000000000),
    ('save_review_sequence', True), ('save_review_sequence', '1'),
    ('save_review_required', 0), ('save_review_confirmable', None), ('binding_valid', 1),
])
def test_editor_loaded_status_shape_required(field, bad):
    current = status()
    current['wmp_recovery']['probe_editor'][field] = bad
    with pytest.raises(deploy.DeployError, match='probe_editor'):
        check(current)


def test_save_review_hold_is_accepted_without_acknowledging_or_clearing_it():
    current = status()
    editor = current['wmp_recovery']['probe_editor']
    editor.update(save_review_required=True, save_review_confirmable=False,
                  binding_valid=False, save_review_sequence=7)
    before = json.dumps(current, sort_keys=True)
    check(current)
    assert json.dumps(current, sort_keys=True) == before


@pytest.mark.parametrize('protocol', [None, True, 0, 1, 3])
def test_identification_receipt_protocol_required(protocol):
    current=status()
    current['wmp_recovery']['identification']['protocol']=protocol
    with pytest.raises(deploy.DeployError, match='identification.protocol'):
        check(current)


def test_delivered_contract_is_sealed_and_matches_producer_consumer_sources():
    from pathlib import Path
    import preload_bundle
    root=Path(preload.ROOT)
    contract=preload.backend_contract()
    assert preload.BACKEND_CONTRACT_PATH in preload_bundle.current_source_files(root)
    producers='\n'.join(p.read_text(encoding='utf-8') for p in (root/'klipper_extras').glob('*.py'))
    consumers='\n'.join(p.read_text(encoding='utf-8') for directory in ('client-preload','config/live')
        for p in (root/directory).rglob('*') if p.is_file() and p.suffix in ('.hpp','.cpp','.c','.cfg'))
    for owner in ('wm_material','wmp_recovery'):
        for path in contract['required'][owner]:
            leaf=path.split('.')[-1]
            assert ('"'+leaf+'"') in producers or ("'"+leaf+"'") in producers, path
            if path not in contract['backend_owned_protocols']:
                assert leaf in consumers, path
    for command in contract['required']['commands']:
        assert ('"'+command+'"') in producers or ("'"+command+"'") in producers, command
        if command not in contract['backend_owned_commands']:
            assert command in consumers, command
    # These internal capabilities protect the backend script ingress itself;
    # they deliberately are not guessed from touchscreen feature strings.
    assert set(contract['backend_owned_protocols'])=={
        'script_generation_protocol','print_cancel_ingress_protocol','command_generation_protocol'}
    assert 'prefix = "WMP_CHECK_SCRIPT_GENERATION SESSION=' in producers


@pytest.mark.parametrize('value', [None, 0, 2, True, 'unsupported'])
def test_optional_capabilities_never_become_installation_requirements(value):
    current=status()
    for name in preload.backend_contract()['optional']['wm_material']:
        current['wm_material'][name]=value
    check(current)


@pytest.mark.parametrize('change', ['version','protocol_type','duplicate_command','overlap','unknown_group'])
def test_malformed_delivered_contract_is_rejected(tmp_path,change):
    from pathlib import Path
    value=preload.backend_contract()
    if change=='version':value['version']=True
    elif change=='protocol_type':value['required']['wm_material']['print_start_protocol']=True
    elif change=='duplicate_command':value['required']['commands'].append(value['required']['commands'][0])
    elif change=='overlap':value['optional']['wm_material']['print_start_protocol']=1
    else:value['required']['unexpected']={}
    path=tmp_path/preload.BACKEND_CONTRACT_PATH
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError):preload.backend_contract(tmp_path)


@pytest.mark.parametrize('state',['error','shutdown'])
def test_contract_refactor_keeps_preexisting_backend_error_restart_acceptance(monkeypatch,state):
    before={'state':state,'state_message':'Existing printer configuration issue','process_id':1}
    after=dict(before,process_id=2)
    replies=iter([before,after,after])
    monkeypatch.setattr(preload,'_printer_info',lambda ctx:next(replies))
    monkeypatch.setattr(preload.time,'sleep',lambda delay:None)
    verified=[]
    monkeypatch.setattr(preload,'verify_guard',lambda ctx:verified.append(True))
    monkeypatch.setattr(preload,'run',lambda connection,command,**kwargs:
                        ('active\n' if 'is-active' in command else '', '', 0))
    ctx=SimpleNamespace(DeployError=deploy.DeployError)
    preload._restart(ctx,object())
    assert verified==[True] and ctx.preload_backend_ready is False
