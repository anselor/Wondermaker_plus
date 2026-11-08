"""Verify the head guard in the running stock screen before a controller restart.

This module uses only the standard library so the installer can run the same
checks over SSH without installing another printer-side helper.
"""
import os
from pathlib import Path
import re
import struct
import time


class GuardNotReady(RuntimeError):
    pass


def guard_profiles(source):
    """Read entry addresses from the guard's actual C profiles."""
    rows = re.findall(
        r'\{"([^"]+)",\s*\d+,\s*UINT64_C\(0x[0-9a-f]+\),\s*(0x[0-9a-f]+)\}',
        source)
    if not rows:
        raise ValueError('Head-configuration guard profiles are missing')
    return {version: int(entry, 16) for version, entry in rows}


def _started(proc):
    # comm (field 2) can contain spaces or parentheses. starttime is field 22.
    return proc.joinpath('stat').read_text().rpartition(')')[2].split()[19]


def verify_once(home, profiles, proc_root='/proc',
                log_path='/tmp/wmp_head-config-guard.log'):
    expected_exe = str(Path(home) / 'TM_T1/bin/client')
    candidates = []
    for proc in Path(proc_root).iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if os.readlink(proc / 'exe') == expected_exe:
                candidates.append(proc)
        except OSError:
            continue
    if len(candidates) != 1:
        raise GuardNotReady('Expected one running stock screen client, found %d' % len(candidates))
    proc = candidates[0]
    started = _started(proc)
    if b'WMP_REQUIRE_HEAD_CONFIG_GUARD=1' not in proc.joinpath('environ').read_bytes().split(b'\0'):
        raise GuardNotReady('The screen service does not require head-guard activation')
    with open(log_path, 'rb') as stream:
        stream.seek(0, os.SEEK_END)
        stream.seek(max(0, stream.tell() - 131072))
        log = stream.read().decode('utf-8', 'replace')
    applied = re.findall(
        r'^\[pid ' + re.escape(proc.name) + r'\] client ([^:]+): '
        r'destructive head reset blocked; communication faults keep Klipper stopped$',
        log, re.M)
    if not applied or applied[-1] not in profiles:
        raise GuardNotReady('No successful head-guard activation for the running screen client')
    entry = profiles[applied[-1]]
    with proc.joinpath('mem').open('rb', buffering=0) as memory:
        memory.seek(entry)
        jump = memory.read(16)
    if len(jump) != 16:
        raise GuardNotReady('Could not read the live head-reset callback')
    load, branch, target = struct.unpack('<IIQ', jump)
    if (load, branch) != (0x58000050, 0xd61f0200):
        raise GuardNotReady('The live head-reset callback is not guarded')
    library = Path(home) / 'wmp/lib/libwmp_head-config-guard.so'
    metadata = library.stat()
    protected = False
    for line in proc.joinpath('maps').read_text().splitlines():
        fields = line.split(None, 5)
        if len(fields) != 6:
            continue
        region, permissions, _, device, inode, path = fields
        low, high = (int(value, 16) for value in region.split('-'))
        major, minor = (int(value, 16) for value in device.split(':'))
        if (low <= target < high and 'x' in permissions
                and path == str(library.resolve())
                and int(inode) == metadata.st_ino
                and (major, minor) == (os.major(metadata.st_dev), os.minor(metadata.st_dev))):
            protected = True
            break
    if not protected:
        raise GuardNotReady('The callback does not target the installed head-guard library')
    if _started(proc) != started or os.readlink(proc / 'exe') != expected_exe:
        raise GuardNotReady('The screen process changed during head-guard verification')
    return {'pid': int(proc.name), 'version': applied[-1]}


def wait_for_guard(home, profiles, timeout=30.):
    deadline = time.monotonic() + timeout
    while True:
        try:
            return verify_once(home, profiles)
        except (OSError, ValueError, IndexError, GuardNotReady) as error:
            if time.monotonic() >= deadline:
                raise RuntimeError('Head-configuration protection could not be verified: %s' % error)
        time.sleep(.5)
