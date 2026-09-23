import importlib.util
import struct
import threading
import time
import zlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'wmp_screen', ROOT / 'device/wmp_screen.py')
SCREEN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCREEN)


def decode(packet, baseline=None):
    raw = zlib.decompress(packet)
    magic, mode, count = SCREEN.FRAME_HEADER.unpack_from(raw)
    assert magic == SCREEN.FRAME_MAGIC
    pos = SCREEN.FRAME_HEADER.size
    if mode == SCREEN.FRAME_FULL:
        assert count == 0
        return bytearray(raw[pos:]), []
    assert mode == SCREEN.FRAME_ROWS and baseline is not None
    rows = []
    for _ in range(count):
        rows.append(SCREEN.ROW_HEADER.unpack_from(raw, pos))
        pos += SCREEN.ROW_HEADER.size
    stride = SCREEN.WIDTH * SCREEN.BPP
    result = bytearray(baseline)
    for y, height in rows:
        size = height * stride
        result[y * stride:(y + height) * stride] = raw[pos:pos + size]
        pos += size
    assert pos == len(raw)
    return result, rows


def blank():
    return bytearray(SCREEN.FRAME_BYTES)


def fill_rows(frame, start, end, value):
    stride = SCREEN.WIDTH * SCREEN.BPP
    frame[start * stride:end * stride] = bytes([value]) * ((end - start) * stride)


def test_first_frame_is_a_full_baseline():
    frame = blank()
    frame[123:456] = b'X' * 333
    decoded, rows = decode(SCREEN.encode_update(frame, None))
    assert decoded == frame and rows == []


def test_changed_rows_reconstruct_exact_frame_and_keep_ui_bands_separate():
    before = blank()
    after = blank()
    fill_rows(after, 20, 24, 0x31)
    fill_rows(after, 94, 99, 0x72)  # crosses the top/main boundary at row 96
    fill_rows(after, 420, 423, 0xA5)
    decoded, rows = decode(SCREEN.encode_update(after, before), before)
    assert decoded == after
    assert len(rows) >= 3
    assert all(not (y < 96 < y + height) for y, height in rows)


def test_large_change_falls_back_to_full_frame():
    before = blank()
    after = bytearray(b'Z' * SCREEN.FRAME_BYTES)
    decoded, rows = decode(SCREEN.encode_update(after, before), before)
    assert decoded == after and rows == []


def test_active_capture_is_capped_at_five_fps_and_hidden_client_disconnects():
    assert SCREEN.BUSY_HZ <= 5
    page = (ROOT / 'device/www/index.html').read_text()
    assert 'visibilitychange' in page
    assert 'IntersectionObserver' in page
    assert 'aborter.abort()' in page


def test_wait_for_ignores_notifications_until_frame_changes():
    screen = object.__new__(SCREEN.Screen)
    screen.cond = threading.Condition()
    screen.blob = b'old'
    screen.seq = 7
    result = []

    waiter = threading.Thread(
        target=lambda: result.append(screen.wait_for(7, 1.0)))
    waiter.start()
    time.sleep(0.02)
    with screen.cond:
        screen.cond.notify_all()
    time.sleep(0.02)
    assert waiter.is_alive()

    with screen.cond:
        screen.blob = b'new'
        screen.seq = 8
        screen.cond.notify_all()
    waiter.join(1.0)
    assert result == [(b'new', 8)]
