# SPDX-License-Identifier: GPL-3.0-or-later
"""Read and save physical WM nozzle settings without motion or a restart.

Keep the vendor's storage locations so its other screens continue to agree.
The caller serializes saves and checks printer admission. A revision covers
both complete files; a stale draft must never overwrite a newer edit.
"""
import hashlib
import math
import os
from pathlib import Path
import re
import stat
import tempfile

MATERIALS = ("Hardened steel", "Stainless steel")
DIAMETERS = (0.2, 0.4, 0.6, 0.8)


def _read(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Nozzle configuration must be a regular file")
    with path.open("rb") as stream:
        raw = stream.read(2 * 1024 * 1024 + 1)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("Nozzle configuration is too large")
    return raw.decode("utf-8")


def _setting(text, section, key, delimiter):
    lines = text.splitlines(keepends=True)
    section_start = None
    section_end = len(lines)
    current = None
    found = []
    for index, line in enumerate(lines):
        header = re.fullmatch(r"\s*\[([^\]]+)\]\s*(?:[#;].*)?", line.rstrip("\r\n"))
        if header:
            if current == section:
                section_end = index
            current = header[1].strip()
            if current == section:
                if section_start is not None:
                    raise ValueError("Duplicate nozzle configuration section")
                section_start = index
        if current == section:
            match = re.fullmatch(r"(\s*" + re.escape(key) + r"\s*" + re.escape(delimiter)
                                 + r"\s*)([^#;\r\n]*?)(\s*(?:[#;].*)?)(\r?\n)?", line)
            if match:
                found.append((index, match))
    if len(found) > 1:
        raise ValueError("Duplicate nozzle configuration value")
    return lines, section_start, section_end, found


def _value(text, section, key, delimiter):
    found = _setting(text, section, key, delimiter)[3]
    return found[0][1][2].strip() if found else None


def _edit(text, section, key, delimiter, value, allow_missing=False):
    lines, start, end, found = _setting(text, section, key, delimiter)
    if found:
        index, match = found[0]
        lines[index] = match[1] + value + match[3] + (match[4] or "")
    elif not allow_missing:
        raise ValueError("Nozzle diameter is not defined in the main printer configuration")
    else:
        newline = "\r\n" if "\r\n" in text else "\n"
        if start is None:
            return text.rstrip("\r\n") + newline * 2 + "[" + section + "]" + newline + key + delimiter + value + newline
        if end and not lines[end - 1].endswith("\n"):
            lines[end - 1] += newline
        lines.insert(end, key + delimiter + value + newline)
    return "".join(lines)


def _revision(config, ini):
    return hashlib.sha256((config + "\0" + ini).encode("utf-8")).hexdigest()


def plan_head_mapping(config, ini, source_heads, effective_settings):
    """Pure nozzle relocation for an already verified identity permutation.

    Reject active overrides instead of editing a value which will not take
    effect. Unknown material or missing diameter requires explicit resolution.
    Caller publishes both files with the matching UUID and calibration changes.
    """
    if (not isinstance(source_heads, (list, tuple)) or not 1 <= len(source_heads) <= 4
            or any(type(h) is not int for h in source_heads)
            or sorted(source_heads) != list(range(len(source_heads)))):
        raise ValueError('Expected a verified nozzle head permutation')
    if re.search(r'(?m)^#\*#\s*nozzle_diameter\s*[:=]', config):
        raise ValueError('Nozzle diameter has an auto-saved override')
    values = []
    for head in range(len(source_heads)):
        section = 'extruder' + (str(head) if head else '')
        diameter = _value(config, section, 'nozzle_diameter', ':')
        material = _value(ini, 'nozzle', 'type%d' % head, '=')
        if diameter is None or material not in ('0', '1'):
            raise ValueError('Complete nozzle settings required before remapping')
        number = float(diameter)
        if not math.isfinite(number) or not 0 < number <= 2:
            raise ValueError('Invalid saved nozzle diameter')
        active = effective_settings.get(section, {}).get('nozzle_diameter')
        if type(active) not in (int, float) or not math.isfinite(active) or abs(active - number) > 0.000001:
            raise ValueError('Active nozzle settings differ from migration source')
        values.append((diameter, material))
    changed_config, changed_ini = config, ini
    for destination, source in enumerate(source_heads):
        section = 'extruder' + (str(destination) if destination else '')
        diameter, material = values[source]
        if values[destination][0] != diameter:
            changed_config = _edit(changed_config, section, 'nozzle_diameter', ':', diameter)
        if values[destination][1] != material:
            changed_ini = _edit(changed_ini, 'nozzle', 'type%d' % destination, '=', material)
    return changed_config, changed_ini


def _atomic(path, text):
    path = Path(path)
    info = path.stat()
    fd, name = tempfile.mkstemp(prefix=".wmp-nozzle-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            # Stock WM may leave tmt1.ini owned by root in the writable config
            # directory. Atomic replacement is permitted there, but the Klipper
            # user cannot give its new file back to root. Preserve ownership
            # when permitted; otherwise keep the replacement service-owned.
            privileged = os.geteuid() == 0
            owner = info.st_uid if privileged else -1
            group = (info.st_gid if privileged or info.st_gid in
                     {os.getegid(), *os.getgroups()} else -1)
            if owner != -1 or group != -1:
                os.fchown(stream.fileno(), owner, group)
            os.fchmod(stream.fileno(), stat.S_IMODE(info.st_mode))
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class NozzleSettings:
    def __init__(self, config_path, ini_path):
        self.config_path = str(config_path)
        self.ini_path = str(ini_path)
        self._parsed = None
        self._status_files = None

    def _file_versions(self):
        versions = []
        for path in (self.config_path, self.ini_path):
            info = os.lstat(path)
            if not stat.S_ISREG(info.st_mode):
                raise ValueError("Nozzle configuration must be a regular file")
            versions.append((info.st_dev, info.st_ino, info.st_size,
                             info.st_mtime_ns, info.st_ctime_ns))
        return tuple(versions)

    def read_status(self):
        """Reuse display data until either file changes; commands read afresh.

        ctime catches in-place rewrites that preserve length and mtime; inode
        catches atomic replacement. Never cache a read spanning a file change.
        """
        try:
            versions = self._file_versions()
            if self._parsed is not None and versions == self._status_files:
                return {h: dict(v) for h, v in self._parsed[2].items()}, self._parsed[3]
            self._status_files = None
            result = self.read()
            if self._file_versions() == versions:
                self._status_files = versions
            return result
        except (OSError, ValueError):
            self._status_files = None
            raise

    def read(self):
        config, ini = _read(self.config_path), _read(self.ini_path)
        # Still read both files on every observation: stock editors can rewrite
        # them in place, even without a useful timestamp/size change. Only skip
        # parsing when their complete content matches the validated snapshot.
        if self._parsed is not None and self._parsed[:2] == (config, ini):
            return {head: dict(values) for head, values in self._parsed[2].items()}, self._parsed[3]
        heads = {}
        for head in range(4):
            section = "extruder" + (str(head) if head else "")
            diameter = _value(config, section, "nozzle_diameter", ":")
            if diameter is None:
                continue
            diameter = float(diameter)
            if not math.isfinite(diameter) or not 0 < diameter <= 2:
                raise ValueError("Invalid saved nozzle diameter")
            material = _value(ini, "nozzle", "type%d" % head, "=")
            material = MATERIALS[int(material)] if material in ("0", "1") else "Unknown"
            heads["h%d" % head] = {"diameter": diameter, "material": material}
        revision = _revision(config, ini)
        self._parsed = (config, ini, heads, revision)
        # The caller adds active runtime settings to its returned dictionaries.
        return {head: dict(values) for head, values in heads.items()}, revision

    def save(self, head, diameter, material, expected):
        if type(head) is not int or head not in range(4):
            raise ValueError("Invalid physical head")
        if type(diameter) not in (int, float) or diameter not in DIAMETERS or material not in MATERIALS:
            raise ValueError("Unsupported nozzle diameter or material: " +
                             ("diameter must be numeric" if type(diameter) not in (int, float) else
                              "diameter=%s" % repr(diameter)[:80] if diameter not in DIAMETERS else
                              "material=%s" % repr(material)[:80]))
        config, ini = _read(self.config_path), _read(self.ini_path)
        if _revision(config, ini) != expected:
            raise ValueError("Nozzle settings changed; reopen the editor")
        # An auto-saved override would win over the edited main value after
        # restart. Do not report a successful change which cannot take effect.
        if re.search(r"(?m)^#\*#\s*nozzle_diameter\s*[:=]", config):
            raise ValueError("Nozzle diameter has an auto-saved override")
        section = "extruder" + (str(head) if head else "")
        current_diameter = _value(config, section, "nozzle_diameter", ":")
        current_material = _value(ini, "nozzle", "type%d" % head, "=")
        # Saving unchanged values must not rewrite formatting, invalidate other
        # editor revisions, or generate needless writes to printer storage.
        changed_config = (config if current_diameter is not None and float(current_diameter) == diameter
                          else _edit(config, section, "nozzle_diameter", ":", "%.1f" % diameter))
        material_index = str(MATERIALS.index(material))
        changed_ini = (ini if current_material == material_index
                       else _edit(ini, "nozzle", "type%d" % head, "=", material_index, True))
        changes = [(self.config_path, config, changed_config), (self.ini_path, ini, changed_ini)]
        try:
            for path, before, after in changes:
                if _read(path) != before:
                    raise ValueError("Nozzle configuration changed during save")
                if after != before:
                    _atomic(path, after)
            if any(_read(path) != after for path, before, after in changes):
                raise ValueError("Nozzle save readback did not match")
        except Exception as error:
            # Recover ordinary I/O failures without overwriting concurrent
            # third-party edits. These are two vendor files, not a cross-file
            # atomic transaction; subsequent status always reads actual files.
            recovery_errors = []
            for path, before, after in reversed(changes):
                try:
                    current = _read(path)
                    if current == after and before != after:
                        _atomic(path, before)
                    elif current != before:
                        recovery_errors.append("another edit")
                except (OSError, ValueError):
                    recovery_errors.append("recovery failed")
            if recovery_errors:
                raise ValueError("Nozzle save interrupted: " + ", ".join(recovery_errors)
                                 + "; reload settings") from error
            raise
        return self.read()
