import ast
import configparser
import logging
from pathlib import Path
from types import SimpleNamespace
import pytest
import wmp_saved_variables as cache


class Stock:
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


@pytest.fixture
def store(tmp_path):
    s = Stock();s.filename = str(tmp_path/'variables.cfg')
    s.printer = SimpleNamespace(command_error=RuntimeError);s.allVariables = {}
    Path(s.filename).write_text("[Variables]\nstate = {'nested': [1, 2]}\ncount = 0\n")
    s.loadVariables();return s


def test_unchanged_literals_reused_without_sharing_mutable_values(store, monkeypatch):
    parsed=[];original=ast.literal_eval;callbacks=[]
    def track(text):parsed.append(text);return original(text)
    monkeypatch.setattr(ast, 'literal_eval', track)
    assert cache.install(store, lambda: callbacks.append(dict(store.allVariables)))
    store.loadVariables();assert len(parsed)==2
    store.allVariables['state']['nested'].append(99)
    store.loadVariables();assert len(parsed)==2
    assert store.allVariables['state']=={'nested':[1,2]}
    Path(store.filename).write_text("[Variables]\nstate = {'nested': [1, 2]}\ncount = 1\n")
    store.loadVariables();assert len(parsed)==3 and store.allVariables['count']==1
    assert len(callbacks)==3 and callbacks[-1]['count']==1


def test_errors_do_not_publish_partial_cache_or_call_completion(store):
    called=[];assert cache.install(store, lambda:called.append(True));store.loadVariables()
    before=store.allVariables
    Path(store.filename).write_text('[Variables]\ncount = 5\nbroken = no_literal\n')
    with pytest.raises(RuntimeError, match='Unable to parse'):store.loadVariables()
    assert store.allVariables is before and len(called)==1
    Path(store.filename).write_text('[Variables]\ncount = 7\n')
    store.loadVariables();assert store.allVariables=={'count':7}
    Path(store.filename).unlink();store.loadVariables()
    assert store.allVariables=={}  # same missing-file semantics as stock


def test_custom_loader_is_not_replaced(store):
    class Custom(Stock):
        def loadVariables(self):self.allVariables={'custom':True}
    store.__class__=Custom;original=store.loadVariables
    assert not cache.install(store, lambda:None)
    assert store.loadVariables==original


def test_installation_does_not_reload_write_or_yield_and_is_idempotent(store):
    before=Path(store.filename).read_bytes();called=[];values=store.allVariables
    assert cache.install(store, lambda:called.append(True))
    loader=store.loadVariables
    assert cache.install(store, lambda:called.append(False))
    assert store.loadVariables==loader and store.allVariables is values
    assert not called and Path(store.filename).read_bytes()==before
