"""Input shaper backport: upstream Klipper shaper, calibration and resonance test.

Replaces six unmodified vendor Klipper files and builds the C helper on the
printer. See klipper_backport/input_shaper/README.md.
"""
import shaper_backport as tool

NAME = 'shaper'
DESCRIPTION = 'Current upstream Klipper input shaper and resonance test'
NEEDS_SSH = True
NEEDS_SUDO = True
RESTART_AFTER = None
RECEIPT_KIND = 'shaper-backport'


class _Printer(tool.Printer):
    """Run the backport installer over the deploy context's connection."""

    def __init__(self, ctx):
        self.ctx = ctx
        ctx.ssh()
        self.host, self.user, self.password = ctx.host, ctx.user, ctx.password
        self.home = '/home/%s' % self.user

    def ssh(self):
        return self.ctx.ssh()

    def sftp(self):
        return self.ctx.sftp()

    def close(self):
        pass


def _run(ctx, action, *args):
    try:
        return action(_Printer(ctx), *args)
    except tool.BackportError as error:
        raise ctx.DeployError(str(error))


def _installed(printer):
    return tool.is_installed(printer, tool.survey(printer))


def _prepare(printer):
    if _installed(printer):
        return 'installed'
    tool.prepare(printer)
    return 'stock'


def preflight(ctx):
    if _run(ctx, _prepare) == 'installed':
        print('Input shaper backport already installed')
    else:
        print('Input shaper backport checks passed; C helper built in staging')


def install(ctx):
    before = 'installed' if _run(ctx, _installed) else 'stock'
    receipt = {'kind': RECEIPT_KIND, 'version': 1, 'before': before}
    if before == 'installed':
        print('Input shaper backport already installed')
        return receipt
    if 'preload' in getattr(ctx, 'installing_components', ()):
        # The Klipper service restart resets the controllers. The stock
        # screen must not handle that reset without the head guard.
        from . import preload
        preload.verify_guard(ctx)
    journal = getattr(getattr(ctx, 'rollback_backend', None), 'journal', None)
    if journal is not None:
        journal.prepare_component(NAME, receipt)
    if _run(ctx, tool.install) != 0:
        raise ctx.DeployError('Input shaper backport was not installed; the '
                              'stock files were restored.')
    return receipt


def _restore(printer):
    if tool.describe(tool.survey(printer)) == 'stock':
        return 0
    return tool.cmd_uninstall(printer, None)


def rollback(ctx, receipt):
    if (not isinstance(receipt, dict)
            or set(receipt) != {'kind', 'version', 'before'}
            or receipt['kind'] != RECEIPT_KIND
            or type(receipt['version']) is not int or receipt['version'] != 1
            or receipt['before'] not in ('stock', 'installed')):
        raise ctx.DeployError('Invalid input shaper recovery receipt')
    if receipt['before'] == 'installed':
        return
    if _run(ctx, _restore) != 0:
        raise ctx.DeployError('Stock input shaper files restored but Klipper '
                              'is not ready. Check klippy.log.')


def preflight_uninstall(ctx):
    def inspect(printer):
        states=tool.survey(printer)
        if tool.describe(states)=='stock':
            return 0
        if any(value not in ('stock','backport') for value in states.values()):
            raise tool.BackportError('Unknown input shaper files; no components removed')
        raw=printer.read(printer.state('manifest.json'))
        if raw is None:
            raise tool.BackportError('Missing stock input shaper originals')
        import json
        tool.stock_originals(printer,json.loads(raw.decode()))
        return 0
    _run(ctx,inspect)


def uninstall(ctx):
    if _run(ctx, tool.cmd_uninstall, None) != 0:
        raise ctx.DeployError('Stock input shaper files restored but Klipper '
                              'is not ready. Check klippy.log.')


def status(ctx):
    _run(ctx, tool.cmd_status, None)
