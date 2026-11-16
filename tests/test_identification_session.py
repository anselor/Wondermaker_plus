"""Run the setup sequence with actual UUID transactions and modeled hardware."""
import copy
import json

import pytest
from test_identification_transaction import files, module, snapshot


class Hardware:
    def __init__(self, order=(3, 2, 1, 0)):
        self.order = order
        self.commands = []
        self.shutdowns = []
        self.fail_command = None
        self.final_dock_error = False
        self.mode_clear_error = False
        self.picks = 0
        self.state = dict(ready=True, idle=True, paused=False, fault=0,
                          recovery_ready=True, mounted=False, docked=[True] * 4,
                          homed_axes='xyz', identifying=False, toolchange_success=True)

    def observe(self):
        return copy.deepcopy(self.state)

    def execute(self, command):
        self.commands.append(command)
        if command == self.fail_command:
            raise RuntimeError('injected command failure')
        if command == 'G28':
            self.state['homed_axes'] = 'xyz'
        elif command.startswith('_CHANGE_TOOL T='):
            physical = int(command.split('=')[1])
            self.picks += 1
            self.state.update(mounted=True, docked=[n != self.order[physical] for n in range(4)])
        elif command == 'PARK_CURRENT_TOOL':
            if self.final_dock_error and self.picks == 4:
                self.state['fault'] = -3
            else:
                self.state.update(mounted=False, docked=[True] * 4)
        elif 'VARIABLE=is_nozzle_setting' in command:
            if command.endswith('VALUE=0') and self.mode_clear_error:
                raise RuntimeError('cannot clear mode')
            self.state['identifying'] = command.endswith('VALUE=1')


def session(files, hardware):
    return module.IdentificationSession(module.MappingTransaction(files, 4),
                                        hardware.observe, hardware.execute,
                                        hardware.shutdowns.append)


def test_full_sequence_commits_only_after_docking_and_has_numbered_stages(files):
    hardware = Hardware()
    operation = session(files, hardware)
    journal = operation.run()
    assert operation.state == 'complete'
    assert json.loads(journal.read_text())['state'] == 'committed'
    assert hardware.commands[-2:] == ['SAVE_VARIABLE VARIABLE=is_nozzle_setting VALUE=0', 'M400']
    assert [s['number'] for s in operation.status()['steps']] == list(range(1, 8))
    assert all(s['state'] == 'complete' for s in operation.status()['steps'])
    assert not hardware.state['mounted'] and not hardware.state['identifying']
    assert 'FIRMWARE_RESTART' not in hardware.commands


@pytest.mark.parametrize('field,value', [('idle', False), ('paused', True), ('ready', False),
                                       ('mounted', True), ('fault', -3), ('recovery_ready', False),
                                       ('identifying', True), ('docked', [True, None, True, True])])
def test_unsafe_entry_has_no_commands_or_writes(files, field, value):
    hardware = Hardware()
    hardware.state[field] = value
    before = snapshot(files)
    operation = session(files, hardware)
    with pytest.raises(ValueError):
        operation.run()
    assert not hardware.commands
    assert snapshot(files) == before


@pytest.mark.parametrize('case', ['pickup-command', 'duplicate', 'dock-error', 'toolchange-failed', 'clear-mode'])
def test_failed_stage_stops_before_commit_and_never_retries_motion(files, case):
    hardware = Hardware(order=(3, 3, 1, 0) if case == 'duplicate' else (3, 2, 1, 0))
    if case == 'pickup-command':
        hardware.fail_command = '_CHANGE_TOOL T=1'
    elif case == 'dock-error':
        hardware.final_dock_error = True
    elif case == 'toolchange-failed':
        hardware.state['toolchange_success'] = False
    elif case == 'clear-mode':
        hardware.mode_clear_error = True
    operation = session(files, hardware)
    before = snapshot(files)
    with pytest.raises((ValueError, RuntimeError)):
        operation.run()
    assert snapshot(files) == before
    assert operation.state == 'failed'
    assert len([s for s in operation.status()['steps'] if s['state'] == 'failed']) == 1
    assert not operation.transaction.committed
    assert 'FIRMWARE_RESTART' not in hardware.commands
    commands = list(hardware.commands)
    with pytest.raises(ValueError, match='cannot be resumed'):
        operation.run()
    assert hardware.commands == commands
    if case == 'clear-mode':
        assert len(hardware.shutdowns) == 1
    else:
        assert not hardware.state['identifying']


def test_unconfirmed_homing_stops_before_pickup(files):
    hardware = Hardware()
    hardware.state['homed_axes'] = ''
    execute = hardware.execute
    def no_home(command):
        execute(command)
        if command == 'G28':
            hardware.state['homed_axes'] = 'xy'
    hardware.execute = no_home
    before = snapshot(files)
    operation = session(files, hardware)
    with pytest.raises(ValueError, match='Homing completion'):
        operation.run()
    assert hardware.commands == ['G28', 'M400']
    assert snapshot(files) == before


def test_pause_arriving_during_pickup_stops_further_motion(files):
    hardware = Hardware()
    execute = hardware.execute
    def pause_during_pickup(command):
        execute(command)
        if command == '_CHANGE_TOOL T=0':
            hardware.state['paused'] = True
    hardware.execute = pause_during_pickup
    operation = session(files, hardware)
    before = snapshot(files)
    with pytest.raises(ValueError, match='idle printer'):
        operation.run()
    pick = hardware.commands.index('_CHANGE_TOOL T=0')
    assert hardware.commands[pick + 1:] == ['M400', 'SAVE_VARIABLE VARIABLE=is_nozzle_setting VALUE=0']
    assert snapshot(files) == before
