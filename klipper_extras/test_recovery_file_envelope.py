import configparser
import copy
import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
import wmp_recovery_file_envelope as analysis
import wm_material

ROOT=Path(__file__).resolve().parents[1]
STAMP=(ROOT/'tests/fixtures/recovery_two_color_stamp.gcode').read_bytes()
PROOF={'version':1,'sha256':'a'*64}


def arguments(data=STAMP):
    line=b'G1 X161.750 Y128.250 E0.89315 F1200\n'
    position=data.index(line)+len(line)
    execution={'job_id':'test_job','head':'h2','mapping':[0,1,2,3],
        'file_position':position,'file':{'size':len(data),'sha256':hashlib.sha256(data).hexdigest()},
        'gcode_position':[161.75,128.25,.2,0.], 'parser_position':[161.75,128.25,.2,0.],
        'absolute_coordinates':True,'absolute_extrude':False}
    context={'tool':2,'offsets':[[0.,0.,0.] for _ in range(4)],'file_effect_contract':PROOF}
    return execution,context


def derive(data=STAMP, *, matrix=None, fade=0., edit=None):
    execution,context=arguments(data)
    if edit:edit(execution,context)
    return analysis.analyze(io.BytesIO(data),execution,context,matrix or [[0.,0.],[0.,0.]],fade,PROOF)


def test_actual_completed_two_color_stamp():
    assert derive()['max_z']==2.


def test_future_deposition_and_sequential_objects_beyond_checkpoint_are_included():
    data=STAMP.replace(b'\nPRINT_END',b'\nG90\nG1 Z250\nG1 X10 E1\nG1 Z0.2\nG1 X20 E1\nPRINT_END')
    assert derive(data)['max_z']==251.


def test_dense_mesh_fade_and_all_tool_offsets_are_conservative():
    def edit(execution,context):
        context['offsets'][3][2]=.7
    assert derive(matrix=[[.1,-.8],[.25,.05]],fade=.4,edit=edit)['max_z']==3.
    assert derive(matrix=[[-.1,-.8],[-.25,-.05]],fade=-.2)['max_z']==2.


def test_relative_xyz_and_g92_e_not_g92_xyz():
    data=STAMP.replace(b'\nPRINT_END',b'\nG91\nM82\nG1 Z120\nG1 X2 E-1\nG90\nM83\nG92 E0\nPRINT_END')
    assert derive(data)['max_z']==123.
    with pytest.raises(ValueError,match='coordinate reset'):
        derive(STAMP.replace(b'\nPRINT_END',b'\nG92 Z0\nPRINT_END'))


@pytest.mark.parametrize('command',[b'G2 X2 Y3 I1 E1',b'CUSTOM_PURGE',b'BED_MESH_CLEAR',
    b'SET_GCODE_OFFSET Z=100',b'SET_KINEMATIC_POSITION Z=1',b'G1 Znan E1',b'G1 Z1e999 E1'])
def test_unsupported_effects_report_exact_command_and_byte(command):
    with pytest.raises(ValueError,match='byte'):
        derive(STAMP.replace(b'\nPRINT_END',b'\n'+command+b'\nPRINT_END'))


@pytest.mark.parametrize('change',['hash','boundary','tool','mode','position','proof'])
def test_checkpoint_and_whole_job_binding(change):
    execution,context=arguments()
    if change=='hash':execution['file']['sha256']='f'*64
    elif change=='boundary':execution['file_position']-=1
    elif change=='tool':execution['head']='h3'
    elif change=='mode':execution['absolute_extrude']=True
    elif change=='position':execution['gcode_position'][2]=3
    else:context.pop('file_effect_contract')
    with pytest.raises(ValueError):analysis.analyze(io.BytesIO(STAMP),execution,context,[[0.,0.],[0.,0.]],0.,PROOF)


@pytest.mark.parametrize('changed', ['START_PRINT', '_WMP_XY_TRAVEL', 'PRINT_END',
                                      '_WMP_PRINT_END_CLEARANCE_AND_WIPE', '_WMP_PRINT_LOWER_BED', '_WMP_PRINT_STOP_PARK',
                                      '_CHANGING_TOOL', '_CHECK_CHANGE_TOOL', '_UNLOCK_TOOL', '_LOCK_TOOL',
                                      '_WMP_TOOL_RETURN_BEGIN', '_WMP_TOOL_RETURN_FINISH'])
