# SPDX-License-Identifier: GPL-3.0-or-later
"""Durable probe and calibration save evidence; never replay a write."""
import logging

import hashlib

import json

import math

import copy

import configparser

import io

import re


import os

import tempfile

import fcntl

from contextlib import contextmanager


class ProbeSaveRecord:
    """Durable evidence, never an instruction to replay a configuration write."""
    LIMIT = 1024 * 1024

    def __init__(self, path):
        self.path = os.path.abspath(path)

    @staticmethod
    def _payload(record):
        if (not isinstance(record, dict) or set(record) != {
                'version', 'session', 'request', 'config_path', 'section',
                'offset', 'autosave', 'before_sha256'}
                or type(record['version']) is not int or record['version'] != 1):
            raise ValueError('Invalid probe save evidence')
        for key in ('session', 'request'):
            if not isinstance(record[key], str) or not re.fullmatch('[0-9a-f]{32}', record[key]):
                raise ValueError('Invalid probe save identity')
        if (not isinstance(record['config_path'], str) or not os.path.isabs(record['config_path'])
                or not isinstance(record['section'], str) or not record['section']
                or not isinstance(record['offset'], str)
                or not math.isfinite(float(record['offset']))
                or not isinstance(record['before_sha256'], str)
                or not re.fullmatch('[0-9a-f]{64}', record['before_sha256'])):
            raise ValueError('Invalid probe save configuration identity')
        autosave = record['autosave']
        if not isinstance(autosave, dict) or not all(
                isinstance(section, str) and isinstance(values, dict)
                and all(isinstance(k, str) and isinstance(v, str) for k, v in values.items())
                for section, values in autosave.items()):
            raise ValueError('Invalid probe save configuration snapshot')
        if autosave.get(record['section'], {}).get('z_offset') != record['offset']:
            raise ValueError('Probe save offset does not match snapshot')
        return json.dumps(record, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()

    def read(self):
        try:
            with open(self.path, 'rb') as stream:
                raw = stream.read(self.LIMIT + 1)
        except FileNotFoundError:
            return None
        if len(raw) > self.LIMIT:
            raise ValueError('Probe save evidence is too large')
        try:
            envelope = json.loads(raw)
            if not isinstance(envelope, dict) or set(envelope) != {'record', 'sha256'}:
                raise ValueError('Invalid probe save evidence envelope')
            record = envelope['record']
            payload = self._payload(record)
            if hashlib.sha256(payload).hexdigest() != envelope['sha256']:
                raise ValueError('Probe save evidence checksum mismatch')
            return record
        except (TypeError, KeyError, OverflowError) as error:
            raise ValueError('Invalid probe save evidence') from error

    @contextmanager
    def _lock(self):
        with open(self.path + '.lock', 'a+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield

    @staticmethod
    def _digest(record):
        return hashlib.sha256(ProbeSaveRecord._payload(record)).hexdigest()

    def acknowledged(self, record):
        digest = self._digest(record)
        try:
            with open(self.path + '.' + digest + '.ack', 'rb') as stream:
                raw = stream.read(4097)
        except FileNotFoundError:
            return False
        if len(raw) > 4096:
            raise ValueError('Invalid probe save acknowledgement')
        ack = json.loads(raw)
        retained = isinstance(ack, dict) and ack.get('version') == 2
        keys = {'version', 'record_sha256', 'review'} | ({'retained_offset'} if retained else set())
        if (not isinstance(ack, dict) or set(ack) != keys
                or type(ack['version']) is not int or ack['version'] not in (1, 2)
                or ack['record_sha256'] != digest or not isinstance(ack['review'], str)
                or not re.fullmatch('[0-9a-f]{64}', ack['review'])):
            raise ValueError('Invalid probe save acknowledgement')
        if retained:
            offset = ack['retained_offset']
            if not isinstance(offset, str) or len(offset) > 64 or not math.isfinite(float(offset)):
                raise ValueError('Invalid retained probe offset')
        return True

    def _publish(self, path, payload, replace=False):
        parent = os.path.dirname(path)
        fd, temporary = tempfile.mkstemp(prefix='.wmp-probe-save-', dir=parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            if replace:
                os.replace(temporary, path)
            else:
                os.link(temporary, path)
            directory = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def create(self, record, replace_history=False):
        payload = self._payload(record)
        envelope = json.dumps({'record': record, 'sha256': hashlib.sha256(payload).hexdigest()},
                              sort_keys=True, allow_nan=False).encode()
        if len(envelope) > self.LIMIT:
            raise ValueError('Probe save evidence is too large')
        with self._lock():
            if replace_history:
                # Evidence is diagnostic. Preserve the previous bytes if possible,
                # but a missing ACK or damaged record cannot forbid a new save.
                try:
                    with open(self.path, 'rb') as stream:
                        previous_bytes = stream.read(self.LIMIT + 1)
                    archive = self.path + '.' + hashlib.sha256(previous_bytes).hexdigest() + '.record'
                    if not os.path.exists(archive):
                        self._publish(archive, previous_bytes)
                except FileNotFoundError:
                    pass
                except Exception:
                    logging.exception('Unable to archive previous probe save evidence')
                self._publish(self.path, envelope, replace=True)
                return
            previous = self.read()
            if previous is not None:
                if not self.acknowledged(previous):
                    raise FileExistsError('Resolve previous probe save evidence first')
                if previous == record:
                    raise ValueError('A new probe save request is required')
                archive = ProbeSaveRecord(self.path + '.' + self._digest(previous) + '.record')
                archived = archive.read()
                if archived is None:
                    archive.create(previous)
                elif archived != previous:
                    raise ValueError('Probe save archive changed')
                if self.read() != previous:
                    raise ValueError('Probe save evidence changed before publication')
            self._publish(self.path, envelope, replace=previous is not None)

    def acknowledge(self, config_path, disk_autosave, loaded_config, pending, review, retain=False):
        with self._lock():
            current = self.review(config_path, disk_autosave, loaded_config, pending)
            if current is None or current['review'] != review:
                raise ValueError('Probe save review changed; review it again')
            if not retain and not current['configuration_matches']:
                raise ValueError('Current configuration does not match the recorded save')
            if retain and not current['retainable']:
                raise ValueError('Current configuration is not eligible for retention')
            record = current['record']
            if self.acknowledged(record):
                directory = os.open(os.path.dirname(self.path), os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
                return  # Lost reply: retain and durably confirm the original acknowledgement.
            digest = self._digest(record)
            ack = {'version': 1, 'record_sha256': digest, 'review': review}
            if retain:
                ack.update(version=2, retained_offset=current['loaded_offset'])
            self._publish(self.path + '.' + digest + '.ack', json.dumps(ack, sort_keys=True).encode())

    def review(self, config_path, disk_autosave, loaded_config, pending):
        record = self.read()
        if record is None:
            return None
        if os.path.abspath(config_path) != record['config_path']:
            raise ValueError('Probe save evidence belongs to a different configuration')
        if not isinstance(loaded_config, dict) or not isinstance(pending, dict):
            raise ValueError('Loaded probe configuration evidence is unavailable')
        matches = disk_autosave == record['autosave'] and not pending
        matches = matches and all(
            isinstance(loaded_config.get(section), dict) and loaded_config[section].get(key) == value
            for section, values in record['autosave'].items() for key, value in values.items())
        # An explicit retention choice covers only a changed probe offset. Other
        # calibration changes, pending edits or unloaded disk values remain held.
        loaded_offset = loaded_config.get(record['section'], {}).get('z_offset')
        valid_offset = False
        try:
            valid_offset = isinstance(loaded_offset, str) and len(loaded_offset) <= 64 and math.isfinite(float(loaded_offset))
        except (ValueError, OverflowError):
            pass
        expected = copy.deepcopy(record['autosave'])
        expected[record['section']]['z_offset'] = loaded_offset
        retainable = bool(valid_offset and not pending and loaded_offset != record['offset']
                          and disk_autosave == expected and all(
                              isinstance(loaded_config.get(section), dict)
                              and all(loaded_config[section].get(key) == value for key, value in values.items())
                              for section, values in disk_autosave.items()))
        differences, difference_count = [], 0
        for section in sorted(set(record['autosave']) | set(disk_autosave)):
            recorded_values = record['autosave'].get(section, {})
            disk_values = disk_autosave.get(section, {})
            loaded_values = loaded_config.get(section, {})
            for key in sorted(set(recorded_values) | set(disk_values)):
                recorded, disk = recorded_values.get(key), disk_values.get(key)
                loaded = loaded_values.get(key) if isinstance(loaded_values, dict) else None
                if recorded == disk == loaded:
                    continue
                difference_count += 1
                if len(differences) < 8:
                    differences.append({'section': section[:128], 'key': key[:128],
                                        'recorded': None if recorded is None else str(recorded)[:128],
                                        'disk': None if disk is None else str(disk)[:128],
                                        'loaded': None if loaded is None else str(loaded)[:128]})
        snapshot = [record, config_path, disk_autosave, loaded_config, pending]
        review = hashlib.sha256(json.dumps(snapshot, sort_keys=True, allow_nan=False).encode()).hexdigest()
        return {'record': record, 'configuration_matches': bool(matches), 'review': review,
                'loaded_offset': loaded_offset if valid_offset else None, 'retainable': retainable,
                'differences': differences, 'difference_count': difference_count, 'pending_changes': bool(pending),
                'outcome': 'acknowledged' if self.acknowledged(record) else 'review_required'}


class CalibrationSaveRecord(ProbeSaveRecord):
    """Last bound maintenance save; evidence only, never automatic replay."""
    @staticmethod
    def _payload(record):
        if (not isinstance(record, dict) or set(record) != {
                'version', 'session', 'request', 'config_path', 'autosave', 'state'}
                or type(record['version']) is not int or record['version'] != 1
                or record['state'] not in ('pending', 'saved')):
            raise ValueError('Invalid calibration save evidence')
        for key in ('session', 'request'):
            if not isinstance(record[key], str) or not re.fullmatch('[0-9a-f]{32}', record[key]):
                raise ValueError('Invalid calibration save identity')
        if not isinstance(record['config_path'], str) or not os.path.isabs(record['config_path']):
            raise ValueError('Invalid calibration save path')
        values = record['autosave']
        if (not isinstance(values, dict) or not values or not all(
                isinstance(section, str) and section and isinstance(items, dict) and items
                and all(isinstance(k, str) and isinstance(v, str) for k, v in items.items())
                for section, items in values.items())):
            raise ValueError('Invalid calibration save values')
        return json.dumps(record, sort_keys=True, allow_nan=False, separators=(',', ':')).encode()

    def write(self, record):
        payload = self._payload(record)
        envelope = json.dumps({'record': record, 'sha256': hashlib.sha256(payload).hexdigest()},
                              sort_keys=True, allow_nan=False).encode()
        if len(envelope) > self.LIMIT:
            raise ValueError('Calibration save evidence is too large')
        self._publish(self.path, envelope, replace=True)

    def discard(self):
        # A publication may have succeeded before directory fsync raised.
        # Do not leave positive evidence after a reported receipt-write error.
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        directory = os.open(os.path.dirname(self.path), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def verify(self, record, path, disk, loaded, pending):
        self._payload(record)
        # SAVE_CONFIG serializes ConfigParser values and Klipper parses them
        # again on restart. Multiline mesh values lose continuation indentation
        # in that round trip. Compare the expected *loaded* representation,
        # without weakening numerical/value checks or changing journal bytes.
        # This also verifies receipts written before this normalization existed.
        source = configparser.RawConfigParser(strict=False, inline_comment_prefixes=(';', '#'))
        source.read_dict(record['autosave'])
        serialized = io.StringIO()
        source.write(serialized)
        parsed = configparser.RawConfigParser(strict=False, inline_comment_prefixes=(';', '#'))
        parsed.read_string(serialized.getvalue())
        expected = {section: dict(parsed.items(section, raw=True)) for section in parsed.sections()}
        return (record['state'] == 'saved' and os.path.realpath(path) == record['config_path']
                and not pending and disk == expected
                and all(isinstance(loaded.get(section), dict)
                        and all(loaded[section].get(key) == value for key, value in items.items())
                        for section, items in expected.items()))


