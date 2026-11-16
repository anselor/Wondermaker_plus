"""Component: optional wm_material Klipper extra. Needs SSH (no sudo).
install atomically publishes material helpers and creates wm_material.cfg only
when absent. Existing configuration and filament data are preserved. Klipper
must restart afterwards (deploy.py does this).
"""
import os
import posixpath
import errno
import uuid

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
        destination, _, backup, previous, content = change
        current = _read(sftp, destination)
        if current == previous:
            return False
        if current != content:
            raise RuntimeError('Concurrent edit at ' + destination)
        if previous is not None and _read(sftp, backup) != previous:
            raise RuntimeError('Backup mismatch at ' + backup)
        return True

    try:
        # Detect existing conflicts across the entire helper set before making
        # it a mixture of old and new versions. Recheck immediately before each
        # mutation as another writer may have changed a file since validation.
        for change in changes:
            check(change)
        for change in reversed(changes):
            destination, _, backup, previous, _ = change
            if not check(change):
                continue
            if previous is None:
                sftp.remove(destination)
            else:
                sftp.posix_rename(backup, destination)
            if _read(sftp, destination) != previous:
                raise RuntimeError('Rollback readback mismatch at ' + destination)
    except Exception as error:
        # Do not continue downgrading dependencies after an unconfirmed restore.
        raise RuntimeError('Helper rollback needs inspection: ' + str(error)) from error


def install(ctx, include_recovery=False, install_config=True, prepare=None):
    sftp = ctx.sftp()
    extra, cfg = _paths(ctx)
    token = uuid.uuid4().hex
    changes = []
    published = []
    temporary = []
    try:
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
            with open(os.path.join(SRC, name), "rb") as stream:
                content = stream.read()
            if previous == content:
                continue
            staged = destination + ".wmp-upload-" + token
            temporary.append(staged)
            with sftp.open(staged, "wb") as stream:
                stream.write(content)
            if _read(sftp, staged) != content:
                raise RuntimeError('Upload readback mismatch: ' + destination)
            backup = destination + ".wmp-backup-" + token
            if previous is not None:
                with sftp.open(backup, "wb") as stream:
                    stream.write(previous)
                if _read(sftp, backup) != previous:
                    raise RuntimeError('Backup readback mismatch: ' + destination)
            changes.append((destination, staged, backup, previous, content))
        # The top-level installer can recover a lost process using this complete
        # undo plan, even if a rename committed without returning a response.
        journal = getattr(getattr(ctx, 'rollback_backend', None), 'journal', None)
        if prepare is not None:
            prepare(changes)
        elif journal is not None and journal.value['inflight'] == NAME:
            journal.prepare_component(NAME, changes)
        for change in changes:
            destination, staged, _, previous, content = change
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
        return
    sftp = ctx.sftp()
    extra, _ = _paths(ctx)
    for name in reversed(HELPERS):
        path = posixpath.join(posixpath.dirname(extra), name)
        if _read(sftp, path) is not None:
            sftp.remove(path)
            print('removed ' + path)
    # Keep the commented configuration and filament data for future reinstall.


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