def test_contract_matches_delivered_macro_sources_and_rejects_changes(changed):
    parser=configparser.RawConfigParser(strict=False)
    for name in ('offset_calibrate.cfg','macros.cfg','change_macros.cfg','fz-wipe-nozzle.cfg'):
        parser.read(ROOT/'config/live'/name,encoding='utf-8')
    settings={name.lower():dict(parser.items(name)) for name in parser.sections()}
    proof=analysis.effect_contract(settings,dict(analysis.TRANSFORMS))
    assert proof['version']==1
    modified=copy.deepcopy(settings)
    modified['gcode_macro '+changed.lower()]['gcode']+='\nG1 Z200 E5'
    with pytest.raises(ValueError,match=changed):analysis.effect_contract(modified,analysis.TRANSFORMS)
    transforms=dict(analysis.TRANSFORMS,bed_mesh='f'*64)
    with pytest.raises(ValueError,match='transform'):analysis.effect_contract(settings,transforms)


def test_measured_envelope_preferred_without_analysis_or_writes(tmp_path):
    obj=object.__new__(wm_material.WMMaterial)
    path=tmp_path/'measured.json';path.write_bytes(b'actual measured payload')
    obj._execution_evidence()._deposition_envelope_path=lambda:str(path)
    obj._recovery_storage()._recovery_job_path=lambda:pytest.fail('measured evidence does not need fallback')
    assert obj._recovery_deposition_payload({})==b'actual measured payload'


def test_older_missing_proof_has_actionable_limitation_and_does_not_write(tmp_path):
    obj=object.__new__(wm_material.WMMaterial)
    envelope=tmp_path/'missing.json';job=tmp_path/'job.json'
    payload=json.dumps({'context':{}}).encode();job.write_bytes(payload)
    obj._execution_evidence()._deposition_envelope_path=lambda:str(envelope)
    obj._recovery_storage()._recovery_job_path=lambda:str(job)
    with pytest.raises(ValueError,match='older print'):
        obj._recovery_deposition_payload({'job_fingerprint':obj._recovery_fingerprint(payload)})
    assert not envelope.exists() and job.read_bytes()==payload


def test_compact_exponent_cannot_hide_extrusion():
    with pytest.raises(ValueError, match='parameter syntax'):
        derive(STAMP.replace(b'\nPRINT_END', b'\nG1 X1E2\nPRINT_END'))

def test_inline_quoted_suffix_changes_macro_proof():
    assert analysis.macro_digest('RESPOND MSG="a;b"') != analysis.macro_digest('RESPOND MSG="a;c"')
    assert analysis.macro_digest('RESPOND MSG="a#b"') != analysis.macro_digest('RESPOND MSG="a#c"')


def test_macro_proof_matches_vendor_inline_comment_parsing():
    source = 'G1 X10 ; travel\nRESPOND MSG="a#b" # note\n# whole comment\n'
    parser = configparser.RawConfigParser(inline_comment_prefixes=(';', '#'))
    parser.read_string('[gcode_macro sample]\ngcode:\n' +
                       ''.join('  ' + line + '\n' for line in source.splitlines()))
    loaded = parser.get('gcode_macro sample', 'gcode')
    assert analysis.macro_digest(source) == analysis.macro_digest(loaded)
    assert analysis.macro_digest(source) != analysis.macro_digest(source + 'G1 Z200 E5\n')

def test_negative_later_frame_does_not_reduce_startup_purge():
    def edit(execution, context):
        execution['parser_position'][2] -= 20
    assert derive(edit=edit)['max_z'] == 1.


