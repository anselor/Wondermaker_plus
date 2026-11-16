import configparser

import pytest
from tools.factory_defaults import plan_defaults


def inputs():
    return ({'saved_variables.cfg': b"# keep\r\n[Variables]\r\ncurrent_extruder=3\r\nwmp_print_context={'name': '100% PLA'}\r\n",
             'tmt1.ini': b'[printer]\nmodel=2\n# custom\n[nozzle]\ntype0=1'},
            {'saved_variables.cfg': b'[Variables]\ncurrent_extruder=0\nnew_flag=1\n',
             'tmt1.ini': b'[printer]\nmodel=1\nnew_setting=4\n[nozzle]\ntype0=0\n[display]\nbrightness=80\n'})


def test_additions_preserve_managed_values_comments_and_line_endings():
    targets, factory = inputs()
    result = plan_defaults(targets, factory)
    assert result['saved_variables.cfg'] == targets['saved_variables.cfg'] + b'new_flag=1\r\n'
    assert result['tmt1.ini'] == b'[printer]\nmodel=2\n# custom\nnew_setting=4\n[nozzle]\ntype0=1\n[display]\nbrightness=80\n'
    assert plan_defaults(result, factory) == result


@pytest.mark.parametrize('defect', ['missing', 'invalid', 'literal', 'multiline', 'inheritance'])
def test_invalid_second_file_never_returns_partial_plan(defect):
    targets, factory = inputs()
    if defect == 'missing':
        del targets['tmt1.ini']
    elif defect == 'invalid':
        factory['tmt1.ini'] = b'not an ini file'
    elif defect == 'literal':
        factory['saved_variables.cfg'] = b'[Variables]\nnew_flag=not_a_literal\n'
    elif defect == 'multiline':
        factory['tmt1.ini'] = b'[printer]\nnew_value=one\n two\n'
    else:
        factory['tmt1.ini'] = b'[DEFAULT]\nmodel=1\n[printer]\n'
    before = dict(targets)
    with pytest.raises((ValueError, SyntaxError, configparser.Error)):
        plan_defaults(targets, factory)
    assert targets == before


def test_retained_factory_defaults_are_supported():
    from pathlib import Path
    from tools.factory_defaults import FILES
    root = Path(__file__).resolve().parents[1]
    directory = root / 'analysis/fw_1.1.13_payload/root/home/t13dp/TM_T1/factory_settings'
    factory = {name: (directory / name).read_bytes() for name in FILES}
    targets = {'saved_variables.cfg': b'[Variables]\n',
               'tmt1.ini': b'[printer]\nmodel=2\n'}
    result = plan_defaults(targets, factory)
    assert plan_defaults(result, factory) == result
    assert b'model=2\n' in result['tmt1.ini']


@pytest.fixture
def publication(tmp_path):
    targets, factory = inputs()
    destination, sources = tmp_path / 'config', tmp_path / 'factory'
    destination.mkdir()
    sources.mkdir()
    for name, raw in targets.items():
        (destination / name).write_bytes(raw)
        (sources / name).write_bytes(factory[name])
    return destination, sources, targets


@pytest.mark.parametrize('filename', ['saved_variables.cfg', 'tmt1.ini'])
@pytest.mark.parametrize('after_write', [False, True])
def test_interrupted_publication_recovers_exact_originals(publication, monkeypatch, filename, after_write):
    from tools import factory_defaults as migration
    destination, sources, originals = publication
    write = migration._atomic_write

    def fail(path, data):
        if path.name == filename:
            if after_write:
                write(path, data)
            raise SystemExit('power loss')
        write(path, data)

    with monkeypatch.context() as patch:
        patch.setattr(migration, '_atomic_write', fail)
        with pytest.raises(SystemExit):
            migration.publish_defaults(destination, sources, lambda: True)
    journal, = destination.glob('.wmp-defaults-*.json')
    with pytest.raises(ValueError, match='Resolve interrupted'):
        migration.publish_defaults(destination, sources, lambda: True)
    migration.recover_defaults(destination, journal, lambda: True)
    assert {n: (destination / n).read_bytes() for n in originals} == originals
    completed = migration.publish_defaults(destination, sources, lambda: True)
    assert completed is not None
    assert migration.publish_defaults(destination, sources, lambda: True) is None


def test_recovery_preserves_intervening_edit(publication, monkeypatch):
    from tools import factory_defaults as migration
    destination, sources, _ = publication
    write = migration._atomic_write

    def fail(path, data):
        if path.name == 'tmt1.ini':
            raise SystemExit('power loss')
        write(path, data)

    with monkeypatch.context() as patch:
        patch.setattr(migration, '_atomic_write', fail)
        with pytest.raises(SystemExit):
            migration.publish_defaults(destination, sources, lambda: True)
    (destination / 'tmt1.ini').write_bytes(b'[printer]\nmodel=1\n')
    before = {n: (destination / n).read_bytes() for n in migration.FILES}
    journal, = destination.glob('.wmp-defaults-*.json')
    with pytest.raises(ValueError, match='Concurrent defaults edit'):
        migration.recover_defaults(destination, journal, lambda: True)
    assert {n: (destination / n).read_bytes() for n in migration.FILES} == before


def test_refused_admission_leaves_no_journal_or_writes(publication):
    from tools import factory_defaults as migration
    destination, sources, originals = publication
    with pytest.raises(ValueError, match='stopped writers'):
        migration.publish_defaults(destination, sources, lambda: False)
    assert not list(destination.glob('.wmp-defaults-*.json'))
    assert {n: (destination / n).read_bytes() for n in originals} == originals


