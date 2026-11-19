"""Centre agreement per head during the stock offset measurement."""
from pathlib import Path
import pytest
from test_nozzle_scrub_commands import Command, setup
import wmp_tool_probe

FIXTURES = Path(__file__).parent / 'fixtures'


def phase(runner, head, name):
    runner.active = True
    runner.progress.cmd_phase(Command('', HEAD=str(head), PHASE=name))


def replay(runner, name, order=(0, 1, 2, 3)):
    """Heads measured in order; a head's measurement ends at its sixth Calibrated XY."""
    lines = (FIXTURES / name).read_text(encoding='ascii').splitlines()
    heads = list(order)
    calibrated = 0
    phase(runner, heads[0], 'mounting')
    phase(runner, heads[0], 'position')
    for line in lines:
        runner.nozzle_touch.observe(line)
        if line.startswith('// Calibrated XY:'):
            calibrated += 1
            if calibrated == 6:
                phase(runner, heads[0], 'height')
                heads.pop(0)
                calibrated = 0
                if heads:
                    phase(runner, heads[0], 'mounting')
                    phase(runner, heads[0], 'position')
    return heads


def centre(runner, x, y=293.3):
    runner.nozzle_touch.observe('// Calibrated XY: %f, %f, dx: 3.0, dy: 3.2, dydx: 1.06' % (x, y))


def head_status(runner, head):
    return next(h for h in runner.nozzle_touch.get_status()['heads'] if h['head'] == head)


def spans(runner):
    return [round(h['centre_span'], 3) for h in runner.nozzle_touch.get_status()['heads']]


def measuring(head=1, **config):
    printer, gcode, runner = setup(**config)
    phase(runner, head, 'mounting')
    phase(runner, head, 'position')
    return gcode, runner


def test_clean_run_flags_no_head():
    printer, gcode, runner = setup()
    assert replay(runner, 'toolsetter_clean.log') == []
    status = runner.nozzle_touch.get_status()
    assert status['protocol'] == 2
    assert [h['head'] for h in status['heads']] == [0, 1, 2, 3]
    assert [h['centres'] for h in status['heads']] == [6, 6, 6, 6]
    assert spans(runner) == [0.014, 0.022, 0.014, 0.009]
    assert [h['flagged'] for h in status['heads']] == [False] * 4
    assert status['flagged'] == []


def test_residue_run_flags_heads_whose_centres_disagree():
    printer, gcode, runner = setup()
    replay(runner, 'toolsetter_residue.log')
    assert spans(runner) == [0.783, 0.050, 0.033, 0.011]
    assert runner.nozzle_touch.flagged() == [0, 1, 2]
    assert [h['flagged'] for h in runner.nozzle_touch.get_status()['heads']] == [True, True, True, False]


def test_run_with_remeasurement_clears_the_clean_head():
    printer, gcode, runner = setup()
    first = replay(runner, 'toolsetter_19nov.log', order=(0, 1, 2, 3, 0, 1, 2))
    assert first == [2]  # the log ends during the second measurement of head 3
    status = runner.nozzle_touch.get_status()
    assert [h['centres'] for h in status['heads']] == [6, 6, 4, 6]
    # Head 4 keeps its first measurement; heads 1 to 3 were measured again.
    assert spans(runner) == [0.008, 0.023, 0.006, 0.017]
    assert runner.nozzle_touch.flagged() == []


def test_first_measurement_of_the_run_with_remeasurement():
    printer, gcode, runner = setup()
    lines = (FIXTURES / 'toolsetter_19nov.log').read_text(encoding='ascii').splitlines()
    second = next(i for i, line in enumerate(lines) if i > 0 and line.startswith('// Locating the tool-alignment sensor'))
    head, calibrated = 0, 0
    phase(runner, 0, 'mounting')
    phase(runner, 0, 'position')
    for line in lines[:second]:
        runner.nozzle_touch.observe(line)
        if line.startswith('// Calibrated XY:'):
            calibrated += 1
            if calibrated == 6 and head < 3:
                head, calibrated = head + 1, 0
                phase(runner, head, 'mounting')
                phase(runner, head, 'position')
    assert spans(runner) == [0.558, 0.026, 0.041, 0.017]
    assert runner.nozzle_touch.flagged() == [0, 2]


def test_remeasured_head_is_judged_on_its_new_centres():
    printer, gcode, runner = setup()
    replay(runner, 'toolsetter_19nov.log', order=(0, 1, 2, 3, 0, 1, 2))
    status = head_status(runner, 1)
    assert sorted(status) == ['centre_span', 'centres', 'flagged', 'head']
    assert status['centres'] == 6 and status['flagged'] is False
    assert status['centre_span'] == pytest.approx(0.023437, abs=1e-6)


def test_two_disagreeing_centres_of_three_flag_early():
    gcode, runner = measuring()
    centre(runner, 304.00)
    centre(runner, 304.05)
    assert head_status(runner, 1)['centre_span'] == 0
    assert runner.nozzle_touch.flagged() == []
    centre(runner, 304.10)
    assert head_status(runner, 1)['centre_span'] == pytest.approx(0.05)
    assert runner.nozzle_touch.flagged() == [1]
    # More centres never lower the span: the head stays flagged.
    for x in (304.10, 304.10, 304.10):
        centre(runner, x)
    assert head_status(runner, 1)['centres'] == 6
    assert runner.nozzle_touch.flagged() == [1]


