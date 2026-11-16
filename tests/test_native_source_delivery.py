"""Editable repo source and archive bind the selected prebuilt native payload."""
import json, shutil, subprocess, sys
from pathlib import Path
import pytest
from test_deploy import deploy  # Establish the installer tool import path.
import preload_bundle as pb
from components import preload
from test_preload_bundle import vendor_client, bundle_copy, local_installer
ROOT=Path(__file__).resolve().parents[1]


def test_shipped_native_source_and_archive_are_complete_repo_relative_inputs(tmp_path):
    root=bundle_copy(tmp_path)
    bundle=pb.load_bundle(root)
    pb.verify_source_binding(root,bundle)
    rows=json.loads((root/pb.BUNDLE/'source-inputs.json').read_text())
    assert rows and all(not name.startswith('/') and '..' not in Path(name).parts for name in rows)
    assert 'client-preload/openace-compat/wmp_openace_compat.c' in rows
    assert pb.BUNDLE+'/source/client/native_bootstrap.cpp' in rows
    assert pb.BUNDLE+'/build-offline-arm.sh' in rows
    assert pb.BUNDLE+'/repack-source.py' in rows


@pytest.mark.parametrize('change',['archive_missing','archive_changed','archive_invalid','source_changed','extra_source'])
def test_selected_native_source_failures_preserve_owned_publication(tmp_path,monkeypatch,change):
    root,home,drop,selected,commands,restarts,ctx=local_installer(tmp_path,monkeypatch,exact=True)
    (home/'lib').mkdir();old=home/'lib/libwmp_openace-compat.so';old.write_bytes(b'prior compat')
    drop.write_text('prior override')
    archive=root/pb.BUNDLE/'source.tar.gz'
    if change=='archive_missing':archive.unlink()
    elif change=='archive_changed':archive.write_bytes(archive.read_bytes()+b'bad')
    elif change=='archive_invalid':
        archive.write_bytes(b'not a gzip archive')
        descriptor=root/pb.BUNDLE/'bundle.json'
        value=json.loads(descriptor.read_text());value['source_archive_sha256']=pb.digest(archive)
        descriptor.write_text(json.dumps(value))
    elif change=='source_changed':(root/pb.BUNDLE/'source/client/native_bootstrap.cpp').write_text('changed source')
    else:(root/pb.BUNDLE/'source/client/unrecorded.hpp').write_text('unrecorded source')
    with pytest.raises(deploy.DeployError,match='native source'):
        preload.install(ctx)
    assert old.read_bytes()==b'prior compat' and drop.read_text()=='prior override'
    assert not restarts and not (home/'lib/libwmp_wifi-fix.so').exists()


def test_older_c_profile_does_not_require_native_source_archive(tmp_path,monkeypatch):
    root,home,drop,selected,commands,restarts,ctx=local_installer(tmp_path,monkeypatch,exact=False)
    (root/pb.BUNDLE/'source.tar.gz').unlink()
    shutil.rmtree(root/pb.BUNDLE/'source')
    preload.install(ctx)
    assert restarts and any(c.startswith('gcc ') and 'wmp_openace_compat.c' in c for c in commands)
    client=vendor_client('1.1.12')
    script=pb.preflight_script(root,str(client))
    result=subprocess.run([sys.executable,'-'],input=script,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert 'existing C fixes retained' in result.stdout


def test_no_native_bundle_retains_legacy_c_delivery_without_source_requirements(tmp_path,monkeypatch):
    root,home,drop,selected,commands,restarts,ctx=local_installer(tmp_path,monkeypatch,exact=False)
    shutil.rmtree(root/pb.BUNDLE)
    assert pb.load_bundle(root) is None
    assert pb.preflight_script(root,'unused')==''
    preload.install(ctx)
    assert restarts and any(c.startswith('gcc ') and 'wmp_openace_compat.c' in c for c in commands)


def test_legacy_preflight_ignores_a_structurally_invalid_native_source_archive(tmp_path):
    root=bundle_copy(tmp_path)
    archive=root/pb.BUNDLE/'source.tar.gz';archive.write_bytes(b'not a gzip archive')
    descriptor=root/pb.BUNDLE/'bundle.json';value=json.loads(descriptor.read_text())
    value['source_archive_sha256']=pb.digest(archive);descriptor.write_text(json.dumps(value))
    client=vendor_client('1.1.12')
    script=pb.preflight_script(root,str(client))
    result=subprocess.run([sys.executable,'-'],input=script,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert 'existing C fixes retained' in result.stdout


@pytest.mark.parametrize('change',['duplicate','traversal','symlink','hardlink','missing','bad_member'])
def test_source_archive_members_are_checked_after_its_digest_matches(tmp_path,change):
    import io,tarfile
    root=bundle_copy(tmp_path);archive=root/pb.BUNDLE/'source.tar.gz'
    with tarfile.open(archive,'r:gz') as source:
        records=[(member.name,source.extractfile(member).read()) for member in source]
    if change=='duplicate':records.append(records[0])
    elif change=='traversal':records.append(('../outside',b'outside'))
    elif change=='missing':records.pop()
    elif change=='bad_member':records[-1]=(records[-1][0],records[-1][1]+b'changed')
    with tarfile.open(archive,'w:gz') as target:
        for index,(name,data) in enumerate(records):
            member=tarfile.TarInfo(name);member.size=len(data)
            if index==0 and change in ('symlink','hardlink'):
                member.type=tarfile.SYMTYPE if change=='symlink' else tarfile.LNKTYPE
                member.linkname='../outside';member.size=0
                target.addfile(member)
            else:target.addfile(member,io.BytesIO(data))
    descriptor=root/pb.BUNDLE/'bundle.json';value=json.loads(descriptor.read_text())
    value['source_archive_sha256']=pb.digest(archive);descriptor.write_text(json.dumps(value))
    with pytest.raises(ValueError,match='native source archive'):
        pb.verify_source_binding(root)
    assert not (tmp_path/'outside').exists()
