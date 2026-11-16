#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Install/restore the reviewed Moonraker responsiveness patch on the printer.

Run with the service-management privileges needed for moonraker.service. This
entry point never restarts Klipper, sends G-code, or changes print configuration.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))

import moonraker_directory_service as lifecycle
import moonraker_directory_transaction as tx


def diagnostic_value(value):
    """Bounded scalar diagnostics; never serialize status objects or payloads."""
    if value is None:
        return '<missing>'
    if isinstance(value, (str, int, float, bool)):
        return repr(value)[:80]
    return '<%s>' % type(value).__name__


class MoonrakerService:
    def __init__(self, request=None, run=None, sleep=None, clock=None):
        self.request = request or self._request
        self.run = run or subprocess.run
        self.sleep = sleep or time.sleep
        self.clock = clock or time.monotonic

    @staticmethod
    def _request(path):
        with urllib.request.urlopen('http://127.0.0.1:7125' + path, timeout=5) as response:
            return json.load(response)['result']

    def _stopped_backend(self):
        result = self.run(['systemctl', 'show', 'klipper.service',
                           '--property=LoadState', '--property=ActiveState', '--property=MainPID'],
                          check=True, timeout=10, stdout=subprocess.PIPE, text=True)
        properties = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
        if (properties.get('LoadState') == 'loaded'
                and properties.get('ActiveState') in ('inactive', 'failed')
                and properties.get('MainPID') == '0'):
            return {'process_id': 0, 'stopped': True}
        raise ValueError('Klipper status unavailable and service is not confirmed stopped; '
                         'LoadState=%s, ActiveState=%s, MainPID=%s. Check the printer or stop Klipper explicitly before repair'
                         % tuple(diagnostic_value(properties.get(key)) for key in ('LoadState', 'ActiveState', 'MainPID')))

    def inspect(self):
        try:
            info = self.request('/printer/info')
        except (OSError, ValueError, KeyError):
            return self._stopped_backend()
        pid = info.get('process_id')
        state = info.get('state')
        if type(pid) is not int or pid <= 0:
            return self._stopped_backend()
        if state not in ('ready', 'error', 'shutdown'):
            raise ValueError('Klipper is still starting or its state is unknown: /printer/info.state=' + diagnostic_value(state))
        if state == 'ready':
            status = self.request('/printer/objects/query?print_stats&pause_resume&virtual_sdcard')['status']
            job = status.get('print_stats', {}).get('state')
            paused = status.get('pause_resume', {}).get('is_paused')
            sd = status.get('virtual_sdcard', {})
            if (job not in ('standby', 'complete', 'cancelled', 'error')
                    or paused is not False or sd.get('is_active', False)):
                raise ValueError('Printer must be idle and not paused: print_stats.state=%r, '
                                 'pause_resume.is_paused=%r, virtual_sdcard.is_active=%r'
                                 % (job, paused, sd.get('is_active')))
        # Error/shutdown cannot run a print. Material receipts and metadata do
        # not determine whether Moonraker may restart; Klipper keeps executing
        # independently. Observe process continuity instead of freezing its data.
        baseline = {'process_id': pid}
        try:
            baseline['process_start'] = (Path('/proc') / str(pid) / 'stat').read_text(
                encoding='utf-8').rsplit(')', 1)[1].split()[19]
        except (OSError, IndexError):
            pass  # PID-only observation when /proc start identity is unavailable.
        return baseline

    def stop(self):
        self.run(['systemctl', 'stop', 'moonraker.service'], check=True, timeout=45)
        result = self.run(['systemctl', 'show', 'moonraker.service',
                           '--property=ActiveState', '--property=MainPID'],
                          check=True, timeout=10, stdout=subprocess.PIPE, text=True)
        properties = dict(line.split('=', 1) for line in result.stdout.splitlines())
        if properties.get('ActiveState') != 'inactive' or properties.get('MainPID') != '0':
            raise RuntimeError('Moonraker stop is unconfirmed; source was not published: ActiveState=%s, MainPID=%s'
                               % (diagnostic_value(properties.get('ActiveState')), diagnostic_value(properties.get('MainPID'))))

    def start(self):
        self.run(['systemctl', 'start', 'moonraker.service'], check=True, timeout=45)

    def verify(self, baseline):
        deadline = self.clock() + 90
        while True:
            try:
                self.request('/server/info')  # Confirm Moonraker itself returned.
                current = self.inspect()
            except (OSError, ValueError, KeyError) as error:
                if self.clock() >= deadline:
                    detail = str(error)[:240] if isinstance(error, (ValueError, KeyError)) else type(error).__name__
                    raise RuntimeError('Moonraker/backend observation did not return before the deadline: ' + detail)
                self.sleep(1)
                continue
            identity_fields = ('process_id', 'stopped', 'process_start')
            if any(current.get(key) != baseline.get(key) for key in identity_fields
                   if key in baseline or key != 'process_start'):
                changed = [key for key in identity_fields if (key in baseline or key != 'process_start') and current.get(key) != baseline.get(key)]
                raise RuntimeError('Klipper process identity changed during Moonraker restart: ' + ', '.join(changed))
            return


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'install', 'restore', 'recover', 'status'))
    parser.add_argument('--home', type=Path, required=True, help='Printer account home, e.g. /home/t13dp')
    parser.add_argument('--state', type=Path, required=True, help='Persistent transaction directory')
    parser.add_argument('--original-backup', type=Path, help='Explicitly adopt an already-patched source using its verified original')
    parser.add_argument('--patch', choices=('directory', 'http-error'), default='directory',
                        help='Reviewed source patch; use a separate state directory per patch')
    args = parser.parse_args(argv)
    relative = ('file_manager/file_manager.py' if args.patch == 'directory' else 'application.py')
    target = args.home / 'moonraker/moonraker/components' / relative
    try:
        if args.action in ('prepare', 'install'):
            tx.prepare(target, args.state, original_backup=args.original_backup)
            # Compile without writing pycache, using the actual service Python.
            subprocess.run([str(args.home / 'moonraker-env/bin/python'), '-c',
                            'import pathlib,sys;compile(pathlib.Path(sys.argv[1]).read_bytes(),sys.argv[1],"exec")',
                            str(tx.installed_path(args.state, tx.load_record(target, args.state)[0]))], check=True, timeout=15)
        if args.action in ('install', 'restore', 'recover'):
            lifecycle.execute(target, args.state, MoonrakerService(),
                              restore=args.action == 'restore', recover=args.action == 'recover')
        print(json.dumps({'source': tx.status(target, args.state),
                          'service_operation': lifecycle.read_operation(args.state)}))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
