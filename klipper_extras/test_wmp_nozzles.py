import os
import pytest
import wmp_nozzles as nozzle


@pytest.fixture
def store(tmp_path):
    config = tmp_path / "printer.cfg"
    ini = tmp_path / "tmt1.ini"
    config.write_text("# retained\n" + "".join("[extruder%s]\nnozzle_diameter: 0.400000 # nozzle\nmax_temp: 300\n\n" % (i or "") for i in range(4)))
    ini.write_text("[slot]\nmaterial2=3\n[nozzle]\n" + "".join("type%d=0\n" % i for i in range(4)))
    return nozzle.NozzleSettings(config, ini)


def test_physical_head_save_preserves_other_heads_and_settings(store):
    heads, revision = store.read()
    assert heads["h2"] == {"diameter": 0.4, "material": "Hardened steel"}
    with open(store.config_path) as stream:
        original = stream.read()
    heads, new_revision = store.save(2, 0.6, "Stainless steel", revision)
    assert heads["h2"] == {"diameter": 0.6, "material": "Stainless steel"}
    assert all(heads["h%d" % i]["diameter"] == 0.4 for i in (0, 1, 3))
    assert revision != new_revision
    with open(store.config_path) as stream:
        assert stream.read() == original.replace("[extruder2]\nnozzle_diameter: 0.400000", "[extruder2]\nnozzle_diameter: 0.6")
    with open(store.ini_path) as stream:
        assert "material2=3" in stream.read()
    assert store.read() == (heads, new_revision)


def test_stale_revision_does_not_overwrite_external_changes(store):
    _, revision = store.read()
    with open(store.ini_path, "a") as stream:
        stream.write("# external edit\n")
    before = store.read()
    with pytest.raises(ValueError, match="changed"):
        store.save(0, 0.6, "Stainless steel", revision)
    assert store.read() == before


@pytest.mark.parametrize("head,diameter,material", [
    (True, 0.4, "Hardened steel"), (-1, 0.4, "Hardened steel"), (4, 0.4, "Hardened steel"),
    (0, float("nan"), "Hardened steel"), (0, 0.5, "Hardened steel"),
    (0, "0.4", "Hardened steel"), (0, 0.4, "Unknown"),
])
def test_invalid_choices_leave_both_files_unchanged(store, head, diameter, material):
    before = store.read()
    with pytest.raises(ValueError):
        store.save(head, diameter, material, before[1])
    assert store.read() == before


def test_second_file_failure_restores_first_file(store, monkeypatch):
    before = store.read()
    atomic = nozzle._atomic
    def fail_ini(path, text):
        if path == store.ini_path:
            raise OSError("disk error")
        atomic(path, text)
    monkeypatch.setattr(nozzle, "_atomic", fail_ini)
    with pytest.raises(OSError, match="disk error"):
        store.save(1, 0.8, "Stainless steel", before[1])
    assert store.read() == before


def test_concurrent_edit_is_preserved_on_failure(store, monkeypatch):
    before = store.read()
    original_config = open(store.config_path).read()
    atomic = nozzle._atomic
    def concurrent(path, text):
        atomic(path, text)
        if path == store.config_path:
            with open(store.ini_path, "a") as stream:
                stream.write("# other writer\n")
    monkeypatch.setattr(nozzle, "_atomic", concurrent)
    with pytest.raises(ValueError, match="another edit"):
        store.save(1, 0.8, "Stainless steel", before[1])
    with open(store.ini_path) as stream:
        assert "# other writer" in stream.read()
    with open(store.config_path) as stream:
        assert stream.read() == original_config


def test_missing_material_field_can_be_added_but_missing_diameter_cannot(store):
    with open(store.ini_path, "w") as stream:
        stream.write("[slot]\nmaterial0=0\n")
    _, revision = store.read()
    heads, _ = store.save(3, 0.2, "Hardened steel", revision)
    assert heads["h3"]["material"] == "Hardened steel"
    with open(store.config_path, "w") as stream:
        stream.write("[include extruders.cfg]\n")
    _, revision = store.read()
    with pytest.raises(ValueError, match="main printer configuration"):
        store.save(0, 0.4, "Stainless steel", revision)


@pytest.mark.parametrize("suffix", ["[extruder]\nnozzle_diameter: 0.6\n", "#*# nozzle_diameter = 0.6\n"])
def test_duplicate_sections_and_auto_saved_overrides_refused(store, suffix):
    with open(store.config_path, "a") as stream:
        stream.write(suffix)
    with pytest.raises(ValueError):
        _, revision = store.read()
        store.save(0, 0.6, "Stainless steel", revision)


def test_symlink_refused_and_permissions_preserved(store, tmp_path):
    os.chmod(store.config_path, 0o640)
    _, revision = store.read()
    store.save(0, 0.6, "Stainless steel", revision)
    assert os.stat(store.config_path).st_mode & 0o777 == 0o640
    link = tmp_path / "link.cfg"
    link.symlink_to(store.config_path)
    store.config_path = str(link)
    with pytest.raises(ValueError, match="regular file"):
        store.read()


def test_unchanged_values_preserve_bytes_revision_and_avoid_writes(store, monkeypatch):
    from pathlib import Path
    original = {path: Path(path).read_bytes() for path in (store.config_path, store.ini_path)}
    before = store.read()
    def unexpected_write(path, text):
        raise AssertionError("unchanged nozzle settings must not write files")
    monkeypatch.setattr(nozzle, "_atomic", unexpected_write)
    for head in range(4):
        assert store.save(head, 0.4, "Hardened steel", before[1]) == before
        assert all(Path(path).read_bytes() == raw for path, raw in original.items())


