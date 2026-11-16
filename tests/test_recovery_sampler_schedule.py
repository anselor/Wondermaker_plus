"""Retained SD scheduling evidence for recovery snapshot starvation."""
import ast
import io
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / 'analysis/fw_1.1.13_payload/root/home/t13dp/klipper/klippy'


def method(path, owner, name, namespace):
    tree = ast.parse(path.read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner)
    node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), 'exec'), namespace)
    return namespace[name]


def test_retained_sd_worker_can_offer_no_empty_queue_command_boundary():
    """All timer opportunities may be inside a command or after queued moves.

    Uses retained worker and run_script, with a deterministic reactor/motion
    model. This demonstrates a legal starvation schedule, not printer timing.
    """
    import logging
    import sys
    worker = method(VENDOR / 'extras/virtual_sdcard.py', 'VirtualSD', 'work_handler',
                    {'logging': logging, 'sys': sys})
    run_script = method(VENDOR / 'gcode.py', 'GCodeDispatch', 'run_script', {})
    observations = []
    queued = [False]
    class Mutex:
        held = False
        def test(self): return self.held
        def __enter__(self): self.held = True
        def __exit__(self, *args): self.held = False
    mutex = Mutex()
    class Reactor:
        NOW, NEVER = 0., 1e30
        def unregister_timer(self, timer): pass
        def monotonic(self): return 1.
        def pause(self, when):
            observations.append((mutex.test(), queued[0], sd.cmd_from_sd))
    reactor = Reactor()
    def process(lines, need_ack):
        queued[0] = True
        # Normal buffer backpressure yields while run_script owns the mutex.
        reactor.pause(1.)
    gcode = NS(mutex=mutex, get_mutex=lambda: mutex, _process_commands=process,
               respond_raw=lambda text: None, error=ValueError)
    gcode.run_script = lambda line: run_script(gcode, line)
    results = []
    sd = NS(reactor=reactor, gcode=gcode, current_file=io.StringIO('G1 X150 E.1\n' * 1600),
            file_position=0, next_file_position=0, cmd_from_sd=False,
            work_timer=object(), must_pause_work=False,
            print_stats=NS(note_start=lambda: None, note_complete=lambda: results.append('complete'),
                           note_error=lambda error: results.append(error), note_pause=lambda: results.append('paused')))
    worker(sd, 0.)
    assert results == ['complete']
    assert sum(locked for locked, _, _ in observations) == 1600
    # At the initial read the queue is empty but no print command has completed.
    assert observations[0] == (False, False, False)
    # Later file-read yields release the mutex but retain unscheduled lookahead.
    free = [item for item in observations[1:] if not item[0]]
    assert free and all(item == (False, True, False) for item in free)
    assert not any(not locked and not queue for locked, queue, _ in observations[1:])
