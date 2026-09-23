#!/usr/bin/env python3
"""End-to-end check of the screen bridge, exercised through nginx.

Reads N frames off /wmp-screen/stream.bin exactly as the browser does, inflates
them, and writes the last one out as a PNG so the result can be eyeballed.

usage: uv run --with paramiko python tools/verify_stream.py [frames] [out.png]
"""
import os
import struct
import sys
import time
import urllib.request
import zlib

HOST = os.environ.get("WMP_PRINTER", "printer.local")
BASE = "http://%s/wmp-screen" % HOST
W, H = 800, 480
FRAME_BYTES = W * H * 4
MAGIC = b"WMPF"
FRAME_MAGIC = b"WMP2"


def apply_packet(packet, frame):
    if len(packet) < 7 or packet[:4] != FRAME_MAGIC:
        raise ValueError("bad frame packet")
    mode, count = struct.unpack(">BH", packet[4:7])
    if mode == 0:
        raw = packet[7:]
        if len(raw) != FRAME_BYTES:
            raise ValueError("full frame has %d bytes" % len(raw))
        return bytearray(raw), "full"
    if mode != 1 or frame is None:
        raise ValueError("delta without baseline")
    pos = 7
    rows = []
    for _ in range(count):
        if pos + 4 > len(packet): raise ValueError("truncated row header")
        rows.append(struct.unpack(">HH", packet[pos:pos + 4])); pos += 4
    stride = W * 4
    for y, height in rows:
        size = height * stride
        if y + height > H or pos + size > len(packet):
            raise ValueError("invalid row delta")
        frame[y * stride:(y + height) * stride] = packet[pos:pos + size]
        pos += size
    if pos != len(packet): raise ValueError("trailing delta data")
    return frame, "delta/%d" % count


def png(raw_bgra, path):
    rows = bytearray()
    for y in range(H):
        rows.append(0)
        off = y * W * 4
        for x in range(W):
            p = off + x * 4
            rows += bytes((raw_bgra[p + 2], raw_bgra[p + 1], raw_bgra[p]))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    open(path, "wb").write(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(rows), 6))
        + chunk(b"IEND", b""))


def main():
    want = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    out = sys.argv[2] if len(sys.argv) > 2 else "stream_frame.png"

    t0 = time.time()
    resp = urllib.request.urlopen(BASE + "/stream.bin", timeout=30)
    print("stream.bin -> HTTP %d, %s" % (resp.status, resp.headers.get("Content-Type")))

    buf, got, beats, last = b"", 0, 0, None
    while got < want and time.time() - t0 < 60:
        chunk = resp.read(16384)
        if not chunk:
            break
        buf += chunk
        while len(buf) >= 8:
            if buf[:4] != MAGIC:
                sys.exit("FAIL: bad magic %r - framing is broken" % buf[:4])
            n = struct.unpack(">I", buf[4:8])[0]
            if len(buf) < 8 + n:
                break
            payload, buf = buf[8:8 + n], buf[8 + n:]
            if n == 0:
                beats += 1
                continue
            packet = zlib.decompress(payload)
            try:
                last, kind = apply_packet(packet, last)
            except ValueError as exc:
                sys.exit("FAIL: %s" % exc)
            got += 1
            print("  frame %d: %s, %d compressed -> %d packet bytes (%.1f%% of raw)"
                  % (got, kind, n, len(packet), 100.0 * n / FRAME_BYTES))
    resp.close()

    if not got:
        sys.exit("FAIL: no frames received (%d heartbeats) in %.1fs"
                 % (beats, time.time() - t0))
    png(last, out)
    print("PASS: %d frame(s), %d heartbeat(s) in %.1fs; wrote %s"
          % (got, beats, time.time() - t0, out))


if __name__ == "__main__":
    main()
