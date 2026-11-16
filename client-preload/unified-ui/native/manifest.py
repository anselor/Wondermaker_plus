#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
import hashlib
import json
from pathlib import Path
import sys
from build_id import build_id
from runtime_inputs import RUNTIME_INPUTS
repo,output,image=Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3]
files=[repo/'client-preload/openace-compat/wmp_openace_compat.c']
for path in (repo/'client-preload/unified-ui',repo/'client-preload/openace-compat/screen1113/source'):
 files.extend(p for p in path.rglob('*') if p.is_file() and p.suffix in ('.hpp','.cpp','.h','.c','.sh','.py','.json'))
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
artifact=output/'libwmp_unified_screen_candidate.so'
manifest={'scope':'unified-native-development-candidate','activated':False,'toolchain_image':image,'ui_build_id':build_id(repo),
 'artifact':{'path':artifact.name,'sha256':digest(artifact)},
 'runtime_dependencies':{name:digest(repo/name) for name in RUNTIME_INPUTS},
 'source_inputs':{str(p.relative_to(repo)):digest(p) for p in sorted(set(files))}}
(output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print('Built native candidate:',artifact)
print('SHA256:',manifest['artifact']['sha256'])
