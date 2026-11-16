"""Keep normal/runout preheat, bypass its stale targets only for tool retry."""
import pytest
from test_toolchange_pause import job, paused

COMMANDS = ['M104 T2 S240',
            'SET_GCODE_VARIABLE MACRO=RESUME VARIABLE=resume_temperature2 VALUE=240',
            'M109 T2 S240']

def command(job, text):
    return job.gcode.create_gcode_command('_WMP_SCREEN_RESUME_PREHEAT', '', {'COMMAND_HEX': text.encode().hex()})


def test_managed_tool_pause_ignores_entire_screen_preheat_prefix(job, caplog):
    paused(job)
    forwarded = []
    original = job.gcode.run_script_from_command
    job.gcode.run_script_from_command = forwarded.append
    for text in COMMANDS:
        job.material.cmd_SCREEN_RESUME_PREHEAT(command(job, text))
    assert forwarded == []
    assert job.material._toolchange_pause['temperatures'] == {}
    assert job.sd.file_position == 0 and job.stats.state == 'paused'
    job.gcode.run_script_from_command = original
    job.gcode.run_script('RESUME')
    assert job.sd.file_position == 3 and not job.pause.is_paused


@pytest.mark.parametrize('kind', ['normal_pause', 'runout_pause', 'openace', 'AFC'])
def test_ordinary_and_other_owner_preheat_is_forwarded_byte_for_byte(job, kind):
    job.stats.state = 'paused'
    job.pause.is_paused = True
    if kind in ('openace', 'AFC'):
        paused(job)
        job.objects[kind] = object()
    if kind == 'runout_pause':
        job.material._pause_origin = {'head': 'h2', 'serviced': False}
    forwarded = []
    job.gcode.run_script_from_command = forwarded.append
    for text in COMMANDS:
        job.material.cmd_SCREEN_RESUME_PREHEAT(command(job, text))
    assert forwarded == COMMANDS


@pytest.mark.parametrize('text', ['M104 T2 S240\nG1 X0', 'M104 T4 S240', 'M104 T2 Sbad',
    'SET_GCODE_VARIABLE MACRO=RESUME VARIABLE=resume_bed VALUE=240', 'G1 X0'])
def test_unexpected_preheat_command_reports_exact_reason(job, text):
    forwarded = []
    job.gcode.run_script_from_command = forwarded.append
    with pytest.raises(job.gcode.error, match='Screen Resume preheat rejected: expected one stock'):
        job.material.cmd_SCREEN_RESUME_PREHEAT(command(job, text))
    assert forwarded == []


def test_corrupt_preheat_encoding_reports_reason(job):
    cmd = job.gcode.create_gcode_command('_WMP_SCREEN_RESUME_PREHEAT', '', {'COMMAND_HEX': 'invalid'})
    with pytest.raises(job.gcode.error, match='Screen Resume preheat rejected: non-hexadecimal'):
        job.material.cmd_SCREEN_RESUME_PREHEAT(cmd)


@pytest.mark.parametrize('failure', [False, True])
def test_screen_preheat_progress_clears_on_success_and_error(job, failure):
    job.stats.state = 'paused'
    job.pause.is_paused = True
    def send(text):
        assert text == 'M109 T2 S240'
        assert job.material._resume_progress == {'phase': 'preheating'}
        if failure:
            raise ValueError('heater failure')
    job.gcode.run_script_from_command = send
    if failure:
        with pytest.raises(ValueError, match='heater failure'):
            job.material.cmd_SCREEN_RESUME_PREHEAT(command(job, 'M109 T2 S240'))
    else:
        job.material.cmd_SCREEN_RESUME_PREHEAT(command(job, 'M109 T2 S240'))
    assert job.material._resume_progress == {}
