"""Plan WM+ executable-config updates without replacing machine configuration.

Planning is read-only. Publication is explicit and never restarts services.
The managed include is last, before SAVE_CONFIG, matching the vendor parser's
linear include semantics. Hardware sections and custom macros are never copied
from repository baselines.
"""
import configparser
import glob
import hashlib
import json
import os
import re
from pathlib import Path
import stat
import tempfile

import preload_bundle as bundle

FILENAME = 'wmp-screen-runtime.cfg'
HEADER = '# WM+ managed screen runtime configuration (v1).\n'
OWNERSHIP = '# WM+ generated option hashes: '
BLOCK = ('\n# >>> WM+ screen runtime include\n[include ' + FILENAME + ']\n'
         '# <<< WM+ screen runtime include\n')
SAVE_MARKER = b'#*# <---------------------- SAVE_CONFIG ---------------------->'


class RollbackUnconfirmed(RuntimeError):
    pass


def owned_options(section):
    if section in {'filament_switch_sensor filament%d' % n for n in range(4)}:
        return ('runout_gcode', 'insert_gcode', 'pause_on_runout')
    if section.startswith(('gcode_macro ', 'delayed_gcode ')) or section == 'homing_override':
        return ('gcode', 'rename_existing', 'axes')
    return ()


def option_hash(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def generated_ownership(text):
    """Read per-option provenance; absent/invalid evidence never grants ownership."""
    records = [line[len(OWNERSHIP):] for line in text.splitlines() if line.startswith(OWNERSHIP)]
    if len(records) != 1:
        return None
    try:
        values = json.loads(records[0])
        if not isinstance(values, dict):
            return None
        for options in values.values():
            if not isinstance(options, dict) or any(not isinstance(value, str) or not re.fullmatch('[a-f0-9]{64}', value) for value in options.values()):
                return None
        return values
    except (ValueError, TypeError):
        return None


def plan(root, directory):
    root, directory = Path(root), Path(directory).absolute()
    main, managed = directory/'printer.cfg', directory/FILENAME
    reads = {}
    read_targets = {}
    include_matches = {}
    provenance_files = set()

    def read(path):
        path = Path(path).absolute()
        if os.path.commonpath((str(path), str(directory))) != str(directory):
            raise ValueError('Configuration include outside printer directory: ' + str(path))
        if path in (main, managed) and path.is_symlink():
            raise ValueError('Refuse linked writable configuration: ' + str(path))
        resolved = str(path.resolve())
        data = path.read_bytes()
        if str(path.resolve()) != resolved or (path in read_targets and resolved != read_targets[path]):
            raise ValueError('Configuration include target changed while planning: ' + str(path))
        if path in reads and data != reads[path]:
            raise ValueError('Configuration changed while planning: ' + str(path))
        reads[path] = data
        read_targets[path] = resolved
        text = data.decode('utf-8')
        if str(path.relative_to(directory)) in provenance_files:
            return text
        for raw in text.splitlines():
            match = configparser.RawConfigParser.SECTCRE.match(raw.split('#', 1)[0])
            header = match and match.group('header')
            if header and header.startswith('include '):
                pattern = os.path.normpath(str(path.parent / header[8:].strip()))
                if os.path.commonpath((pattern, str(directory))) != str(directory):
                    raise ValueError('Configuration include outside printer directory: ' + pattern)
                matches = sorted(glob.glob(pattern))
                if pattern in include_matches and matches != include_matches[pattern]:
                    raise ValueError('Configuration include membership changed while planning: ' + pattern)
                include_matches[pattern] = matches
        return text

    main_text = read(main)
    if managed.exists():
        if not read(managed).startswith(HEADER):
            raise ValueError('Refuse to replace an unowned ' + FILENAME)
    elif managed.is_symlink():
        raise ValueError('Refuse linked ' + FILENAME)
    if main_text.count(BLOCK) > 1:
        raise ValueError('Duplicate WM+ include block')
    without = main_text.replace(BLOCK, '')
    if '# >>> WM+ screen runtime include' in without or '# <<< WM+ screen runtime include' in without:
        raise ValueError('Edited or incomplete WM+ include block; review it before updating')

    actual = bundle.read_active_config(main, read_file=read)
    owners = sorted(set(actual.sections()) & {'openace', 'AFC'})
    if owners:
        raise ValueError('This screen release supports standalone WM+ only; active '
                         + ', '.join(owners)
                         + ' configuration is unsupported. No configuration was changed.')

    def underlying(path):
        text = read(path)
        return '' if path == managed else without if path == main else text

    base = bundle.read_active_config(main, read_file=underlying)
    expected = bundle.read_active_config(root/'config/live/printer.cfg',
                                        include_paths=[root/name for name in bundle.CONFIG_BASELINES])
    output = configparser.RawConfigParser()
    warnings = []
    omitted = bundle.optional_filament_hook_omissions(base)
    for section in sorted(omitted):
        if section.startswith('filament_switch_sensor '):
            warnings.append('Omitted optional filament runout hooks: ' + section + ' is not configured')
    for section in expected.sections():
        options = owned_options(section)
        if section in omitted or not options:
            continue
        if section.startswith('filament_switch_sensor ') and not base.has_option(section, 'switch_pin'):
            raise ValueError('Missing printer-owned sensor pin: ' + section)
        if base.has_option(section, 'rename_existing') and not expected.has_option(section, 'rename_existing'):
            raise ValueError('Unexpected existing command rename: ' + section)
        output.add_section(section)
        for option in options:
            if expected.has_option(section, option):
                value = expected.get(section, option)
                if not base.has_option(section, option) or bundle.config_contract_value(section, option, base.get(section, option)) != bundle.config_contract_value(section, option, value):
                    output.set(section, option, value)
        # Retain variable/timer values in original files. Defaults that only
        # existed in our previous generated file must survive its replacement.
        for option in expected.options(section):
            if option not in options and not base.has_option(section, option):
                value = actual.get(section, option) if actual.has_option(section, option) else expected.get(section, option)
                output.set(section, option, value)
        if not output.options(section):
            output.remove_section(section)
    for section in ('wmp_recovery', 'wm_material', 'wmp_case_light'):
        if not base.has_section(section):
            output.add_section(section)
            # Retain settings if a prior generated helper section had them.
            if section != 'wm_material' and actual.has_section(section):
                for option, value in actual.items(section):
                    output.set(section, option, value)

    # Three-way ownership: previous generated value, current value, new value.
    # Store only hashes of values we actually supply, never user-retained values.
    ownership = {section: {option: option_hash(value) for option, value in output.items(section)
                          if expected.has_option(section, option) and value == expected.get(section, option)
                          and (option in owned_options(section) or not actual.has_option(section, option))}
                 for section in output.sections()}
    if managed in reads:
        previous_text = reads[managed].decode('utf-8')
        provenance = generated_ownership(previous_text)
        if provenance is None:
            # Older releases kept a hashed publication artifact but no inline
            # ownership map. A completed, verified artifact is package evidence.
            for backup in sorted((path for path in directory.glob('.wmp-config-backup-*') if path.is_dir() and not path.is_symlink()), key=lambda path: path.stat().st_mtime_ns, reverse=True):
                try:
                    if (backup/'journal.json').is_symlink() or (backup/(FILENAME+'.after')).is_symlink():
                        continue
                    provenance_files.add(str((backup/'journal.json').relative_to(directory)))
                    journal = json.loads(read(backup/'journal.json'))
                    if journal.get('state') != 'published':
                        continue
                    entry = next(item for item in journal['files'] if item['file'] == FILENAME)
                    provenance_files.add(str((backup/(FILENAME+'.after')).relative_to(directory)))
                    artifact = read(backup/(FILENAME+'.after'))
                    if not artifact.startswith(HEADER) or hashlib.sha256(artifact.encode('utf-8')).hexdigest() != entry['after']:
                        continue
                    provenance = generated_ownership(artifact)
                    if provenance is None:
                        known = configparser.RawConfigParser(strict=False)
                        known.read_string(artifact)
                        provenance = {section: {option: option_hash(value) for option, value in known.items(section)
                                               if option in owned_options(section)}
                                      for section in known.sections() if not section.startswith('include ')}
                    break
                except (OSError, ValueError, KeyError, TypeError, StopIteration, configparser.Error):
                    continue
        provenance = provenance or {}
        previous = configparser.RawConfigParser(strict=False)
        previous.read_string(previous_text)
        for section in previous.sections():
            for option, value in previous.items(section):
                owned = provenance.get(section, {}).get(option)
                if owned == option_hash(value):
                    if output.has_option(section, option):
                        ownership.setdefault(section, {})[option] = option_hash(output.get(section, option))
                    continue  # unchanged package output can be updated/retired
                if section in omitted and section.startswith('filament_switch_sensor '):
                    raise ValueError('Edited sensor hook has no machine-owned sensor; restore its hardware section or remove the custom hook: ' + section + ' / ' + option)
                if output.has_option(section, option) and output.get(section, option) == value:
                    if owned:
                        ownership.get(section, {}).pop(option, None)
                    continue
                if not owned and base.has_option(section, option) and base.get(section, option) == value and not output.has_option(section, option):
                    continue  # already preserved in the underlying config
                if not output.has_section(section):
                    output.add_section(section)
                output.set(section, option, value)
                ownership.get(section, {}).pop(option, None)
                warnings.append('Preserved user or unproven managed setting: ' + section + ' / ' + option)

    # Migrate WM+'s former 50 mm finish default, including when it lives in
    # the underlying legacy config. Retain other operator-selected distances.
    section, option = 'gcode_macro PRINT_END', 'variable_bed_drop'
    source = output if output.has_option(section, option) else base
    if source.has_option(section, option):
        try:
            old_default = float(source.get(section, option)) == 50.0
        except ValueError:
            old_default = False
        if old_default:
            if not output.has_section(section):
                output.add_section(section)
            value = expected.get(section, option)
            output.set(section, option, value)
            ownership.setdefault(section, {})[option] = option_hash(value)

    # A shared hot-path rate replaces the former per-return variable. An
    # explicitly configured shared value wins; otherwise carry a non-default
    # legacy return speed forward. The old 200 mm/s default upgrades to 500.
    section, option = 'gcode_macro _WMP_XY_TRAVEL', 'variable_hot_travel_speed'
    legacy, old_option = 'gcode_macro _WMP_TOOL_RETURN_BEGIN', 'variable_return_speed'
    if not actual.has_option(section, option) and actual.has_option(legacy, old_option):
        value = actual.get(legacy, old_option)
        try:
            if float(value) in (200., 500.):
                value = expected.get(section, option)
        except ValueError:
            pass  # Preserve invalid custom values for explicit operator review.
        if not output.has_section(section):
            output.add_section(section)
        output.set(section, option, value)
        if value == expected.get(section, option):
            ownership.setdefault(section, {})[option] = option_hash(value)
        else:
            ownership.get(section, {}).pop(option, None)

    import io
    stream = io.StringIO()
    output.write(stream)
    material_include = '[include wm_material*.cfg]\n\n' if not base.has_section('wm_material') else ''
    generated = (HEADER + OWNERSHIP + json.dumps(ownership, sort_keys=True, separators=(',', ':')) + '\n'
                 + '# Generated behavior only; machine settings remain in their original files.\n'
                 + ''.join('# ' + warning + '\n' for warning in warnings) + '\n' + material_include + stream.getvalue()).encode()
    original_body, marker, calibration = without.encode().partition(SAVE_MARKER)
    updated_main = original_body + BLOCK.encode() + marker + calibration
    # SAVE_CONFIG may insert blank lines after our already-final include. Keep
    # those bytes when no executable configuration follows the owned block.
    # New sections/includes after it still require moving it to the end.
    current_body = main_text.partition(SAVE_MARKER.decode())[0]
    if BLOCK in current_body and not current_body.split(BLOCK, 1)[1].strip():
        updated_main = reads[main]
    changes = []
    if not output.sections() and managed not in reads and BLOCK not in main_text:
        return {'changes': [], 'include_matches': include_matches, 'read_targets': {str(path.relative_to(directory)): target for path, target in read_targets.items()}, 'read_hashes': {str(path.relative_to(directory)): hashlib.sha256(data).hexdigest() for path, data in reads.items()}, 'managed_sections': []}
    for path, data in ((managed, generated), (main, updated_main)):
        old = reads.get(path)
        if old != data:
            changes.append({'file': path.name, 'before': old, 'after': data})
    return {'changes': changes,
            'include_matches': include_matches,
            'read_targets': {str(path.relative_to(directory)): target for path, target in read_targets.items()},
            'read_hashes': {str(path.relative_to(directory)): hashlib.sha256(data).hexdigest() for path, data in reads.items()},
            'managed_sections': output.sections(), 'warnings': warnings,
            'provenance_files': sorted(provenance_files)}


def removal_plan(root, directory, material_only=False):
    """Disable provably owned behavior; preserve custom sections and calibration.

    This plans from current bytes, without an install receipt or stock snapshot.
    Remaining legacy/custom dependencies keep their helpers installed.
    """
    root, directory = Path(root), Path(directory).absolute()
    main, managed, material = (directory/name for name in ('printer.cfg', FILENAME, 'wm_material.cfg'))
    reads, targets, matches = {}, {}, {}
    def read(path):
        path = Path(path).absolute()
        if os.path.commonpath((str(path.resolve()), str(directory.resolve()))) != str(directory.resolve()):
            raise ValueError('Configuration include outside printer directory: ' + str(path))
        if path in (main, managed, material) and path.is_symlink():
            raise ValueError('Refuse linked writable configuration: ' + str(path))
        data = path.read_bytes()
        if path in reads and reads[path] != data:
            raise ValueError('Configuration changed while planning removal: ' + str(path))
        reads[path], targets[path] = data, str(path.resolve())
        text = data.decode('utf-8')
        for line in text.splitlines():
            header = configparser.RawConfigParser.SECTCRE.match(line.split('#', 1)[0])
            if header and header.group('header').startswith('include '):
                pattern = os.path.normpath(str(path.parent/header.group('header')[8:].strip()))
                if os.path.commonpath((pattern, str(directory))) != str(directory):
                    raise ValueError('Configuration include outside printer directory: ' + pattern)
                matches[pattern] = sorted(glob.glob(pattern))
        return text
    bundle.read_active_config(main, read_file=read)
    for path in (managed, material):
        if path.exists(): read(path)
    expected = bundle.read_active_config(root/'config/live/printer.cfg',
                                        include_paths=[root/name for name in bundle.CONFIG_BASELINES])
    candidate, retained = {}, []
    kept_definitions, removable_definitions = set(), {}
    helpers = {'wm_material', 'wmp_recovery', 'wmp_case_light'}
    def transform(path, remove_helpers=False):
        text = reads[path].decode('utf-8')
        chunks = re.split(r'(?m)(?=^[ \t]*\[[^\]\r\n]+\][ \t]*(?:[#;].*)?$)', text)
        output = []
        for chunk in chunks:
            header = configparser.RawConfigParser.SECTCRE.match(chunk)
            section = header.group('header') if header else None
            remove = False
            if section in helpers:
                remove = remove_helpers and (not material_only or section == 'wm_material')
            elif section and not material_only and path == managed and expected.has_section(section):
                previous = configparser.RawConfigParser(strict=False)
                previous.read_string(chunk)
                options = dict(previous.items(section))
                remove = bool(owned_options(section)) and all(
                    expected.has_option(section, key)
                    and bundle.config_contract_value(section, key, value)
                        == bundle.config_contract_value(section, key, expected.get(section, key))
                    for key, value in options.items())
                if remove and section.startswith(('gcode_macro ', 'delayed_gcode ')):
                    removable_definitions[section] = section.split(' ', 1)[1]
                if section in kept_definitions:
                    remove = False
                if not remove: retained.append(section)
            if remove:
                output.append('# Disabled WM+ section; original settings retained below.\n'
                              + ''.join('# ' + line for line in chunk.splitlines(keepends=True)))
            else:
                output.append(chunk)
        return ''.join(output).encode('utf-8')
    if managed in reads:
        if not reads[managed].startswith(HEADER.encode()):
            raise ValueError('Refuse removal from unowned ' + FILENAME)
        candidate[managed] = transform(managed)
    def proposed(path):
        path = Path(path).absolute()
        return candidate[path].decode('utf-8') if path in candidate else read(path)
    active = bundle.read_active_config(main, read_file=proposed)
    dependencies = []
    if removable_definitions:
        stock_paths = sorted((root/'config/stock').glob('*.cfg'))
        stock = (bundle.read_active_config(root/'config/stock/printer.cfg', include_paths=stock_paths)
                 if stock_paths else configparser.RawConfigParser())
        dynamic_callers = set()
        # Preserve definitions, not rewritten callers. Read all retained config
        # so custom includes and edited package macros have the same protection.
        # Unchanged stock dynamic commands already worked without this include.
        while True:
            needed = set()
            active_names = {section.casefold() for section in active.sections()}
            for section in active.sections():
                values = [value for key, value in active.items(section)
                          if key == 'gcode' or key.endswith('_gcode')]
                text = '\n'.join(values)
                commands = re.sub(r'{%.*?%}', '', text, flags=re.DOTALL)
                for definition, name in removable_definitions.items():
                    target = re.escape(name)
                    literal_call = (not expected.has_option(definition, 'rename_existing')
                                    and re.search(r'^\s*' + target + r'(?:\s|$)', commands, re.IGNORECASE | re.MULTILINE))
                    explicit_target = re.search(r'(?:\b(?:MACRO|ID)\s*=\s*|gcode_macro\s+)'
                                                + target + r'(?![A-Za-z0-9_])', text, re.IGNORECASE)
                    named_value = any(value.strip().strip('\'"').casefold() == name.casefold()
                                      for _, value in active.items(section))
                    if definition.casefold() not in active_names and (literal_call or explicit_target or named_value):
                        needed.add(definition)
                stock_text = '\n'.join(value for key, value in stock.items(section)
                    if key == 'gcode' or key.endswith('_gcode')) if stock.has_section(section) else None
                if text == stock_text:
                    continue
                for line in commands.splitlines():
                    command = line.strip()
                    if not command or command.startswith(('#', ';', '{%', '{ action_', '{action_')):
                        continue
                    first = command.split(None, 1)[0]
                    if ('{' in first or (first.upper() in ('UPDATE_DELAYED_GCODE', 'SET_GCODE_VARIABLE')
                            and re.search(r'\b(?:ID|MACRO)\s*=\s*[^\s]*\{', command, re.IGNORECASE))):
                        dynamic_callers.add(section)
                        needed.update(removable_definitions)
                        break
            new = needed - kept_definitions
            if not new:
                break
            kept_definitions.update(new)
            candidate[managed] = transform(managed)
            active = bundle.read_active_config(main, read_file=proposed)
        dependencies.extend(section + ' (dynamic command target; definitions retained)'
                            for section in sorted(dynamic_callers))
    for section in active.sections():
        if section in helpers: continue
        text = section + '\n' + '\n'.join(value for _, value in active.items(section))
        if re.search(r'\b(?:_?WMP_[A-Z0-9_]+|wm_material|wmp_recovery|wmp_case_light)\b', text, re.IGNORECASE):
            dependencies.append(section)
    if not dependencies:
        for path in (managed, material):
            if path in reads:
                candidate[path] = transform(path, remove_helpers=True)
    # Keep the include if custom executable sections remain. A comment-only file
    # can stay on disk as evidence but need not remain in the active include tree.
    if managed in candidate:
        parsed = configparser.RawConfigParser(strict=False)
        parsed.read_string(candidate[managed].decode('utf-8'))
        if not parsed.sections():
            candidate[main] = reads[main].replace(BLOCK.encode(), b'')
    # Helper sections in another user/legacy include also need their modules.
    final_active = bundle.read_active_config(main, read_file=proposed)
    dependencies.extend(section for section in helpers if final_active.has_section(section))
    changes = [{'file': path.name, 'before': reads[path], 'after': data}
               for path, data in candidate.items() if reads[path] != data]
    return {'changes': changes, 'include_matches': matches,
            'read_targets': {str(path.relative_to(directory)): value for path, value in targets.items()},
            'read_hashes': {str(path.relative_to(directory)): hashlib.sha256(value).hexdigest() for path, value in reads.items()},
            'managed_sections': [], 'retained_sections': sorted(set(retained)),
            'retained_dependencies': sorted(set(dependencies))}


def _atomic(path, data):
    metadata = path.stat() if path.exists() else None
    fd, temporary = tempfile.mkstemp(prefix='.wmp-config-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), stat.S_IMODE(metadata.st_mode) if metadata else 0o644)
            if metadata:
                os.fchown(stream.fileno(), metadata.st_uid, metadata.st_gid)
        os.replace(temporary, path)
        parent = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def publish(directory, planned, backup=None):
    """Publish only the reviewed two-file plan; no helper installs or restart.

    Retain a backup journal on success and failure. Never roll back over a
    concurrent edit. An ambiguous successful rename is handled by byte readback.
    """
    directory = Path(directory).absolute()

    def current(path):
        if path.is_symlink() or os.path.commonpath((str(path.resolve()), str(directory.resolve()))) != str(directory.resolve()):
            raise ValueError('Refuse linked configuration destination: ' + str(path))
        return path.read_bytes() if path.exists() else None

    for pattern, matches in planned['include_matches'].items():
        if sorted(glob.glob(pattern)) != matches:
            raise ValueError('Configuration include membership changed since review: ' + pattern)

    for name, digest in planned['read_hashes'].items():
        path = directory/name
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('Unsafe configuration dependency path')
        if str(path.resolve()) != planned['read_targets'][name]:
            raise ValueError('Configuration include target changed since review: ' + name)
        data = path.read_bytes() if path.exists() else None
        if data is None or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError('Configuration changed since review: ' + name)
    for change in planned['changes']:
        if change['file'] not in ('printer.cfg', FILENAME, 'wm_material.cfg'):
            raise ValueError('Unexpected configuration destination')
        if current(directory/change['file']) != change['before']:
            raise ValueError('Configuration destination changed since review: ' + change['file'])
    if not planned['changes']:
        return None
    if backup is None:
        backup = Path(tempfile.mkdtemp(prefix='.wmp-config-backup-', dir=directory))
    else:
        backup = Path(backup).absolute()
        if backup.parent != directory or not backup.name.startswith('.wmp-config-backup-'):
            raise ValueError('Unsafe configuration backup destination')
        backup.mkdir(mode=0o700, exist_ok=False)
    journal = {'state': 'prepared', 'files': []}
    for change in planned['changes']:
        if change['before'] is not None:
            _atomic(backup/(change['file']+'.before'), change['before'])
        # Retain the reviewed candidate too: a restarted process must not need
        # to reconstruct an interrupted transaction from newer source files.
        _atomic(backup/(change['file']+'.after'), change['after'])
        journal['files'].append({'file': change['file'], 'before': None if change['before'] is None else hashlib.sha256(change['before']).hexdigest(),
                                 'after': hashlib.sha256(change['after']).hexdigest()})
    _atomic(backup/'journal.json', json.dumps(journal, indent=2).encode())
    attempted = []
    try:
        for change in planned['changes']:
            path = directory/change['file']
            if current(path) != change['before']:
                raise ValueError('Configuration destination changed during publication: ' + change['file'])
            attempted.append(change)
            _atomic(path, change['after'])
            if current(path) != change['after']:
                raise ValueError('Configuration publication readback failed: ' + change['file'])
        journal['state'] = 'published'
        _atomic(backup/'journal.json', json.dumps(journal, indent=2).encode())
        return backup
    except Exception as failure:
        errors = []
        for change in reversed(attempted):
            path = directory/change['file']
            try:
                data = current(path)
                if data == change['before']:
                    continue
                if data != change['after']:
                    raise ValueError('Concurrent edit; refusing rollback over ' + change['file'])
                if change['before'] is None:
                    path.unlink()
                else:
                    _atomic(path, change['before'])
            except Exception as error:
                errors.append(str(error))
        journal.update(state='rollback-unconfirmed' if errors else 'rolled-back', error=str(failure), rollback_errors=errors)
        try:
            _atomic(backup/'journal.json', json.dumps(journal, indent=2).encode())
        except Exception as journal_error:
            if errors:
                raise RollbackUnconfirmed('Configuration rollback and journal need inspection: ' + str(backup)) from journal_error
            raise
        if errors:
            raise RollbackUnconfirmed('Configuration rollback needs inspection: ' + str(backup) + ': ' + '; '.join(errors)) from failure
        raise


def recover_interrupted(directory, backup):
    """Restore an interrupted publication from its durable reviewed bytes.

    Explicit caller action only; this does not admit operations or restart the
    printer. Old journals without candidates require their original plan.
    Successful publications must use ordinary reviewed restore, not this route.
    """
    directory = Path(directory).absolute()
    backup = Path(backup).absolute()
    if (backup.parent != directory or backup.is_symlink()
            or not backup.name.startswith('.wmp-config-backup-')):
        raise ValueError('Invalid configuration backup location')
    journal_path = backup/'journal.json'
    if journal_path.is_symlink():
        raise ValueError('Linked configuration journal')
    journal = json.loads(journal_path.read_text(encoding='utf-8'))
    if journal.get('state') not in ('prepared', 'restoring', 'rollback-unconfirmed'):
        raise ValueError('Configuration transaction is not interrupted')
    entries = journal.get('files')
    if not isinstance(entries, list) or not entries or len(entries) > 3:
        raise ValueError('Invalid configuration transaction entries')
    changes = []
    names = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {'file', 'before', 'after'}:
            raise ValueError('Invalid configuration transaction entry')
        name = entry['file']
        if name not in ('printer.cfg', FILENAME, 'wm_material.cfg') or name in names:
            raise ValueError('Unexpected configuration destination')
        names.add(name)
        change = {'file': name}
        for stage in ('before', 'after'):
            digest = entry[stage]
            if stage == 'before' and digest is None:
                change[stage] = None
                continue
            saved = backup/(name+'.'+stage)
            if saved.is_symlink():
                raise ValueError('Linked configuration transaction evidence')
            content = saved.read_bytes()
            if hashlib.sha256(content).hexdigest() != digest:
                raise ValueError('Configuration transaction evidence differs: ' + name)
            change[stage] = content
        changes.append(change)
    # restore preflights all current destinations before the first mutation,
    # checks again at each write, and journals uncertain rollback outcomes.
    restore(directory, {'changes': changes}, backup)
    return backup


def restore(directory, planned, backup):
    """Undo a successful publication using its reviewed plan and backup.

    This does not restart services. The caller must coordinate service recovery
    with the other installed components before admitting printer operations.
    """
    directory = Path(directory).absolute()
    if not planned['changes']:
        return
    backup = Path(backup).absolute()
    if (backup.parent != directory or backup.is_symlink()
            or not backup.name.startswith('.wmp-config-backup-')):
        raise ValueError('Invalid configuration backup location')
    journal_path = backup/'journal.json'
    if journal_path.is_symlink():
        raise ValueError('Linked configuration journal')
    journal = json.loads(journal_path.read_text(encoding='utf-8'))
    expected = []
    names = set()
    for change in planned['changes']:
        name = change['file']
        if name not in ('printer.cfg', FILENAME, 'wm_material.cfg') or name in names:
            raise ValueError('Unexpected configuration destination')
        names.add(name)
        expected.append({'file': name,
                         'before': None if change['before'] is None else hashlib.sha256(change['before']).hexdigest(),
                         'after': hashlib.sha256(change['after']).hexdigest()})
        if change['before'] is not None:
            saved = backup/(name+'.before')
            if saved.is_symlink() or saved.read_bytes() != change['before']:
                raise ValueError('Configuration backup differs from reviewed plan: ' + name)
    if (journal.get('files') != expected or journal.get('state') not in
            ('prepared', 'published', 'restoring', 'rollback-unconfirmed', 'rolled-back')):
        raise ValueError('Configuration journal differs from reviewed publication')

    def current(name):
        path = directory/name
        if path.is_symlink() or path.resolve().parent != directory.resolve():
            raise ValueError('Refuse linked configuration destination: ' + name)
        return path.read_bytes() if path.exists() else None

    # Refuse an already-visible conflict before making even a partial restore.
    for change in planned['changes']:
        if current(change['file']) not in (change['before'], change['after']):
            raise RollbackUnconfirmed('Concurrent edit; refusing rollback over ' + change['file'])
    journal['state'] = 'restoring'
    _atomic(journal_path, json.dumps(journal, indent=2).encode())
    try:
        for change in reversed(planned['changes']):
            name = change['file']
            data = current(name)
            if data == change['before']:
                continue
            if data != change['after']:
                raise ValueError('Concurrent edit; refusing rollback over ' + name)
            if change['before'] is None:
                (directory/name).unlink()
                parent = os.open(directory, os.O_RDONLY)
                try:
                    os.fsync(parent)
                finally:
                    os.close(parent)
            else:
                _atomic(directory/name, change['before'])
            if current(name) != change['before']:
                raise ValueError('Configuration restoration readback failed: ' + name)
        for change in planned['changes']:
            if current(change['file']) != change['before']:
                raise ValueError('Configuration changed during restoration: ' + change['file'])
        journal['state'] = 'rolled-back'
        _atomic(journal_path, json.dumps(journal, indent=2).encode())
    except Exception as failure:
        journal.update(state='rollback-unconfirmed', error=str(failure))
        try:
            _atomic(journal_path, json.dumps(journal, indent=2).encode())
        finally:
            raise RollbackUnconfirmed('Configuration restoration needs inspection: ' + str(backup)) from failure


def remote_script(root, directory, reviewed=None, *, action='publish', backup=None):
    """Ship source via stdin; planning uses only a disposable baseline directory."""
    root = Path(root)
    if (action not in ('publish', 'restore', 'recover', 'remove-plan', 'material-remove-plan')
            or (action == 'restore' and reviewed is None)
            or (action == 'recover' and (reviewed is not None or backup is None))):
        raise ValueError('Invalid configuration transaction action')
    sources = {name: (root / 'tools' / (name + '.py')).read_text(encoding='utf-8')
               for name in ('preload_bundle', 'reconcile_screen_config')}
    script = '''import json, pathlib, sys, tempfile, types
for name, source in %r.items():
    module = types.ModuleType(name)
    sys.modules[name] = module
    exec(compile(source, name + '.py', 'exec'), module.__dict__)
r = sys.modules['reconcile_screen_config']
directory = pathlib.Path(%r)
''' % (sources, str(directory))
    if action == 'recover':
        return script + '''try:
    r.recover_interrupted(directory, %r)
    print(json.dumps({'state': 'rolled-back', 'backup': %r}))
except Exception as error:
    print(json.dumps({'state': 'rollback-unconfirmed', 'error': str(error)}))
''' % (str(backup), str(backup))
    if reviewed is not None:
        script += '''planned = json.loads(%r)
for change in planned['changes']:
    for key in ('before', 'after'):
        if change[key] is not None:
            change[key] = bytes.fromhex(change[key])
''' % json.dumps(reviewed)
        if action == 'restore':
            return script + '''try:
    r.restore(directory, planned, %r)
    print(json.dumps({'state': 'rolled-back'}))
except Exception as error:
    print(json.dumps({'state': 'rollback-unconfirmed', 'error': str(error)}))
''' % (str(backup) if backup is not None else None)
        return script + '''
try:
    backup = r.publish(directory, planned, %r)
    print(json.dumps({'state': 'published', 'backup': str(backup) if backup else None}))
except Exception as error:
    print(json.dumps({'state': 'failed', 'rollback_confirmed': not isinstance(error, r.RollbackUnconfirmed), 'error': str(error)}))
''' % (str(backup) if backup is not None else None)
    baselines = {name: (root / name).read_text(encoding='utf-8') for name in bundle.CONFIG_BASELINES}
    if action in ('remove-plan', 'material-remove-plan'):
        baselines.update({str(path.relative_to(root)): path.read_text(encoding='utf-8')
                          for path in (root/'config/stock').glob('*.cfg')})
    return script + '''with tempfile.TemporaryDirectory(prefix='wmp-config-plan-') as temporary:
    root = pathlib.Path(temporary)
    for name, text in %r.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
    planned = r.removal_plan(root, directory, material_only=%r) if %r else r.plan(root, directory)
texts = {name: (directory / name).read_text(encoding='utf-8') for name in planned['read_hashes']
         if name not in planned.get('provenance_files', [])}
for change in planned['changes']:
    texts[change['file']] = change['after'].decode('utf-8')
    for key in ('before', 'after'):
        if change[key] is not None:
            change[key] = change[key].hex()
print(json.dumps({'plan': planned, 'texts': texts}))
''' % (baselines, action == 'material-remove-plan', action in ('remove-plan', 'material-remove-plan'))
