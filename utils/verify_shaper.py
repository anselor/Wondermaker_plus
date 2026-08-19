#!/usr/bin/env python3
"""Closed-loop input-shaper verification (Bambu-style).

Unlike TEST_RESONANCES (sweeps frequencies with the shaper OFF to
characterize the machine), this drives rapid oscillating moves at real
print accelerations with the shaper ON and measures the residual vibration
that actually reaches the part. Runs each axis at several accelerations,
both shaper-on and shaper-off, so you see how much the shaper helps and the
accel at which ringing returns.

    uv run --with paramiko --with numpy python utils/verify_shaper.py
    ... [--accels 2000,3500,5000,8000] [--axis X|Y|both]

Restores the machine's configured shaper and accel limit on exit.
"""
import argparse, json, math, os, sys, time, urllib.request

HOST = os.environ.get("WMP_PRINTER", "printer.local")
USER = os.environ.get("WMP_USER", "t13dp")
PASS = os.environ.get("WMP_PASS", "CHANGE_ME")
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(REPO, "utils", ".klippy_cache")
# resonance band to integrate (machine modes live here); excludes the low-freq
# content of the intended oscillation itself.
BAND = (25.0, 100.0)


def api(path, payload=None, timeout=30):
    req = urllib.request.Request(f"http://{HOST}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def gcode(s, timeout=120):
    return api("/printer/gcode/script", {"script": s}, timeout)


def ssh():
    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASS, timeout=20)
    return c


def band_energy(csv_local):
    """Integrate accelerometer PSD over BAND from a raw lis2dw CSV."""
    import numpy as np
    sys.path.insert(0, CACHE)
    from extras import shaper_calibrate
    rows = []
    with open(csv_local) as f:
        for line in f:
            if line.startswith("#"):
                continue
            p = line.split(",")
            if len(p) >= 4:
                try:
                    rows.append([float(x) for x in p[:4]])
                except ValueError:
                    pass
    if len(rows) < 100:
        return None
    helper = shaper_calibrate.ShaperCalibrate(printer=None)

    class D:
        def get_samples(self):
            return rows
    cal = helper.process_accelerometer_data(D())
    cal.normalize_to_frequencies()
    f = np.array(cal.freq_bins)
    psd = np.array(cal.psd_sum)
    m = (f >= BAND[0]) & (f <= BAND[1])
    return float(np.trapezoid(psd[m], f[m]))


def oscillate(axis, lo, hi, vel, accel, cycles):
    gcode(f"SET_VELOCITY_LIMIT ACCEL={accel} ACCEL_TO_DECEL={accel}")
    gcode("G90")
    body = "\n".join(f"G1 {axis}{hi} F{vel}\nG1 {axis}{lo} F{vel}"
                     for _ in range(cycles))
    gcode(body + "\nM400", timeout=180)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--accels", default="2000,3500,5000,8000")
    ap.add_argument("--axis", default="both", choices=["X", "Y", "both"])
    ap.add_argument("--vel", type=int, default=18000, help="mm/min oscillation feed")
    ap.add_argument("--cycles", type=int, default=8)
    args = ap.parse_args()
    accels = [int(a) for a in args.accels.split(",")]
    axes = ["X", "Y"] if args.axis == "both" else [args.axis]

    st = api("/printer/objects/query?print_stats&configfile=settings", timeout=10)
    if st["result"]["status"]["print_stats"]["state"] == "printing":
        sys.exit("printer is printing")
    isp = st["result"]["status"]["configfile"]["settings"]["input_shaper"]
    cfg_accel = st["result"]["status"]["configfile"]["settings"]["printer"]["max_accel"]
    saved = {k: isp.get(k) for k in ("shaper_type_x", "shaper_freq_x",
                                     "shaper_type_y", "shaper_freq_y")}
    print(f"configured shaper: X {saved['shaper_type_x']}@{saved['shaper_freq_x']}  "
          f"Y {saved['shaper_type_y']}@{saved['shaper_freq_y']}  max_accel {cfg_accel}")

    print("homing...")
    gcode("G28", timeout=240)
    # keep travel comfortably inside limits; oscillate around bed center
    spans = {"X": (40, 260), "Y": (40, 260)}
    c = ssh(); sftp = c.open_sftp()
    results = []
    try:
        for axis in axes:
            lo, hi = spans[axis]
            gcode(f"G90\nG1 X150 Y150 F12000\nM400")
            for shaper_on in (True, False):
                if shaper_on:
                    gcode(f"SET_INPUT_SHAPER "
                          f"SHAPER_TYPE_X={saved['shaper_type_x']} SHAPER_FREQ_X={saved['shaper_freq_x']} "
                          f"SHAPER_TYPE_Y={saved['shaper_type_y']} SHAPER_FREQ_Y={saved['shaper_freq_y']}")
                else:
                    gcode("SET_INPUT_SHAPER SHAPER_FREQ_X=0 SHAPER_FREQ_Y=0")
                for accel in accels:
                    tag = f"v_{axis}_{'on' if shaper_on else 'off'}_{accel}"
                    gcode(f"ACCELEROMETER_MEASURE CHIP=lis2dw NAME={tag}")
                    oscillate(axis, lo, hi, args.vel, accel, args.cycles)
                    gcode(f"ACCELEROMETER_MEASURE CHIP=lis2dw NAME={tag}")
                    time.sleep(0.5)
                    remote = f"/tmp/lis2dw-{tag}.csv"
                    local = f"/tmp/{tag}.csv"
                    try:
                        sftp.get(remote, local)
                        e = band_energy(local)
                        os.remove(local); c.exec_command(f"rm -f {remote}")
                    except Exception as ex:
                        e = None
                        print(f"  {tag}: pull/analyze failed: {ex}")
                    results.append((axis, shaper_on, accel, e))
                    print(f"  {axis} shaper={'ON ' if shaper_on else 'OFF'} "
                          f"accel={accel:5d}  band-energy={e:.3e}" if e else
                          f"  {axis} accel={accel} (no data)")
    finally:
        # restore configured shaper + accel
        gcode(f"SET_INPUT_SHAPER "
              f"SHAPER_TYPE_X={saved['shaper_type_x']} SHAPER_FREQ_X={saved['shaper_freq_x']} "
              f"SHAPER_TYPE_Y={saved['shaper_type_y']} SHAPER_FREQ_Y={saved['shaper_freq_y']}")
        gcode(f"SET_VELOCITY_LIMIT ACCEL={cfg_accel}")
        c.close()

    print("\n=== residual vibration (lower is better; energy in "
          f"{BAND[0]:.0f}-{BAND[1]:.0f} Hz) ===")
    print(f"{'axis':4} {'accel':>6}  {'shaper ON':>12} {'shaper OFF':>12}  {'reduction':>9}")
    bykey = {(a, s, ac): e for a, s, ac, e in results}
    for axis in axes:
        for accel in accels:
            on = bykey.get((axis, True, accel))
            off = bykey.get((axis, False, accel))
            red = f"{(1-on/off)*100:.0f}%" if on and off else "?"
            print(f"{axis:4} {accel:6d}  {on:12.3e} {off:12.3e}  {red:>9}"
                  if on and off else f"{axis} {accel}: incomplete")
    print("\nInterpretation: with a good shaper, 'ON' stays low and flat as accel "
          "rises. Where 'ON' climbs steeply is where the shaper stops coping — "
          "keep print accel below that. Small ON/OFF reduction = shaper not "
          "matched to the real resonance.")


if __name__ == "__main__":
    main()
