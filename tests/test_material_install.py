"""Material upgrades must preserve printer configuration and persisted state."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_deploy import deploy  # Tools module path, also when run alone.

spec = importlib.util.spec_from_file_location(
    'material_install', Path(__file__).resolve().parents[1] / 'tools/components/material.py')
material = importlib.util.module_from_spec(spec)
spec.loader.exec_module(material)


class SFTP:
    def __init__(self, root, fail_stage=None, fail_publish=None):
        self.root = root
        self.fail_stage = fail_stage
        self.fail_publish = fail_publish
        self.publications = 0

    def path(self, path):
        return self.root / path.lstrip('/')

    def open(self, path, mode):
        if 'w' in mode and '.wmp-upload-' in path and self.fail_stage in (path.split('/')[-1].split('.wmp-upload-')[0],):
            raise OSError('injected upload failure')
        return self.path(path).open(mode)

    def remove(self, path):
        self.path(path).unlink()

    def stat(self,path):
        return self.path(path).stat()

    def lstat(self,path):
        return self.path(path).lstat()

    def chmod(self,path,mode):
        self.path(path).chmod(mode)

    def chown(self,path,uid,gid):
        import os
        os.chown(self.path(path),uid,gid)

    def posix_rename(self, source, destination):
        if '.wmp-upload-' in source:
            self.publications += 1
            if self.publications == self.fail_publish:
                raise OSError('injected publication failure')
        self.path(source).replace(self.path(destination))


def setup(tmp_path, existing=True, **failures):
    sftp = SFTP(tmp_path, **failures)
    ctx = SimpleNamespace(user='printer', sftp=lambda: sftp)
    extra, cfg = material._paths(ctx)
    sftp.path(extra).parent.mkdir(parents=True)
    sftp.path(cfg).parent.mkdir(parents=True)
    if existing:
        sftp.path(cfg).write_text('[wm_material]\nload_feed_mm: 57\nload_purge_mm: 62\ncross_material_purge_mm: 95\n')
        for name in material.HELPERS:
            sftp.path(extra).with_name(name).write_text('previous ' + name)
    for name in ('wmp_filament_operation.json', 'wmp_filament_loaded.json', 'wmp_hotend_materials.json', 'wmp_filaments.json', 'wmp_filament_catalogue.json', 'tmt1.ini'):
        sftp.path(cfg).with_name(name).write_text('user data ' + name)
    return ctx, sftp, extra, cfg


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*')
            if p.is_file() and '.wmp-backup-' not in p.name}


def test_upgrade_preserves_custom_settings_and_filament_data(tmp_path):
    ctx, sftp, extra, cfg = setup(tmp_path)
    before = snapshot(sftp.path(cfg).parent)
    material.install(ctx)
    assert snapshot(sftp.path(cfg).parent) == before
    for name in material.HELPERS:
        assert sftp.path(extra).with_name(name).read_bytes() == (Path(material.SRC) / name).read_bytes()
        assert not list(sftp.path(extra).parent.glob(name + '.wmp-backup-*'))
    first = snapshot(tmp_path)
    material.install(ctx)
    assert snapshot(tmp_path) == first


def test_fresh_install_creates_defaults(tmp_path):
    ctx, sftp, _, cfg = setup(tmp_path, existing=False)
    material.install(ctx)
    assert sftp.path(cfg).read_bytes() == (Path(material.SRC) / 'wm_material.cfg').read_bytes()


@pytest.mark.parametrize('existing', [False, True])
@pytest.mark.parametrize('failure', [
    {'fail_stage': 'wm_material.py'},
    {'fail_stage': 'wmp_plr_records.py'},
    {'fail_stage': 'wmp_filament_types.py'},
    {'fail_stage': 'wmp_filament_profiles.py'},
    {'fail_publish': 1}, {'fail_publish': 2}, {'fail_publish': 3},
    {'fail_publish': 6}, {'fail_publish': 7},
])
def test_failures_restore_previous_install(tmp_path, existing, failure):
    ctx, _, _, _ = setup(tmp_path, existing=existing, **failure)
    before = snapshot(tmp_path)
    with pytest.raises(OSError, match='injected'):
        material.install(ctx)
    assert snapshot(tmp_path) == before


def test_new_config_publication_failure_rolls_back_helpers(tmp_path):
    ctx, _, _, _ = setup(tmp_path, existing=False, fail_publish=len(material.HELPERS) + 1)
    before = snapshot(tmp_path)
    with pytest.raises(OSError, match='injected'):
        material.install(ctx)
    assert snapshot(tmp_path) == before


def test_unreadable_config_is_not_treated_as_missing(tmp_path, monkeypatch):
    ctx, sftp, _, cfg = setup(tmp_path)
    original = sftp.open
    def denied(path, mode):
        if path == cfg:
            raise PermissionError(13, 'permission denied', path)
        return original(path, mode)
    monkeypatch.setattr(sftp, 'open', denied)
    before = snapshot(tmp_path)
    with pytest.raises(PermissionError):
        material.install(ctx)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('existing', [False, True])
def test_lost_rename_reply_restores_all_helpers(tmp_path, monkeypatch, existing):
    ctx, sftp, _, _ = setup(tmp_path, existing=existing)
    before = snapshot(tmp_path)
    rename = sftp.posix_rename
    def lost_reply(source, destination):
        rename(source, destination)
        if '.wmp-upload-' in source and sftp.publications == 2:
            raise OSError('lost rename reply')
    monkeypatch.setattr(sftp, 'posix_rename', lost_reply)
    with pytest.raises(OSError, match='lost rename reply'):
        material.install(ctx)
    assert snapshot(tmp_path) == before


def test_helper_receipt_supports_config_failure_rollback(tmp_path):
    ctx, sftp, extra, cfg = setup(tmp_path)
    recovery = sftp.path(extra).with_name('wmp_recovery.py')
    recovery.write_bytes(b'previous recovery')
    before = snapshot(tmp_path)
    changes = material.install(ctx, include_recovery=True, install_config=False)
    assert len(changes) == len(material.HELPERS) + 4  # Includes durable ownership.
    material.rollback(ctx, changes)
    assert snapshot(tmp_path) == before


def test_rollback_refuses_concurrent_edit_before_restoring_any_helpers(tmp_path):
    ctx, sftp, extra, _ = setup(tmp_path)
    changes = material.install(ctx)
    path = sftp.path(extra)
    path.write_bytes(b'operator edit')
    before = snapshot(tmp_path)
    with pytest.raises(RuntimeError, match='Concurrent edit'):
        material.rollback(ctx, changes)
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize('existing',[False,True])
@pytest.mark.parametrize('after_rename',[False,True])
@pytest.mark.parametrize('publication_index',range(1, len(material.HELPERS) + 2))
def test_process_loss_uses_prepublication_journal(tmp_path,monkeypatch,existing,after_rename,publication_index):
    from test_deploy import deploy
    from install_journal import Journal
    ctx,sftp,_,_=setup(tmp_path/'printer',existing=existing)
    before=snapshot(tmp_path/'printer')
    journal=Journal(tmp_path/'install.json')
    journal.create('printer','printer',['material']);journal.begin('material')
    ctx.rollback_backend=SimpleNamespace(journal=journal)
    ctx.host='printer';ctx.printing_now=lambda:False
    rename=sftp.posix_rename
    attempts=[]
    def process_lost(source,destination):
        attempts.append(destination)
        if len(attempts)!=publication_index:
            return rename(source,destination)
        if after_rename:rename(source,destination)
        raise SystemExit('installer process lost')
    monkeypatch.setattr(sftp,'posix_rename',process_lost)
    with pytest.raises(SystemExit):material.install(ctx)
    saved=Journal(journal.path).load('printer','printer')
    assert saved.value['inflight']=='material'
    assert len(saved.recovery_receipts()[0][1])==(len(material.HELPERS) + (not existing) + 1)
    monkeypatch.setattr(sftp,'posix_rename',rename)
    monkeypatch.setattr(deploy.REGISTRY['material'],'rollback',material.rollback)
    deploy.recover_installation(ctx,journal.path)
    assert snapshot(tmp_path/'printer')==before
    assert Journal(journal.path).load('printer','printer').value['state']=='restored'


def test_undo_checkpoint_failure_prevents_helper_publication(tmp_path,monkeypatch):
    from install_journal import Journal
    ctx,sftp,_,_=setup(tmp_path/'printer')
    before=snapshot(tmp_path/'printer')
    journal=Journal(tmp_path/'install.json')
    journal.create('printer','printer',['material']);journal.begin('material')
    ctx.rollback_backend=SimpleNamespace(journal=journal)
    def fail():raise OSError('checkpoint disk full')
    monkeypatch.setattr(journal,'save',fail)
    with pytest.raises(OSError,match='checkpoint disk full'):material.install(ctx)
    assert sftp.publications==0
    assert snapshot(tmp_path/'printer')==before


def test_corrupt_backup_blocks_entire_helper_restore(tmp_path):
    ctx,sftp,_,_=setup(tmp_path)
    changes=material.install(ctx)
    changed = next(change for change in changes if change[3] is not None)
    # Receipts from older releases still support and validate disk backups.
    backup=changed[0]+'.wmp-backup-legacy'
    sftp.path(backup).write_bytes(b'corrupted backup')
    changes[changes.index(changed)]=(changed[0],changed[1],backup,changed[3],changed[4])
    before=snapshot(tmp_path)
    with pytest.raises(RuntimeError,match='Backup mismatch'):
        material.rollback(ctx,changes)
    assert snapshot(tmp_path)==before


def test_lost_restore_reply_stops_then_retry_finishes(tmp_path,monkeypatch):
    ctx,sftp,_,_=setup(tmp_path)
    before=snapshot(tmp_path)
    changes=material.install(ctx)
    rename=sftp.posix_rename;attempts=[]
    def lost_reply(source,destination):
        attempts.append(destination)
        rename(source,destination)
        raise OSError('lost restore reply')
    monkeypatch.setattr(sftp,'posix_rename',lost_reply)
    with pytest.raises(RuntimeError,match='lost restore reply'):
        material.rollback(ctx,changes)
    assert attempts==[changes[-1][0]]
    assert sftp.path(changes[0][0]).read_bytes()==changes[0][4]
    monkeypatch.setattr(sftp,'posix_rename',rename)
    material.rollback(ctx,changes)
    assert snapshot(tmp_path)==before


def test_conflict_after_precheck_stops_before_that_mutation(tmp_path,monkeypatch):
    ctx,sftp,_,_=setup(tmp_path)
    changes=material.install(ctx)
    rename=sftp.posix_rename;attempts=[]
    def concurrent_edit(source,destination):
        attempts.append(destination)
        rename(source,destination)
        sftp.path(changes[-2][0]).write_bytes(b'operator edit during recovery')
    monkeypatch.setattr(sftp,'posix_rename',concurrent_edit)
    with pytest.raises(RuntimeError,match='Concurrent edit'):
        material.rollback(ctx,changes)
    assert attempts==[changes[-1][0]]
    assert sftp.path(changes[-2][0]).read_bytes()==b'operator edit during recovery'
    assert sftp.path(changes[0][0]).read_bytes()==changes[0][4]


def test_unconfirmed_helper_restore_blocks_earlier_component_rollback(tmp_path,monkeypatch):
    from test_deploy import deploy
    ctx,sftp,_,_=setup(tmp_path)
    ctx.printing_now=lambda:False
    ctx.rollback_backend=deploy.BackendRollback(ctx)
    events=[]
    component=SimpleNamespace(NAME='config',rollback=lambda *args:events.append('config restored'))
    ctx.rollback_backend.record(component,{'kind':'previous component'})
    rename=sftp.posix_rename;published=[]
    def fail(source,destination):
        if len(published)==1:
            sftp.path(published[0]).write_bytes(b'concurrent operator edit')
            raise OSError('publication failed')
        rename(source,destination);published.append(destination)
    monkeypatch.setattr(sftp,'posix_rename',fail)
    with pytest.raises(RuntimeError,match='Concurrent edit'):
        material.install(ctx)
    assert ctx.rollback_backend.blocked
    with pytest.raises(deploy.DeployError,match='recovery is unconfirmed'):
        ctx.rollback_backend()
    assert events==[]
    assert ctx.rollback_backend.pending


@pytest.mark.parametrize('fail_after_update', [False, True])
def test_upgrade_never_overwrites_newer_filament_operation(tmp_path, monkeypatch, fail_after_update):
    import json
    ctx, sftp, extra, cfg = setup(tmp_path)
    operation = sftp.path(cfg).with_name('wmp_filament_operation.json')
    old = {'version': 1, 'operation': {'id': 'interrupted', 'head': 'h2',
           'action': 'load', 'session': 'old', 'state': 'unknown', 'phase': 'heating'}}
    new = {'version': 1, 'operation': dict(old['operation'], session='new',
           state='failed', phase='stopped', recovered=True)}
    operation.write_text(json.dumps(old))
    rename = sftp.posix_rename
    def changed(source, destination):
        rename(source, destination)
        if '.wmp-upload-' in source and sftp.publications == 1:
            # Runtime/operator data is not an installer-owned rollback target.
            operation.write_text(json.dumps(new))
            if fail_after_update:
                raise OSError('lost publication reply after runtime journal update')
    monkeypatch.setattr(sftp, 'posix_rename', changed)
    if fail_after_update:
        with pytest.raises(OSError, match='lost publication reply'):
            material.install(ctx)
        assert sftp.path(extra).read_text() == 'previous wm_material.py'
    else:
        material.install(ctx)
    assert json.loads(operation.read_text()) == new
    assert not list(operation.parent.glob('wmp_filament_operation.json.wmp-*'))


def test_remote_paths_do_not_use_host_path_separator(tmp_path, monkeypatch):
    import ntpath
    ctx, sftp, extra, cfg = setup(tmp_path)
    # Replace only this module's os facade, keeping local file reads native.
    native_join = material.os.path.join
    host_path = SimpleNamespace(
        dirname=ntpath.dirname,
        join=lambda parent, name: ntpath.join(parent, name)
        if parent.startswith('/home/printer/') else native_join(parent, name))
    monkeypatch.setattr(material, 'os', SimpleNamespace(path=host_path))
    receipt = material.install(ctx, include_recovery=True)
    assert receipt
    assert all('\\' not in row[0] and row[0].startswith('/home/printer/') for row in receipt)
    monkeypatch.setattr(sftp, 'stat', lambda path: sftp.path(path).stat(), raising=False)
    from components import config
    monkeypatch.setattr(material, '__package__', 'components')
    monkeypatch.setattr(config, 'remove_configuration', lambda ctx, **kw: {'retained_dependencies': []})
    material.uninstall(ctx)
    assert sftp.path(extra).read_text() == 'previous wm_material.py'


@pytest.mark.parametrize('package_import', [False, True])
def test_installed_helpers_import_without_repository_fallback(tmp_path, package_import):
    """Exercise actual transitive imports using only freshly installed files."""
    import subprocess
    import sys
    ctx, sftp, extra, _ = setup(tmp_path, existing=False)
    material.install(ctx)
    directory = sftp.path(extra).parent
    import_root = directory.parent if package_import else directory
    statement = 'from extras import wm_material' if package_import else 'import wm_material'
    subprocess.run([sys.executable, '-I', '-c',
                    'import sys; sys.path.insert(0, %r); %s; '
                    'assert callable(wm_material.load_config)' % (str(import_root), statement)],
                   check=True, capture_output=True, text=True)


def test_runtime_contract_matches_installable_helper_set():
    import preload_bundle
    root = Path(material.ROOT)
    assert set(preload_bundle.backend_helper_names(root)) == set(material.HELPERS) | {
        'wmp_identification.py', 'wmp_recovery.py', 'wmp_case_light.py'}


def test_full_removal_preflight_checks_last_shared_owner(tmp_path):
    import file_ownership
    ctx, sftp, extra, cfg = setup(tmp_path, existing=False)
    material.install(ctx)
    inventory_path = sftp.path(extra).with_name(file_ownership.FILENAME)
    inventory = file_ownership.load(inventory_path.read_bytes(), set(material.HELPERS))
    name = 'wm_material.py'
    inventory['files'][name]['owners'] = ['config','material']
    inventory_path.write_bytes(file_ownership.encode(inventory))
    sftp.path(extra).write_bytes(b'unknown edited helper')
    before = snapshot(tmp_path)
    ctx.removing_components = {'config','material'}
    with pytest.raises(ValueError, match='changed before removal'):
        material.release_helpers(ctx,'config',dry_run=True)
    assert snapshot(tmp_path) == before
    ctx.removing_components = {'config'}
    _, changes = material.release_helpers(ctx,'config',dry_run=True)
    assert name not in changes


def test_repeated_helper_release_does_not_republish_inventory(tmp_path):
    ctx, sftp, extra, cfg = setup(tmp_path, existing=False)
    material.install(ctx)
    material.release_helpers(ctx,'material')
    publications = sftp.publications
    material.release_helpers(ctx,'material')
    assert sftp.publications == publications
