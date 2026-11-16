"""Exact prebuilt screen payload verification. Never loads the candidate library."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess

BUNDLE = 'client-preload/openace-compat/screen1113'
CURRENT_BUNDLE = 'client-preload/unified-screen1113'


def bundle_relative(root):
    # A present but incomplete new package must fail, never silently downgrade.
    path=Path(root)/CURRENT_BUNDLE
    return CURRENT_BUNDLE if path.exists() or path.is_symlink() else BUNDLE


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def elf_contract(path):
    data=Path(path).read_bytes()
    if len(data)<64 or data[:6]!=b'\x7fELF\x02\x01':raise ValueError('bundle must be ELF64 little endian')
    kind,machine=struct.unpack_from('<HH',data,16)
    if kind!=3 or machine!=183:raise ValueError('bundle must be an AArch64 shared object')
    phoff=struct.unpack_from('<Q',data,32)[0];size,count=struct.unpack_from('<HH',data,54)
    if size<56 or count>128 or phoff+size*count>len(data):raise ValueError('invalid ELF program headers')
    loads=[];dynamic=None
    for n in range(count):
        tag,flags,offset,address,_,filesz,_,_=struct.unpack_from('<IIQQQQQQ',data,phoff+n*size)
        if offset+filesz>len(data):raise ValueError('invalid ELF segment')
        if tag==1:loads.append((address,offset,filesz))
        if tag==2:dynamic=(offset,filesz)
    if dynamic is None:raise ValueError('missing ELF dynamic table')
    tags={};needed=[]
    for pos in range(dynamic[0],dynamic[0]+dynamic[1]-15,16):
        tag,value=struct.unpack_from('<QQ',data,pos)
        if tag==0:break
        if tag==1:needed.append(value)
        else:tags[tag]=value
    strings=None
    for address,offset,length in loads:
        if address<=tags.get(5,-1)<address+length:
            start=offset+tags[5]-address;end=start+tags.get(10,0)
            if end>offset+length:raise ValueError('invalid ELF string table')
            strings=data[start:end]
    if strings is None:raise ValueError('missing ELF string table')
    names=[]
    for index in needed:
        end=strings.find(b'\0',index)
        if end<index:raise ValueError('invalid ELF dependency')
        names.append(strings[index:end].decode('ascii'))
    return dict(machine='AArch64',nodelete=bool(tags.get(0x6ffffffb,0)&8),needed=sorted(names))


def load_bundle(root):
    root=Path(root);directory=root/bundle_relative(root)
    if directory.is_symlink():raise ValueError('screen package directory must not be a symlink')
    p=directory/'bundle.json'
    if not p.exists():
        if bundle_relative(root)==CURRENT_BUNDLE:raise ValueError('current screen package is incomplete')
        return None  # Existing C-only package remains valid.
    value=json.loads(p.read_text(encoding='utf-8'))
    if type(value) is not dict or set(value)!={'version','scope','profile','artifact','source_manifest_sha256','source_archive_sha256','legacy_c_sha256'} or type(value['version']) is not int or value['version']!=1:
        raise ValueError('unsupported screen bundle descriptor')
    if value['scope'] not in ('packaging-control-only','reviewed-delivery'):
        raise ValueError('unknown screen bundle delivery scope')
    profile=value['profile'];artifact=value['artifact']
    if type(profile) is not dict or set(profile)!={'firmware','sha256','size'} or profile['firmware']!='1.1.13':raise ValueError('unsupported native profile')
    if type(artifact) is not dict or set(artifact)!={'file','sha256','size','machine','nodelete','needed'}:raise ValueError('invalid screen artifact fields')
    if not isinstance(artifact['file'],str) or not re.fullmatch(r'[A-Za-z0-9_.-]+',artifact['file']):raise ValueError('invalid bundle artifact path')
    if type(artifact['nodelete']) is not bool or type(artifact['needed']) is not list or any(type(name) is not str for name in artifact['needed']):raise ValueError('invalid ELF dependency metadata')
    for expected in (profile['sha256'],artifact['sha256'],value['source_manifest_sha256'],value['source_archive_sha256'],value['legacy_c_sha256']):
        if not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected):raise ValueError('invalid bundle digest')
    for length in (profile['size'],artifact['size']):
        if type(length) is not int or length<=0:raise ValueError('invalid bundle length')
    binary=directory/artifact['file']
    if binary.is_symlink() or not binary.is_file() or binary.stat().st_size!=artifact['size'] or digest(binary)!=artifact['sha256']:
        raise ValueError('screen artifact bytes do not match sealed descriptor')
    if digest(directory/'source-inputs.json')!=value['source_manifest_sha256']:raise ValueError('screen source manifest changed')
    if digest(root/'client-preload/openace-compat/wmp_openace_compat.c')!=value['legacy_c_sha256']:raise ValueError('screen bundle does not preserve this legacy compat source')
    actual=elf_contract(binary)
    if actual!={key:artifact[key] for key in actual} or not actual['nodelete']:raise ValueError('screen ELF dependency/NODELETE contract changed')
    return value


def installer_source_files(root):
    """Explicit installation payload; never collect local credentials or caches."""
    root = Path(root)
    names = ['tools/deploy.py', 'tools/local_env.py', 'tools/preflight.py',
             'tools/preload_bundle.py', 'tools/factory_defaults.py', 'tools/reconcile_screen_config.py', 'utils/config_sync.py',
             'tools/touchscreen_settings.py', 'tools/touchscreen_transaction.py', 'tools/touchscreen_runtime.py',
             'tools/install_journal.py', 'tools/validate_klipper_config.py', 'tools/verify_head_guard.py',
             'tools/moonraker_directory_patch.py', 'tools/moonraker_http_error_patch.py',
             'tools/moonraker_directory_transaction.py',
             'tools/moonraker_directory_service.py', 'tools/moonraker_directory_install.py',
             'klipper_extras/wm_material.cfg', 'config/README.md',
             'scripts/install.sh', 'scripts/uninstall.sh',
             'device/wmp_screen.py', 'device/nginx-screen.conf',
             'device/timelapse-camera-fix.sh', 'device/wmp-screen.service',
             'device/wmp-timelapse-camera.service', 'device/www/index.html']
    names += ['tools/components/' + name + '.py' for name in
              ('__init__', 'config', 'material', 'moonraker', 'preload', 'shaper', 'touchscreen')]
    names += ['tools/shaper_backport.py', 'klipper_backport/input_shaper/README.md']
    names += ['klipper_backport/input_shaper/klippy/' + name for name in (
        'mathutil.py', 'chelper/kin_shaper.c', 'extras/input_shaper.py',
        'extras/resonance_tester.py', 'extras/shaper_calibrate.py', 'extras/shaper_defs.py')]
    names += ['client-preload/' + name + '/' + source for name, source in (
        ('openace-compat', 'wmp_openace_compat.c'),
        ('head-config-guard', 'wmp_head_config_guard.c'),
        ('wifi-fix', 'wmp_wififix.c'), ('fan-fix', 'wmp_fanfix.c'),
        ('recovery-fix', 'wmp_recoveryfix.c'), ('case-light', 'wmp_case_light.c'))]
    # Match the shipped baseline, not arbitrary files under config/live.
    names += ['config/live/' + name for name in (
        'change_extruder.cfg', 'change_macros.cfg', 'crowsnest.conf',
        'extruder0.cfg', 'extruder1.cfg', 'extruder2.cfg', 'extruder3.cfg',
        'fluidd.cfg', 'fz-wipe-nozzle.cfg', 'hub.cfg', 'load_cell.cfg',
        'macros.cfg', 'moonraker.conf', 'offset_calibrate.cfg', 'printer.cfg',
        'test_macro.cfg', 'timelapse.cfg', 'zru-s.cfg', 'case_light.cfg')]
    # Machine-owned wm_zru files intentionally remain on the destination printer.
    for name in names:
        path = root / name
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('installer input missing or outside source root: ' + name)
    return tuple(sorted(set(names)))


def current_source_files(root):
    """Rebuild and installation inputs with the matching backend baseline."""
    import ast
    root=Path(root)
    native=root/'client-preload/unified-ui/native'
    contract=native/'runtime_inputs.py'
    tree=ast.parse(contract.read_text(encoding='utf-8'))
    declarations=[node for node in tree.body if isinstance(node,ast.Assign)
                  and any(isinstance(target,ast.Name) and target.id=='RUNTIME_INPUTS'
                          for target in node.targets)]
    if len(declarations)!=1:raise ValueError('invalid runtime dependency contract')
    runtime=ast.literal_eval(declarations[0].value)
    if not isinstance(runtime,tuple) or not runtime or any(not isinstance(p,str) for p in runtime):
        raise ValueError('invalid runtime dependency paths')
    files=[root/name for name in installer_source_files(root)]
    for directory in (root/'client-preload/unified-ui',root/'client-preload/openace-compat/screen1113/source'):
        if not directory.is_dir():raise ValueError('unified source tree is missing')
        files.extend(p for p in directory.rglob('*') if p.is_file() and p.suffix in ('.hpp','.cpp','.h','.c','.sh','.py','.json'))
    for name in runtime:
        if name.startswith('/') or '..' in Path(name).parts or '\\' in name:
            raise ValueError('unsafe runtime dependency path')
        files.append(root/name)
    for required in ('bootstrap.cpp','build-arm.sh','manifest.py','build_id.py','runtime_inputs.py'):
        if not (native/required).is_file():raise ValueError('unified rebuild input missing: '+required)
    if any(not p.is_file() or p.is_symlink() or not p.resolve().is_relative_to(root.resolve()) for p in files):
        raise ValueError('unified rebuild input missing or outside source root')
    return tuple(sorted({p.relative_to(root).as_posix() for p in files}))


def native_source_files(root):
    """Repository-relative inputs sufficient for the pinned source rebuild."""
    root=Path(root)
    if bundle_relative(root)==CURRENT_BUNDLE:return current_source_files(root)
    directory=root/BUNDLE;source=directory/'source'
    if not source.is_dir():raise ValueError('native source tree is missing')
    files=[p for p in source.rglob('*') if p.is_file()]
    toolchain=directory/'toolchain'
    if not toolchain.is_dir():raise ValueError('native toolchain provenance is missing')
    files += [p for p in toolchain.rglob('*') if p.is_file()]
    files += [root/'client-preload/openace-compat/wmp_openace_compat.c',
              root/'tools/preload_bundle.py']
    files += [directory/name for name in ('build-offline-arm.sh','repack-source.py',
              'toolchain.json','README.md','vendor-provenance.json')]
    files += [directory/'review-history'/name for name in ('source-review.json',
              'native121-inputs.json','inherited-source-review.md','target-dependency-preflight.json')]
    if not files or any(not p.is_file() or p.is_symlink() for p in files):
        raise ValueError('native rebuild input is missing or is a symlink')
    return tuple(sorted(str(p.relative_to(root)).replace('\\','/') for p in files))


def verify_source_binding(root,bundle=None):
    """Local package completeness; never a target motion or runtime permission."""
    import tarfile
    from pathlib import PurePosixPath
    root=Path(root);bundle=load_bundle(root) if bundle is None else bundle
    if bundle is None:return
    directory=root/bundle_relative(root)
    inputs=json.loads((directory/'source-inputs.json').read_text(encoding='utf-8'))
    if type(inputs) is not dict or set(inputs)!=set(native_source_files(root)):
        raise ValueError('native source manifest does not cover the repository rebuild inputs')
    for name,want in inputs.items():
        path=PurePosixPath(name)
        if (not isinstance(name,str) or path.is_absolute() or '..' in path.parts
                or not isinstance(want,str) or not re.fullmatch('[0-9a-f]{64}',want)
                or digest(root/name)!=want):
            raise ValueError('native source input changed: '+str(name))
    archive=directory/'source.tar.gz'
    if (archive.is_symlink() or not archive.is_file()
            or digest(archive)!=bundle['source_archive_sha256']):
        raise ValueError('native source archive is missing or changed')
    seen=set()
    try:
        with tarfile.open(archive,'r:gz') as stream:
            for member in stream:
                if (not member.isfile() or member.name not in inputs or member.name in seen
                        or hashlib.sha256(stream.extractfile(member).read()).hexdigest()!=inputs[member.name]):
                    raise ValueError('native source archive member does not match its manifest')
                seen.add(member.name)
    except (tarfile.TarError,EOFError) as error:
        raise ValueError('native source archive is invalid: '+str(error)) from error
    if seen!=set(inputs):raise ValueError('native source archive omits rebuild inputs')


def exact_profile(bundle,client):
    p=Path(client)
    return p.is_file() and p.stat().st_size==bundle['profile']['size'] and digest(p)==bundle['profile']['sha256']


def validate_dependencies(bundle,code,output):
    if code or re.search(r'not found|undefined symbol|not a dynamic executable|statically linked',output,re.I):
        raise ValueError('screen dependencies/relocations unavailable: '+output[-4000:])
    for name in bundle['artifact']['needed']:
        if not re.search(re.escape(name)+r'\s+=>\s+/',output):raise ValueError('screen dependency unresolved: '+name)


def verify_dependencies(bundle,artifact):
    # glibc ldd trace/relocation mode, never dlopen or execute the candidate.
    result=subprocess.run(['ldd','-r',str(artifact)],capture_output=True,text=True,timeout=30,
                          env={k:v for k,v in os.environ.items() if k not in ('LD_PRELOAD','LD_LIBRARY_PATH')})
    validate_dependencies(bundle,result.returncode,result.stdout+'\n'+result.stderr)


def verify_staged(root,client):
    bundle=load_bundle(root)
    if bundle is None or not exact_profile(bundle,client):return False
    verify_dependencies(bundle,Path(root)/bundle_relative(root)/bundle['artifact']['file'])
    return True



def select_delivery(root,client,*,qualify=False):
    bundle=load_bundle(root)
    if type(qualify) is not bool:
        raise ValueError('qualification must be an explicit boolean')
    if qualify and (bundle is None or bundle_relative(root)!=CURRENT_BUNDLE
                    or bundle['scope']!='packaging-control-only'):
        raise ValueError('qualification requires the current packaging-control-only screen bundle')
    if bundle is None or not exact_profile(bundle,client):
        if qualify:raise ValueError('qualification requires the exact supported client')
        return False
    if bundle['scope']!='reviewed-delivery' and not qualify:
        raise ValueError('screen bundle is packaging-control-only; final reviewed UI artifact required before installation')
    verify_dependencies(bundle,Path(root)/bundle_relative(root)/bundle['artifact']['file'])
    return True


def preflight_script(root,client,*,qualify=False):
    """Disposable remote port; payload is exact local verified package bytes."""
    root=Path(root);bundle=load_bundle(root)
    if bundle is None:
        if qualify:raise ValueError('qualification requires a current screen bundle')
        return ''
    source_error=''
    try:verify_source_binding(root,bundle)
    except (ValueError,OSError,KeyError,TypeError) as error:source_error=str(error)
    files={}
    location=bundle_relative(root)
    for relative in (location+'/bundle.json',location+'/source-inputs.json',location+'/'+bundle['artifact']['file'],
                     'client-preload/openace-compat/wmp_openace_compat.c'):
        files[relative]=base64.b64encode((root/relative).read_bytes()).decode('ascii')
    return Path(__file__).read_text(encoding='utf-8')+'''\nimport tempfile\nwith tempfile.TemporaryDirectory(prefix='wmp-screen-check-') as temporary:\n for relative, encoded in %r.items():\n  target=Path(temporary)/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(base64.b64decode(encoded))\n bundle=load_bundle(temporary)\n if exact_profile(bundle,%r) and %r:raise ValueError('native source delivery unavailable: '+%r)\n enabled=select_delivery(temporary,%r,qualify=%r)\n print('screen bundle exact1113 dependency check passed' if enabled else 'screen unavailable on this profile; existing C fixes retained')\n'''%(files,client,source_error,source_error,client,qualify)


def verify_backend_helpers(root, home):
    """Read-only gate against the staged package, before publishing its UI.

    Configuration reconciliation is separate: never treat printer.cfg or saved
    filament data as files to overwrite to satisfy this binary-code contract.
    """
    root=Path(root)
    if bundle_relative(root)!=CURRENT_BUNDLE:return {}
    load_bundle(root)  # Validate the manifest digest before trusting its entries.
    inputs=json.loads((root/CURRENT_BUNDLE/'source-inputs.json').read_text(encoding='utf-8'))
    verified={}
    for name in ('wm_material.py','wmp_orca_profiles.py','wmp_nozzles.py','wmp_saved_variables.py', 'wmp_recovery_retirement.py','wmp_recovery.py','wmp_identification.py','wmp_case_light.py'):
        expected=inputs.get('klipper_extras/'+name)
        if not isinstance(expected,str) or not re.fullmatch('[0-9a-f]{64}',expected):
            raise ValueError('screen package omits backend helper: '+name)
        installed=Path(home)/'klipper/klippy/extras'/name
        if not installed.is_file() or digest(installed)!=expected:
            raise ValueError('screen/backend mismatch: '+name+
                             '; install matching config and material components before preload')
        verified[name]=expected
    return verified


CONFIG_BASELINES = ('config/live/macros.cfg', 'config/live/change_macros.cfg',
                    'config/live/offset_calibrate.cfg', 'config/live/fz-wipe-nozzle.cfg',
                    'config/live/printer.cfg', 'config/live/case_light.cfg',
                    'config/live/extruder0.cfg', 'config/live/extruder1.cfg',
                    'config/live/extruder2.cfg', 'config/live/extruder3.cfg')


def read_active_config(filename, include_paths=None, read_file=None):
    """Read includes in vendor Klipper order without importing printer modules."""
    import configparser
    import glob
    parser=configparser.RawConfigParser(strict=False, inline_comment_prefixes=(';', '#'))
    visiting=set()
    allowed=None if include_paths is None else {str(Path(p).absolute()) for p in include_paths}
    def visit(path):
        path=Path(path).absolute()
        if path in visiting:raise ValueError('recursive configuration include: '+str(path))
        visiting.add(path)
        buffer=[]
        def flush():
            if buffer:
                parser.read_string('\n'.join(buffer), source=str(path))
                buffer.clear()
        for raw in (path.read_text(encoding='utf-8') if read_file is None else read_file(path)).splitlines():
            line=raw.split('#',1)[0]
            match=configparser.RawConfigParser.SECTCRE.match(line)
            header=match and match.group('header')
            if header and header.startswith('include '):
                flush()
                pattern=str(path.parent/header[8:].strip())
                matches=sorted(glob.glob(pattern))
                if allowed is not None:
                    matches=[p for p in matches if str(Path(p).absolute()) in allowed]
                if allowed is None and not matches and not glob.has_magic(pattern):
                    raise ValueError('missing configuration include: '+pattern)
                for included in matches:visit(included)
            else:buffer.append(line)
        flush()
        visiting.remove(path)
    visit(filename)
    return parser


def config_contract_value(section, option, value):
    # These fixed sensor templates have no multiline string literals. A comment
    # removed by the target parser leaves an empty line; a callback-only merge
    # may omit it. Preserve every nonempty line (including Jinja/G-code order).
    sensor = section in {f'filament_switch_sensor filament{i}' for i in range(4)}
    delayed = section in {f'delayed_gcode delayed_pause{i}' for i in range(4)}
    if (sensor and option in ('runout_gcode', 'insert_gcode')) or (delayed and option == 'gcode'):
        return '\n'.join(line for line in value.strip().splitlines() if line.strip())
    return value.strip()


def optional_filament_hook_omissions(actual):
    """Only absent optional sensors with no retained consumer may be omitted."""
    omitted = set()
    for head in range(4):
        sensor = 'filament_switch_sensor filament%d' % head
        timer = 'delayed_gcode delayed_pause%d' % head
        if actual.has_section(sensor):
            continue
        for section in actual.sections():
            for option, value in actual.items(section):
                if section == timer:
                    if option == 'initial_duration' and float(value) > 0:
                        raise ValueError('Missing sensor required by active timer: ' + sensor + ' / ' + timer)
                    continue
                if sensor in value or re.search(r'\bID\s*=\s*delayed_pause%d\b' % head, value, re.IGNORECASE):
                    raise ValueError('Missing sensor required by retained configuration: ' + sensor + ' / ' + section + ' / ' + option)
        omitted.update((sensor, timer))
    return omitted


def verify_backend_config(root, home):
    """Require current executable macro bodies, retaining machine configuration."""
    import configparser
    root=Path(root)
    if bundle_relative(root)!=CURRENT_BUNDLE:return []
    load_bundle(root)
    inputs=json.loads((root/CURRENT_BUNDLE/'source-inputs.json').read_text(encoding='utf-8'))
    for name in CONFIG_BASELINES:
        path=root/name
        if name not in inputs or not path.is_file() or digest(path)!=inputs[name]:
            raise ValueError('screen configuration baseline missing or changed: '+name)
    # Follow the baseline printer's include order. Only these package-owned
    # files define the macro contract; hardware includes are printer-specific.
    expected=read_active_config(root/'config/live/printer.cfg',
                                include_paths=[root/name for name in CONFIG_BASELINES])
    actual=read_active_config(Path(home)/'printer_data/config/printer.cfg')
    for section in ('wm_material','wmp_recovery','wmp_case_light'):
        if not actual.has_section(section):raise ValueError('required active configuration missing: '+section)
    omitted = optional_filament_hook_omissions(actual)
    checked=[]
    for section in expected.sections():
        if section in omitted:
            continue
        filament_sensor = section in {f'filament_switch_sensor filament{i}' for i in range(4)}
        if not (section.startswith(('gcode_macro ', 'delayed_gcode ')) or section=='homing_override' or filament_sensor):
            continue
        if not actual.has_section(section):raise ValueError('required active macro missing: '+section)
        # Sensor callbacks are executable behavior too. Pins, debounce timing,
        # heater calibration and all other machine settings remain untouched.
        options = ('runout_gcode', 'insert_gcode', 'pause_on_runout') if filament_sensor else ('gcode','rename_existing','axes')
        for option in options:
            if expected.has_option(section,option):
                want=config_contract_value(section,option,expected.get(section,option))
                if not actual.has_option(section,option) or config_contract_value(section,option,actual.get(section,option))!=want:
                    raise ValueError('screen/macro mismatch: '+section+' / '+option)
        for option in expected.options(section):
            if option.startswith('variable_') and not actual.has_option(section,option):
                raise ValueError('macro variable missing: '+section+' / '+option)
        checked.append(section)
    return checked


def _sync_publication_file(path):
    with open(path, 'rb') as stream:
        os.fsync(stream.fileno())


def _sync_publication_directory(path):
    fd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _save_publication_journal(stage, rows):
    import tempfile
    fd, temporary = tempfile.mkstemp(prefix='.publication-', dir=stage)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(rows, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, stage/'publication.json')
        _sync_publication_directory(stage)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def restore_publication(stage):
    """Restore our publication only; preserve later edits and verify backups."""
    import shutil
    stage=Path(stage);journal=stage/'publication.json'
    if not journal.exists():
        raise ValueError('preload publication journal missing; restoration unconfirmed')
    if journal.is_symlink():raise ValueError('linked preload journal')
    rows=json.loads(journal.read_text(encoding='utf-8'))
    if not isinstance(rows,list) or not rows:raise ValueError('invalid preload journal')
    seen=set()
    def current(row):
        target=Path(row['target'])
        if target.is_symlink() or str(target.resolve())!=row['resolved_target']:
            raise ValueError('preload destination link changed: '+str(target))
        if target.exists() and not target.is_file():raise ValueError('non-regular preload destination')
        return digest(target) if target.exists() else None
    for row in rows:
        if not isinstance(row,dict) or set(row)!={'target','backup','before','after','resolved_target'}:
            raise ValueError('preload journal lacks verified restoration data')
        if not Path(row['target']).is_absolute() or row['target'] in seen:
            raise ValueError('invalid preload restoration destination')
        seen.add(row['target'])
        if not isinstance(row['after'],str) or not re.fullmatch('[0-9a-f]{64}',row['after']):
            raise ValueError('invalid preload publication hash')
        if row['backup'] is None:
            if row['before'] is not None:raise ValueError('missing preload backup')
        else:
            if not isinstance(row['backup'],str) or not re.fullmatch(r'previous-[0-9]+',row['backup']):
                raise ValueError('invalid preload backup path')
            saved=stage/row['backup']
            if saved.is_symlink() or digest(saved)!=row['before']:
                raise ValueError('preload backup mismatch: '+row['backup'])
        if current(row) not in (row['before'],row['after']):
            raise ValueError('concurrent edit; refusing preload rollback: '+row['target'])
    for row in reversed(rows):
        target=Path(row['target'])
        actual=current(row)
        if actual==row['before']:continue
        if actual!=row['after']:raise ValueError('preload changed during restoration: '+str(target))
        if row['backup'] is None:
            target.unlink()
        else:
            # A killed restore can leave its copy behind. Never reuse or delete
            # an unconfirmed leftover; a fresh exclusive file lets retries
            # recover from the verified backup without trusting that copy.
            import tempfile
            fd, name = tempfile.mkstemp(prefix='.'+target.name+'.wmp-restore-', dir=target.parent)
            os.close(fd)
            temp = Path(name)
            try:
                shutil.copy2(stage/row['backup'],temp)
                _sync_publication_file(temp)
                if current(row)!=row['after']:
                    raise ValueError('preload changed during restoration: '+str(target))
                os.replace(temp,target)
            finally:
                if temp.exists():temp.unlink()
        _sync_publication_directory(target.parent)
        if current(row)!=row['before']:raise ValueError('preload restoration readback mismatch')
    if any(current(row)!=row['before'] for row in rows):
        raise ValueError('preload changed before restoration completed')


def recovery_environment(home):
    """Resolve the material extra's record location from installed active config."""
    home = Path(home)
    config = read_active_config(home/'printer_data/config/printer.cfg')
    if not config.has_section('wm_material'):
        return {}
    ini = config.get('wm_material', 'ini_path', fallback='~/printer_data/config/tmt1.ini').strip()
    if ini.startswith('~/'):
        ini = str(home/ini[2:])
    if not ini.startswith('/') or any(ord(c) < 32 or ord(c) == 127 for c in ini):
        raise ValueError('wm_material ini_path must resolve to an absolute path')
    return {'WMP_RECOVERY_JOB_PATH': str(Path(ini).parent/'wmp_recovery_job.json'),
            'WMP_RECOVERY_JOB_REQUIRED': '1'}


