"""Historical sealed native artifact/source bytes through the real staged publisher; target loader is modeled."""
import json
from pathlib import Path
import pytest
from test_deploy import deploy  # Establish the installer tool import path.
import preload_bundle as pb
from components import preload
from test_preload_bundle import vendor_client, local_installer, bundle_copy
ROOT=Path(__file__).resolve().parents[1]
NATIVE_ELF_SHA='5ddd7d8e5c20a5158e9151afe34cf80e5ef1d8fb0b9c3c117b34815d693eabdf'
REPO_SOURCE_INPUTS_SHA='b5702364bda66dbd7b32f79e13d942895f7756499f66d98b363e64ee4b9a1691'
REPO_SOURCE_ARCHIVE_SHA='05bcb65564d18a98eb70b3a24b53cd86ac7e73a3d94fd589b121b482fe736675'

def test_historical_descriptor_binds_sealed_rebuild_inputs_and_artifact(tmp_path):
    root=bundle_copy(tmp_path)
    bundle=pb.load_bundle(root)
    assert bundle['scope']=='reviewed-delivery'
    assert bundle['artifact']['sha256']==NATIVE_ELF_SHA
    assert pb.digest(root/pb.BUNDLE/bundle['artifact']['file'])==NATIVE_ELF_SHA
    assert bundle['source_manifest_sha256']==REPO_SOURCE_INPUTS_SHA
    assert bundle['source_archive_sha256']==REPO_SOURCE_ARCHIVE_SHA
    assert len(json.loads((root/pb.BUNDLE/'source-inputs.json').read_text()))==32

@pytest.mark.parametrize('fail',[False,True])
def test_actual_final_bytes_publish_once_and_rollback_restores_previous_set(tmp_path,monkeypatch,fail):
    root,home,drop,selected,commands,restarts,ctx=local_installer(tmp_path,monkeypatch,exact=True)
    (home/'lib').mkdir();old=home/'lib/libwmp_openace-compat.so';old.write_bytes(b'prior compatible library');drop.write_text('prior override')
    observed=[]
    def restart(_ctx,_connection, **kwargs):
        observed.append(pb.digest(old))
        if fail and len(observed)==1:
            assert observed[-1]==NATIVE_ELF_SHA
            raise deploy.DeployError('modeled service restart failure')
    monkeypatch.setattr(preload,'_restart',restart)
    if fail:
        with pytest.raises(deploy.DeployError,match='modeled service restart failure'):preload.install(ctx)
        assert old.read_bytes()==b'prior compatible library' and drop.read_text()=='prior override'
        assert len(observed)==2 and not (home/'lib/libwmp_wifi-fix.so').exists()
    else:
        preload.install(ctx)
        assert observed==[NATIVE_ELF_SHA] and pb.digest(old)==NATIVE_ELF_SHA
        assert drop.read_text().count('libwmp_openace-compat.so')==1
    assert not any(c.startswith('gcc ') and 'wmp_openace_compat.c' in c for c in commands)


def test_actual_final_preflight_payload_verifies_with_modeled_target_loader(tmp_path,monkeypatch):
    import subprocess,sys
    root,home,drop,selected,commands,restarts,ctx=local_installer(tmp_path,monkeypatch,exact=True)
    client=vendor_client('1.1.13')
    script=pb.preflight_script(root,str(client))
    result=subprocess.run([sys.executable,'-'],input=script,text=True,capture_output=True)
    assert result.returncode==0,result.stderr
    assert 'screen bundle exact1113 dependency check passed' in result.stdout
    assert not drop.exists() and not restarts


def test_c5_provenance_is_integer_scope_not_installed_or_unrestricted_numeric_proof():
    provenance=json.loads((ROOT/pb.BUNDLE/'review-provenance.json').read_text())
    assert provenance['source_input_count']==32
    assert provenance['historical_native_input_count']==121
    # This reviewed null-prompt change differs from the preserved inherited review.
    assert provenance['inherited_source_review_matches'] is False
    assert provenance['artifact_sha256']==NATIVE_ELF_SHA
    assert provenance['fractional_requests_supported'] is False
    assert provenance['arm_executed'] is False and provenance['installed'] is False
    assert provenance['installed_exports_verified'] is False
    assert provenance['target_dependency_exports_verified'] is False
    assert provenance['native_application_verified'] is False
    # Old successful target proof remains historical, never rebound to this ELF.
    assert provenance['actual_target_dependency_preflight']['exit'] == 0
    assert provenance['actual_target_dependency_preflight']['applies_to_current_artifact'] is False
    assert provenance['actual_target_dependency_preflight']['artifact_sha256'] != NATIVE_ELF_SHA
    assert 'Inherited' in provenance['software_review_scope']
    assert 'integer-only' in provenance['fractional_backend_contract_review']
    control=pb.load_bundle(ROOT/'tests/fixtures/native-screen-control')
    assert control['scope']=='packaging-control-only'
    assert control['artifact']['sha256']=='fdb0c902742e6d04eed14653a80f35ffa3c6d26e7a96c8124d986ba8080704dd'


def test_reviewed_elf_declares_dynamic_symbol_lookup_dependency(tmp_path):
    bundle=pb.load_bundle(bundle_copy(tmp_path))
    assert 'libdl.so.2' in bundle['artifact']['needed']
    # Losing that resolver must still refuse rather than rely on the host client
    # or relax the real preflight's undefined-symbol check.
    complete='\n'.join(name+' => /lib/'+name+' (0x123)' for name in bundle['artifact']['needed'])
    missing='\n'.join(row for row in complete.splitlines() if not row.startswith('libdl.so.2'))
    with pytest.raises(ValueError,match='unresolved: libdl'):
        pb.validate_dependencies(bundle,0,missing)
    with pytest.raises(ValueError,match='undefined symbol: dlsym'):
        pb.validate_dependencies(bundle,0,complete+'\nundefined symbol: dlsym')
    pb.validate_dependencies(bundle,0,complete)
