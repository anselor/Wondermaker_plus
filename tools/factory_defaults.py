"""Plan factory-default additions before the backend starts owning configuration.

The planner is pure; publication retains a durable rollback journal. Its caller
must stop and exclude writers for the entire transaction. This module does not
coordinate services. Existing values and formatting remain byte-for-byte intact.
"""
import ast
import configparser
import re


FILES = ('saved_variables.cfg', 'tmt1.ini')


def _parse(raw):
    if not isinstance(raw, bytes) or len(raw) > 2 * 1024 * 1024:
        raise ValueError('Missing or oversized defaults input')
    text = raw.decode('utf-8')
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read_string(text)
    if parser.defaults():
        raise ValueError('Inherited defaults require explicit migration')
    return text, parser


def plan_defaults(targets, factory):
    """Return both candidates, or fail before producing any publication plan."""
    if set(targets) != set(FILES) or set(factory) != set(FILES):
        raise ValueError('Both defaults files are required')
    planned = {}
    for name in FILES:
        text, current = _parse(targets[name])
        _, defaults = _parse(factory[name])
        additions = {}
        for section in defaults.sections():
            for key, value in defaults.items(section, raw=True):
                if not current.has_option(section, key):
                    # Do not emit ambiguous multiline additions into an existing
                    # document. The factory defaults currently use scalar lines.
                    if '\n' in value or '\r' in value:
                        raise ValueError('Multiline factory default requires explicit migration')
                    if name == 'saved_variables.cfg':
                        if section != 'Variables':
                            raise ValueError('Unexpected saved-variable defaults section')
                        ast.literal_eval(value)
                    additions.setdefault(section, []).append((key, value))
        if not additions:
            planned[name] = targets[name]
            continue
        newline = '\r\n' if '\r\n' in text else '\n'
        lines = text.splitlines(keepends=True)
        # Insert at each section end, preserving every original byte, including
        # comments and literal percent signs in managed records.
        ends = {}
        section = None
        for index, line in enumerate(lines):
            match = re.match(r'^\s*\[([^\]]+)\]', line)
            if match:
                if section is not None:
                    ends[section] = index
                section = match.group(1)
        if section is not None:
            ends[section] = len(lines)
        insertions = {}
        suffix = []
        for section, values in additions.items():
            content = ''.join(key + '=' + value + newline for key, value in values)
            if section in ends:
                insertions[ends[section]] = insertions.get(ends[section], '') + content
            else:
                suffix.append('[' + section + ']' + newline + content)
        result = ''
        for index in range(len(lines) + 1):
            if index in insertions:
                if result and not result.endswith(('\n', '\r')):
                    result += newline
                result += insertions[index]
            if index < len(lines):
                result += lines[index]
        if suffix:
            if result and not result.endswith(('\n', '\r')):
                result += newline
            result += ''.join(suffix)
        candidate = result.encode('utf-8')
        _, check = _parse(candidate)
        for section in current.sections():
            for key, value in current.items(section, raw=True):
                if check.get(section, key, raw=True) != value:
                    raise ValueError('Default insertion changed an existing value')
        for section, values in additions.items():
            for key, value in values:
                if check.get(section, key, raw=True) != value:
                    raise ValueError('Default insertion did not round-trip')
        planned[name] = candidate
    return planned


