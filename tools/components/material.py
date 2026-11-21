"""Component: optional wm_material Klipper extra. Needs SSH (no sudo).
install atomically publishes material helpers and creates wm_material.cfg only
when absent. Existing configuration and filament data are preserved. Klipper
must restart afterwards (deploy.py does this).
"""
import os
import posixpath
import errno
import uuid
import json
import stat
import file_ownership

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.path.join(ROOT, "klipper_extras")
EXTRA_DST = "klipper/klippy/extras/wm_material.py"      # relative to the printer user's home
CFG_DST = "printer_data/config/wm_material.cfg"

HELPERS = (
    'wmp_xy_homing.py',
    'wmp_orca_profiles.py',
    'wmp_orca_mapping.py',
    'wmp_nozzles.py',
    'wmp_nozzle_runtime.py',
    'wmp_saved_variables.py',
    'wmp_recovery_retirement.py',
    'wmp_recovery_file_envelope.py',
    'wmp_plr_records.py',
    'wmp_filament_types.py',
    'wmp_filament_profiles.py',
    'wmp_persistence.py',
    'wmp_print_cancel.py',
    'wmp_stop_points.py',
    'wmp_component.py',
    'wmp_toolhead_service.py',
    'wmp_plr_execution.py',
    'wmp_plr_motion.py',
    'wmp_plr_storage.py',
    'wmp_plr_worker.py',
    'wmp_plr_attempt.py',
    'wmp_plr_clearance.py',
    'wmp_plr_review.py',
    'wmp_plr_jobs.py',
    'wmp_print_submission.py',
    'wmp_print_preparation.py',
    'wmp_filament_planning.py',
    'wmp_filament_service.py',
    'wmp_toolchange_repair.py',
    'wmp_paused_service.py',
    'wmp_observation.py',
    'wmp_material_settings.py',
    'wmp_filament_state.py',
    'wmp_config_save.py',
    'wmp_material_status.py',
    'wmp_command_routing.py',
    'wmp_material_owners.py',
    'wmp_calibration_records.py',
    'wmp_probe_state.py',
    'wmp_probe_editor.py',
    'wmp_calibration_outcome.py',
    'wmp_calibration_progress.py',
    'wmp_nozzle_scrub.py',
    'wmp_nozzle_touch.py',
    'wmp_tool_probe.py',
    'wmp_offset_snapshot.py',
    'wmp_calibration.py',
    'wm_material.py',
)





def exists(sftp, path):
    try:
        sftp.stat(path)
        return True
    except IOError:
        return False









NAME = "material"
DESCRIPTION = "Use touchscreen material settings for filament unloading"
NEEDS_SSH = True
NEEDS_SUDO = False
RESTART_AFTER = "klipper"


def _paths(ctx):
    home = "/home/%s" % ctx.user
    return home + "/" + EXTRA_DST, home + "/" + CFG_DST


def preflight(ctx):
    import preflight as checks
    checks.material(ctx)


def _read(sftp, path):
    try:
        if hasattr(sftp,'lstat'):
            info=sftp.lstat(path)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError('Refuse non-regular helper resource: '+path)
        with sftp.open(path, "rb") as stream:
            return stream.read()
    except IOError as error:
        if error.errno != errno.ENOENT:
            raise
        return None


def rollback(ctx, changes):
    """Restore only our published bytes; never overwrite a later operator edit."""
    sftp = ctx.sftp()
    def check(change):
        destination, _, backup, previous, content = change[:5]
        current = _read(sftp, destination)
        if current == previous:
            return False
        if current != content:
            raise RuntimeError('Concurrent edit at ' + destination)
        if previous is not None and backup is not None and _read(sftp, backup) != previous:
            raise RuntimeError('Backup mismatch at ' + backup)
        return True

    try:
        # Detect existing conflicts across the entire helper set before making
        # it a mixture of old and new versions. Recheck immediately before each
        # mutation as another writer may have changed a file since validation.
        for change in changes:
            check(change)
        for change in reversed(changes):
            destination, _, backup, previous, _ = change[:5]
            metadata=change[5] if len(change)>5 else None
            if not check(change):
                continue
            if previous is None:
                sftp.remove(destination)
            else:
                if backup is not None:
                    sftp.posix_rename(backup, destination)
                else:
                    # The protected installer receipt already contains the
                    # previous bytes; no per-update backup needs to litter the
                    # printer. The factory inventory is a different baseline.
                    temporary=destination+'.wmp-restore-'+uuid.uuid4().hex
                    with sftp.open(temporary,'wb') as stream:
                        stream.write(previous)
                    if _read(sftp,temporary)!=previous:
                        raise RuntimeError('Rollback upload readback mismatch')
                    try:
                        if metadata is not None:
                            sftp.chmod(temporary,metadata['mode'])
                            sftp.chown(temporary,metadata['uid'],metadata['gid'])
                        sftp.posix_rename(temporary,destination)
                    finally:
                        if _read(sftp,temporary)==previous:
                            sftp.remove(temporary)
            if _read(sftp, destination) != previous:
                raise RuntimeError('Rollback readback mismatch at ' + destination)
    except Exception as error:
        # Do not continue downgrading dependencies after an unconfirmed restore.
        raise RuntimeError('Helper rollback needs inspection: ' + str(error)) from error


