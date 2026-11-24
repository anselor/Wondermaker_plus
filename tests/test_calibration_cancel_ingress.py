"""Out-of-band intent is bound to a ticket, with cleanup on the command path."""
from types import SimpleNamespace
import pytest
from test_calibration_commands import setup
from test_calibration_tickets import ticket


class Request:
    error=RuntimeError
    def __init__(self,runner,**changes):
        a=runner._current_attempt
        self.args=dict(session=runner.session,request=a['request'],ticket=a['ticket'])
        self.args.update(changes);self.reply=None
    def get_str(self,key):return self.args[key]
    def send(self,value):self.reply=value


def test_request_during_command_does_not_dispatch_or_touch_heaters():
    p,runner=setup();seen=[]
    def running(command):
        p.objects['heaters'].heaters['extruder2'].set_temp(220)
        request=Request(runner);before=list(p.sent)
        runner.handle_cancel(request);runner.handle_cancel(request)
        assert request.reply['state']=='requested'
        assert p.sent==before and p.off==0
        seen.append(command)
    p.on_run=running
    with pytest.raises(RuntimeError,match='cancellation requested; stopped after G28'):
        runner.cmd_run(ticket(runner,'G28',1))
    assert seen==['G28'] and p.off==1 and not p.shutdown
    assert runner.attempt_status()['cancel_phase']=='after G28'
    p.on_run=lambda _:pytest.fail('queued stage executed after Cancel')
    with pytest.raises(RuntimeError):runner.cmd_run(ticket(runner,'SHAPER_CALIBRATE',1,1))


@pytest.mark.parametrize('field,value',[('session','old'),('request','b'*32),('ticket','2')])
def test_stale_binding_never_changes_attempt(field,value):
    p,runner=setup();runner.cmd_run(ticket(runner,number=1))
    with pytest.raises(RuntimeError,match='changed'):
        runner.handle_cancel(Request(runner,**{field:value}))
    assert not runner.attempt_status().get('cancel_requested')


@pytest.mark.parametrize('owner',['openace','AFC'])
def test_external_owner_is_not_cancelled(owner):
    p,runner=setup();runner.cmd_run(ticket(runner,number=1));p.objects[owner]=object()
    with pytest.raises(RuntimeError,match='owner changed'):runner.handle_cancel(Request(runner))
    assert not runner.attempt_status().get('cancel_requested')


def test_between_commands_cancel_prevents_dispatch_and_later_attempt_is_clean():
    p,runner=setup();runner.cmd_run(ticket(runner,number=1))
    old=Request(runner);runner.handle_cancel(old);before=list(p.sent)
    with pytest.raises(RuntimeError,match='before G28'):runner.cmd_run(ticket(runner,'G28',1,1))
    assert p.sent==before and not p.shutdown
    runner.cmd_run(ticket(runner,number=2))
    assert not runner.attempt_status().get('cancel_requested')
    with pytest.raises(RuntimeError):runner.handle_cancel(old)


def test_cancel_is_refused_during_config_save():
    p,runner=setup();runner.cmd_run(ticket(runner,number=1));runner._saving=True
    with pytest.raises(RuntimeError,match='not cancelable'):runner.handle_cancel(Request(runner))
    assert not runner.attempt_status().get('cancel_requested')


def test_endpoint_registration_uses_calibration_owner():
    from test_calibration_commands import Printer,module
    p=Printer();endpoints={}
    p.objects['webhooks']=SimpleNamespace(register_endpoint=lambda path,cb:endpoints.update({path:cb}))
    runner=module.CalibrationCommands(p,p)
    assert endpoints['wmp/calibration/cancel']==runner.handle_cancel


def test_scrub_cancel_finishes_atomic_tool_command_but_skips_front_travel():
    from test_nozzle_scrub_commands import setup as scrub_setup
    p,gcode,runner=scrub_setup()
    original=gcode.run_script_from_command
    observed=[]
    def run(script):
        original(script)
        if script=='_WMP_CALIBRATION_TOOL T=1':
            runner.handle_cancel(Request(runner))
            observed.append('tool command completed')
    gcode.run_script_from_command=run
    with pytest.raises(p.command_error,match='cancellation requested'):
        runner.cmd_run(ticket(runner,'_WMP_SCRUB_HEAD T=1',1))
    assert observed==['tool command completed']
    assert not any(s.startswith('_WMP_XY_TRAVEL') for s in gcode.sent)
    assert p.heaters['extruder1'].target_temp==0
    assert not p.shutdown


def test_cancel_before_first_command_consumes_only_its_ticket_without_hardware():
    p,runner=setup()
    command=ticket(runner,'G28',1)
    request=object.__new__(Request);request.args=dict(session=runner.session,request=command.binding['REQUEST'],ticket='1');request.reply=None
    runner.handle_cancel(request)
    runner.cmd_run(command)
    assert p.sent==[] and p.off==0
    assert runner.attempt_status()['cancel_cleanup']['park']=='not_moved'
    with pytest.raises(RuntimeError):runner.cmd_run(ticket(runner,'G28',1,1))
    runner.cmd_run(ticket(runner,'G28',2))
    assert p.sent==['G28'] and not runner.attempt_status().get('cancel_requested')


def test_pre_cancel_never_stops_another_request_with_the_same_next_ticket():
    p,runner=setup()
    request=object.__new__(Request);request.args=dict(session=runner.session,request='a'*32,ticket='1');request.reply=None
    runner.handle_cancel(request)
    runner.cmd_run(ticket(runner,'G28',1,request='b'*32))
    assert p.sent==['G28'] and not runner.attempt_status().get('cancel_requested')
