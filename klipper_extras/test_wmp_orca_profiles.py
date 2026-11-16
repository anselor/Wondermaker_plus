import io
import json
import zipfile
import pytest
from wmp_orca_profiles import import_bytes, extract_profiles


def preset(**updates):
    return dict(type='filament', name='Example PLA', filament_vendor=['Example'],
                filament_type=['PLA'], nozzle_temperature=['220'], **updates)


def test_extracts_only_metadata_and_optional_color():
    result = import_bytes(json.dumps(preset(default_filament_colour=['#aB1234'],
        filament_start_gcode=['G28'], hot_plate_temp=['60'])).encode())
    profile = result['profiles'][0]
    assert profile['identity'] == dict(brand='Example', material='PLA', nozzle_temp=220, color='#AB1234')
    assert not result['errors'] and not result['warnings']
    assert len(profile['id']) == 64
    assert 'G28' not in json.dumps(result) and 'bed_temp' not in profile['identity']


def test_bundle_resolves_parent_and_ignores_other_preset_types():
    base = preset(instantiation='false', nozzle_temperature_range_low=['200'], nozzle_temperature_range_high=['240'])
    child = dict(type='filament', name='My PLA', inherits='Example PLA', filament_vendor=['Mine'])
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        for name, value in [('base.json', base), ('child.json', child), ('printer.json', {'type': 'machine'})]:
            archive.writestr(name, json.dumps(value))
    result = import_bytes(output.getvalue())
    assert len(result['profiles']) == 1 and not result['errors']
    assert result['profiles'][0]['identity'] == dict(brand='Mine', material='PLA', nozzle_temp=220, nozzle_temp_min=200, nozzle_temp_max=240)


def test_missing_parent_is_visible_even_if_explicit_fields_suffice():
    result = extract_profiles([preset(inherits='Unavailable')])
    assert len(result['profiles']) == 1 and 'Missing parent' in result['warnings'][0]
    result = extract_profiles([dict(type='filament', name='Child', inherits='Unavailable')])
    assert not result['profiles'] and 'Missing brand' in result['errors'][0]


@pytest.mark.parametrize('field,value', [('nozzle_temperature', ['nan']), ('nozzle_temperature', ['351']),
    ('nozzle_temperature', [True]), ('nozzle_temperature', ['200', '220']),
    ('filament_vendor', ['Bad\nname']), ('default_filament_colour', ['red']),
    ('nozzle_temperature_range_high', ['210'])])
def test_invalid_values_are_not_imported(field, value):
    source = preset(); source[field] = value
    result = extract_profiles([source])
    assert not result['profiles'] and result['errors']


def test_cycles_and_conflicting_names_are_rejected():
    a, b = preset(inherits='B'), preset(); b['name'] = 'B'; b['inherits'] = 'Example PLA'
    assert not extract_profiles([a, b])['profiles']
    b = preset(); b['filament_vendor'] = ['Other']
    assert not extract_profiles([preset(), b])['profiles']


def test_duplicate_json_keys_and_archive_entries_rejected():
    with pytest.raises(ValueError, match='Duplicate JSON'):
        import_bytes(b'{"type":"filament","type":"machine"}')
    output = io.BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('a.json', '{}')
        with pytest.warns(UserWarning): archive.writestr('a.json', '{}')
    with pytest.raises(ValueError, match='Duplicate archive'):
        import_bytes(output.getvalue())


def test_repeat_import_has_stable_id_and_no_invented_colour():
    raw = json.dumps(preset()).encode()
    assert import_bytes(raw) == import_bytes(raw)
    assert 'color' not in import_bytes(raw)['profiles'][0]['identity']


def test_orca_user_export_without_type_header():
    source = preset(); del source['type']
    source['filament_settings_id'] = ['Example PLA']
    source['from'] = 'User'; source['version'] = '2.3.0.0'
    result = import_bytes(json.dumps(source).encode())
    assert len(result['profiles']) == 1 and not result['errors']


