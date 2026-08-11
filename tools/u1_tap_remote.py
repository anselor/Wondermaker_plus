#!/usr/bin/env python3
"""Runs ON the printer (as root). Injects touch events into /dev/input/event0.

usage: u1_tap_remote.py tap X Y
       u1_tap_remote.py swipe X1 Y1 X2 Y2 [steps]
       u1_tap_remote.py backlight N
"""
import struct, sys, time

DEV = "/dev/input/event0"
BL = "/sys/class/backlight/backlight/brightness"

EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
SYN_REPORT = 0
BTN_TOUCH = 0x14A
ABS_X, ABS_Y = 0x00, 0x01
ABS_MT_SLOT, ABS_MT_TOUCH_MAJOR = 0x2F, 0x30
ABS_MT_POSITION_X, ABS_MT_POSITION_Y, ABS_MT_TRACKING_ID = 0x35, 0x36, 0x39

_tid = [int(time.time()) % 60000]


def emit(f, evs):
    buf = b"".join(struct.pack("llHHi", 0, 0, t, c, v) for t, c, v in evs)
    buf += struct.pack("llHHi", 0, 0, EV_SYN, SYN_REPORT, 0)
    f.write(buf)
    f.flush()


def down(f, x, y):
    _tid[0] = (_tid[0] + 1) % 65535
    emit(f, [(EV_ABS, ABS_MT_SLOT, 0),
             (EV_ABS, ABS_MT_TRACKING_ID, _tid[0]),
             (EV_ABS, ABS_MT_POSITION_X, x),
             (EV_ABS, ABS_MT_POSITION_Y, y),
             (EV_ABS, ABS_MT_TOUCH_MAJOR, 30),
             (EV_KEY, BTN_TOUCH, 1),
             (EV_ABS, ABS_X, x), (EV_ABS, ABS_Y, y)])


def move(f, x, y):
    emit(f, [(EV_ABS, ABS_MT_SLOT, 0),
             (EV_ABS, ABS_MT_POSITION_X, x),
             (EV_ABS, ABS_MT_POSITION_Y, y),
             (EV_ABS, ABS_X, x), (EV_ABS, ABS_Y, y)])


def up(f):
    emit(f, [(EV_ABS, ABS_MT_SLOT, 0),
             (EV_ABS, ABS_MT_TRACKING_ID, -1),
             (EV_KEY, BTN_TOUCH, 0)])


def main():
    cmd = sys.argv[1]
    if cmd == "backlight":
        open(BL, "w").write(sys.argv[2])
        return
    with open(DEV, "wb", buffering=0) as f:
        if cmd == "tap":
            x, y = int(sys.argv[2]), int(sys.argv[3])
            down(f, x, y)
            time.sleep(0.08)
            up(f)
        elif cmd == "swipe":
            x1, y1, x2, y2 = map(int, sys.argv[2:6])
            steps = int(sys.argv[6]) if len(sys.argv) > 6 else 15
            down(f, x1, y1)
            for i in range(1, steps + 1):
                move(f, x1 + (x2 - x1) * i // steps, y1 + (y2 - y1) * i // steps)
                time.sleep(0.012)
            time.sleep(0.03)
            up(f)
        else:
            sys.exit("unknown cmd " + cmd)
    print("ok " + " ".join(sys.argv[1:]))


main()
