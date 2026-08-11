#!/usr/bin/env python3
"""Drive the U1 printer's touchscreen UI over SSH.

usage: u1.py tap X Y [out.png]
       u1.py swipe X1 Y1 X2 Y2 [out.png]
       u1.py shot [out.png]
       u1.py backlight N
       u1.py sh 'command'
"""
import sys, struct, zlib, time, os, paramiko

HOST, USER, PASS = "printer.local", "t13dp", "CHANGE_ME"
W, H, BPP = 800, 480, 4
REMOTE = "/tmp/u1_tap.py"
LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "u1_tap_remote.py")


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASS, timeout=15,
              allow_agent=False, look_for_keys=False)
    return c


def run(c, cmd, sudo=False):
    if sudo:
        cmd = f"echo {PASS} | sudo -S bash -c {shq(cmd)}"
    _, out, err = c.exec_command(cmd, timeout=int(os.environ.get("U1_TIMEOUT", "300")))
    o = out.read().decode("utf-8", "replace")
    e = out.channel.recv_exit_status()
    return o, err.read().decode("utf-8", "replace"), e


def shq(s):
    return "'" + s.replace("'", "'\\''") + "'"


def push_helper(c):
    sftp = c.open_sftp()
    sftp.put(LOCAL, REMOTE)
    sftp.close()


def shot(c, out):
    sftp = c.open_sftp()
    f = sftp.open("/dev/fb0", "rb")
    f.prefetch(W * H * BPP)
    raw = f.read(W * H * BPP)
    f.close()
    sftp.close()
    rows = bytearray()
    for y in range(H):
        rows.append(0)
        off = y * W * BPP
        for x in range(W):
            p = off + x * BPP
            rows += bytes((raw[p + 2], raw[p + 1], raw[p]))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(bytes(rows), 6))
           + chunk(b"IEND", b""))
    open(out, "wb").write(png)
    print("wrote " + out, file=sys.stderr)


def main():
    cmd = sys.argv[1]
    c = connect()
    if cmd == "sh":
        o, e, rc = run(c, sys.argv[2], sudo=("--sudo" in sys.argv))
        print(o, end="")
        if e.strip():
            print("--- stderr ---\n" + e, file=sys.stderr)
        print(f"--- exit {rc} ---", file=sys.stderr)
    elif cmd == "shot":
        shot(c, sys.argv[2] if len(sys.argv) > 2 else "screen.png")
    elif cmd in ("tap", "swipe", "backlight"):
        push_helper(c)
        n = {"tap": 2, "swipe": 4, "backlight": 1}[cmd]
        argv = sys.argv[2:2 + n]
        o, e, rc = run(c, f"python3 {REMOTE} {cmd} {' '.join(argv)}", sudo=True)
        print(o.strip() or e.strip(), file=sys.stderr)
        if cmd != "backlight":
            time.sleep(1.2)
            shot(c, sys.argv[2 + n] if len(sys.argv) > 2 + n else "screen.png")
    c.close()


main()
