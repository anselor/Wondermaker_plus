#!/usr/bin/env python3
"""Development-only, single-shot interruption of an explicitly bound recovery.

Run while monitoring the printer camera. Never starts a print or restarts services.
Without --stop-services it only captures the qualifying checkpoint.
"""
import argparse
import errno
import json
import time
from pathlib import Path


def read_execution(sftp, runtime_path, legacy_path):
    """Prefer current runtime evidence; only absence permits legacy lookup."""
    try:
        stream = sftp.open(runtime_path, 'rb')
    except OSError as error:
        if error.errno != errno.ENOENT:
            raise
        stream = sftp.open(legacy_path, 'rb')
    with stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError('Execution record exceeds limit')
    return raw


def decision(status, execution, *, attempt_id, session, filename, file_sha256):
    material = status['wm_material']
    attempt = material.get('recovery_attempt', {})
    request = attempt.get('request', {})
    if (material['session_id'] != session or request.get('id') != attempt_id
            or request.get('session') != session or request.get('file') != filename
            or material.get('afc_metadata', {}).get('owner') != 'standalone'):
        raise ValueError('Recovery identity or owner changed: '
                         + ', '.join(name for name, observed, expected in (
                             ('wm_material.session_id', material['session_id'], session),
                             ('recovery_attempt.request.id', request.get('id'), attempt_id),
                             ('recovery_attempt.request.session', request.get('session'), session),
                             ('recovery_attempt.request.file', request.get('file'), filename),
                             ('afc_metadata.owner', material.get('afc_metadata', {}).get('owner'), 'standalone'))
                                     if observed != expected))
    if status['webhooks']['state'] != 'ready':
        raise ValueError('Printer is not ready: webhooks.state must be ready')
    continuation = attempt.get('continuation', {}).get('state')
    if (attempt.get('state') in ('unknown', 'stopped', 'failed')
            or continuation in ('complete', 'cancelled', 'paused', 'unknown', 'interrupted')):
        raise ValueError('Recovery is no longer advancing: '
                         + ('recovery_attempt.state is terminal or unknown'
                            if attempt.get('state') in ('unknown', 'stopped', 'failed')
                            else 'recovery_attempt.continuation.state is terminal or interrupted'))
    if attempt.get('state') != 'complete' or continuation != 'started':
        return False
    if status['print_stats']['state'] != 'printing':
        raise ValueError('Resumed print is not active: print_stats.state must be printing')
    if (status['print_stats'].get('filename') != filename
            or not status['virtual_sdcard']['is_active']
            or status['pause_resume']['is_paused']):
        raise ValueError('Active job changed: '
                         + ', '.join(name for name, changed in (
                             ('print_stats.filename differs', status['print_stats'].get('filename') != filename),
                             ('virtual_sdcard.is_active is false', not status['virtual_sdcard']['is_active']),
                             ('pause_resume.is_paused is true', status['pause_resume']['is_paused'])) if changed))
    checkpoint = attempt['checkpoint']
    return (execution.get('state') == 'completed'
            and execution.get('session') == session
            and execution.get('job_fingerprint') == checkpoint['job_fingerprint']
            and execution.get('file', {}).get('path') == filename
            and execution.get('file', {}).get('sha256') == file_sha256
            and checkpoint['file_position'] < execution.get('file_position', -1)
            < execution.get('file', {}).get('size', 0))


def main():
    from types import SimpleNamespace
    from deploy import Context
    from components.preload import _checked
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('attempt-id', 'session', 'filename', 'file-sha256', 'output'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--timeout', type=float, default=240)
    parser.add_argument('--stop-services', action='store_true')
    parser.add_argument('--checkpoint-dir', help='Remote native recovery directory (default: ~/TM_T1/bin)')
    args = parser.parse_args()
    if not 0 < args.timeout <= 600:
        parser.error('timeout must be between 0 and 600 seconds')
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    binding = dict(attempt_id=args.attempt_id, session=args.session,
                   filename=args.filename, file_sha256=args.file_sha256)
    ctx = Context(SimpleNamespace())
    try:
        directory = args.checkpoint_dir or '/home/' + ctx.user + '/TM_T1/bin'
        path = directory.rstrip('/') + '/wmp_recovery_execution.json'
        legacy_path = '/home/' + ctx.user + '/printer_data/config/wmp_recovery_execution.json'
        query = '/printer/objects/query?webhooks&print_stats&pause_resume&virtual_sdcard&wm_material'
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            status = json.loads(ctx.moonraker(query))['result']['status']
            raw = read_execution(ctx.sftp(), path, legacy_path)
            execution = json.loads(raw)
            if decision(status, execution, **binding):
                # Recheck live identity immediately before the single mutation.
                status = json.loads(ctx.moonraker(query))['result']['status']
                if not decision(status, execution, **binding):
                    raise ValueError('Checkpoint no longer qualifies')
                (output / 'status.json').write_text(json.dumps(status, indent=2))
                (output / 'execution.json').write_bytes(raw)
                (output / 'intent.json').write_text(json.dumps(dict(binding, stop_services=args.stop_services)))
                if args.stop_services:
                    # Never retry this command if its reply times out.
                    result = _checked(ctx, ctx.ssh(),
                        'systemctl stop makerbase-client.service klipper.service',
                        sudo=True, timeout=45)
                    (output / 'stop-result.txt').write_text(result)
                print('New checkpoint captured; services stopped' if args.stop_services else 'New checkpoint captured; no mutation')
                return
            time.sleep(.25)
        raise TimeoutError('No qualifying checkpoint; no services stopped')
    finally:
        ctx.close()


if __name__ == '__main__':
    main()