def install(ctx, include_recovery=False, install_config=True, prepare=None, owner='material'):
    sftp = ctx.sftp()
    extra, cfg = _paths(ctx)
    token = uuid.uuid4().hex
    changes = []
    published = []
    temporary = []
    try:
        inventory_path = posixpath.join(posixpath.dirname(extra), file_ownership.FILENAME)
        inventory_before = _read(sftp, inventory_path)
        with open(os.path.join(ROOT, 'config/provenance/legacy-behavior.json'), encoding='utf-8') as stream:
            catalog = json.load(stream)['helpers']
        allowed = set(catalog) | set(HELPERS) | {'wmp_identification.py', 'wmp_recovery.py', 'wmp_case_light.py'}
        inventory = file_ownership.load(inventory_before, allowed)
        # Read every destination before publishing anything. Existing user
        # configuration is authoritative; defaults are only for first install.
        destinations = [(name, posixpath.join(posixpath.dirname(extra), name))
                        for name in HELPERS]
        if include_recovery:
            destinations.append(('wmp_identification.py', posixpath.join(posixpath.dirname(extra), 'wmp_identification.py')))
            destinations.append(('wmp_recovery.py', posixpath.join(posixpath.dirname(extra), 'wmp_recovery.py')))
            destinations.append(('wmp_case_light.py', posixpath.join(posixpath.dirname(extra), 'wmp_case_light.py')))
        if install_config and _read(sftp, cfg) is None:
            destinations.append(("wm_material.cfg", cfg))
        for name, destination in destinations:
            previous = _read(sftp, destination)
            metadata=None
            if previous is not None and hasattr(sftp,'stat'):
                info=sftp.stat(destination)
                metadata={'mode':info.st_mode & 0o777,'uid':info.st_uid,'gid':info.st_gid}
            with open(os.path.join(SRC, name), "rb") as stream:
                content = stream.read()
            if name.endswith('.py'):
                file_ownership.install(inventory, name, previous, content, owner, catalog, metadata)
            if previous == content:
                continue
            staged = destination + ".wmp-upload-" + token
            temporary.append(staged)
            with sftp.open(staged, "wb") as stream:
                stream.write(content)
            if metadata is not None:
                sftp.chmod(staged,metadata['mode'])
                sftp.chown(staged,metadata['uid'],metadata['gid'])
            if _read(sftp, staged) != content:
                raise RuntimeError('Upload readback mismatch: ' + destination)
            backup = None
            changes.append((destination, staged, backup, previous, content, metadata))
        inventory_content = file_ownership.encode(inventory)
        if inventory_before != inventory_content:
            staged = inventory_path + '.wmp-upload-' + token
            temporary.append(staged)
            with sftp.open(staged, 'wb') as stream:
                stream.write(inventory_content)
            if hasattr(sftp,'chmod'):
                sftp.chmod(staged,0o600)
            if _read(sftp, staged) != inventory_content:
                raise RuntimeError('Helper inventory upload readback mismatch')
            backup = None
            # Immutable originals must be durable before the first helper write.
            info=sftp.stat(inventory_path) if inventory_before is not None and hasattr(sftp,'stat') else None
            metadata={'mode':info.st_mode & 0o777,'uid':info.st_uid,'gid':info.st_gid} if info else None
            changes.insert(0, (inventory_path, staged, backup, inventory_before, inventory_content, metadata))
        # The top-level installer can recover a lost process using this complete
        # undo plan, even if a rename committed without returning a response.
        journal = getattr(getattr(ctx, 'rollback_backend', None), 'journal', None)
        if prepare is not None:
            prepare(changes)
        elif journal is not None and journal.value['inflight'] == NAME:
            journal.prepare_component(NAME, changes)
        for change in changes:
            destination, staged, _, previous, content = change[:5]
            if _read(sftp, destination) != previous:
                raise RuntimeError('Destination changed during installation: ' + destination)
            # Record before rename: the server may commit and lose the reply.
            published.append(change)
            sftp.posix_rename(staged, destination)
            if _read(sftp, destination) != content:
                raise RuntimeError('Publication readback mismatch: ' + destination)
    except Exception:
        try:
            rollback(ctx, published)
        except Exception:
            backend = getattr(ctx, 'rollback_backend', None)
            if backend is not None:
                backend.blocked = True
            raise
        raise
    finally:
        for path in temporary:
            try:
                sftp.remove(path)
            except IOError as error:
                if error.errno != errno.ENOENT:
                    raise
    print("Installed material helpers; preserved existing configuration and filament data")
    return published


