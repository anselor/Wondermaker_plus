#!/usr/bin/env python3
"""Bind this repository's actual rebuild inputs to its prebuilt native library."""
from pathlib import Path
import gzip,hashlib,importlib.util,io,json,re,shutil,tarfile

DIRECTORY=Path(__file__).resolve().parent
ROOT=DIRECTORY.parents[2]
spec=importlib.util.spec_from_file_location('native_bundle_format',str(ROOT/'tools/preload_bundle.py'))
format_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(format_module)
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,data):
    temporary=path.with_name(path.name+'.repacking')
    temporary.write_bytes(data);temporary.replace(path)
def encoded(value):return (json.dumps(value,indent=2,sort_keys=True)+'\n').encode()

source_names=format_module.native_source_files(ROOT)
inputs={name:digest(ROOT/name) for name in source_names}
toolchain=json.loads((DIRECTORY/'toolchain.json').read_text())
artifact=DIRECTORY/'build-arm/libwmp_openace_screen_candidate.so'
contract=format_module.elf_contract(artifact)
assert contract['machine']=='AArch64' and contract['nodelete']
assert 'libdl.so.2' in contract['needed']
versions=(DIRECTORY/'build-arm/readelf.txt').read_text()
for prefix,key in (('GLIBC','maximum_glibc'),('GLIBCXX','maximum_glibcxx'),('CXXABI','maximum_cxxabi'),('GCC','maximum_gcc')):
    bound=tuple(int(x) for x in toolchain[key].split('.'))
    found=re.findall(r'Name: '+prefix+r'_([0-9.]+)\b',versions)
    assert found and all(tuple(int(x) for x in name.split('.'))<=bound for name in found), (prefix,found,bound)
assert re.search(r'File: libdl\.so\.2',versions)
write(DIRECTORY/'source-inputs.json',encoded(inputs))
# Reproducible archive: no host names/UIDs/timestamps and no absolute paths.
archive=DIRECTORY/'source.tar.gz'
temporary=archive.with_name(archive.name+'.repacking')
with temporary.open('wb') as raw:
    with gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0,compresslevel=1) as compressed:
        with tarfile.open(fileobj=compressed,mode='w|') as stream:
            for name in sorted(inputs):
                data=(ROOT/name).read_bytes();record=tarfile.TarInfo(name)
                record.size=len(data);record.mode=0o755 if name.endswith('.sh') else 0o644
                record.uid=record.gid=record.mtime=0
                stream.addfile(record,io.BytesIO(data))
temporary.replace(archive)
write(DIRECTORY/'screen.so',artifact.read_bytes())
legacy=ROOT/'client-preload/openace-compat/wmp_openace_compat.c'
bundle={'version':1,'scope':'reviewed-delivery','profile':toolchain['profile'],
        'artifact':dict(file='screen.so',sha256=digest(artifact),size=artifact.stat().st_size,**contract),
        'source_manifest_sha256':digest(DIRECTORY/'source-inputs.json'),
        'source_archive_sha256':digest(archive),'legacy_c_sha256':digest(legacy)}
write(DIRECTORY/'bundle.json',encoded(bundle))
history=json.loads((DIRECTORY/'review-history/source-review.json').read_text())
source_review_matches=all(digest(ROOT/name)==want for name,want in history['reviewed_production_source_hashes'].items())
target_matches=digest(artifact)==history['target_preflight_artifact_sha256']
provenance={'version':1,'artifact_source':str((DIRECTORY/'screen.so').relative_to(ROOT)),
 'artifact_sha256':digest(artifact),'source_inputs':str((DIRECTORY/'source-inputs.json').relative_to(ROOT)),
 'source_input_count':len(inputs),'source_manifest_sha256':bundle['source_manifest_sha256'],
 'source_archive':str(archive.relative_to(ROOT)),'source_archive_sha256':bundle['source_archive_sha256'],
 'source_layout':'repository-relative-rebuild-inputs','historical_native_input_count':121,
 'historical_native_manifest_sha256':history['historical_native_manifest_sha256'],
 'software_review':str((DIRECTORY/'review-history/inherited-source-review.md').relative_to(ROOT)),
 'software_review_sha256':history['inherited_source_review_sha256'],
 'software_review_scope':'Inherited review of unchanged native/legacy C/C++ source; not a new build approval or installed UI claim',
 'inherited_source_review_matches':source_review_matches,
 'reviewed_scope':'management/M600 plus paused manual reload; integer procedures only',
 'fractional_requests_supported':False,'fractional_backend_contract_review':'Historical integer-only source scope; no unrestricted numeric completion claim',
 'arm_executed':False,'installed':False,'installed_exports_verified':False,'native_application_verified':False,
 'target_dependency_exports_verified':target_matches,
 'actual_target_dependency_preflight':{'receipt':str((DIRECTORY/'review-history/target-dependency-preflight.json').relative_to(ROOT)),
   'sha256':history['target_dependency_preflight_sha256'],'artifact_sha256':history['target_preflight_artifact_sha256'],
   'applies_to_current_artifact':target_matches,'exit':0},
 'profile_unchanged':True,'legacy_c_unchanged':source_review_matches,
 'original_control_artifact_sha256':'fdb0c902742e6d04eed14653a80f35ffa3c6d26e7a96c8124d986ba8080704dd'}
write(DIRECTORY/'review-provenance.json',encoded(provenance))
format_module.verify_source_binding(ROOT,bundle)
print(json.dumps({'artifact_sha256':digest(artifact),'source_inputs':len(inputs),
 'source_manifest_sha256':bundle['source_manifest_sha256'],'source_archive_sha256':bundle['source_archive_sha256'],
 'inherited_source_review_matches':source_review_matches,'target_preflight_still_applies':target_matches}))