def _read_file(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('Defaults input must be a regular file: ' + str(path))
    with path.open('rb') as stream:
        data = stream.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        raise ValueError('Defaults input is too large')
    return data


def _atomic_write(path, data):
    import os
    import stat
    import tempfile
    previous = path.stat() if path.exists() else None
    fd, temporary = tempfile.mkstemp(prefix='.wmp-defaults-', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            os.fchmod(stream.fileno(), stat.S_IMODE(previous.st_mode) if previous else 0o600)
            if previous:
                os.fchown(stream.fileno(), previous.st_uid, previous.st_gid)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _journal(path, record, state):
    import json
    candidate = dict(record, state=state)
    _atomic_write(path, (json.dumps(candidate, sort_keys=True) + '\n').encode())
    record['state'] = state


def _load_journal(path):
    import json
    if path.is_symlink() or not path.is_file():
        raise ValueError('Invalid defaults journal')
    with path.open('rb') as stream:
        raw = stream.read(32 * 1024 * 1024 + 1)
    if len(raw) > 32 * 1024 * 1024:
        raise ValueError('Defaults journal is too large')
    record = json.loads(raw)
    if record.get('version') != 1 or record.get('state') not in ('prepared', 'complete', 'rolled-back'):
        raise ValueError('Unknown defaults journal')
    # Terminal records are history, not an ongoing input dependency. Their
    # payload is needed only when undoing a genuinely prepared transaction.
    if record['state'] != 'prepared':
        return record, None
    decoded = {}
    for field in ('before', 'factory', 'after'):
        if set(record[field]) != set(FILES):
            raise ValueError('Incomplete defaults journal')
        decoded[field] = {name: bytes.fromhex(value) for name, value in record[field].items()}
    if plan_defaults(decoded['before'], decoded['factory']) != decoded['after']:
        raise ValueError('Defaults journal candidate differs from its source')
    return record, decoded


def recover_defaults(directory, journal, admit):
    """Roll back an interrupted publication; never overwrite an unrelated edit."""
    from pathlib import Path
    directory, journal = Path(directory).resolve(), Path(journal).absolute()
    if journal.parent != directory or not re.fullmatch(r'\.wmp-defaults-[a-f0-9]{32}\.json', journal.name):
        raise ValueError('Invalid defaults journal path')
    record, decoded = _load_journal(journal)
    if record['state'] != 'prepared':
        return
    if admit() is not True:
        raise ValueError('Defaults recovery requires stopped writers')
    for name in FILES:
        if _read_file(directory / name) not in (decoded['before'][name], decoded['after'][name]):
            raise ValueError('Concurrent defaults edit needs inspection: ' + name)
    for name in reversed(FILES):
        if admit() is not True:
            raise ValueError('Defaults recovery admission changed')
        current = _read_file(directory / name)
        if current == decoded['before'][name]:
            continue
        if current != decoded['after'][name]:
            raise ValueError('Concurrent defaults edit needs inspection: ' + name)
        _atomic_write(directory / name, decoded['before'][name])
    if any(_read_file(directory / name) != decoded['before'][name] for name in FILES):
        raise ValueError('Defaults recovery verification failed')
    if admit() is not True:
        raise ValueError('Defaults recovery admission changed')
    _journal(journal, record, 'rolled-back')


def publish_defaults(directory, factory_directory, admit):
    """Publish under caller-held writer exclusion; retain exact recovery evidence.

    Admission is an additional check, not a substitute for service ownership or
    mutual exclusion. Pending transactions must be recovered explicitly first.
    """
    import uuid
    from pathlib import Path
    directory, factory_directory = Path(directory).resolve(), Path(factory_directory).resolve()
    for path in directory.glob('.wmp-defaults-*.json'):
        record, _ = _load_journal(path)
        if record['state'] == 'prepared':
            raise ValueError('Resolve interrupted defaults migration: ' + str(path))
    if admit() is not True:
        raise ValueError('Defaults migration requires stopped writers')
    before = {name: _read_file(directory / name) for name in FILES}
    factory = {name: _read_file(factory_directory / name) for name in FILES}
    after = plan_defaults(before, factory)
    if before == after:
        return None
    record = {'version': 1, 'state': 'prepared',
              **{field: {name: value.hex() for name, value in values.items()}
                 for field, values in (('before', before), ('factory', factory), ('after', after))}}
    journal = directory / ('.wmp-defaults-' + uuid.uuid4().hex + '.json')
    _journal(journal, record, 'prepared')
    expected = dict(before)
    for name in FILES:
        if admit() is not True:
            raise ValueError('Defaults migration admission changed')
        if any(_read_file(directory / key) != value for key, value in expected.items()):
            raise ValueError('Defaults snapshot changed')
        if before[name] != after[name]:
            _atomic_write(directory / name, after[name])
            expected[name] = after[name]
    if any(_read_file(directory / name) != after[name] for name in FILES):
        raise ValueError('Defaults publication verification failed')
    if admit() is not True:
        raise ValueError('Defaults migration admission changed')
    _journal(journal, record, 'complete')
    return journal


def startup_defaults(directory, factory_directory, admit, report):
    """Startup may continue only with verified unchanged or restored inputs."""
    from pathlib import Path
    directory = Path(directory)
    # A pre-existing interrupted transaction must be settled before taking the
    # usable baseline. Its current files might already be a partial publication.
    previous = set(directory.glob('.wmp-defaults-*.json'))
    for journal in sorted(previous):
        recover_defaults(directory, journal, admit)
    before = {name: _read_file(directory / name) for name in FILES}
    for name, raw in before.items():
        _, parsed = _parse(raw)
        if name == 'saved_variables.cfg':
            if parsed.sections() != ['Variables']:
                raise ValueError('Existing saved variables are not usable')
            for _, value in parsed.items('Variables', raw=True):
                ast.literal_eval(value)
    try:
        publish_defaults(directory, factory_directory, admit)
        return True
    except Exception as failure:
        try:
            created = sorted(set(directory.glob('.wmp-defaults-*.json')) - previous)
            if len(created) == 1:
                record, _ = _load_journal(created[0])
                if record['state'] == 'complete':
                    prior = {name: bytes.fromhex(record['before'][name]) for name in FILES}
                    factory = {name: bytes.fromhex(record['factory'][name]) for name in FILES}
                    after = {name: bytes.fromhex(record['after'][name]) for name in FILES}
                    if prior == before and plan_defaults(prior, factory) == after and all(_read_file(directory / name) == after[name] for name in FILES):
                        report('Defaults update completed; both files verified after reported error: ' + str(failure))
                        return True
            for journal in created:
                recover_defaults(directory, journal, admit)
            if any(_read_file(directory / name) != before[name] for name in FILES):
                raise ValueError('Original defaults inputs were not restored')
        except Exception as recovery:
            raise RuntimeError('Defaults migration repair required: ' + str(recovery)) from failure
        report('Defaults update skipped; original files verified unchanged/restored: ' + str(failure))
        return False


def main():
    """Klipper ExecStartPre entry; main process must not yet be running."""
    import argparse
    import fcntl
    import subprocess
    from pathlib import Path
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, required=True)
    args = parser.parse_args()
    directory = args.home / 'printer_data/config'
    factory = args.home / 'TM_T1/factory_settings'

    def stopped():
        result = subprocess.run(['systemctl', 'show', 'klipper.service',
                                 '--property=MainPID', '--value'],
                                check=True, capture_output=True, text=True, timeout=10)
        return result.stdout.strip() == '0'

    with (directory / '.wmp-defaults.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        import sys
        startup_defaults(directory, factory, stopped, lambda message: print(message, file=sys.stderr))


if __name__ == '__main__':
    main()
