# SPDX-License-Identifier: GPL-3.0-or-later
"""Recoverable service lifecycle around a prepared directory patch transaction.

The adapter supplies inspect(), stop(), start(), and verify(baseline). inspect
must establish no active print (or a positively stopped/faulted backend) and
return a JSON-safe process identity baseline; verify must establish Moonraker
availability and unchanged Klipper process identity. stop must confirm the
service stopped before returning. The transaction lock spans every service call.
"""
import json

import moonraker_directory_transaction as tx


def checkpoint(directory, record, phase):
    record = dict(record, phase=phase)
    tx.atomic_write(directory / 'service.json', (json.dumps(record, sort_keys=True) + '\n').encode())
    return record


def read_operation(directory):
    path = directory / 'service.json'
    if not path.exists() and not path.is_symlink():
        return None
    raw, _ = tx.read_regular(path)
    value = json.loads(raw)
    if (not isinstance(value, dict)
            or set(value) != {'version', 'before', 'desired', 'baseline', 'phase'}
            or value['version'] != 1
            or value['before'] not in ('original', 'installed', 'previous')
            or value['desired'] not in ('original', 'installed', 'previous')
            or not isinstance(value['baseline'], dict)
            or value['phase'] not in ('prepared', 'stopped', 'published', 'started',
                                      'restoring', 'complete', 'recovered')):
        raise ValueError('Invalid Moonraker service operation receipt')
    return value


def recover_locked(target, directory, service, operation):
    # Journal before stopping: termination at any later instruction remains
    # recoverable. A failed observation never authorizes a competing operation.
    operation = checkpoint(directory, operation, 'restoring')
    service.stop()
    tx.publish(target, directory, restore=operation['before'] == 'original',
               previous=operation['before'] == 'previous')
    service.start()
    service.verify(operation['baseline'])
    checkpoint(directory, operation, 'recovered')


def execute(target, directory, service, *, restore=False, recover=False, previous=False):
    """Apply/restore prepared source; explicitly recover interrupted operations.

Caller must use tx.prepare before first use. No automatic process retries: a
    live operation owns the file lock, including while waiting for the service.
    """
    with tx.locked(target, directory) as (target, directory):
        _, original, installed = tx.load_record(target, directory)
        current, _ = tx.read_regular(target)
        if current not in tx.source_versions(target, directory).values():
            raise ValueError('Refusing to overwrite changed Moonraker source')
        operation = read_operation(directory)
        pending = operation is not None and operation['phase'] not in ('complete', 'recovered')
        if recover:
            if pending:
                recover_locked(target, directory, service, operation)
                return True
            return False
        if pending:
            raise ValueError('Interrupted Moonraker operation needs explicit recovery')
        baseline = service.inspect()
        if not isinstance(baseline, dict):
            raise ValueError('Invalid service baseline')
        before = tx.source_state(target, directory, current)
        desired = 'previous' if previous else 'original' if restore else 'installed'
        if before == desired:
            service.verify(baseline)
            return False
        operation = checkpoint(directory, dict(version=1, before=before,
                                               desired=desired, baseline=baseline), 'prepared')
        try:
            service.stop()
            operation = checkpoint(directory, operation, 'stopped')
            tx.publish(target, directory, restore=restore, previous=previous)
            operation = checkpoint(directory, operation, 'published')
            service.start()
            operation = checkpoint(directory, operation, 'started')
            service.verify(baseline)
            checkpoint(directory, operation, 'complete')
        except Exception as error:
            # If stop failed, its outcome is uncertain: preserve receipt and let
            # explicit recovery observe/stop the service. Do not publish anything.
            if operation['phase'] == 'prepared':
                raise
            try:
                recover_locked(target, directory, service, operation)
            except Exception as recovery_error:
                raise RuntimeError('Moonraker recovery remains unconfirmed: ' + str(recovery_error)) from error
            raise
        return True