def test_changed_admission_keeps_durable_unresolved_transaction(publication):
    from tools import factory_defaults as migration
    destination, sources, originals = publication
    calls = 0

    def admit():
        nonlocal calls
        calls += 1
        return calls < 3

    with pytest.raises(ValueError, match='admission changed'):
        migration.publish_defaults(destination, sources, admit)
    journal, = destination.glob('.wmp-defaults-*.json')
    migration.recover_defaults(destination, journal, lambda: True)
    assert {n: (destination / n).read_bytes() for n in originals} == originals


def test_altered_journal_candidate_is_rejected_before_recovery(publication):
    import json
    from tools import factory_defaults as migration
    destination, sources, _ = publication
    journal = migration.publish_defaults(destination, sources, lambda: True)
    record = json.loads(journal.read_text())
    record['state'] = 'prepared'
    record['after']['tmt1.ini'] = b'[printer]\nmodel=99\n'.hex()
    journal.write_text(json.dumps(record))
    before = {n: (destination / n).read_bytes() for n in migration.FILES}
    with pytest.raises(ValueError, match='candidate differs'):
        migration.recover_defaults(destination, journal, lambda: True)
    assert {n: (destination / n).read_bytes() for n in migration.FILES} == before


@pytest.mark.parametrize('pid', ['0', '123'])
def test_service_entry_requires_backend_main_process_stopped(tmp_path, monkeypatch, pid):
    import subprocess
    import sys
    from types import SimpleNamespace
    from tools import factory_defaults as migration
    targets, factory = inputs()
    config = tmp_path / 'printer_data/config'
    sources = tmp_path / 'TM_T1/factory_settings'
    config.mkdir(parents=True)
    sources.mkdir(parents=True)
    for name in migration.FILES:
        (config / name).write_bytes(targets[name])
        (sources / name).write_bytes(factory[name])
    def query(command, **kwargs):
        assert command == ['systemctl', 'show', 'klipper.service', '--property=MainPID', '--value']
        return SimpleNamespace(stdout=pid + '\n')
    monkeypatch.setattr(subprocess, 'run', query)
    monkeypatch.setattr(sys, 'argv', ['factory_defaults.py', '--home', str(tmp_path)])
    if pid == '0':
        migration.main()
        assert {n: (config / n).read_bytes() for n in migration.FILES} == migration.plan_defaults(targets, factory)
    else:
        migration.main()  # no publication; usable originals permit normal startup
        assert {n: (config / n).read_bytes() for n in migration.FILES} == targets


def test_startup_missing_factory_preserves_usable_inputs(publication):
    from tools import factory_defaults as migration
    destination, sources, originals = publication
    (sources / 'tmt1.ini').unlink()
    messages = []
    assert migration.startup_defaults(destination, sources, lambda: True, messages.append) is False
    assert messages and 'original files verified' in messages[0]
    assert {name: (destination / name).read_bytes() for name in originals} == originals


@pytest.mark.parametrize('after_write', [False, True])
def test_startup_partial_failure_rolls_back_before_allowing_start(publication, monkeypatch, after_write):
    from tools import factory_defaults as migration
    destination, sources, originals = publication
    write = migration._atomic_write
    failed = False
    def fail(path, data):
        nonlocal failed
        if path.name == 'tmt1.ini' and not failed:
            failed = True
            if after_write:
                write(path, data)
            raise OSError('injected publication failure')
        write(path, data)
    monkeypatch.setattr(migration, '_atomic_write', fail)
    messages = []
    assert migration.startup_defaults(destination, sources, lambda: True, messages.append) is False
    assert {name: (destination / name).read_bytes() for name in originals} == originals
    assert messages and 'injected publication failure' in messages[0]


def test_startup_concurrent_partial_edit_requires_repair(publication, monkeypatch):
    from tools import factory_defaults as migration
    destination, sources, _ = publication
    write = migration._atomic_write
    def fail(path, data):
        if path.name == 'tmt1.ini':
            path.write_bytes(b'[printer]\nmodel=99\n')
            raise OSError('concurrent edit')
        write(path, data)
    monkeypatch.setattr(migration, '_atomic_write', fail)
    with pytest.raises(RuntimeError, match='repair required'):
        migration.startup_defaults(destination, sources, lambda: True, lambda _: None)
    assert (destination / 'tmt1.ini').read_bytes() == b'[printer]\nmodel=99\n'


def test_completed_defaults_history_does_not_revalidate_old_payload(publication):
    from tools import factory_defaults as migration
    destination, sources, _ = publication
    journal = destination / ('.wmp-defaults-' + 'a' * 32 + '.json')
    journal.write_text('{"version":1,"state":"complete","before":"obsolete"}')
    assert migration.startup_defaults(destination, sources, lambda: True, lambda _: None)


def test_startup_lost_completion_reply_verifies_both_published_files(publication, monkeypatch):
    from tools import factory_defaults as migration
    destination, sources, originals = publication
    write = migration._journal
    def fail(path, record, state):
        write(path, record, state)
        if state == 'complete':
            raise OSError('lost completion reply')
    monkeypatch.setattr(migration, '_journal', fail)
    messages = []
    assert migration.startup_defaults(destination, sources, lambda: True, messages.append)
    factory = {name: (sources / name).read_bytes() for name in originals}
    assert {name: (destination / name).read_bytes() for name in originals} == migration.plan_defaults(originals, factory)
    assert 'both files verified' in messages[0]
