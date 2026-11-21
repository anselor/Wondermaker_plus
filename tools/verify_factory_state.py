"""Read-only verification before factory-state motion comparisons.

No G-code, service changes, bootloader requests or firmware writes. The report
contains source hashes and verification outcomes, not printer configuration.
"""
import argparse
import json
import os
from pathlib import Path

from deploy import Context
import preflight

ROOT=Path(__file__).resolve().parents[1]


def inspection_script(manifest,home):
    if manifest.get('version')!=1 or not isinstance(manifest.get('files'),dict) or not manifest['files']:
        raise ValueError('Invalid factory motion baseline')
    for name,digest in manifest['files'].items():
        if Path(name).is_absolute() or '..' in Path(name).parts or not name.endswith(('.py','.c','.h')) or len(digest)!=64:
            raise ValueError('Unsafe factory motion baseline')
    return '''import hashlib,json,os,pathlib,subprocess,time,urllib.request
baseline=json.loads(%r)
home=pathlib.Path(%r)
root=home/'klipper/klippy'
report={'files':{},'checks':{},'scope':baseline['source']}
latest=0
for name,expected in baseline['files'].items():
    path=root/name
    if not path.is_file() or path.is_symlink():
        report['files'][name]={'matches':False,'reason':'missing or linked'}
        continue
    raw=path.read_bytes().replace(b'\\r\\n',b'\\n')
    actual=hashlib.sha256(raw).hexdigest()
    report['files'][name]={'matches':actual==expected,'sha256':actual}
    latest=max(latest,path.stat().st_mtime)
client=home/'TM_T1/bin/client'
report['checks']['stock_client']=client.is_file() and hashlib.sha256(client.read_bytes()).hexdigest()==baseline['stock_client_sha256']
for service,key in [('klipper','klipper_pid'),('makerbase-client','screen_pid')]:
    value=subprocess.check_output(['systemctl','show',service+'.service','--property=MainPID','--value'],text=True).strip()
    report[key]=int(value)
    try:
        maps=pathlib.Path('/proc/'+value+'/maps').read_text()
    except (OSError,ValueError):
        report['checks'][key+'_unmapped_wmp']=False
        continue
    report['checks'][key+'_unmapped_wmp']='libwmp_' not in maps
    if key=='klipper_pid':
        fields=pathlib.Path('/proc/'+value+'/stat').read_text().split(') ',1)[1].split()
        started=time.time()-float(pathlib.Path('/proc/uptime').read_text().split()[0])+int(fields[19])/os.sysconf('SC_CLK_TCK')
        report['checks']['process_started_after_source_restore']=started+0.1>=latest
        helper=root/'chelper/c_helper.so'
        report['checks']['rebuilt_c_helper']=helper.is_file() and helper.stat().st_mtime >= (root/'chelper/kin_shaper.c').stat().st_mtime
        loaded=[line for line in maps.splitlines() if 'c_helper.so' in line]
        report['checks']['current_c_helper_mapped']=helper.is_file() and bool(loaded) and all(' (deleted)' not in line and int(line.split()[4])==helper.stat().st_ino for line in loaded)
with urllib.request.urlopen('http://127.0.0.1:7125/printer/objects/query?webhooks&configfile&print_stats&pause_resume&virtual_sdcard',timeout=5) as response:
    status=json.load(response)['result']['status']
report['checks']['ready']=status['webhooks']['state']=='ready'
report['checks']['idle']=status['print_stats']['state'] not in ('printing','paused') and not status['pause_resume']['is_paused'] and not status['virtual_sdcard']['is_active']
settings=status['configfile']['settings']
active=[]
for section,options in settings.items():
    text=section+'\\n'+'\\n'.join(str(value) for value in options.values())
    if section in ('wm_material','wmp_recovery','wmp_case_light') or 'WMP_' in text.upper() or 'WM_MATERIAL' in text.upper():
        active.append(section)
report['active_wmp_sections']=active
report['checks']['no_active_wmp_configuration']=not active
behavior={}
for section,options in baseline.get('behavior',{}).items():
    actual=settings.get(section.lower(),{})
    behavior[section]=all(key in actual and hashlib.sha256(str(actual[key]).strip().encode()).hexdigest() in (expected if isinstance(expected,list) else [expected]) for key,expected in options.items())
report['factory_behavior']=behavior
report['checks']['factory_motion_macros']=all(behavior.values())
report['verified']=all(row['matches'] for row in report['files'].values()) and all(report['checks'].values())
print(json.dumps(report))
''' % (json.dumps(manifest),home)


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--output',type=Path,help='save verification outcomes to a new local JSON file')
    args=cli.parse_args()
    import preload_bundle
    preload_bundle.verify_source_binding(ROOT)
    baseline=json.loads((ROOT/'config/provenance/factory-motion.json').read_text(encoding='utf-8'))
    ctx=Context(argparse.Namespace())
    try:
        ctx.ssh()
        result=json.loads(preflight.remote(ctx,inspection_script(baseline,'/home/'+ctx.user),sudo=True,quiet=True))
    finally:
        ctx.close()
    if args.output:
        fd=os.open(args.output,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w') as stream:json.dump(result,stream,indent=2)
    print(json.dumps(result,indent=2))
    return 0 if result['verified'] else 1


if __name__=='__main__':
    raise SystemExit(main())