def publish_stage(stage,libdir,dropin,recovery_env=None,start_backend=False,defaults_paths=None,require_guard=False):
    import shutil
    stage=Path(stage);libdir=Path(libdir);dropin=Path(dropin)
    journal=stage/'publication.json'
    if journal.exists() or journal.is_symlink():
        raise ValueError('preload publication journal already exists; recover the previous transaction first')
    outputs=json.loads((stage/'outputs.json').read_text(encoding='utf-8'))
    if not outputs or any(not re.fullmatch(r'libwmp_[A-Za-z0-9_-]+\.so',name) for name in outputs):raise ValueError('invalid staged library list')
    for name,row in outputs.items():
        if (not isinstance(row,dict) or set(row)!={'file','sha256'} or not re.fullmatch(r'[A-Za-z0-9_.-]+',row['file'])
                or not re.fullmatch('[0-9a-f]{64}',row['sha256']) or digest(stage/row['file'])!=row['sha256']):
            raise ValueError('staged library bytes changed before publication: '+name)
    duplicates=[p.name for p in libdir.glob('libwmp_openace*.so') if p.name!='libwmp_openace-compat.so']
    if duplicates:raise ValueError('ambiguous duplicate compat/screen library: '+', '.join(duplicates))
    libdir.mkdir(parents=True,exist_ok=True);dropin.parent.mkdir(parents=True,exist_ok=True)
    targets=[(libdir/name,stage/row['file']) for name,row in sorted(outputs.items())]
    libs=sorted({str(p) for p in libdir.glob('libwmp_*.so')}|{str(t) for t,_ in targets})
    environment = ''
    for key, value in sorted((recovery_env or {}).items()):
        if key not in ('WMP_RECOVERY_JOB_PATH', 'WMP_RECOVERY_JOB_REQUIRED') or not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('invalid recovery service environment')
        escaped = value.replace('\\', '\\\\').replace('"', '\\"').replace('%', '%%')
        environment += 'Environment="%s=%s"\n' % (key, escaped)
    # The managed screen suppresses the vendor's unconditional Klipper restart.
    # Some factory images leave Klipper disabled and rely on that screen call
    # for cold boot. A systemd start dependency replaces it without restarting
    # an already-running backend when only the screen is restarted.
    unit = '[Unit]\nWants=klipper.service\nAfter=klipper.service\n\n' if start_backend else ''
    if defaults_paths is not None:
        if not start_backend or set(defaults_paths) != {'helper', 'dropin', 'home'}:
            raise ValueError('Defaults ownership requires the managed backend dependency')
        for value in defaults_paths.values():
            if not isinstance(value, str) or not value.startswith('/') or any(c in value for c in '\n\r\0"%\\'):
                raise ValueError('Invalid defaults service path')
        helper = Path(defaults_paths['helper'])
        backend_dropin = Path(defaults_paths['dropin'])
        helper.parent.mkdir(parents=True, exist_ok=True)
        backend_dropin.parent.mkdir(parents=True, exist_ok=True)
        source = stage / 'factory_defaults.py'
        if not source.is_file() or source.is_symlink():
            raise ValueError('Missing staged defaults helper')
        defaults_unit = stage / 'prospective-defaults-dropin'
        defaults_unit.write_text('[Service]\nExecStartPre=/usr/bin/python3 "' + str(helper)
                                 + '" --home "' + defaults_paths['home'] + '"\n')
        targets.extend([(helper, source), (backend_dropin, defaults_unit)])
        environment += 'Environment="WMP_DEFAULTS_OWNER=1"\n'
    if require_guard and not any(Path(lib).name == 'libwmp_head-config-guard.so' for lib in libs):
        raise ValueError('The head-config-guard library is missing; screen restart blocked')
    environment += 'Environment="WMP_REQUIRE_HEAD_CONFIG_GUARD=1"\n'
    prospective=stage/'prospective-dropin';prospective.write_text(unit+'[Service]\nEnvironment="LD_PRELOAD=%s"\n'%' '.join(libs) + environment)
    targets.append((dropin,prospective));rows=[]
    for index,(target,source) in enumerate(targets):
        if target.is_symlink() or target.exists() and not target.is_file():raise ValueError('refusing non-regular preload destination: '+str(target))
        backup=None
        if target.exists():
            backup='previous-%d'%index
            shutil.copy2(target,stage/backup)
            _sync_publication_file(stage/backup)
        rows.append(dict(target=str(target.absolute()),backup=backup,
                         before=digest(stage/backup) if backup else None,
                         after=digest(source),resolved_target=str(target.resolve())))
    _save_publication_journal(stage,rows)
    try:
        for (target,source),row in zip(targets,rows):
            if (target.is_symlink() or str(target.resolve())!=row['resolved_target']
                    or (digest(target) if target.exists() else None)!=row['before']):
                raise ValueError('preload destination changed during publication: '+str(target))
            # An interrupted earlier stage may leave an unconfirmed copy.
            # Do not let it block a new, independently journaled installation.
            import tempfile
            fd, name = tempfile.mkstemp(prefix='.'+target.name+'.wmp-new-', dir=target.parent)
            os.close(fd)
            temp = Path(name)
            try:
                shutil.copy2(source,temp)
                _sync_publication_file(temp)
                if (target.is_symlink() or str(target.resolve())!=row['resolved_target']
                        or (digest(target) if target.exists() else None)!=row['before']):
                    raise ValueError('preload destination changed during publication: '+str(target))
                os.replace(temp,target)
            finally:
                if temp.exists():temp.unlink()
            _sync_publication_directory(target.parent)
            if digest(target)!=row['after']:raise ValueError('preload publication readback mismatch')
    except Exception:
        restore_publication(stage)
        raise
    return libs
