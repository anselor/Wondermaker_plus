"""Publication failures must preserve the observable on-disk outcome."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    'wmp_persistence_test', Path(__file__).resolve().parents[1] / 'klipper_extras/wmp_persistence.py')
persistence = importlib.util.module_from_spec(spec)
spec.loader.exec_module(persistence)


@pytest.mark.parametrize('failure', ['file_sync', 'replace', 'directory_sync'])
def test_publication_failure_reports_error_and_cleans_temporary(tmp_path, monkeypatch, failure):
    destination = tmp_path / 'state.json'
    destination.write_bytes(b'old')
    real_sync = persistence.os.fsync
    calls = []

    def sync(fd):
        calls.append(fd)
        if len(calls) == (2 if failure == 'directory_sync' else 1) and failure != 'replace':
            raise OSError('injected sync failure')
        real_sync(fd)

    def replace(source, target):
        raise OSError('injected rename failure')

    monkeypatch.setattr(persistence.os, 'fsync', sync)
    if failure == 'replace':
        monkeypatch.setattr(persistence.os, 'replace', replace)
    with pytest.raises(OSError, match='injected'):
        persistence.atomic_write(str(destination), b'new', '.test-state-')
    # A directory-sync failure is after publication. Callers must see the error
    # without mistaking it for proof that no write occurred.
    assert destination.read_bytes() == (b'new' if failure == 'directory_sync' else b'old')
    assert list(tmp_path.iterdir()) == [destination]