def uninstall(ctx):
    # Disable helper sections first. Retain helpers while legacy or user macros
    # still call them; deleting files first would strand the next Klipper boot.
    from . import config
    planned = config.remove_configuration(ctx, material_only=True)
    if planned['retained_dependencies']:
        raise ctx.DeployError('Material uninstall incomplete: remaining configuration requires its helpers; remove config first')
    release_helpers(ctx, 'material')
    # Keep the commented configuration and filament data for future reinstall.


def release_helpers(ctx, owner, dry_run=False):
    """Release a component's implicit and explicit helpers, retaining consumers.

    All conflicts are checked before the first restore. The inventory is updated
    last, so an interrupted removal can repeat original restorations safely.
    """
    sftp = ctx.sftp()
    extra, _ = _paths(ctx)
    directory = posixpath.dirname(extra)
    inventory_path = posixpath.join(directory, file_ownership.FILENAME)
    raw = _read(sftp, inventory_path)
    with open(os.path.join(ROOT, 'config/provenance/legacy-behavior.json'), encoding='utf-8') as stream:
        known = json.load(stream)['helpers']
    allowed = set(known) | set(HELPERS) | {'wmp_identification.py', 'wmp_recovery.py', 'wmp_case_light.py'}
    current = lambda name: _read(sftp, posixpath.join(directory, name))
    inventory = file_ownership.load(raw, allowed)
    if raw is None:
        # Older installations have no inventory. Only exact published helper
        # bytes establish ownership; unknown originals require explicit review.
        names = allowed if owner == 'material' else {'wmp_identification.py', 'wmp_recovery.py', 'wmp_case_light.py'}
        for name in names:
            data = current(name)
            if data is None:
                continue
            if file_ownership.digest(data) not in known.get(name, []):
                raise ctx.DeployError('Cannot establish original helper provenance: ' + name)
            file_ownership.install(inventory, name, data, data, owner, known)
    updated, changes = file_ownership.removal(inventory, owner, current)
    if dry_run:
        return updated, changes
    # Validate all resources again immediately before each mutation.
    expected = {name: current(name) for name in changes}
    for name, content in changes.items():
        path = posixpath.join(directory, name)
        if current(name) != expected[name]:
            raise ctx.DeployError('Concurrent helper edit before removal: ' + name)
        if content is None:
            sftp.remove(path)
        else:
            temporary = path + '.wmp-upload-' + uuid.uuid4().hex
            with sftp.open(temporary, 'wb') as stream:
                stream.write(content)
            metadata=updated['files'][name]['metadata']
            if metadata is not None:
                sftp.chmod(temporary,metadata['mode'])
                sftp.chown(temporary,metadata['uid'],metadata['gid'])
            sftp.posix_rename(temporary, path)
        if current(name) != content:
            raise ctx.DeployError('Helper removal readback mismatch: ' + name)
        print('Restored original helper state: ' + path)
    if _read(sftp, inventory_path) != raw:
        raise ctx.DeployError('Helper ownership changed during removal')
    if any(current(name) != content for name, content in changes.items()):
        raise ctx.DeployError('Helpers changed during removal')
    if raw is not None or inventory['files']:
        temporary = inventory_path + '.wmp-upload-' + uuid.uuid4().hex
        with sftp.open(temporary, 'wb') as stream:
            stream.write(file_ownership.encode(updated))
        if hasattr(sftp,'chmod'):
            sftp.chmod(temporary,0o600)
        sftp.posix_rename(temporary, inventory_path)
        if _read(sftp,inventory_path)!=file_ownership.encode(updated):
            raise ctx.DeployError('Helper ownership publication readback mismatch')


def preflight_uninstall(ctx):
    ctx.ssh()
    if 'config' not in getattr(ctx,'removing_components',set()):
        import preflight as checks
        import reconcile_screen_config
        directory='/home/'+ctx.user+'/printer_data/config'
        planned=json.loads(checks.remote(ctx,reconcile_screen_config.remote_script(
            ROOT,directory,action='material-remove-plan'),quiet=True))['plan']
        if planned['retained_dependencies']:
            raise ctx.DeployError('Remove the dependent config component before removing material helpers')
    release_helpers(ctx,'material',dry_run=True)


def status(ctx):
    sftp = ctx.sftp()
    extra, cfg = _paths(ctx)
    print("wm_material.py:  %s" % ("installed" if exists(sftp, extra) else "absent"))
    print("wm_material.cfg: %s" % ("installed" if exists(sftp, cfg) else "absent"))
    try:
        q = ctx.moonraker("/printer/objects/query?wm_material")
        print("Running helper:     %s" % ("present" if '"available"' in q else "not loaded; restart Klipper after installation"))
    except Exception as e:
        print("Running helper:     could not check Moonraker: %s" % e)