def test_supported_readback_is_read_only_cached_and_revalidates_context(tmp_path):
    obj=object.__new__(wm_material.WMMaterial)
    envelope=tmp_path/'missing.json';job=tmp_path/'job.json';gcode=tmp_path/'stamp.gcode'
    execution,context=arguments();payload=json.dumps({'context':context}).encode()
    job.write_bytes(payload);gcode.write_bytes(STAMP)
    execution.update(job_fingerprint=obj._recovery_fingerprint(payload),mesh_fingerprint='mesh')
    obj._execution_evidence()._deposition_envelope_path=lambda:str(envelope)
    obj._recovery_storage()._recovery_job_path=lambda:str(job)
    obj._recovery_clearance()._recovery_file_effect_contract=lambda:PROOF
    obj._recovery_clearance()._recovery_file_mesh=lambda execution:([[0.,0.],[0.,0.]],0.,'mesh')
    mesh=SimpleNamespace(fade_target=0.,get_status=lambda now:{'mesh_matrix':[[0.,0.],[0.,0.]]})
    reactor=SimpleNamespace(monotonic=lambda:0.,pause=lambda when:None)
    obj.printer=SimpleNamespace(get_reactor=lambda:reactor,lookup_object=lambda name:mesh if name=='bed_mesh' else object())
    def file_identity(sd, info):
        st=gcode.stat()
        return str(gcode),(st.st_dev,st.st_ino,st.st_size,st.st_mtime_ns)
    obj._print_service()._print_file_identity=file_identity
    result=obj._recovery_deposition_payload(execution)
    assert json.loads(result)['max_z']==2.
    assert not envelope.exists() and job.read_bytes()==payload
    assert obj._recovery_deposition_payload(execution)==result
    obj._recovery_clearance()._recovery_file_effect_contract=lambda:{'version':1,'sha256':'f'*64}
    with pytest.raises(ValueError,match='proof changed'):obj._recovery_deposition_payload(execution)
    assert not envelope.exists()


