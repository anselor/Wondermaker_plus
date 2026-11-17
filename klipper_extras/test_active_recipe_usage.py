import configparser
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import pytest
import wmp_recovery_file_envelope as envelope
from test_wm_material import material, print_material, FakeCommand, profile_command, start_command

ROOT = Path(__file__).resolve().parents[1]
STAMP = (ROOT/'tests/fixtures/recovery_two_color_stamp.gcode').read_bytes()


def settings():
    parser=configparser.RawConfigParser(strict=False)
    for name in ('offset_calibrate.cfg','macros.cfg','change_macros.cfg','fz-wipe-nozzle.cfg'):
        parser.read(ROOT/'config/live'/name)
    return {name.lower():dict(parser.items(name)) for name in parser.sections()}


@pytest.mark.parametrize('data,expected', [(STAMP,[2,3]),(STAMP.replace(b'T3\n',b'T1\n'),[1,2]),
    (STAMP.replace(b'CHAMBER=0 ', b'CHAMBER=45 CHAMBER_HOLD=120 '), [2,3])])
def test_whole_supported_stamp_membership(data,expected):
    scan=envelope.ToolUsage()
    for line in data.splitlines(keepends=True): scan.feed(line)
    assert scan.complete()==expected


@pytest.mark.parametrize('line', [b'MY_CUSTOM_MACRO\n',b'ACTIVATE_EXTRUDER EXTRUDER=extruder\n',b'SAVE_VARIABLE VARIABLE=box_modify_t2 VALUE=0\n'])
def test_unknown_effect_never_claims_complete_membership(line):
    scan=envelope.ToolUsage()
    for raw in STAMP.replace(b'\nPRINT_END',b'\n'+line+b'PRINT_END').splitlines(keepends=True): scan.feed(raw)
    with pytest.raises(ValueError):scan.complete()


@pytest.fixture
def usage_machine(print_material):
    obj,objects,request,path=print_material
    cfg=settings()
    objects['configfile']=SimpleNamespace(get_status=lambda now:{'settings':cfg})
    obj._recovery_clearance()._recovery_file_effect_contract=lambda:envelope.effect_contract(cfg,dict(envelope.TRANSFORMS))
    variables=objects['save_variables'].values['variables']
    variables.update({f'box_modify_t{i}':i for i in range(4)})
    variables.update({f'box_modify_t{i}_backup':i for i in range(4)})
    objects['extruder']=objects['extruder1']=objects['extruder3']=object()
    profiles={f'h{i}':dict(obj._profiles()[0]['h2']) for i in range(4)}
    Path(obj.profile_path).write_text(json.dumps(profiles))
    path.write_bytes(STAMP)
    scan=obj._begin_usage_scan(str(path))
    for line in STAMP.splitlines(keepends=True):scan['scanner'].feed(line)
    obj._finish_usage_scan(scan,hashlib.sha256(STAMP).hexdigest())
    stream=open(path,'r')
    objects['virtual_sdcard'].current_file=stream
    obj._bind_usage_stream()
    obj.printer.state='printing';objects['virtual_sdcard'].active=True
    yield obj,objects,cfg,path,stream
    stream.close()


def save(obj,head,**changes):
    identity=dict(obj._profiles()[0][f'h{head}'],**changes)
    obj.cmd_SET_FILAMENT(FakeCommand(HEAD=head,EXPECT=obj._profiles()[1],PROFILE=json.dumps(identity).encode().hex()))


@pytest.mark.parametrize('paused',[False,True])
def test_actual_bound_job_permits_unused_recipe_without_touching_print(usage_machine,paused):
    obj,objects,cfg,path,stream=usage_machine
    if paused:
        obj.printer.state='paused';objects['pause_resume'].values['is_paused']=True;objects['virtual_sdcard'].active=False
    position=stream.tell();scripts=list(objects['gcode'].scripts)
    save(obj,0,material='PLA',nozzle_temp=215)
    save(obj,1,nozzle_temp=230)
    assert stream.tell()==position and objects['gcode'].scripts==scripts
    with pytest.raises(ValueError):save(obj,2,material='PLA')
    with pytest.raises(ValueError):save(obj,3,material='PLA')
    assert obj._recipe_write_status(1)['h0']['allowed']
    assert not obj._recipe_write_status(1)['h2']['allowed']


@pytest.mark.parametrize('drift',['generation','mapping','session','stream','macros','file'])
def test_binding_dependencies_not_generic_generation(usage_machine,drift):
    obj,objects,cfg,path,stream=usage_machine
    replacement=None
    if drift=='generation':obj._command_generation=99
    elif drift=='mapping':objects['save_variables'].values['variables']['box_modify_t2']=0
    elif drift=='session':obj.session_id='new'
    elif drift=='stream':
        replacement=open(path);objects['virtual_sdcard'].current_file=replacement
    elif drift=='macros':cfg['gcode_macro t2']['gcode']+='\nT0'
    else:
        before=path.stat();path.write_bytes(STAMP.replace(b'T3\n',b'T0\n'));os.utime(path,ns=(before.st_atime_ns,before.st_mtime_ns))
    try:
        if drift=='generation':save(obj,0,material='PLA')
        else:
            with pytest.raises(ValueError):save(obj,0,material='PLA')
    finally:
        if replacement:replacement.close()


