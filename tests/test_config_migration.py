import importlib.util
import subprocess
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


sync = module('tested_sync', 'utils/config_sync.py')
update = module('tested_update', 'tools/update_config_base.py')


def test_diff_preserves_calibration_boundary_and_missing_newline(tmp_path, monkeypatch):
    monkeypatch.setattr(sync, 'LIVE', str(tmp_path))
    marker = sync.SAVE_CONFIG_MARKER
    (tmp_path / 'printer.cfg').write_bytes(b'new body\n' + marker + b'\nLOCAL SECRET')
    t = SimpleNamespace(read=lambda name: b'old body\n' + marker + b'\nREMOTE SECRET')
    patch = sync.patch_for(t, 'printer.cfg')
    assert '-old body\n+new body\n' in patch
    assert 'SECRET' not in patch
    (tmp_path / 'macro.cfg').write_bytes(b'new body\n')
    t.read = lambda name: b'old body'
    patch = sync.patch_for(t, 'macro.cfg')
    assert '-old body\n\\ No newline at end of file\n+new body\n' in patch
    remote = tmp_path / 'remote'
    remote.write_bytes(b'old body')
    result = subprocess.run(['patch', '--batch', str(remote)], input=patch, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert remote.read_bytes() == b'new body\n'


def test_missing_file_preview_and_exclusions(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sync, 'LIVE', str(tmp_path))
    (tmp_path / 'new.cfg').write_text('new\n')
    (tmp_path / 'wm_zru_mcu.cfg').write_text('MACHINE UUID')
    def missing(name):
        raise FileNotFoundError(name)
    sync.run(SimpleNamespace(read=missing), SimpleNamespace(mode='diff', patch=True))
    output = capsys.readouterr().out
    assert '--- /dev/null' in output and '+new\n' in output
    assert 'MACHINE' not in output and 'wm_zru_mcu' not in output


def inputs(tmp_path, texts=('value: old\n', 'value: new\n', 'value: old\n')):
    dirs = [tmp_path / name for name in ('old', 'new', 'live')]
    for p, text in zip(dirs, texts):
        p.mkdir()
        (p / 'macros.cfg').write_text(text)
    return dirs


def test_candidate_preserves_local_edits_and_never_changes_inputs(tmp_path):
    old, new, live = inputs(tmp_path, ('vendor: old\n\nlocal: old\n', 'vendor: new\n\nlocal: old\n', 'vendor: old\n\nlocal: ours\n'))
    before = (live / 'macros.cfg').read_bytes()
    out = tmp_path / 'candidate'
    assert update.main([str(old), str(new), str(live), '--output', str(out)]) == 0
    assert (out / 'macros.cfg').read_text() == 'vendor: new\n\nlocal: ours\n'
    assert (live / 'macros.cfg').read_bytes() == before
    assert update.main([str(old), str(new), str(live), '--output', str(live)]) == 2


def test_failed_merge_never_publishes_partial_candidate(tmp_path, monkeypatch):
    dirs = inputs(tmp_path)
    out = tmp_path / 'candidate'
    monkeypatch.setattr(update.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=255, stdout='', stderr='fatal failure'))
    assert update.main([*map(str, dirs), '--output', str(out)]) == 2
    assert not out.exists()
    assert (dirs[2] / 'macros.cfg').read_text() == 'value: old\n'


def test_binary_rejected_and_machine_state_excluded(tmp_path):
    dirs = inputs(tmp_path)
    for d in dirs:
        (d / 'wm_zru_mcu.cfg').write_text('private UUID')
        (d / 'saved_variables.cfg').write_text('runtime state')
        (d / 'printer.cfg').write_bytes(b'body\n' + sync.SAVE_CONFIG_MARKER + b'\nprivate mesh')
    candidate, _ = update.plan(*dirs)
    assert 'wm_zru_mcu.cfg' not in candidate and 'saved_variables.cfg' not in candidate
    assert candidate['printer.cfg'] == 'body\n'
    (dirs[1] / 'macros.cfg').write_bytes(b'binary\0data')
    assert update.main([*map(str, dirs), '--output', str(tmp_path / 'candidate')]) == 2
    assert not (tmp_path / 'candidate').exists()


def test_conflicts_and_file_decisions_are_explicit(tmp_path):
    dirs = inputs(tmp_path, ('setting: base\n', 'setting: theirs\n', 'setting: ours\n'))
    (dirs[1] / 'new.cfg').write_text('vendor added\n')
    for d in (dirs[0], dirs[2]):
        (d / 'removed.cfg').write_text('review removal\n')
    candidate, decisions = update.plan(*dirs)
    assert '<<<<<<< live/macros.cfg' in candidate['macros.cfg']
    assert candidate['new.cfg'] == 'vendor added\n'
    assert candidate['removed.cfg'] == 'review removal\n'
    assert all(any(x.startswith(prefix) for x in decisions) for prefix in ('ADD', 'REMOVED', 'CONFLICT'))


def test_dropped_markers_need_review(tmp_path):
    old = '# >>> wondermaker+ begin: retained\nold\n# <<< wondermaker+ end: retained\n'
    dirs = inputs(tmp_path, (old, 'new\n', old))
    _, decisions = update.plan(*dirs)
    assert any('marked changes lost: retained' in d for d in decisions)
