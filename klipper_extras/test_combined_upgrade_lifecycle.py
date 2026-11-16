"""Combined released-state boot through real constructors and Ready ingress."""
import json
import configparser
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
from wm_material import WMMaterial
from wmp_recovery import CalibrationCommands, ProbeSaveRecord
from test_wm_material import profile_command

class Mutex:
    held=False
    def test(self):return self.held
    def __enter__(self):self.held=True
    def __exit__(self,*args):self.held=False

class Gcode:
    quick_stop_flag=False
    is_printer_ready=True
    def __init__(self):self.commands={};self.issued=[];self.mutex=Mutex()
    def register_command(self,name,callback,**kwargs):
        old=self.commands.pop(name,None)
        if callback:self.commands[name]=callback
        return old
    def get_status(self,now):return {'commands':dict(self.commands)}
    def get_mutex(self):return self.mutex
    def error(self,text):return ValueError(text)
    def run_script(self,text):return self._process_commands(text.splitlines())
    def run_script_from_command(self,text):return self._process_commands(text.splitlines())
    def _process_commands(self,lines,need_ack=False):self.issued.extend(lines)

class Reactor:
    NOW=0.;NEVER=float('inf')
    def __init__(self):self.timers=[]
    def monotonic(self):return 10.
    def register_timer(self,callback,when):self.timers.append(callback);return callback
    def update_timer(self,*args):pass

class Config:
    def __init__(self,printer,path):self.printer=printer;self.path=path
    def get_printer(self):return self.printer
    def getfloat(self,key,default,**kwargs):return default
    def get(self,key,default=None):
        return {'ini_path':str(self.path/'tmt1.ini'),'recovery_checkpoint_dir':str(self.path/'checkpoints'),
                'usb_profile_root':str(self.path/'usb')}.get(key,default)

class ConfigFile:
    status_raw_config={'probe':{'z_offset':'1.500'}}
    status_save_pending={}
    def get_status(self,now):return {'settings':{'probe':{'z_offset':1.5}},'save_config_pending_items':{}}
    def _read_config_file(self,path):return Path(path).read_text()
    def _find_autosave_data(self,data):return '',data
    def _build_config_wrapper(self,data,path):
        parser=configparser.RawConfigParser();parser.read_string(data)
        return NS(fileconfig=parser)

class Printer:
    def __init__(self,path):
        self.path=path;self.events={};self.gcode=Gcode();self.reactor=Reactor();self.saved={'fail_flag':-3,'is_nozzle_setting':0}
        for name in ('CANCEL_PRINT','SAVE_CONFIG','SAVE_CONFIG_NO_RESTART'):
            self.gcode.register_command(name,lambda cmd:pytest.fail('startup replayed a stock mutation'))
        self.objects={'gcode':self.gcode,
          'webhooks':NS(register_endpoint=lambda *args:None),
          'save_variables':NS(get_status=lambda now:{'variables':self.saved}),
          'print_stats':NS(get_status=lambda now:{'state':'error'}),
          'pause_resume':NS(get_status=lambda now:{'is_paused':False}),
          'virtual_sdcard':NS(is_active=lambda:False,is_cmd_from_sd=lambda:False,current_file=None),
          'extruder2':NS(),
          'custom_hall':NS(get_status=lambda now:{'Raw':5000}),
          'filament_switch_sensor sensor_b':NS(get_status=lambda now:{'filament_detected':False}),
          'toolhead':NS(get_status=lambda now:{'homed_axes':'xyz'}),
          'configfile':ConfigFile()}
    def lookup_object(self,name,default=None):
        if name.startswith('filament_switch_sensor docked'):return NS(get_status=lambda now:{'filament_detected':True})
        return self.objects.get(name,default)
    def register_event_handler(self,name,callback):self.events.setdefault(name,[]).append(callback)
    def get_reactor(self):return self.reactor
    def get_start_args(self):return {'config_file':str(self.path/'printer.cfg')}
    def is_shutdown(self):return False


