"""SSH observation deadlines without replaying remote commands."""
import sys
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from components import touchscreen

class Channel:
    def __init__(self, stdout=(), stderr=(), completed=True):
        self.stdout, self.stderr = list(stdout), list(stderr)
        self.completed, self.closed, self.exit_reads = completed, False, 0
    def recv_ready(self): return bool(self.stdout)
    def recv_stderr_ready(self): return bool(self.stderr)
    def recv(self, size): return self.stdout.pop(0)
    def recv_stderr(self, size): return self.stderr.pop(0)
    def exit_status_ready(self):
        return self.completed and not self.stderr
    def recv_exit_status(self):
        assert self.exit_status_ready(), 'would block indefinitely'
        self.exit_reads += 1
        return 7
    def close(self): self.closed = True

def client(channel):
    calls = []
    def execute(cmd, **kwargs):
        calls.append(cmd)
        return NS(), NS(channel=channel), NS()
    return NS(exec_command=execute), calls

def test_drains_both_streams_and_split_utf8(capsys):
    channel = Channel([b'a\xe2', b'\x82\xac\n'], [b'warning\n'] * 10)
    connection, calls = client(channel)
    assert touchscreen.run(connection, 'one operation') == ('a€\n', '\n'.join(['warning'] * 10), 7)
    assert capsys.readouterr().out == 'a€\n'
    assert calls == ['one operation']
    assert channel.exit_reads == 1

@pytest.mark.parametrize('continuous', [False, True])
def test_total_deadline_bounds_missing_exit_and_partial_output(monkeypatch, continuous):
    clock = [0.0]
    def now():
        clock[0] += .01
        return clock[0]
    monkeypatch.setattr(touchscreen.time, 'monotonic', now)
    monkeypatch.setattr(touchscreen.time, 'sleep', lambda delay: None)
    channel = Channel(completed=False)
    if continuous:
        channel.recv_ready = lambda: True
        channel.recv = lambda size: b'partial'
    connection, calls = client(channel)
    with pytest.raises(TimeoutError, match='outcome is unconfirmed and was not retried'):
        touchscreen.run(connection, 'mutating command', timeout=.1, stream=False)
    assert channel.closed
    assert channel.exit_reads == 0
    assert calls == ['mutating command']
