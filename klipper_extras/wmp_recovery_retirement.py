# SPDX-License-Identifier: GPL-3.0-or-later
"""Raw recovery evidence preservation; no machine commands or record deletion.

This layer does not authorize retirement. The caller must bind review to its
session and hold command ownership, and supply admission checks during archive
publication. Publishing an archive alone never disables recovery.
"""
import configparser
import hashlib
import json
import os
import re
import stat
import tempfile


class ArchiveUnavailable(ValueError):
    """Diagnostic archive cannot be preserved; current evidence remains binding."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode('ascii')


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def identity(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


def disabled_offer(raw):
    """Disable only the exact reviewed native flag; preserve all other bytes."""
    if raw is None:
        return None
    parser = configparser.ConfigParser(interpolation=None)
    try:
        parser.read_string(raw.decode('utf-8'))
        if parser.defaults() or parser.sections() != ['plr_print']:
            raise ValueError('Unrecognized native recovery offer')
        flag = parser.get('plr_print', 'was_interrupted')
        if flag == 'False':
            return raw
        if flag != 'True' or not parser.get('plr_print', 'plr_file').strip():
            raise ValueError('Unrecognized native recovery offer')
    except configparser.Error as error:
        raise ValueError('Unrecognized native recovery offer: ' + str(error)) from error
    result, count = re.subn(rb'(?m)^(\s*was_interrupted\s*=\s*)True([ \t]*\r?$)',
                            rb'\g<1>False\2', raw)
    if count != 1:
        raise ValueError('Unrecognized native recovery offer flag')
    return result


def read_file(path, limit):
    """Only ENOENT means absent; preserve empty and non-JSON regular files."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return {'present': False}, None
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size > limit:
            raise ValueError('Recovery evidence must be a bounded regular file')
        payload = stream.read(limit + 1)
        if (len(payload) != before.st_size
                or identity(os.fstat(stream.fileno())) != identity(before)
                or identity(os.stat(path, follow_symlinks=False)) != identity(before)):
            raise ValueError('Recovery evidence changed while reading')
    return {'present': True, 'identity': identity(before),
            'sha256': hashlib.sha256(payload).hexdigest()}, payload


def runtime_evidence_path(legacy, runtime):
    """Only absence permits legacy evidence; other read errors stay explicit."""
    try:
        os.lstat(runtime)
    except FileNotFoundError:
        return legacy
    return runtime