def test_poll_policy_does_not_touch_files_or_reparse(usage_machine,monkeypatch):
    obj,objects,cfg,path,stream=usage_machine
    with monkeypatch.context() as patch:
        patch.setattr('wm_material.os.stat',lambda *a,**k:pytest.fail('status stat'))
        patch.setattr('wm_material.os.fstat',lambda *a,**k:pytest.fail('status fstat'))
        patch.setattr(envelope.ToolUsage,'feed',lambda *a:pytest.fail('status parse'))
        for _ in range(10):assert obj._recipe_write_status(1)['h0']['allowed']


def test_actual_sd_scan_survives_unavailable_optional_recovery(usage_machine):
    obj,objects,cfg,path,stream=usage_machine
    sd=objects['virtual_sdcard']
    sd.from_sd=True;sd.file_position=0;sd.next_file_position=1
    objects['gcode_macro START_PRINT']=SimpleNamespace(get_status=lambda now:{'print_body_ready':False})
    obj._material_settings()._recipe_usage_observation=None
    # The fixture has no loaded h3 evidence. Recovery staging fails only after
    # the actual open SD stream has been independently scanned for membership.
    with pytest.raises(ValueError,match='Loaded material evidence'):
        obj._recovery_jobs()._stage_active_sd_recovery()
    assert obj._material_settings()._active_recipe_heads(0,check_file=True)=={'h2','h3'}
    save(obj,0,nozzle_temp=220)


@pytest.mark.parametrize('unsupported',[False,True])
@pytest.mark.parametrize('missing_recovery',[False,True])
def test_managed_entry_never_gates_print_on_usage_support(print_material,unsupported,missing_recovery):
    obj,objects,request,path=print_material
    cfg=settings()
    objects['configfile']=SimpleNamespace(get_status=lambda now:{'settings':cfg})
    obj._recovery_clearance()._recovery_file_effect_contract=lambda:envelope.effect_contract(cfg,dict(envelope.TRANSFORMS))
    data=STAMP if not unsupported else STAMP.replace(b'\nPRINT_END',b'\nMY_CUSTOM_MACRO\nPRINT_END')
    path.write_bytes(data)
    request['file'].update(size=path.stat().st_size,modified=path.stat().st_mtime)
    request['profile_revision']=obj._profiles()[1]
    if missing_recovery:
        loaded=obj._loaded_filament_status(0)
        loaded['h2'].pop('source')
        obj._filament_state()._loaded_filament_status=lambda now:loaded
    obj.cmd_START_PRINT(start_command(request))
    if missing_recovery:assert 'source identity' in obj._print_recovery_error
    assert obj.print_submission['state']=='submitted'
    assert objects['gcode'].scripts[-1].startswith('SDCARD_PRINT_FILE')
    observation=getattr(obj._material_settings(),'_recipe_usage_observation',None)
    if unsupported:
        assert observation is None
        assert 'MY_CUSTOM_MACRO' in obj._material_settings()._recipe_usage_error
    else:
        assert observation['tools']==(2,3)
        assert observation['stream'] is None
        with path.open() as actual:
            objects['virtual_sdcard'].current_file=actual
            obj._bind_usage_stream()
            assert obj._material_settings()._active_recipe_heads(0,check_file=True)=={'h2','h3'}


def test_complete_tool_membership_uses_full_mapping_not_requested_subset(usage_machine):
    obj,objects,cfg,path,stream=usage_machine
    variables=objects['save_variables'].values['variables']
    for suffix in ('','_backup'):
        variables['box_modify_t2'+suffix]=1
        variables['box_modify_t3'+suffix]=1
    # Re-observe the actual job at its valid startup boundary with a many-to-one
    # mapping; both sliced tools consume head 1, not physical heads 2 and 3.
    scan=obj._begin_usage_scan(str(path))
    for line in STAMP.splitlines(keepends=True):scan['scanner'].feed(line)
    obj._finish_usage_scan(scan,hashlib.sha256(STAMP).hexdigest(),stream)
    assert obj._material_settings()._active_recipe_heads(0,check_file=True)=={'h1'}
    save(obj,2,material='PLA')
    with pytest.raises(ValueError):save(obj,1,material='PLA')


@pytest.mark.parametrize('head',['h0','unknown'])
def test_known_unused_head_still_excludes_its_active_filament_service(usage_machine,head):
    obj,objects,cfg,path,stream=usage_machine
    obj.filament_operation={'state':'running','head':head}
    with pytest.raises(ValueError,match='active filament'):
        save(obj,0,material='PLA')
    assert not obj._recipe_write_status(0)['h0']['allowed']


def test_optional_recovery_still_detects_in_place_source_change_during_scan(print_material):
    obj,objects,request,path=print_material
    cfg=settings()
    objects['configfile']=SimpleNamespace(get_status=lambda now:{'settings':cfg})
    obj._recovery_clearance()._recovery_file_effect_contract=lambda:envelope.effect_contract(cfg,dict(envelope.TRANSFORMS))
    path.write_bytes(STAMP)
    request['file'].update(size=path.stat().st_size,modified=path.stat().st_mtime)
    loaded=obj._loaded_filament_status(0)
    obj._filament_state()._loaded_filament_status=lambda now:loaded
    obj.printer.get_reactor().pause=lambda when:loaded['h2'].update(source='external:h1')
    obj.cmd_START_PRINT(start_command(request))
    assert obj.print_submission['state']=='submitted'
    assert 'Loaded filament changed during recovery staging' in obj._print_recovery_error
    assert obj._material_settings()._recipe_usage_observation['tools']==(2,3)
