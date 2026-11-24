"""Startup bookkeeping yields with both tiny lines and huge comment chunks."""
from types import SimpleNamespace
from wmp_plr_jobs import _ScanCooperator


def test_short_slow_lines_yield_before_a_megabyte():
    clock = [0.]
    pauses = []
    def pause(when):
        pauses.append(when)
        clock[0] = when
    worker = _ScanCooperator(SimpleNamespace(monotonic=lambda: clock[0], pause=pause))
    for _ in range(64):
        clock[0] += .001
        worker.advance(4)
    assert len(pauses) == 1
    assert pauses[0] < .067
    assert worker.bytes == 0


def test_comment_chunks_yield_without_waiting_for_time():
    pauses = []
    worker = _ScanCooperator(SimpleNamespace(monotonic=lambda: 0., pause=pauses.append))
    worker.advance(65536)
    assert pauses == [.001]


def test_fast_small_batch_avoids_per_line_clock_and_pause():
    calls = []
    worker = _ScanCooperator(SimpleNamespace(monotonic=lambda: calls.append(1) or 0.,
                                            pause=lambda _: calls.append('pause')))
    for _ in range(63): worker.advance(32)
    assert calls == [1]
    worker.advance(32)
    assert calls == [1, 1]