def test_material_only_save_preserves_diameter_format(store, monkeypatch):
    from pathlib import Path
    original_config = Path(store.config_path).read_bytes()
    atomic = nozzle._atomic
    writes = []
    def record(path, text):
        writes.append(path)
        atomic(path, text)
    monkeypatch.setattr(nozzle, "_atomic", record)
    before = store.read()
    heads, revision = store.save(2, 0.4, "Stainless steel", before[1])
    assert writes == [store.ini_path]
    assert Path(store.config_path).read_bytes() == original_config
    assert heads['h2']['material'] == 'Stainless steel' and revision != before[1]


def test_atomic_replace_root_owned_stock_ini_as_service_user(tmp_path, monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace
    path = tmp_path / 'tmt1.ini'
    path.write_text('[nozzle]\ntype2=0\n')
    os.chmod(path, 0o640)
    original_stat = Path.stat
    def stock_owner(p, *args, **kwargs):
        result = original_stat(p, *args, **kwargs)
        if p == path:
            return SimpleNamespace(st_mode=result.st_mode, st_uid=0, st_gid=0)
        return result
    monkeypatch.setattr(Path, 'stat', stock_owner)
    monkeypatch.setattr(os, 'geteuid', lambda: 1001)
    monkeypatch.setattr(os, 'getegid', lambda: 111)
    monkeypatch.setattr(os, 'getgroups', lambda: [111, 5, 20])
    def forbidden_chown(*args):
        pytest.fail('A service user cannot preserve root ownership')
    monkeypatch.setattr(os, 'fchown', forbidden_chown)
    nozzle._atomic(path, '[nozzle]\ntype2=1\n')
    assert path.read_text() == '[nozzle]\ntype2=1\n'
    assert original_stat(path).st_mode & 0o777 == 0o640


def test_unchanged_status_reuses_parse_but_detects_same_size_external_edit(store, monkeypatch):
    calls = []
    original = nozzle._setting
    def counted(*args):
        calls.append(args[1:])
        return original(*args)
    monkeypatch.setattr(nozzle, "_setting", counted)
    heads, revision = store.read()
    initial_calls = len(calls)
    assert initial_calls == 8
    # The status adapter adds runtime fields; those must not contaminate cache.
    heads["h0"]["diameter"] = 99
    heads["h0"]["active_diameter"] = 99
    for _ in range(20):
        current, current_revision = store.read()
        assert current["h0"] == {"diameter": .4, "material": "Hardened steel"}
        assert current_revision == revision
    assert len(calls) == initial_calls
    # Do not trust timestamps or size: the stock editor can overwrite in place.
    before = os.stat(store.ini_path)
    with open(store.ini_path) as stream:
        text = stream.read()
    with open(store.ini_path, "w") as stream:
        stream.write(text.replace("type2=0", "type2=1"))
    os.utime(store.ini_path, ns=(before.st_atime_ns, before.st_mtime_ns))
    changed, changed_revision = store.read()
    assert changed["h2"]["material"] == "Stainless steel"
    assert changed_revision != revision and len(calls) == initial_calls * 2


def test_cached_nozzles_do_not_hide_invalid_or_missing_configuration(store):
    store.read()
    with open(store.ini_path, "a") as stream:
        stream.write("[nozzle]\ntype0=1\n")
    with pytest.raises(ValueError, match="Duplicate"):
        store.read()
    os.unlink(store.ini_path)
    with pytest.raises(ValueError, match="regular file"):
        store.read()


def test_status_reads_unchanged_files_once_and_isolates_output(store, monkeypatch):
    reads = []
    original = nozzle._read
    monkeypatch.setattr(nozzle, '_read', lambda path: (reads.append(path), original(path))[1])
    expected = store.read_status()
    for _ in range(10):
        actual = store.read_status()
        assert actual == expected
        actual[0]['h0']['diameter'] = .8
    assert len(reads) == 2
    store.read()  # Commands still read both complete files.
    assert len(reads) == 4


@pytest.mark.parametrize('replace', [False, True])
def test_status_detects_same_size_preserved_mtime_edit(store, replace):
    from pathlib import Path
    before = store.read_status()
    path = Path(store.config_path)
    info = path.stat()
    text = path.read_text().replace('0.400000', '0.600000')
    if replace:
        staged = path.with_suffix('.new')
        staged.write_text(text)
        os.utime(staged, ns=(info.st_atime_ns, info.st_mtime_ns))
        os.replace(staged, path)
    else:
        path.write_text(text)
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
    after = store.read_status()
    assert after[0]['h0']['diameter'] == .6 and after[1] != before[1]


def test_status_rejects_file_removed_or_replaced_by_symlink(store):
    from pathlib import Path
    store.read_status()
    path = Path(store.ini_path)
    text = path.read_text()
    path.unlink()
    with pytest.raises(OSError): store.read_status()
    target = path.with_suffix('.other')
    target.write_text(text)
    path.symlink_to(target)
    with pytest.raises(ValueError, match='regular'): store.read_status()


def test_status_does_not_cache_a_read_spanning_an_external_edit(store, monkeypatch):
    from pathlib import Path
    original = store.read
    def changing():
        result = original()
        path = Path(store.ini_path)
        path.write_text(path.read_text().replace('type0=0', 'type0=1'))
        return result
    monkeypatch.setattr(store, 'read', changing)
    assert store.read_status()[0]['h0']['material'] == 'Hardened steel'
    assert store._status_files is None
    monkeypatch.setattr(store, 'read', original)
    assert store.read_status()[0]['h0']['material'] == 'Stainless steel'
