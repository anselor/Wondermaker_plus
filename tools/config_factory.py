"""Recognize published legacy behavior without copying machine configuration.

The catalog contains exact executable-option hashes from reviewed releases.
Unknown code never acquires ownership merely by using a WM+ name.
"""
import configparser
import hashlib
import io
import json
import re
from pathlib import Path

import preload_bundle as bundle

CATALOG = 'config/provenance/legacy-behavior.json'
OPTIONS = ('gcode', 'rename_existing', 'axes', 'runout_gcode',
           'insert_gcode', 'pause_on_runout')


def parser(text):
    result = configparser.RawConfigParser(strict=False, inline_comment_prefixes=(';', '#'))
    # Match the vendor parser, including its unconditional # stripping.
    result.read_string('\n'.join(line.split('#', 1)[0] for line in text.splitlines()))
    return result


def restore_behavior(text, stock, known, *, material_only=False):
    """Return factory executable behavior, retaining non-executable tuning.

    Changed sections are backed up by the caller's publication transaction.
    New package-only macros are removed only when their executable options all
    match published evidence. SAVE_CONFIG bytes and unrelated chunks are opaque.
    """
    if material_only:
        return text
    body, marker, saved = text.partition('#*# <---------------------- SAVE_CONFIG ---------------------->')
    chunks = re.split(r'(?m)(?=^[ \t]*\[[^\]\r\n]+\][ \t]*(?:[#;].*)?$)', body)
    output = []
    for chunk in chunks:
        match = configparser.RawConfigParser.SECTCRE.match(chunk)
        section = match.group('header') if match else None
        if section in ('wm_material', 'wmp_recovery', 'wmp_case_light'):
            # These loaders belong to WM+, including when an older installer
            # put them directly in printer.cfg or case_light.cfg.
            continue
        evidence = known.get(section, {})
        if not evidence:
            output.append(chunk)
            continue
        current = parser(chunk)
        keys=set(OPTIONS)
        if section=='homing_override':
            keys.update(('set_position_x','set_position_y','set_position_z'))
        executable = {key: value for key, value in current.items(section) if key in keys}
        def recognized(key, value):
            value = bundle.config_contract_value(section, key, value)
            return hashlib.sha256(value.encode()).hexdigest() in evidence.get(key, [])
        if not stock.has_section(section):
            if executable and all(recognized(key, value) for key, value in executable.items()):
                continue
            output.append(chunk)
            continue
        # Restore a command as one executable contract. Mixing factory G-code
        # with an operator's different rename/axes option can break its calls.
        unknown = any(not recognized(key,value) and not (
            stock.has_option(section,key)
            and bundle.config_contract_value(section,key,value)
                == bundle.config_contract_value(section,key,stock.get(section,key)))
            for key,value in executable.items())
        if unknown:
            output.append(chunk)
            continue
        changed = False
        for key, value in list(current.items(section)):
            if not recognized(key, value):
                continue
            if stock.has_option(section, key):
                wanted = stock.get(section, key)
                if bundle.config_contract_value(section, key, value) == bundle.config_contract_value(section, key, wanted):
                    continue
                current.set(section, key, wanted)
            else:
                current.remove_option(section, key)
            changed = True
        if changed:
            stream = io.StringIO()
            current.write(stream)
            output.append(stream.getvalue())
        else:
            output.append(chunk)
    return ''.join(output) + marker + saved


def inputs(root):
    root = Path(root)
    catalog = json.loads((root / CATALOG).read_text(encoding='utf-8'))
    if catalog.get('version') != 1 or not isinstance(catalog.get('sections'), dict):
        raise ValueError('Unsupported legacy behavior catalog')
    paths = sorted((root / 'config/stock').glob('*.cfg'))
    stock = bundle.read_active_config(root / 'config/stock/printer.cfg', include_paths=paths)
    return stock, catalog['sections']