def test_one_stray_centre_of_six_does_not_flag():
    gcode, runner = measuring()
    for x in (304.000, 304.004, 304.500, 304.008, 304.010, 304.002):
        centre(runner, x)
    status = head_status(runner, 1)
    assert status['centres'] == 6
    assert status['centre_span'] == pytest.approx(0.010)
    assert status['flagged'] is False


def test_worse_axis_counts():
    gcode, runner = measuring()
    for y in (293.30, 293.31, 293.36, 293.40):
        centre(runner, 304.0, y)
    status = head_status(runner, 1)
    assert status['centre_span'] == pytest.approx(0.06)
    assert status['flagged'] is True


def test_span_at_the_limit_is_not_flagged():
    gcode, runner = measuring()
    for x in (304.000, 304.030, 304.060):
        centre(runner, x)
    assert runner.nozzle_touch.flagged() == []
    gcode, runner = measuring()
    for x in (304.000, 304.031, 304.062):
        centre(runner, x)
    assert runner.nozzle_touch.flagged() == [1]


def test_remounting_a_head_clears_its_centres():
    gcode, runner = measuring()
    for x in (304.0, 304.1, 304.2):
        centre(runner, x)
    phase(runner, 2, 'mounting')
    phase(runner, 2, 'position')
    centre(runner, 304.0)
    assert runner.nozzle_touch.flagged() == [1]
    phase(runner, 1, 'mounting')
    assert head_status(runner, 1) == {'head': 1, 'centres': 0, 'centre_span': 0, 'flagged': False}
    assert runner.nozzle_touch.flagged() == []
    phase(runner, 1, 'position')
    centre(runner, 304.0)
    assert head_status(runner, 1)['centres'] == 1
    assert head_status(runner, 2)['centres'] == 1


def test_limit_zero_disables():
    gcode, runner = measuring(offset_centre_spread=0)
    for x in (304.0, 304.5, 305.0):
        centre(runner, x)
    assert head_status(runner, 1)['centre_span'] == pytest.approx(0.5)
    assert head_status(runner, 1)['flagged'] is False
    assert runner.nozzle_touch.flagged() == []


def test_limit_option():
    gcode, runner = measuring(offset_centre_spread=0.06)
    for x in (304.00, 304.05, 304.10):
        centre(runner, x)
    assert runner.nozzle_touch.flagged() == []
    with pytest.raises(Exception, match='offset_centre_spread'):
        setup(offset_centre_spread=-0.1)


def test_lines_outside_position_phase_or_attempt_are_ignored():
    gcode, runner = measuring()
    phase(runner, 1, 'height')
    centre(runner, 304.0)
    assert head_status(runner, 1)['centres'] == 0
    phase(runner, 1, 'position')
    runner.active = False
    centre(runner, 304.0)
    assert head_status(runner, 1)['centres'] == 0
    # Status of another request: progress and touch status disagree.
    runner.active = True
    runner.nozzle_touch.request = 'b' * 32
    centre(runner, 304.0)
    assert head_status(runner, 1)['centres'] == 0


def test_other_output_is_ignored():
    gcode, runner = measuring()
    handler, = gcode.output_handlers
    for text in ('', 'ok', '!! Move out of range', '// 碰撞检测已禁用', '// Calibrated XY:',
                 '// Calibrated XY: abc, 1.0', '// Calibrated XY: 1.0.0, 2.0', '// Calibrated XY: nan, 2.0',
                 '// x: 299.000000, y: 289.000000, dir: x+', '// Probe made contact at 301.0, 289.0, 8.65',
                 '// Probe samples exceed tolerance. Retrying...',
                 '// WM+: load-cell false trigger after 0.0400 mm travel; re-zeroing and repeating the touch',
                 None, b'// Calibrated XY: 1.0, 2.0', 12):
        handler(text)
    assert head_status(runner, 1)['centres'] == 0
    handler('// x: 1, y: 2, dir: x+\n// Calibrated XY: 1, 2\n// Calibrated XY: 1.5, 2, dx: 1')
    assert head_status(runner, 1)['centres'] == 2


def test_reset_names_the_request_and_clears_heads():
    gcode, runner = measuring()
    for x in (304.0, 304.1, 304.2):
        centre(runner, x)
    request = 'b' * 32
    runner.active = False
    runner.cmd_run(Command('M400', SESSION=runner.session, REQUEST=request, SEQUENCE='0', TICKET='1'))
    assert runner.nozzle_touch.get_status() == {'protocol': 2, 'request': request, 'heads': [], 'flagged': [], 'restore': 'none'}
    runner.nozzle_touch.reset('c' * 32)
    assert runner.nozzle_touch.get_status()['request'] == 'c' * 32


def test_false_trigger_report_does_not_change_the_centres():
    gcode, runner = measuring()
    report = '// ' + wmp_tool_probe.FALSE_TRIGGER_REPORT % 0.0031
    for x in (304.000, 304.004, 304.008):
        runner.nozzle_touch.observe(report)
        centre(runner, x)
        runner.nozzle_touch.observe(report)
    status = head_status(runner, 1)
    assert status['centres'] == 3
    assert status['centre_span'] == pytest.approx(0.004)
    assert status['flagged'] is False