class EvidenceStore:
    def __init__(self, managed_directory, checkpoint_directory, runtime_directory=None):
        # Paths come from server configuration, never from a review request.
        self.directory = os.path.abspath(managed_directory)
        checkpoint_directory = os.path.abspath(checkpoint_directory)
        self.files = {
            name: (os.path.join(self.directory, filename), 65536)
            for name, filename in (
                ('job', 'wmp_recovery_job.json'),
                ('execution', 'wmp_recovery_execution.json'),
                ('attempt', 'wmp_recovery_attempt.json'),
                ('envelope', 'wmp_recovery_envelope.json'))}
        if runtime_directory is not None:
            for name in ('execution', 'envelope'):
                legacy, limit = self.files[name]
                runtime = os.path.join(os.path.abspath(runtime_directory), os.path.basename(legacy))
                self.files[name] = (runtime_evidence_path(legacy, runtime), limit)
        for suffix in ('A', 'B'):
            filename = 'plr_data%s.ini' % suffix
            self.files['checkpoint_' + suffix] = (os.path.join(checkpoint_directory, filename), 65536)
            self.files['coordinates_' + suffix] = (os.path.join(checkpoint_directory, filename + '.wmp-coordinates'), 256)
        self.files['offer'] = (os.path.join(checkpoint_directory, 'plr.ini'), 65536)

    def _collect(self):
        records, payloads = {}, {}
        for name, (path, limit) in sorted(self.files.items()):
            records[name], payloads[name] = read_file(path, limit)
        return {'version': 1, 'records': records}, payloads

    def snapshot(self):
        manifest, payloads = self._collect()
        repeated, repeated_payloads = self._collect()
        if manifest != repeated or payloads != repeated_payloads:
            raise ValueError('Recovery evidence changed during review')
        return manifest, payloads

    def review(self):
        manifest, _ = self.snapshot()
        receipt, _ = read_file(self.receipt_path, 16384)
        return {'manifest': manifest, 'fingerprint': fingerprint(manifest), 'receipt': receipt}

    @property
    def receipt_path(self):
        return os.path.join(self.directory, 'wmp_recovery_retirement.json')

    def archive(self, expected, admit):
        """Preserve reviewed bytes; admit must raise if ownership is lost."""
        admit()
        manifest, payloads = self.snapshot()
        if (self.review() != expected or expected.get('manifest') != manifest
                or expected.get('fingerprint') != fingerprint(manifest)):
            raise ValueError('Recovery evidence changed after review')
        payload = canonical({'version': 1, 'manifest': manifest,
                             'records': {key: None if value is None else value.hex()
                                         for key, value in payloads.items()}})
        digest = hashlib.sha256(payload).hexdigest()
        path = os.path.join(self.directory, 'wmp_recovery_retirement_archive_' + digest + '.json')
        fd, temporary = tempfile.mkstemp(prefix='.wmp-retirement-', dir=self.directory)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            admit()
            if self.review() != expected:
                raise ValueError('Recovery evidence changed before archival')
            try:
                os.link(temporary, path)
            except FileExistsError:
                if read_file(path, 1000000)[1] != payload:
                    raise ArchiveUnavailable('Recovery archive conflicts with preserved evidence')
            directory = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            if read_file(path, 1000000)[1] != payload:
                raise ArchiveUnavailable('Recovery archive readback differs')
            admit()
            if self.review() != expected:
                raise ValueError('Recovery evidence changed during archival')
            return {'archive': digest, 'fingerprint': expected['fingerprint']}
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def retirement(self, *, attempt_only=False):
        """Return verified durable evidence and whether it matches current files.

        A damaged receipt/archive raises; it never means 'no receipt' or grants
        authority to skip normal recovery restoration/admission.
        """
        receipt_info, payload = read_file(self.receipt_path, 16384)
        if payload is None:
            return None
        receipt = json.loads(payload)
        if isinstance(receipt, dict) and receipt.get('version') == 3:
            return self._unarchived_retirement(receipt, receipt_info, payload, attempt_only)
        if (not isinstance(receipt, dict) or set(receipt) not in ({
                'version', 'id', 'session', 'archive', 'fingerprint'}, {
                'version', 'id', 'session', 'archive', 'fingerprint', 'offer_after'})
                or type(receipt['version']) is not int
                or receipt['version'] != (2 if 'offer_after' in receipt else 1)
                or any(not isinstance(receipt[key], str) or not re.fullmatch(pattern, receipt[key])
                       for key, pattern in (('id', r'[A-Za-z0-9_-]{1,64}'),
                                            ('session', r'[A-Za-z0-9_-]{1,64}'),
                                            ('archive', r'[0-9a-f]{64}'),
                                            ('fingerprint', r'[0-9a-f]{64}')))):
            raise ValueError('Invalid recovery retirement receipt')
        path = os.path.join(self.directory, 'wmp_recovery_retirement_archive_' + receipt['archive'] + '.json')
        _, raw = read_file(path, 1000000)
        if raw is None or hashlib.sha256(raw).hexdigest() != receipt['archive']:
            raise ValueError('Recovery retirement archive is missing or changed')
        archive = json.loads(raw)
        if (not isinstance(archive, dict) or set(archive) != {'version', 'manifest', 'records'}
                or type(archive['version']) is not int or archive['version'] != 1
                or fingerprint(archive['manifest']) != receipt['fingerprint']):
            raise ValueError('Recovery retirement archive binding is invalid')
        manifest, records = archive['manifest'], archive['records']
        names = set(self.files)
        if (not isinstance(manifest, dict) or set(manifest) != {'version', 'records'}
                or type(manifest['version']) is not int or manifest['version'] != 1
                or not isinstance(manifest['records'], dict) or not isinstance(records, dict)
                or set(records) not in (names, names - {'offer'})
                or set(manifest['records']) != set(records)
                or any(value is not None and (not isinstance(value, str)
                    or len(value) > 131072 or len(value) % 2
                    or re.fullmatch(r'[0-9a-f]*', value) is None) for value in records.values())):
            raise ValueError('Invalid recovery retirement archive records')
        current, data = self.snapshot()
        expected_manifest = archive['manifest']
        expected_data = archive['records']
        if receipt['version'] == 2:
            if not isinstance(records.get('offer'), str):
                raise ValueError('Retired native offer has no original bytes')
            original = bytes.fromhex(archive['records']['offer'])
            after = disabled_offer(original)
            info = receipt['offer_after']
            if (after == original or not isinstance(info, dict)
                    or set(info) != {'present', 'identity', 'sha256'} or info['present'] is not True
                    or not isinstance(info['identity'], list) or len(info['identity']) != 5
                    or any(type(v) is not int or v < 0 for v in info['identity'])
                    or info['identity'][2] != len(after)
                    or info['sha256'] != hashlib.sha256(after).hexdigest()):
                raise ValueError('Invalid retired native offer binding')
            expected_manifest = dict(expected_manifest,
                records=dict(expected_manifest['records'], offer=info))
            expected_data = dict(expected_data, offer=after.hex())
        # Older archives predate offer capture. They can still retire the exact
        # old evidence when no offer exists, but cannot authorize a newly found
        # native prompt. Keep the attempt-only rule below scoped to the attempt.
        compared, compared_data = current, data
        if ('offer' not in archive['manifest']['records']
                and 'offer' not in archive['records'] and data['offer'] is None):
            compared = dict(current, records={k: v for k, v in current['records'].items() if k != 'offer'})
            compared_data = {k: v for k, v in data.items() if k != 'offer'}
        matches = compared == expected_manifest
        if (matches and receipt['version'] == 1 and data['offer'] is not None
                and disabled_offer(data['offer']) != data['offer']):
            # An archival-only receipt from the earlier writer did not clear
            # this prompt. Require a new explicit review rather than declaring
            # complete or silently extending that old confirmation.
            matches = False
        if attempt_only:
            # An unchanged retired attempt must not come back to life when a
            # new job replaces other files. This grants no retirement of that
            # new job or its execution checkpoint.
            matches = (current['records']['attempt'] == archive['manifest']['records']['attempt'])
            if matches and archive['records']['attempt'] != (None if data['attempt'] is None else data['attempt'].hex()):
                raise ValueError('Recovery retirement attempt bytes differ')
        if matches and not attempt_only and expected_data != {key: None if value is None else value.hex()
                                               for key, value in compared_data.items()}:
            raise ValueError('Recovery retirement archive bytes differ')
        if read_file(self.receipt_path, 16384) != (receipt_info, payload):
            raise ValueError('Recovery retirement receipt changed during verification')
        return dict(receipt, matches=matches)

    def _unarchived_retirement(self, receipt, receipt_info, payload, attempt_only):
        """Verify explicit retirement without claiming an archive was preserved."""
        if (set(receipt) != {'version', 'id', 'session', 'fingerprint', 'manifest',
                            'retired_manifest', 'archive_warning'}
                or type(receipt['version']) is not int
                or any(not isinstance(receipt[k], str) or not re.fullmatch(pattern, receipt[k])
                       for k, pattern in (('id', r'[A-Za-z0-9_-]{1,64}'),
                                          ('session', r'[A-Za-z0-9_-]{1,64}'),
                                          ('fingerprint', r'[0-9a-f]{64}')))
                or not isinstance(receipt['archive_warning'], str)
                or not 0 < len(receipt['archive_warning']) <= 512):
            raise ValueError('Invalid unarchived recovery retirement receipt')
        current, data = self.snapshot()
        for manifest in (receipt['manifest'], receipt['retired_manifest']):
            if (not isinstance(manifest, dict) or set(manifest) != {'version', 'records'}
                    or manifest['version'] != 1 or not isinstance(manifest['records'], dict)
                    or set(manifest['records']) != set(self.files)):
                raise ValueError('Invalid unarchived retirement manifest')
            for info in manifest['records'].values():
                if (not isinstance(info, dict) or set(info) not in ({'present'}, {'present', 'identity', 'sha256'})
                        or type(info['present']) is not bool
                        or set(info) != ({'present', 'identity', 'sha256'} if info['present'] else {'present'})
                        or (info['present'] and (not isinstance(info['identity'], list)
                            or len(info['identity']) != 5
                            or any(type(v) is not int or v < 0 for v in info['identity'])
                            or not isinstance(info['sha256'], str)
                            or not re.fullmatch(r'[0-9a-f]{64}', info['sha256'])))
                        or (not info['present'] and set(info) != {'present'})):
                    raise ValueError('Invalid unarchived retirement record binding')
        original, retired = receipt['manifest'], receipt['retired_manifest']
        if (fingerprint(original) != receipt['fingerprint']
                or any(original['records'][k] != retired['records'][k] for k in self.files if k != 'offer')):
            raise ValueError('Unarchived retirement changed unrelated evidence')
        matches = current == retired
        if attempt_only:
            matches = current['records']['attempt'] == retired['records']['attempt']
        elif matches and data['offer'] is not None and disabled_offer(data['offer']) != data['offer']:
            matches = False
        if read_file(self.receipt_path, 16384) != (receipt_info, payload):
            raise ValueError('Recovery retirement receipt changed during verification')
        return dict(receipt, matches=matches)

    def retire(self, expected, request_id, session, admit):
        """Explicit caller-authorized retirement with best-effort archival.

        Caller owns the command mutex. A result lost after publication is read
        back, never inferred from the request or replayed machine actions.
        """
        for value in (request_id, session):
            if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value):
                raise ValueError('Invalid recovery retirement identity')
        admit()
        try:
            previous = self.retirement()
        except (ValueError, OSError):
            # A fresh explicit review binds even a corrupt historical receipt.
            # Publication below still verifies its exact reviewed bytes.
            previous = None
        if previous is not None and previous['id'] == request_id:
            if (previous['session'] != session or not previous['matches']
                    or previous['fingerprint'] != expected.get('fingerprint')):
                raise ValueError('Recovery retirement request identity was reused')
            return previous
        try:
            archived = self.archive(expected, admit)
            receipt = dict(archived, version=1, id=request_id, session=session)
        except (OSError, ArchiveUnavailable) as error:
            # Keep normal evidence binding and required publication below. An
            # unavailable diagnostic archive does not prohibit explicit discard.
            receipt = dict(version=3, id=request_id, session=session,
                           fingerprint=expected['fingerprint'], manifest=expected['manifest'],
                           retired_manifest=expected['manifest'], archive_warning=str(error)[:512] or 'Archive unavailable')
        publication_review = expected
        manifest, raw = self.snapshot()
        if self.review() != expected:
            raise ValueError('Recovery evidence changed before offer retirement')
        after = disabled_offer(raw['offer'])
        if after != raw['offer']:
            self._clear_offer(expected, after, admit)
            publication_review = self.review()
            current, current_raw = self.snapshot()
            if (publication_review['manifest'] != current
                    or publication_review['receipt'] != expected['receipt']
                    or {k: v for k, v in current['records'].items() if k != 'offer'} !=
                       {k: v for k, v in manifest['records'].items() if k != 'offer'}
                    or current_raw != dict(raw, offer=after)):
                raise ValueError('Recovery evidence changed during offer retirement; review again')
            if receipt['version'] == 3:
                receipt['retired_manifest'] = current
            else:
                receipt.update(version=2, offer_after=current['records']['offer'])
        payload = canonical(receipt)
        fd, temporary = tempfile.mkstemp(prefix='.wmp-retirement-receipt-', dir=self.directory)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            admit()
            if self.review() != publication_review:
                raise ValueError('Recovery evidence or receipt changed before retirement')
            os.replace(temporary, self.receipt_path)
            directory = os.open(self.directory, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            admit()
            result = self.retirement()
            if result != dict(receipt, matches=True):
                raise ValueError('Recovery retirement publication was not confirmed')
            return result
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _clear_offer(self, expected, after, admit):
        path, limit = self.files['offer']
        admit()
        if self.review() != expected:
            raise ValueError('Native recovery offer changed before discard')
        fd, temporary = tempfile.mkstemp(prefix='.wmp-retirement-offer-', dir=os.path.dirname(path))
        try:
            with os.fdopen(fd, 'wb') as stream:
                os.fchmod(stream.fileno(), stat.S_IMODE(os.stat(path, follow_symlinks=False).st_mode))
                stream.write(after)
                stream.flush()
                os.fsync(stream.fileno())
            admit()
            if self.review() != expected:
                raise ValueError('Recovery evidence changed during offer discard')
            os.replace(temporary, path)
            directory = os.open(os.path.dirname(path), os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            admit()
            if read_file(path, limit)[1] != after:
                raise ValueError('Native recovery offer discard was not confirmed')
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
