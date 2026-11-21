"""Generate inert migration evidence from pinned, already published ancestry.

Run from a Git checkout; the installer itself never invokes Git or downloads
migration code. Review catalog diffs and reseal the screen source package.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

import config_factory
import preload_bundle


def factory_options(directory):
    sections={}
    for path in Path(directory).glob('*.cfg'):
        parsed=config_factory.parser(path.read_text(encoding='utf-8'))
        for section in parsed.sections():
            if not section.startswith(('gcode_macro ','delayed_gcode ')) and section!='homing_override':
                continue
            for key,value in parsed.items(section):
                if key in ('gcode','rename_existing','axes'):
                    digest=hashlib.sha256(preload_bundle.config_contract_value(section,key,value).encode()).hexdigest()
                    sections.setdefault(section,{}).setdefault(key,set()).add(digest)
    return sections


def build(root, ref, vendor_factory=None):
    root = Path(root)
    def git(*args):
        return subprocess.check_output(['git', '-C', str(root), *args])
    commit = git('rev-parse', ref).decode().strip()
    names = git('rev-list', '--objects', commit, '--', 'config/live', 'klipper_extras').decode().splitlines()
    sections, helpers, files = {}, {}, {}
    for item in names:
        oid, _, name = item.partition(' ')
        path = Path(name)
        helper = name.startswith('klipper_extras/') and path.name.startswith(('wmp_', 'wm_material')) and path.suffix=='.py'
        config = name.startswith('config/live/') and path.suffix=='.cfg'
        whole = name.startswith('config/live/') and path.suffix=='.conf'
        if not (helper or config or whole):
            continue
        raw = git('cat-file', 'blob', oid)
        if helper:
            helpers.setdefault(path.name, set()).add(hashlib.sha256(raw).hexdigest())
        if whole:
            files.setdefault(path.name,set()).add(hashlib.sha256(raw).hexdigest())
        if config:
            try:
                parsed = config_factory.parser(raw.decode('utf-8'))
            except (UnicodeError, config_factory.configparser.Error):
                continue
            for section in parsed.sections():
                if not section.startswith(('gcode_macro ', 'delayed_gcode ', 'filament_switch_sensor ')) and section!='homing_override':
                    continue
                for key, value in parsed.items(section):
                    digest = hashlib.sha256(preload_bundle.config_contract_value(section,key,value).encode()).hexdigest()
                    sections.setdefault(section,{}).setdefault(key,set()).add(digest)
    factory=factory_options(root/'config/stock')
    existing=root/config_factory.CATALOG
    prior=json.loads(existing.read_text(encoding='utf-8')).get('factory_sections',{}) if existing.exists() else {}
    sources=[prior]
    if vendor_factory:
        client=Path(vendor_factory).parent/'bin/client'
        baseline=json.loads((root/'config/provenance/factory-motion.json').read_text(encoding='utf-8'))
        if not client.is_file() or hashlib.sha256(client.read_bytes()).hexdigest()!=baseline['stock_client_sha256']:
            raise ValueError('Factory variants require the matching retained 1.1.13 vendor client')
        sources.append(factory_options(vendor_factory))
    for source in sources:
        for section,options in source.items():
            for key,hashes in options.items():
                factory.setdefault(section,{}).setdefault(key,set()).update(hashes)
    return {'version':1, 'published_ancestry':commit,
            'sections':{s:{k:sorted(v) for k,v in sorted(opts.items())} for s,opts in sorted(sections.items())},
            'files':{n:sorted(v) for n,v in sorted(files.items())},
            'factory_sections':{s:{k:sorted(v) for k,v in sorted(opts.items())} for s,opts in sorted(factory.items())},
            'helpers':{n:sorted(v) for n,v in sorted(helpers.items())}}


if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--published-ref',required=True)
    cli.add_argument('--vendor-factory',type=Path,help='matching retained 1.1.13 factory_settings directory')
    args=cli.parse_args()
    root=Path(__file__).resolve().parents[1]
    value=build(root,args.published_ref,args.vendor_factory)
    (root/config_factory.CATALOG).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    print('Recorded',len(value['sections']),'behavior sections and',len(value['helpers']),'helper names')
