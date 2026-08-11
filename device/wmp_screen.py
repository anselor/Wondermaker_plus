#!/usr/bin/env python3
"""wmp-screen: stream the printer's framebuffer and inject touch events.

Serves a live, interactive view of /dev/fb0 plus a small JSON API that writes
synthetic multitouch events into the Goodix panel, so the vendor UI can be
driven from a browser. Designed to sit behind nginx and be embedded in Fluidd
as an `iframe` webcam.

Standard library only -- the printer has Python 3.9 and no pip packages.

Frames go out as raw BGRA compressed with zlib rather than as MJPEG. On this
RK3308 that measured 35ms/frame against 179ms for a persistent ffmpeg pipe, it
is lossless (the UI is text and flat colour, which JPEG smears), and it avoids
a subprocess whose rawvideo demuxer holds one frame back -- that lag would have
shown every screen one change behind. The browser inflates via
DecompressionStream and blits to a canvas.
"""

import json
import mmap
import os
import struct
import subprocess
import sys
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

FB_DEV = "/dev/fb0"
TOUCH_DEV = "/dev/input/event0"
BACKLIGHT = "/sys/class/backlight/backlight/brightness"
WWW_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "www")

WIDTH, HEIGHT, BPP = 800, 480, 4
FRAME_BYTES = WIDTH * HEIGHT * BPP

BIND_HOST = os.environ.get("WMP_HOST", "127.0.0.1")
BIND_PORT = int(os.environ.get("WMP_PORT", "8975"))
ZLIB_LEVEL = int(os.environ.get("WMP_ZLIB_LEVEL", "3"))
IDLE_HZ = float(os.environ.get("WMP_IDLE_HZ", "4"))
BUSY_HZ = float(os.environ.get("WMP_BUSY_HZ", "10"))
BUSY_WINDOW = float(os.environ.get("WMP_BUSY_WINDOW", "3"))
HEARTBEAT_S = float(os.environ.get("WMP_HEARTBEAT", "10"))
ARMED = os.environ.get("WMP_ARMED", "1") not in ("0", "false", "no")

MAGIC = b"WMPF"

# linux/input-event-codes.h
EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
SYN_REPORT = 0
BTN_TOUCH = 0x14A
ABS_X, ABS_Y = 0x00, 0x01
ABS_MT_SLOT, ABS_MT_TOUCH_MAJOR = 0x2F, 0x30
ABS_MT_POSITION_X, ABS_MT_POSITION_Y, ABS_MT_TRACKING_ID = 0x35, 0x36, 0x39

# struct input_event on 64-bit: two 8-byte timeval fields, then type/code/value
EVENT_FMT = "llHHi"


def log(msg):
    sys.stderr.write("[wmp-screen] %s\n" % msg)
    sys.stderr.flush()


def _clamp(x, y):
    return (max(0, min(WIDTH - 1, int(x))), max(0, min(HEIGHT - 1, int(y))))


# --------------------------------------------------------------------------
# Touch injection
# --------------------------------------------------------------------------