def test_catalogue_is_compact_atomic_and_idempotent(tmp_path):
    from wmp_orca_profiles import read_catalogue, save_catalogue
    path = tmp_path / 'catalogue.json'
    profiles, revision = read_catalogue(path)
    selection = extract_profiles([preset()])['profiles']
    saved, new_revision = save_catalogue(path, selection, revision)
    assert new_revision != revision and len(saved) == 1
    assert read_catalogue(path) == (saved, new_revision)
    assert save_catalogue(path, selection, new_revision) == (saved, new_revision)
    with pytest.raises(ValueError, match='changed'):
        save_catalogue(path, selection, revision)
    assert not list(tmp_path.glob('.wmp-catalogue-*'))


def test_failed_catalogue_write_preserves_existing_store(tmp_path, monkeypatch):
    import os
    from wmp_orca_profiles import read_catalogue, save_catalogue
    path = tmp_path / 'catalogue.json'
    selection = extract_profiles([preset()])['profiles']
    save_catalogue(path, selection, read_catalogue(path)[1])
    before = path.read_bytes()
    def fail(*args): raise OSError('disk failure')
    monkeypatch.setattr(os, 'replace', fail)
    with pytest.raises(OSError): save_catalogue(path, selection, read_catalogue(path)[1])
    assert path.read_bytes() == before and not list(tmp_path.glob('.wmp-catalogue-*'))


def test_corrupt_catalogue_and_modified_record_are_not_saved(tmp_path):
    from wmp_orca_profiles import read_catalogue, save_catalogue, catalogue_revision
    path = tmp_path / 'catalogue.json'
    selection = extract_profiles([preset()])['profiles']
    selection[0]['identity']['brand'] = 'changed'
    with pytest.raises(ValueError, match='content changed'):
        save_catalogue(path, selection, catalogue_revision({}))
    path.write_text('broken')
    with pytest.raises(ValueError): read_catalogue(path)
    assert path.read_text() == 'broken'


def test_usb_scan_review_and_save(tmp_path):
    from wmp_orca_profiles import UsbProfileImport
    root = tmp_path / 'usb'; root.mkdir()
    (root / 'profile.json').write_text(json.dumps(preset()))
    (root / 'print.gcode').write_text('G28')
    importer = UsbProfileImport(root, tmp_path / 'catalogue.json')
    listing = importer.scan(); assert len(listing['files']) == 1
    review = importer.review(listing['files'][0]['id'])
    assert review['state'] == 'review' and not (tmp_path / 'catalogue.json').exists()
    result = importer.save(review['token'])
    assert result['count'] == 1 and result['state'] == 'saved'
    with pytest.raises(ValueError, match='expired'): importer.save(review['token'])


def test_usb_absent_and_symlinks_are_not_followed(tmp_path):
    from wmp_orca_profiles import UsbProfileImport
    importer = UsbProfileImport(tmp_path / 'absent', tmp_path / 'catalogue.json')
    assert importer.scan()['message'] == 'Insert a USB drive'
    root = tmp_path / 'usb'; root.mkdir()
    outside = tmp_path / 'outside.json'; outside.write_text(json.dumps(preset()))
    (root / 'link.json').symlink_to(outside)
    importer = UsbProfileImport(root, tmp_path / 'catalogue.json')
    assert not importer.scan()['files']
    file = root / 'real.json'; file.write_text(json.dumps(preset()))
    selected = importer.scan()['files'][0]['id']
    file.unlink(); file.symlink_to(outside)
    with pytest.raises(OSError): importer.review(selected)


def test_usb_refresh_invalidates_old_review(tmp_path):
    from wmp_orca_profiles import UsbProfileImport
    root = tmp_path / 'usb'; root.mkdir(); (root / 'a.json').write_text(json.dumps(preset()))
    importer = UsbProfileImport(root, tmp_path / 'catalogue.json')
    review = importer.review(importer.scan()['files'][0]['id'])
    importer.scan()
    with pytest.raises(ValueError, match='expired'): importer.save(review['token'])
