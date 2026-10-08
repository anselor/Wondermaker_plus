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


def test_browser_paints_real_unaligned_full_and_row_packets(tmp_path):
    """Execute the actual JS renderer against packets made by the Python bridge."""
    import shutil
    import subprocess
    import pytest
    if not shutil.which('node'):
        pytest.skip('node required for browser renderer check')
    page = (ROOT / 'device/www/index.html').read_text()
    renderer = page[page.index('  function paintRows('):page.index('  function inflate(')]
    raw = bytes([0x12, 0x34, 0x56, 0]) * (SCREEN.WIDTH * SCREEN.HEIGHT)
    full = zlib.decompress(SCREEN.encode_full(raw))
    updated = bytearray(raw)
    updated[800 * 4:800 * 4 + 4] = bytes([0xaa, 0xbb, 0xcc, 0])
    delta = zlib.decompress(SCREEN.encode_update(bytes(updated), raw))
    paths = [tmp_path / 'full.bin', tmp_path / 'delta.bin']
    paths[0].write_bytes(full)
    paths[1].write_bytes(delta)
    script = '''const assert = require('assert'), fs = require('fs');
var DEV_W=800, DEV_H=480, BPP=4, FRAME_MAGIC=0x574d5032;
var outPix=new Uint32Array(DEV_W*DEV_H), imgData={}, frames=0;
var drawn=[], ctx={putImageData: (...args)=>drawn.push(args)}, dead={classList:{remove:()=>{}}};
''' + renderer + '''
for (const path of process.argv.slice(2)) {
  const bytes=fs.readFileSync(path);
  // Give the packet an arbitrary nonzero offset as real browser buffers can have.
  const packet=new Uint8Array(bytes.length+2); packet.set(bytes,2);
  paint(packet.subarray(2));
}
assert.equal(frames,2);
assert.equal(outPix[0],0xff123456);
assert.equal(outPix[800],0xffaabbcc);
assert.equal(outPix[801],0xff123456);
assert.equal(drawn.length,2);
'''
    js = tmp_path / 'render.js'
    js.write_text(script)
    subprocess.run(['node', str(js), *map(str, paths)], check=True)