def test_restart_saved_mesh_reconstruction_does_not_activate_or_write(tmp_path, monkeypatch):
    import importlib.util
    import sys
    fixture=ROOT/'tests/fixtures/vendor_1_1_13_zmesh.py'
    spec=importlib.util.spec_from_file_location('wmp_test_vendor_mesh',fixture)
    vendor=importlib.util.module_from_spec(spec);spec.loader.exec_module(vendor)
    monkeypatch.setitem(sys.modules,spec.name,vendor)
    mesh_type=type('SavedOnlyMesh',(),{'__module__':spec.name})
    mesh=mesh_type()
    params={'min_x':0.,'max_x':200.,'min_y':0.,'max_y':200.,'x_count':4,'y_count':4,
            'mesh_x_pps':3,'mesh_y_pps':3,'algo':'bicubic','tension':.6}
    profile={'mesh_params':params,'points':[[.1,.2,.1,0.],[.2,.3,.2,.1],[.1,.2,.3,.2],[0.,.1,.2,.1]]}
    mesh.pmgr=SimpleNamespace(get_profiles=lambda:{'wmp_print':profile})
    mesh.fade_start=1.;mesh.fade_end=10.;mesh.fade_dist=9.;mesh.FADE_DISABLE=2**31
    mesh.base_fade_target=None
    mesh.set_mesh=lambda value:pytest.fail('read-only review must not activate a mesh')
    mesh.get_status=lambda now:{'profile_name':'','mesh_matrix':[]}
    obj=object.__new__(wm_material.WMMaterial)
    obj.printer=SimpleNamespace(lookup_object=lambda name:mesh)
    actual=vendor.ZMesh(copy.deepcopy(params),'wmp_print');actual.build_mesh(profile['points'])
    offsets=[4.,-2.,.15];grid=actual.get_mesh_matrix();fade=actual.get_z_average()
    canonical=[grid,[[0.,0.],[200.,200.],offsets[:2]],[1.,10.,9.,fade,.15]]
    fingerprint=hashlib.sha256(json.dumps(canonical,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    execution={'mesh_offsets':offsets,'mesh_fingerprint':fingerprint}
    assert obj._recovery_clearance()._recovery_file_mesh(execution)==(grid,fade,fingerprint)
    assert mesh.get_status(0)['profile_name']==''
    assert not list(tmp_path.iterdir())
    # Exercise the real read-only payload path after restart, not just the helper.
    execution,context=arguments()
    execution.update(mesh_offsets=offsets,mesh_fingerprint=fingerprint)
    job=tmp_path/'job.json';gcode=tmp_path/'stamp.gcode';envelope=tmp_path/'missing.json'
    payload=json.dumps({'context':context}).encode();job.write_bytes(payload);gcode.write_bytes(STAMP)
    execution['job_fingerprint']=obj._recovery_fingerprint(payload)
    obj._recovery_storage()._recovery_job_path=lambda:str(job);obj._execution_evidence()._deposition_envelope_path=lambda:str(envelope)
    obj._recovery_clearance()._recovery_file_effect_contract=lambda:PROOF
    obj.printer.get_reactor=lambda:SimpleNamespace(monotonic=lambda:0.,pause=lambda when:None)
    def identity(sd, info):
        stat=gcode.stat()
        return str(gcode),(stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns)
    obj._print_service()._print_file_identity=identity
    assert json.loads(obj._recovery_deposition_payload(execution))['max_z']==2.
    assert not envelope.exists() and job.read_bytes()==payload
    assert mesh.get_status(0)['profile_name']==''
    profile['points'][0][0]=.8
    with pytest.raises(ValueError,match='differs'):obj._recovery_clearance()._recovery_file_mesh(execution)


def test_rounded_mesh_fingerprint_cannot_shrink_integer_ceiling():
    # Raw interpolation may be slightly above the rounded zero grid.
    assert derive(matrix=[[0.,0.],[0.,0.]])['max_z'] >= 1.0000004


@pytest.mark.parametrize('started,ended', [(False,False),(True,False),(True,True)])
def test_membership_move_shortcut_matches_full_dialect(started,ended):
    import random
    rng=random.Random(419)
    lines=['G1', 'g0 X1 Y2 E.5 F12000', 'G1 X1 X2', 'G1 X1e999',
           'G1 X'+'9'*310, 'G1 Xnan', 'G1 X1Y2', 'G1 X١٢', 'G1 x1',
           'G1 E1 X2', 'G1 X1 ; non-ASCII comment: café', 'G01 X1',
           'G1 X1 # comment', 'T3', 'START_PRINT INITIAL_TOOL=2', 'PRINT_END']
    for _ in range(2000):
        keys=rng.sample('XYZEF',rng.randrange(6))
        if rng.randrange(2): keys.sort(key='XYZEF'.index)
        values=['0','-1.25','+.5','123456.','0001','+0.00003','1e3','nan']
        lines.append(rng.choice(['G0','G1','g1'])+''.join(
            rng.choice([' ','  ','\t'])+key+rng.choice(values) for key in keys))
    for source in lines:
        raw=(source+'\n').encode('utf-8')
        line=raw.split(b';',1)[0].decode('ascii',errors='replace').strip()
        try:
            if '\ufffd' in line: raise ValueError('nonascii')
            analysis.classified_command(line,started,ended)
            expected=True
        except (ValueError,UnicodeError):expected=False
        scan=analysis.ToolUsage();scan.started=started;scan.ended=ended
        scan.feed(raw)
        assert (not scan.error)==expected,source


@pytest.mark.parametrize('name,previous', [
    ('_WMP_TOOL_RETURN_BEGIN', '8c794eec2350652e75ea46ace1eb3f0f832682a25914708b1dddf271b16e1a75'),
    ('_WMP_TOOL_RETURN_FINISH', '66a330b655f72f0073a97f5c8027d3ce3ddd978c89b7049a2048cbb131119873')])
def test_identification_completion_changes_only_nonmotion_bookkeeping(name, previous):
    parser = configparser.RawConfigParser(strict=False)
    parser.read(ROOT / 'config/live/change_macros.cfg', encoding='utf-8')
    body = parser.get('gcode_macro ' + name, 'gcode')
    without_result = '\n'.join(line for line in body.splitlines()
        if 'SET_GCODE_VARIABLE MACRO=_WMP_TOOL_RETURN_BEGIN VARIABLE=completed_success ' not in line)
    assert analysis.macro_digest(without_result) == previous


@pytest.mark.parametrize('name,previous', [
    ('_UNLOCK_TOOL', '75c806836f674fc7784d2d23cd37ab3b1389f7f69ce139a55e45c3c88f75c399'),
    ('_LOCK_TOOL', '90e973e4dfd7d04a1cd467f509517d5f5edb12ac7cb8c35fc816b931b3683960')])
def test_coupling_region_changes_only_invocation_bookkeeping(name, previous):
    import re
    parser = configparser.RawConfigParser(strict=False)
    parser.read(ROOT / 'config/live/change_macros.cfg', encoding='utf-8')
    body = parser.get('gcode_macro ' + name, 'gcode')
    pattern = r'(?m)^[ \t]*\{% if printer\.wm_material is defined and printer\.openace is not defined and printer\.AFC is not defined %\}\n[ \t]*_WMP_COUPLING_(?:BEGIN|END)[^\n]*\n[ \t]*\{% endif %\}\n?'
    original, count = re.subn(pattern, '', body)
    assert count == 2 and analysis.macro_digest(original) == previous
