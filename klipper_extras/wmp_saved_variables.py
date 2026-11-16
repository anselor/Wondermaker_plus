# SPDX-License-Identifier: GPL-3.0-or-later
"""Reuse parsed literals in the stock SAVE_VARIABLE loader, without caching files.

The recognized loader is from Klipper (Dushyant Ahuja, 2020). Unsupported/custom
loaders are left untouched. Saving, file format and write ordering stay stock.
"""
import ast
import configparser
import copy
import inspect
import logging
import textwrap

# Compare syntax, not whitespace, comments or the path to the installed module.
_STOCK_LOADER = '''
def loadVariables(self):
    allvars = {}
    varfile = configparser.ConfigParser()
    try:
        varfile.read(self.filename)
        if varfile.has_section('Variables'):
            for name, val in varfile.items('Variables'):
                allvars[name] = ast.literal_eval(val)
    except:
        msg = "Unable to parse existing variable file"
        logging.exception(msg)
        raise self.printer.command_error(msg)
    self.allVariables = allvars
'''


def _syntax(source):
    return ast.dump(ast.parse(textwrap.dedent(source)), include_attributes=False)


class CachedLoader:
    def __init__(self, store, after_load):
        self.store = store
        self.after_load = after_load
        self.parsed = {}

    def load(self):
        # Read the actual file every time, including after every stock save.
        # Commit the cache only once the complete file has validated.
        allvars, parsed = {}, {}
        varfile = configparser.ConfigParser()
        try:
            varfile.read(self.store.filename)
            if varfile.has_section('Variables'):
                for name, text in varfile.items('Variables'):
                    previous = self.parsed.get(name)
                    value = (previous[1] if previous is not None and previous[0] == text
                             else ast.literal_eval(text))
                    parsed[name] = (text, value)
                    # Plugins may mutate nested values in allVariables. Never
                    # let that mutate the independently validated parse cache.
                    allvars[name] = copy.deepcopy(value)
        except:
            msg = "Unable to parse existing variable file"
            logging.exception(msg)
            raise self.store.printer.command_error(msg)
        self.store.allVariables = allvars
        self.parsed = parsed
        self.after_load()


def install(store, after_load):
    """Install only on the known stock implementation; return whether active."""
    if getattr(store, '_wmp_cached_loader', None) is not None:
        return True
    original = getattr(store, 'loadVariables', None)
    try:
        if (getattr(original, '__self__', None) is not store
                or _syntax(inspect.getsource(original)) != _syntax(_STOCK_LOADER)):
            return False
    except (OSError, TypeError, SyntaxError):
        return False
    loader = CachedLoader(store, after_load)
    # No reload, write or callback during installation. The first normal load
    # validates the current file and populates the cache.
    store.loadVariables = loader.load
    store._wmp_cached_loader = loader
    logging.info("WM+: saved-variable parse cache active")
    return True
