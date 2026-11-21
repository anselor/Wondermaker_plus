"""Factory screen resources remain distinct from immediately previous updates."""
import json
from pathlib import Path
import pytest
from test_deploy import deploy
import preload_bundle as pb


def publish(root,version,drop=None):
    stage=root/('stage-'+version);stage.mkdir()
    source=stage/'screen.so';source.write_bytes(version.encode())
    (stage/'outputs.json').write_text(json.dumps({'libwmp_openace-compat.so':{'file':source.name,'sha256':pb.digest(source)}}))
    lib=root/'lib';drop=drop or root/'screen.conf'
    pb.publish_stage(stage,lib,drop)
    return stage,lib,drop


def test_update_then_factory_restore_does_not_restore_previous_wmp(tmp_path):
    _,lib,drop=publish(tmp_path,'r3')
    _,_,_=publish(tmp_path,'r4',drop)
    pb.restore_preload_factory(lib,drop)
    assert not drop.exists()
    assert not (lib/'libwmp_openace-compat.so').exists()
    assert pb.restore_preload_factory(lib,drop) is None


def test_update_rollback_restores_previous_generation_and_factory_evidence(tmp_path):
    _,lib,drop=publish(tmp_path,'r3')
    original=pb._preload_inventory_path(lib).read_bytes()
    second,_,_=publish(tmp_path,'r4',drop)
    pb.restore_publication(second)
    assert (lib/'libwmp_openace-compat.so').read_bytes()==b'r3'
    assert pb._preload_inventory_path(lib).read_bytes()==original
    pb.restore_preload_factory(lib,drop)
    assert not drop.exists()


def test_existing_custom_override_and_metadata_are_restored(tmp_path):
    drop=tmp_path/'screen.conf';drop.write_text('[Service]\nEnvironment="CUSTOM=1"\n');drop.chmod(0o640)
    before=drop.read_bytes()
    _,lib,_=publish(tmp_path,'r4',drop)
    pb.restore_preload_factory(lib,drop)
    assert drop.read_bytes()==before
    assert drop.stat().st_mode & 0o777 == 0o640


def test_legacy_payloads_are_archived_once_and_removed(tmp_path):
    lib=tmp_path/'lib';lib.mkdir();old=lib/'libwmp_retired-patch.so';old.write_bytes(b'old owned payload')
    drop=tmp_path/'screen.conf';drop.write_text('[Service]\nEnvironment="LD_PRELOAD='+str(old)+'"\n')
    pb.adopt_legacy_preload(lib,drop)
    pb.adopt_legacy_preload(lib,drop)
    assert len(list(tmp_path.glob('preload-legacy-originals-*')))==1
    pb.restore_preload_factory(lib,drop)
    assert not old.exists() and not drop.exists()


def test_concurrent_edit_blocks_entire_factory_restore(tmp_path):
    _,lib,drop=publish(tmp_path,'r4')
    drop.write_text('operator edit')
    with pytest.raises(ValueError,match='changed before removal'):
        pb.restore_preload_factory(lib,drop)
    assert (lib/'libwmp_openace-compat.so').read_bytes()==b'r4'