def seed(path,state):
    (path/'printer.cfg').write_text('[probe]\nz_offset: 1.500\n')
    (path/'tmt1.ini').write_text('[slot]\nmaterial0=0\nmaterial1=0\nmaterial2=3\nmaterial3=0\n')
    for kind,action in [('toolhead','take'),('filament','unload')]:
        (path/('wmp_'+kind+'_operation.json')).write_text(json.dumps({'version':1,'operation':
            {'id':kind+'_old','head':'h2','action':action,'state':state,'session':'released-session'}}))
    (path/'wmp_print_cancel.json').write_text(json.dumps({'version':1,'id':'cancel_old','session':'released-session',
        'file':'old.gcode','state':'pending','phase':'cancelling','message':'Interrupted'}))
    (path/'wmp_recovery_attempt.json').write_text(json.dumps({'version':1,
        'request':{'id':'recover_old','session':'released-session','file':'old.gcode','execution_hash':'a'*16},
        'state':'running','stages':[{'name':'prepare','state':'running'}],'error':''}))
    ProbeSaveRecord(str(path/'wmp_probe_save.json')).create({'version':1,'session':'a'*32,'request':'b'*32,
        'config_path':str(path/'printer.cfg'),'section':'probe','offset':'1.500',
        'autosave':{'probe':{'z_offset':'1.500'}},'before_sha256':'c'*64})
    # A released staged job is durable evidence; process-local pending dispatch
    # must not be resurrected from it by the new constructor.
    (path/'wmp_recovery_job.json').write_text(json.dumps({'version':1,'state':'staged','owner':'standalone',
        'session':'released-session','file':{'path':'old.gcode'}}))

@pytest.mark.parametrize('old_state',['running','pending'])
@pytest.mark.parametrize('fresh_action',['UNLOCK','G28'])
def test_combined_old_state_boot_is_idempotent_no_replay_and_fresh_action_reachable(tmp_path,old_state,fresh_action):
    seed(tmp_path,old_state)
    preserved={p.name:p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
    stable=None
    for boot in range(2):
        printer=Printer(tmp_path)
        backend=WMMaterial(Config(printer,tmp_path));printer.objects['wm_material']=backend
        calibration=CalibrationCommands(printer,printer.gcode)
        printer.objects['wmp_recovery']=NS(get_status=lambda now:{'calibration_active':calibration.active or calibration.probe_editor.busy(),
            'homing':False,'identification':{'state':'idle'}})
        for callback in list(printer.events['klippy:ready']):callback()
        assert printer.gcode.issued==[]  # no old tool, filament, cancel or recovery replay
        assert backend._pending_recovery_submission is None and backend.print_submission=={}
        assert backend.toolhead_operation['state']=='unknown' and backend.filament_operation['state']=='unknown'
        assert backend._print_cancel['state']=='unknown' and not backend._print_cancel_active()
        assert not backend._recovery_attempt_active()
        assert calibration.probe_editor.state=='save_review' and not calibration.probe_editor.busy()
        assert calibration.probe_editor.save_review['configuration_matches'] is True
        assert printer.saved['fail_flag']==-3  # startup/read-only paths do not silently clear history
        for name,data in preserved.items():
            if name!='wmp_recovery_attempt.json':assert (tmp_path/name).read_bytes()==data
        archived=list(tmp_path.glob('wmp_recovery_attempt_original_*.json'))
        assert len(archived)==1 and archived[0].read_bytes()==preserved['wmp_recovery_attempt.json']
        snapshot={p.name:p.read_bytes() for p in tmp_path.iterdir() if p.is_file()}
        if stable is not None:assert snapshot==stable
        stable=snapshot
        # Real registered public metadata action and wrapped console ingress.
        printer.gcode.commands['WMP_SET_FILAMENT'](profile_command(backend))
        printer.gcode.run_script(fresh_action)
        assert printer.saved['fail_flag']==0 and printer.gcode.issued==[fresh_action]
        # Remove only the intentional new edit before simulating the next boot.
        (tmp_path/'wmp_filaments.json').unlink()