class Touch:
    """Writes multitouch protocol-B event sequences to the panel."""

    def __init__(self, dev=TOUCH_DEV):
        self.dev = dev
        self.lock = threading.Lock()
        self._tid = int(time.time()) % 60000

    def _emit(self, fh, events):
        buf = b"".join(struct.pack(EVENT_FMT, 0, 0, t, c, v) for t, c, v in events)
        buf += struct.pack(EVENT_FMT, 0, 0, EV_SYN, SYN_REPORT, 0)
        fh.write(buf)
        fh.flush()

    def _down(self, fh, x, y):
        self._tid = (self._tid + 1) % 65535
        self._emit(fh, [
            (EV_ABS, ABS_MT_SLOT, 0),
            (EV_ABS, ABS_MT_TRACKING_ID, self._tid),
            (EV_ABS, ABS_MT_POSITION_X, x),
            (EV_ABS, ABS_MT_POSITION_Y, y),
            (EV_ABS, ABS_MT_TOUCH_MAJOR, 30),
            (EV_KEY, BTN_TOUCH, 1),
            (EV_ABS, ABS_X, x),
            (EV_ABS, ABS_Y, y),
        ])

    def _move(self, fh, x, y):
        self._emit(fh, [
            (EV_ABS, ABS_MT_SLOT, 0),
            (EV_ABS, ABS_MT_POSITION_X, x),
            (EV_ABS, ABS_MT_POSITION_Y, y),
            (EV_ABS, ABS_X, x),
            (EV_ABS, ABS_Y, y),
        ])

    def _up(self, fh):
        self._emit(fh, [
            (EV_ABS, ABS_MT_SLOT, 0),
            (EV_ABS, ABS_MT_TRACKING_ID, -1),
            (EV_KEY, BTN_TOUCH, 0),
        ])

    @staticmethod
    def backlight():
        try:
            with open(BACKLIGHT) as f:
                return int(f.read().strip())
        except Exception:
            return -1

    def _wake_if_dark(self, fh, x, y):
        """The UI swallows the first touch after blanking as a wake event."""
        if self.backlight() != 0:
            return False
        self._down(fh, x, y)
        time.sleep(0.08)
        self._up(fh)
        time.sleep(0.5)
        return True

    def tap(self, x, y, hold=0.08):
        x, y = _clamp(x, y)
        with self.lock, open(self.dev, "wb", buffering=0) as fh:
            woke = self._wake_if_dark(fh, x, y)
            self._down(fh, x, y)
            time.sleep(hold)
            self._up(fh)
        return {"x": x, "y": y, "woke": woke}

    def swipe(self, x1, y1, x2, y2, steps=15, duration=0.25):
        x1, y1 = _clamp(x1, y1)
        x2, y2 = _clamp(x2, y2)
        steps = max(2, min(60, int(steps)))
        with self.lock, open(self.dev, "wb", buffering=0) as fh:
            woke = self._wake_if_dark(fh, x1, y1)
            self._down(fh, x1, y1)
            for i in range(1, steps + 1):
                self._move(fh, x1 + (x2 - x1) * i // steps,
                           y1 + (y2 - y1) * i // steps)
                time.sleep(duration / steps)
            time.sleep(0.03)
            self._up(fh)
        return {"from": [x1, y1], "to": [x2, y2], "woke": woke}


# --------------------------------------------------------------------------
# Framebuffer capture
# --------------------------------------------------------------------------

class Screen:
    """Publishes a compressed frame whenever the framebuffer changes.

    Capture only runs while something is watching: a full 1.5MB read-and-
    compare costs ~29ms here, so polling around the clock would burn real CPU
    on a board whose UI process already wants 40% of a core.
    """

    def __init__(self):
        self.fd = os.open(FB_DEV, os.O_RDONLY)
        self.map = mmap.mmap(self.fd, FRAME_BYTES, mmap.MAP_SHARED,
                             mmap.PROT_READ)
        self.cond = threading.Condition()
        self.blob = None
        self.seq = 0
        self.last_change = 0.0
        self.viewers = 0
        self.frames = 0
        self._prev = None
        self._busy_until = 0.0

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def nudge(self):
        """Poll faster for a moment -- called after an injected touch."""
        self._busy_until = time.time() + BUSY_WINDOW
        with self.cond:
            self.cond.notify_all()

    def add_viewer(self, delta):
        with self.cond:
            self.viewers = max(0, self.viewers + delta)
            self.cond.notify_all()

    def _loop(self):
        while True:
            with self.cond:
                while self.viewers <= 0:
                    self._prev = None      # force a fresh frame for the next viewer
                    self.cond.wait(30)
            t0 = time.time()
            try:
                self.map.seek(0)
                raw = self.map.read(FRAME_BYTES)
                if raw != self._prev:
                    blob = zlib.compress(raw, ZLIB_LEVEL)
                    self._prev = raw
                    self._busy_until = time.time() + BUSY_WINDOW
                    with self.cond:
                        self.blob = blob
                        self.seq += 1
                        self.frames += 1
                        self.last_change = time.time()
                        self.cond.notify_all()
            except Exception as exc:
                log("capture error: %s" % exc)
                time.sleep(1.0)
            hz = BUSY_HZ if time.time() < self._busy_until else IDLE_HZ
            time.sleep(max(0.0, (1.0 / hz) - (time.time() - t0)))

    def wait_for(self, last_seq, timeout):
        with self.cond:
            if self.seq == last_seq:
                self.cond.wait(timeout)
            return self.blob, self.seq

    def latest(self):
        with self.cond:
            return self.blob, self.seq


class Snapshotter:
    """One-shot JPEG for debugging and non-browser clients.

    ffmpeg costs ~1.8s to start on this CPU, so results are cached briefly and
    this is deliberately kept off the live path.
    """

    def __init__(self, screen, ttl=2.0):
        self.screen = screen
        self.ttl = ttl
        self.lock = threading.Lock()
        self.jpeg = None
        self.when = 0.0

    def get(self):
        with self.lock:
            if self.jpeg is not None and time.time() - self.when < self.ttl:
                return self.jpeg
            self.screen.map.seek(0)
            raw = self.screen.map.read(FRAME_BYTES)
            cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
                   "-f", "rawvideo", "-pix_fmt", "bgra",
                   "-s", "%dx%d" % (WIDTH, HEIGHT), "-i", "pipe:0",
                   "-an", "-c:v", "mjpeg", "-q:v", "3",
                   "-f", "image2pipe", "pipe:1"]
            try:
                out = subprocess.run(cmd, input=raw, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL,
                                     timeout=20).stdout
            except Exception as exc:
                log("snapshot failed: %s" % exc)
                return None
            if out:
                self.jpeg, self.when = out, time.time()
            return self.jpeg or None


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".png": "image/png",
    ".ico": "image/x-icon",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "wmp-screen"

    screen = None
    touch = None
    snapshotter = None
    armed = ARMED

    def log_message(self, fmt, *args):
        pass  # nginx already logs these

    # -- helpers ---------------------------------------------------------
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode() or "{}") if n else {}

    def _path(self):
        return self.path.split("?", 1)[0]

    # -- routes ----------------------------------------------------------
    def do_GET(self):
        path = self._path()
        if path in ("/", "/index.html"):
            return self._static("index.html")
        if path == "/stream.bin":
            return self._stream()
        if path == "/snapshot.jpg":
            return self._snapshot()
        if path == "/api/state":
            return self._json(self._state())
        if path.startswith("/api/"):
            return self._json({"error": "not found"}, 404)
        return self._static(path.lstrip("/"))

    def do_POST(self):
        path = self._path()
        try:
            if path in ("/api/tap", "/api/swipe"):
                if not Handler.armed:
                    return self._json({"error": "input disarmed"}, 403)
                d = self._read_json()
                if path == "/api/tap":
                    res = self.touch.tap(d["x"], d["y"])
                else:
                    res = self.touch.swipe(d["x1"], d["y1"], d["x2"], d["y2"],
                                           d.get("steps", 15))
                self.screen.nudge()
                return self._json(res)
            if path == "/api/arm":
                Handler.armed = bool(self._read_json().get("armed", True))
                return self._json(self._state())
        except Exception as exc:
            return self._json({"error": str(exc)}, 500)
        return self._json({"error": "not found"}, 404)

    def _state(self):
        return {
            "width": WIDTH, "height": HEIGHT,
            "armed": Handler.armed,
            "backlight": Touch.backlight(),
            "seq": self.screen.seq,
            "viewers": self.screen.viewers,
            "frames": self.screen.frames,
            "last_change": self.screen.last_change,
        }

    def _static(self, rel):
        rel = os.path.normpath(rel).lstrip("/")
        full = os.path.join(WWW_DIR, rel)
        if not full.startswith(WWW_DIR) or not os.path.isfile(full):
            return self._json({"error": "not found"}, 404)
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES.get(
            os.path.splitext(full)[1], "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _snapshot(self):
        jpeg = self.snapshotter.get()
        if not jpeg:
            return self._json({"error": "encode failed"}, 503)
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(jpeg)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(jpeg)

    def _stream(self):
        """Length-prefixed zlib frames: 'WMPF' + uint32 length + payload.

        A zero length is a heartbeat, which keeps proxies from timing out a
        screen that simply is not changing.
        """
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.screen.add_viewer(+1)
        last_seq = -1
        try:
            while True:
                blob, seq = self.screen.wait_for(last_seq, HEARTBEAT_S)
                if blob is None or seq == last_seq:
                    self.wfile.write(MAGIC + struct.pack(">I", 0))
                    self.wfile.flush()
                    continue
                last_seq = seq
                self.wfile.write(MAGIC + struct.pack(">I", len(blob)))
                self.wfile.write(blob)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.screen.add_viewer(-1)


def main():
    if not os.access(FB_DEV, os.R_OK) or not os.access(TOUCH_DEV, os.W_OK):
        log("FATAL: need read on %s and write on %s (run as root)"
            % (FB_DEV, TOUCH_DEV))
        return 1

    screen = Screen()
    screen.start()
    Handler.screen = screen
    Handler.touch = Touch()
    Handler.snapshotter = Snapshotter(screen)

    server = ThreadingHTTPServer((BIND_HOST, BIND_PORT), Handler)
    server.daemon_threads = True
    log("listening on %s:%d (armed=%s)" % (BIND_HOST, BIND_PORT, ARMED))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
