"""Component: Klipper config and required extras. Full install needs SSH;
--config-only and status use Moonraker. Install extra before config can restart.
"""
import os
import json
import subprocess
import sys
import uuid
from datetime import datetime, timezone

NAME = "config"
DESCRIPTION = "Printer configuration and required recovery/light helpers"
NEEDS_SSH = True
NEEDS_SUDO = False
RESTART_AFTER = "klipper"  # activate only after every selected component is installed

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SYNC = os.path.join(ROOT, "utils", "config_sync.py")


def _sync(args, env_extra=None):
    sys.stdout.flush()
    env = dict(os.environ)
    env.update(env_extra or {})
    return subprocess.call([sys.executable, SYNC] + args, env=env)


def _install_extra(ctx):
    # Publish the dependency first, before a new recovery helper can use it.
    for name in ('wmp_identification.py', 'wmp_recovery.py', 'wmp_case_light.py'):
        _install_extra_file(ctx, name)


def _install_extra_file(ctx, name):
    source = os.path.join(ROOT, 'klipper_extras', name)
    destination = '/home/%s/klipper/klippy/extras/%s' % (ctx.user, name)
    sftp = ctx.sftp()
    with open(source, 'rb') as f:
        content = f.read()
    try:
        with sftp.open(destination, 'rb') as f:
            previous = f.read()
    except FileNotFoundError:
        previous = None
    if previous != content:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        if previous is not None:
            with sftp.open(destination + '.wmp-backup-' + stamp, 'wb') as f:
                f.write(previous)
        temporary = destination + '.wmp-upload-' + stamp
        with sftp.open(temporary, 'wb') as f:
            f.write(content)
        sftp.posix_rename(temporary, destination)
        print('Installed Klipper helper: %s' % destination)


def preflight(ctx):
    import preflight as checks
    checks.config(ctx)


def install(ctx):
    import preload_bundle
    if preload_bundle.bundle_relative(ROOT) == preload_bundle.CURRENT_BUNDLE:
        if not hasattr(ctx, 'screen_config_plan') or ctx.config_only or ctx.files:
            raise ctx.DeployError('Unified configuration installation requires its SSH preservation preflight.')
        preload_bundle.verify_source_binding(ROOT)
        import preflight as checks
        import reconcile_screen_config
        from . import material
        # Every helper referenced by the generated config must exist first,
        # including when config is installed without the material component.
        journal = getattr(getattr(ctx, 'rollback_backend', None), 'journal', None)
        def prepare_helpers(changes):
            if journal is not None:
                journal.prepare_component(NAME, {'kind': 'config-helpers', 'helpers': changes})
        helpers = material.install(ctx, include_recovery=True, install_config=False,
                                   prepare=prepare_helpers)
        directory = '/home/' + ctx.user + '/printer_data/config'
        backup = directory + '/.wmp-config-backup-' + uuid.uuid4().hex
        receipt = {'kind': 'preserved-screen-config',
                   'plan': json.loads(json.dumps(ctx.screen_config_plan)),
                   'backup': backup, 'helpers': helpers}
        if journal is not None:
            try:
                journal.prepare_component(NAME, receipt)
            except Exception:
                material.rollback(ctx, helpers)
                raise
        try:
            result = json.loads(checks.remote(ctx, reconcile_screen_config.remote_script(
                ROOT, directory, ctx.screen_config_plan, backup=backup), quiet=True))
        except Exception as error:
            raise ctx.DeployError('Configuration publication outcome is unknown; retained matching helpers. Inspect configuration and backups before restarting: ' + str(error)) from error
        if result.get('state') != 'published':
            if result.get('rollback_confirmed') is True:
                material.rollback(ctx, helpers)
            raise ctx.DeployError('Configuration publication failed: ' + result.get('error', 'unconfirmed result'))
        print('Published preserved configuration; backup: ' + str(result.get('backup')))
        return {'kind': 'preserved-screen-config',
                'plan': json.loads(json.dumps(ctx.screen_config_plan)),
                'backup': result.get('backup'), 'helpers': helpers}
    if getattr(ctx, "config_only", False):
        print('Updating configuration over HTTP; '
              'the matching recovery and case-light helpers must already be installed')
    else:
        _install_extra(ctx)
    args = ["push", "--yes", "--no-restart"]
    args += ctx.files
    if _sync(args, {"WMP_PRINTER": ctx.host}) != 0:
        raise ctx.DeployError("Configuration upload failed. Check the preceding error and the printer backups before retrying.")


def rollback(ctx, receipt):
    """Restore config before removing helpers it may reference; no restart."""
    if isinstance(receipt, dict) and receipt.get('kind') == 'config-helpers':
        from . import material
        material.rollback(ctx, receipt['helpers'])
        return
    if not isinstance(receipt, dict) or receipt.get('kind') != 'preserved-screen-config':
        raise ctx.DeployError('This configuration install has no automatic rollback receipt.')
    import preflight as checks
    import reconcile_screen_config
    from . import material
    try:
        result = json.loads(checks.remote(ctx, reconcile_screen_config.remote_script(
            ROOT, '/home/' + ctx.user + '/printer_data/config', receipt['plan'],
            action='restore', backup=receipt['backup']), quiet=True))
    except Exception as error:
        raise ctx.DeployError('Configuration restoration outcome is unknown; retained matching helpers: ' + str(error)) from error
    if result.get('state') != 'rolled-back':
        raise ctx.DeployError('Configuration restoration unconfirmed; retained matching helpers: ' + result.get('error', 'unknown result'))
    material.rollback(ctx, receipt['helpers'])


def remove_configuration(ctx, material_only=False):
    """Plan against current files and disable only attributable package output."""
    import preflight as checks
    import reconcile_screen_config
    directory = '/home/' + ctx.user + '/printer_data/config'
    result = json.loads(checks.remote(ctx, reconcile_screen_config.remote_script(
        ROOT, directory, action='material-remove-plan' if material_only else 'remove-plan'), quiet=True))
    planned = result['plan']
    for change in planned['changes']:
        print('Disable owned configuration in ' + change['file'] + '; preserve other settings')
    if planned['changes']:
        try:
            outcome = json.loads(checks.remote(ctx, reconcile_screen_config.remote_script(
                ROOT, directory, planned), quiet=True))
        except Exception as error:
            raise ctx.DeployError('Configuration removal outcome is unknown; helper modules retained: ' + str(error)) from error
        if outcome.get('state') != 'published':
            raise ctx.DeployError('Configuration removal unconfirmed; helper modules retained: '
                                  + outcome.get('error', 'unknown publication result'))
        print('Configuration removal backup: ' + str(outcome.get('backup')))
    dependencies = planned.get('retained_dependencies', [])
    if dependencies:
        print('Retained helper modules required by current configuration: ' + ', '.join(dependencies))
    if planned.get('retained_sections'):
        print('Preserved edited configuration sections: ' + ', '.join(planned['retained_sections']))
    return planned


def uninstall(ctx):
    planned = remove_configuration(ctx)
    if planned['retained_dependencies']:
        return
    sftp = ctx.sftp()
    from .material import _read
    for name in ('wmp_recovery.py', 'wmp_identification.py', 'wmp_case_light.py'):
        path = '/home/%s/klipper/klippy/extras/%s' % (ctx.user, name)
        if _read(sftp, path) is not None:
            sftp.remove(path)
            print('removed ' + path)


def status(ctx):
    args = ["diff"] + (["--patch"] if ctx.diff else [])
    _sync(args, {"WMP_PRINTER": ctx.host})
