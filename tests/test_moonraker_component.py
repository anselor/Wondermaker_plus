"""Actual component payloads against disposable source and a modeled service.

Filesystem transactions and subprocess boundaries are real; no printer, SSH,
HTTP server, systemd daemon or service restart is involved.
"""
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from test_deploy import deploy
from components import moonraker
from install_journal import Journal

SOURCE = (Path(__file__).parent / 'fixtures/moonraker_directory_compat.py').read_bytes()
HTTP_SOURCE = (Path(__file__).parent / 'fixtures/moonraker_http_error_compat.py').read_bytes()


@pytest.fixture
def printer(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    target = home / 'moonraker/moonraker/components/file_manager/file_manager.py'
    target.parent.mkdir(parents=True)
    target.write_bytes(SOURCE)
    app = target.parent.parent / 'application.py'
    app.write_bytes(HTTP_SOURCE)
    http_state = home / 'wmp/backups/moonraker-http-error-managed'
    python = home / 'moonraker-env/bin/python'
    python.parent.mkdir(parents=True)
    python.symlink_to(sys.executable)
    state = home / 'wmp/backups/moonraker-directory-managed'
    events = tmp_path / 'events'
    journal = Journal(tmp_path / 'host-journal.json')
    journal.create('test', 'test', ['moonraker']); journal.begin('moonraker')
    ctx = SimpleNamespace(user='test', moonraker_selected=True, moonraker_implicit=False,
                          rollback_backend=SimpleNamespace(journal=journal, blocked=False),
                          DeployError=RuntimeError)
    fake = '''
class FakeService:
 def event(self,name):
  with open(%r,'a') as f:f.write(name+'\\n')
 def inspect(self):
  assert not Path(%r).exists(), 'service is stopped'
  self.event('inspect');return {'session':'unchanged'}
 def stop(self):self.event('stop');Path(%r).touch()
 def start(self):
  self.event('start');Path(%r).unlink(missing_ok=True)
 def verify(self,baseline):
  self.event('verify');assert baseline=={'session':'unchanged'}
MoonrakerService=FakeService
''' % (str(events), str(home/'service-stopped'), str(home/'service-stopped'), str(home/'service-stopped'))
    def remote(ctx, code, **kwargs):
        # Module imports remain real. Inject only the service I/O boundary after
        # those imports, before executing the component's transaction payload.
        marker = 'target=Path('
        assert marker in code
        code = code.replace(marker, fake + '\n' + marker, 1)
        code = code.replace('/home/test', str(home))
        result = subprocess.run([sys.executable, '-I', '-'], input=code,
                                text=True, capture_output=True)
        if result.returncode:
            raise RuntimeError(result.stderr)
        return result.stdout
    monkeypatch.setattr(moonraker.checks, 'remote', remote)
    monkeypatch.setattr(moonraker.checks, 'require_paths', lambda *args, **kwargs: None)
    return SimpleNamespace(home=home, target=target, state=state, events=events,
                           ctx=ctx, journal=journal, remote=remote, app=app, http_state=http_state)


def test_clean_install_receipt_and_restore(printer):
    p = printer
    moonraker.preflight(p.ctx)
    assert not p.state.exists()  # Preflight does not create receipt/lock/backup.
    receipt = moonraker.install(p.ctx)
    assert [e['before'] for e in receipt['patches']] == ['original', 'original']
    assert p.target.read_bytes() != SOURCE
    assert p.app.read_bytes() != HTTP_SOURCE
    assert p.journal.recovery_receipts() == [('moonraker', receipt)]
    moonraker.rollback(p.ctx, receipt)
    assert p.target.read_bytes() == SOURCE
    assert p.app.read_bytes() == HTTP_SOURCE
    assert p.events.read_text().splitlines().count('stop') == 4


def test_preexisting_patch_is_preserved_by_later_install_rollback(printer):
    p = printer
    moonraker.install(p.ctx)
    p.journal.complete_component('moonraker', {'done': True})
    p.ctx.rollback_backend.journal = None
    prior = p.target.read_bytes()
    stops = p.events.read_text().splitlines().count('stop')
    receipt = moonraker.install(p.ctx)
    assert [e['before'] for e in receipt['patches']] == ['installed', 'installed']
    moonraker.rollback(p.ctx, receipt)
    assert p.target.read_bytes() == prior
    assert p.events.read_text().splitlines().count('stop') == stops


def test_lost_publication_reply_recovers_from_prepared_host_receipt(printer, monkeypatch):
    p = printer
    lost = [False]
    def remote(ctx, code, **kwargs):
        result = p.remote(ctx, code, **kwargs)
        if 'lifecycle.execute(target,state,MoonrakerService())' in code and not lost[0]:
            lost[0] = True
            assert [e['before'] for e in p.journal.recovery_receipts()[0][1]['patches']] == ['original', 'original']
            raise OSError('SSH reply lost after successful publication')
        return result
    monkeypatch.setattr(moonraker.checks, 'remote', remote)
    with pytest.raises(OSError, match='SSH reply lost'):
        moonraker.install(p.ctx)
    assert p.target.read_bytes() == SOURCE
    assert not p.ctx.rollback_backend.blocked


def test_foreign_receipt_and_unknown_source_do_not_mutate(printer):
    p = printer
    with pytest.raises(RuntimeError, match='Invalid Moonraker'):
        moonraker.rollback(p.ctx, {'kind': 'moonraker-directory', 'state': '/other', 'before': 'original'})
    p.target.write_bytes(b'unknown Moonraker source')
    moonraker.preflight(p.ctx)
    assert moonraker.install(p.ctx) == {'kind': 'moonraker-directory', 'skipped': True}
    assert not p.state.exists()
    assert p.target.read_bytes() == b'unknown Moonraker source'


def test_implicit_legacy_screen_does_not_require_patch(printer, monkeypatch):
    p = printer
    p.ctx.moonraker_implicit = True
    monkeypatch.setattr(moonraker.preload_bundle, 'bundle_relative', lambda root: moonraker.preload_bundle.BUNDLE)
    moonraker.preflight(p.ctx)
    assert moonraker.install(p.ctx) == {'kind': 'moonraker-directory', 'skipped': True}
    assert not p.state.exists()
    assert not p.events.exists()


def test_loss_before_backup_preparation_still_has_recoverable_host_receipt(printer, monkeypatch):
    p = printer
    def interrupted(ctx, code, **kwargs):
        if 'tx.prepare(target,state)' in code:
            raise KeyboardInterrupt('process died before backup creation')
        return p.remote(ctx, code, **kwargs)
    monkeypatch.setattr(moonraker.checks, 'remote', interrupted)
    with pytest.raises(KeyboardInterrupt):
        moonraker.install(p.ctx)
    assert not p.state.exists()
    receipt = p.journal.recovery_receipts()[0][1]
    monkeypatch.setattr(moonraker.checks, 'remote', p.remote)
    moonraker.rollback(p.ctx, receipt)
    assert p.target.read_bytes() == SOURCE
    assert 'stop' not in p.events.read_text().splitlines()


def test_uninstall_all_does_not_touch_unmanaged_legacy_source(printer):
    p = printer
    p.target.write_bytes(b'legacy Moonraker version outside patch scope')
    moonraker.uninstall(p.ctx)
    assert p.target.read_bytes() == b'legacy Moonraker version outside patch scope'
    assert not p.state.exists()
    assert not p.events.exists()


@pytest.mark.parametrize('matches', [True, False])
def test_implicit_current_bundle_requires_exact_target_client(monkeypatch, matches):
    ctx = SimpleNamespace(user='test', moonraker_implicit=True)
    monkeypatch.setattr(moonraker.preload_bundle, 'bundle_relative', lambda root: moonraker.preload_bundle.CURRENT_BUNDLE)
    monkeypatch.setattr(moonraker.preload_bundle, 'load_bundle', lambda root: {'profile': {'sha256': 'reviewed-client'}})
    calls = []
    def remote(ctx, code, **kwargs):
        calls.append(code)
        return json.dumps(matches)
    monkeypatch.setattr(moonraker.checks, 'remote', remote)
    assert moonraker._enabled(ctx) is matches
    assert len(calls) == 1 and '/home/test/TM_T1/bin/client' in calls[0]
    assert 'reviewed-client' in calls[0]


@pytest.mark.parametrize('lost_after_publish', [False, True])
def test_second_patch_failure_restores_both_prior_states(printer, monkeypatch, lost_after_publish):
    p = printer
    failed = [False]
    def remote(ctx, code, **kwargs):
        is_http_install = 'application.py' in code and moonraker.INSTALL in code
        if is_http_install and not failed[0]:
            failed[0] = True
            # The host journal must already cover both files.
            receipt = p.journal.recovery_receipts()[0][1]
            assert {e['patch'] for e in receipt['patches']} == {'directory', 'http-error'}
            if lost_after_publish:
                p.remote(ctx, code, **kwargs)
            raise OSError('HTTP patch install reply unavailable')
        return p.remote(ctx, code, **kwargs)
    monkeypatch.setattr(moonraker.checks, 'remote', remote)
    with pytest.raises(OSError, match='reply unavailable'):
        moonraker.install(p.ctx)
    assert p.target.read_bytes() == SOURCE
    assert p.app.read_bytes() == HTTP_SOURCE
    assert not p.ctx.rollback_backend.blocked


@pytest.mark.parametrize('preexisting', ['directory', 'http-error'])
def test_mixed_prior_states_rollback_preserves_existing_patch(printer, preexisting):
    p = printer
    moonraker._remote(p.ctx, moonraker.INSTALL, sudo=True, patch=preexisting)
    prior = (p.target.read_bytes(), p.app.read_bytes())
    receipt = moonraker.install(p.ctx)
    assert {e['patch']: e['before'] for e in receipt['patches']} == {
        patch: 'installed' if patch == preexisting else 'original'
        for patch in moonraker.PATCHES}
    moonraker.rollback(p.ctx, receipt)
    assert (p.target.read_bytes(), p.app.read_bytes()) == prior


def test_old_directory_receipt_does_not_remove_http_patch(printer):
    p = printer
    moonraker.install(p.ctx)
    http = p.app.read_bytes()
    moonraker.rollback(p.ctx, {'kind': 'moonraker-directory',
                              'state': moonraker._paths(p.ctx)[2], 'before': 'original'})
    assert p.target.read_bytes() == SOURCE
    assert p.app.read_bytes() == http


def test_invalid_second_receipt_refused_before_first_mutation(printer):
    p = printer
    receipt = moonraker.install(p.ctx)
    before = (p.target.read_bytes(), p.app.read_bytes(), p.events.read_text())
    receipt['patches'][1]['state'] = '/foreign'
    with pytest.raises(RuntimeError, match='Invalid Moonraker'):
        moonraker.rollback(p.ctx, receipt)
    assert (p.target.read_bytes(), p.app.read_bytes(), p.events.read_text()) == before


def test_uninstall_restores_both_managed_sources(printer):
    p = printer
    moonraker.install(p.ctx)
    moonraker.uninstall(p.ctx)
    assert p.target.read_bytes() == SOURCE
    assert p.app.read_bytes() == HTTP_SOURCE


def test_recover_first_patch_stop_before_second_patch_readiness(printer, monkeypatch):
    p = printer
    stopped = [False]
    def interrupted(ctx, code, **kwargs):
        if moonraker.INSTALL in code and not stopped[0]:
            stopped[0] = True
            injection = '''
original_stop = MoonrakerService.stop
def stop_then_die(self):
    original_stop(self)
    raise KeyboardInterrupt('process loss after service stop')
MoonrakerService.stop = stop_then_die
'''
            try:
                p.remote(ctx, code.replace('tx.prepare(target,state)', injection + '\ntx.prepare(target,state)'), **kwargs)
            except RuntimeError as error:
                assert 'process loss after service stop' in str(error)
                raise KeyboardInterrupt('host lost with stopped remote service')
            pytest.fail('Remote interruption did not occur')
        return p.remote(ctx, code, **kwargs)
    monkeypatch.setattr(moonraker.checks, 'remote', interrupted)
    with pytest.raises(KeyboardInterrupt):
        moonraker.install(p.ctx)
    assert (p.home/'service-stopped').exists()
    assert not p.http_state.exists()
    receipt = p.journal.recovery_receipts()[0][1]
    monkeypatch.setattr(moonraker.checks, 'remote', p.remote)
    moonraker.rollback(p.ctx, receipt)
    assert not (p.home/'service-stopped').exists()
    assert p.target.read_bytes() == SOURCE
    assert p.app.read_bytes() == HTTP_SOURCE


def test_vendor_rebaseline_through_normal_preflight_install_and_rollback(printer):
    p=printer
    moonraker.install(p.ctx)
    p.ctx.rollback_backend.journal=None
    old_service=(p.state/'service.json').read_bytes()
    updated=SOURCE+b'\n# independently updated vendor code outside reviewed methods\n'
    p.target.write_bytes(updated)
    moonraker.preflight(p.ctx)
    assert p.target.read_bytes()==updated and not list(p.state.glob('retired-*'))
    receipt=moonraker.install(p.ctx)
    assert receipt['patches'][0]['before']=='original'
    archive=next(p.state.glob('retired-*'))
    assert (archive/'service.json').read_bytes()==old_service
    moonraker.rollback(p.ctx,receipt)
    assert p.target.read_bytes()==updated


def test_loss_before_new_baseline_preparation_preserves_vendor_update_on_recovery(printer, monkeypatch):
    p=printer
    moonraker.install(p.ctx)
    updated=SOURCE+b'\n# new vendor baseline\n'
    p.target.write_bytes(updated)
    def interrupted(ctx,code,**kwargs):
        if moonraker.INSTALL in code:raise KeyboardInterrupt('before new prepare')
        return p.remote(ctx,code,**kwargs)
    monkeypatch.setattr(moonraker.checks,'remote',interrupted)
    with pytest.raises(KeyboardInterrupt):moonraker.install(p.ctx)
    receipt=p.journal.recovery_receipts()[0][1]
    monkeypatch.setattr(moonraker.checks,'remote',p.remote)
    moonraker.rollback(p.ctx,receipt)
    assert p.target.read_bytes()==updated


def test_rebaseline_does_not_retire_pending_service_operation(printer):
    p=printer
    moonraker.install(p.ctx)
    operation=json.loads((p.state/'service.json').read_text())
    operation['phase']='stopped'
    (p.state/'service.json').write_text(json.dumps(operation))
    updated=SOURCE+b'\n# new vendor baseline\n'
    p.target.write_bytes(updated)
    with pytest.raises(RuntimeError,match='Interrupted Moonraker operation'):
        moonraker.preflight(p.ctx)
    assert p.target.read_bytes()==updated and not list(p.state.glob('retired-*'))


@pytest.mark.parametrize('unsupported', ['directory','http-error'])
@pytest.mark.parametrize('preflight_first', [False,True])
def test_optional_unsupported_source_skips_entire_component_before_publication(printer,capsys,unsupported,preflight_first):
    p=printer
    target=p.target if unsupported=='directory' else p.app
    target.write_bytes(b'# unsupported future vendor source\n')
    before=p.target.read_bytes(),p.app.read_bytes()
    if preflight_first:moonraker.preflight(p.ctx)
    receipt=moonraker.install(p.ctx)
    assert receipt=={'kind':'moonraker-directory','skipped':True}
    p.journal.complete_component('moonraker',receipt)
    assert p.journal.recovery_receipts()==[('moonraker',receipt)]
    moonraker.rollback(p.ctx,receipt)
    assert (p.target.read_bytes(),p.app.read_bytes())==before
    assert not p.state.exists() and not p.http_state.exists()
    assert 'stop' not in (p.events.read_text() if p.events.exists() else '')
    message=capsys.readouterr().out
    assert unsupported in message and str(target) in message
    assert 'status stalls' in message and 'No Moonraker patch will be published' in message


def test_unsupported_optional_source_does_not_hide_corrupt_other_receipt(printer):
    p=printer
    moonraker.install(p.ctx)
    p.target.write_bytes(b'# unsupported future directory source\n')
    (p.http_state/'receipt.json').write_text('{bad receipt')
    with pytest.raises(RuntimeError):moonraker.preflight(p.ctx)
    assert p.target.read_bytes()==b'# unsupported future directory source\n'


def test_pending_service_without_source_receipt_is_not_optional_skip(printer):
    p=printer
    p.state.mkdir(parents=True)
    (p.state/'service.json').write_text(json.dumps(dict(version=1,before='original',
        desired='installed',baseline={},phase='stopped')))
    p.target.write_bytes(b'# unrecognized source')
    with pytest.raises(RuntimeError,match='recover all --journal'):
        moonraker.preflight(p.ctx)
    assert p.target.read_bytes()==b'# unrecognized source'
    assert not p.events.exists()


def test_legacy_recipe_upgrade_through_normal_component_preserves_rollback(printer):
    from moonraker_directory_patch import legacy_candidate, candidate
    import hashlib
    p = printer
    p.state.mkdir(parents=True)
    old = legacy_candidate(SOURCE.decode()).encode()
    p.target.write_bytes(old)
    info = p.target.stat()
    record = dict(version=1, target=str(p.target), old=hashlib.sha256(SOURCE).hexdigest(),
                  new=hashlib.sha256(old).hexdigest(), mode=info.st_mode & 0o777,
                  uid=info.st_uid, gid=info.st_gid)
    (p.state/'original.py').write_bytes(SOURCE)
    (p.state/'installed.py').write_bytes(old)
    (p.state/'receipt.json').write_text(json.dumps(record))
    moonraker.preflight(p.ctx)
    assert json.loads((p.state/'receipt.json').read_text())['version'] == 1
    receipt = moonraker.install(p.ctx)
    assert [entry['before'] for entry in receipt['patches']] == ['previous', 'original']
    assert p.target.read_bytes() == candidate(SOURCE.decode()).encode()
    assert json.loads((p.state/'receipt.json').read_text())['version'] == 2
    moonraker.rollback(p.ctx, receipt)
    assert p.target.read_bytes() == old and p.app.read_bytes() == HTTP_SOURCE
    moonraker.uninstall(p.ctx)
    assert p.target.read_bytes() == SOURCE
