#!/usr/bin/env python3
"""Movement-noise test — closed-loop input-shaper verification (Bambu-style).

Unlike TEST_RESONANCES (sweeps frequencies with the shaper OFF to
characterize the machine), this drives a fixed battery of real movement
patterns with the shaper ON at print accelerations and measures the residual
vibration that actually reaches the part. It runs each pattern shaper-ON and
shaper-OFF at several accelerations, then writes a report and two graphs:

  * spectra.png  — residual PSD per pattern (shaper ON): shows WHERE the
                   noise is (which frequency), so a direction-specific rattle
                   is obvious (e.g. a diagonal-only peak the shaper can't fix).
  * summary.png  — residual energy per pattern (ON vs OFF): shows WHICH move
                   types are bad and how much the shaper helps.

    uv run --with paramiko --with numpy --with matplotlib \
        python utils/verify_shaper.py
    ... [--accels 3500,5000,8000] [--patterns x,y,diag_a,diag_b,square,triangle]
        [--out DIR] [--vel 20000] [--cycles 8]

Restores the machine's configured shaper and accel limit on exit.

Patterns (centred on the bed, ~200 mm span):
  x/y       — pure single-axis oscillation (both belts move together)
  diag_a    — 1,1 diagonal (drives the "belt A" / upper loop)
  diag_b    — 1,-1 diagonal (drives the "belt B" / lower loop)
  square    — axis-aligned box (corners are pure X/Y)
  triangle  — angled edges (mixes the belts, like curves/angled walls)
"""
import argparse, datetime, json, math, os, sys, time, urllib.request

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, 'tools'))
from local_env import configure_ssh_client, require  # noqa: E402

HOST = os.environ.get("WMP_PRINTER")
USER = os.environ.get("WMP_USER")
PASS = os.environ.get("WMP_PASS")
CACHE = os.path.join(REPO, "utils", ".klippy_cache")
BAND = (25.0, 100.0)   # resonance band to integrate for the residual metric

# pattern -> list of (x,y) waypoints, looped. Centre 150,150; span keeps a
# safe margin inside the ~312x350 envelope.
C, R = 150, 100
PATTERNS = {
    "x":        [(C - R, C), (C + R, C)],
    "y":        [(C, C - R), (C, C + R)],
    "diag_a":   [(C - R, C - R), (C + R, C + R)],      # 1,1  (upper belt)
    "diag_b":   [(C - R, C + R), (C + R, C - R)],      # 1,-1 (lower belt)
    "square":   [(C - R, C - R), (C + R, C - R), (C + R, C + R), (C - R, C + R)],
    "triangle": [(C, C + R), (C - R, C - R), (C + R, C - R)],
}


def api(path, payload=None, timeout=30):
    global HOST
    HOST = HOST or require("WMP_PRINTER")
    req = urllib.request.Request(f"http://{HOST}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def gcode(s, timeout=240):
    return api("/printer/gcode/script", {"script": s}, timeout)


def ssh():
    import paramiko
    global HOST, USER, PASS
    HOST, USER, PASS = (HOST or require("WMP_PRINTER"),
                        USER or require("WMP_USER"),
                        PASS or require("WMP_PASS"))
    c = paramiko.SSHClient()
    configure_ssh_client(c)
    c.connect(HOST, username=USER, password=PASS, timeout=20)
    return c


def spectrum(csv_local):
    """(band_energy, freq[], psd[]) from a raw lis2dw CSV, or None."""
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
    return float(np.trapezoid(psd[m], f[m])), f, psd


def pattern_script(tag, pts, vel, accel, cycles):
    """Single gcode script that brackets the moves with the accelerometer
    start/stop. Must be one script: ACCELEROMETER_MEASURE runs when received,
    not queued behind kinematic moves, so separate calls race and the window
    closes before the motion happens."""
    moves = "".join(f"G1 X{x} Y{y} F{vel}\n"
                    for _ in range(cycles) for x, y in pts[1:] + pts[:1])
    return (
        f"SET_VELOCITY_LIMIT ACCEL={accel} ACCEL_TO_DECEL={accel}\n"
        f"G90\nG1 X{pts[0][0]} Y{pts[0][1]} F12000\nM400\n"
        f"ACCELEROMETER_MEASURE CHIP=lis2dw NAME={tag}\n"
        f"{moves}M400\n"
        f"ACCELEROMETER_MEASURE CHIP=lis2dw NAME={tag}")


def peak_in_band(f, psd):
    import numpy as np
    m = (f >= BAND[0]) & (f <= BAND[1])
    fm, pm = f[m], psd[m]
    return float(fm[int(np.argmax(pm))])


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--accels", default="5000,8000")
    ap.add_argument("--patterns", default=",".join(PATTERNS))
    ap.add_argument("--vel", type=int, default=20000, help="mm/min oscillation feed")
    ap.add_argument("--cycles", type=int, default=6)
    ap.add_argument("--out", default=None, help="output dir (default resonance/<date>/movement-test)")
    args = ap.parse_args()
    accels = [int(a) for a in args.accels.split(",")]
    pats = [p for p in args.patterns.split(",") if p in PATTERNS]
    graph_accel = accels[len(accels) // 2]   # representative accel for graphs
    outdir = args.out or os.path.join(
        REPO, "resonance", datetime.date.today().isoformat(), "movement-test")
    os.makedirs(outdir, exist_ok=True)

    st = api("/printer/objects/query?print_stats&configfile=settings", timeout=10)
    if st["result"]["status"]["print_stats"]["state"] == "printing":
        sys.exit("printer is printing")
    isp = st["result"]["status"]["configfile"]["settings"]["input_shaper"]
    cfg_accel = st["result"]["status"]["configfile"]["settings"]["printer"]["max_accel"]
    saved = {k: isp.get(k) for k in ("shaper_type_x", "shaper_freq_x",
                                     "shaper_type_y", "shaper_freq_y")}

    def set_shaper(on):
        if on:
            gcode(f"SET_INPUT_SHAPER "
                  f"SHAPER_TYPE_X={saved['shaper_type_x']} SHAPER_FREQ_X={saved['shaper_freq_x']} "
                  f"SHAPER_TYPE_Y={saved['shaper_type_y']} SHAPER_FREQ_Y={saved['shaper_freq_y']}")
        else:
            gcode("SET_INPUT_SHAPER SHAPER_FREQ_X=0 SHAPER_FREQ_Y=0")

    print(f"shaper: X {saved['shaper_type_x']}@{saved['shaper_freq_x']}  "
          f"Y {saved['shaper_type_y']}@{saved['shaper_freq_y']}  max_accel {cfg_accel}")
    print(f"patterns: {', '.join(pats)}   accels: {accels}   -> {outdir}")
    # ACCELEROMETER_MEASURE is a toggle; an interrupted prior run can leave it
    # "started", desyncing every start/stop pair. A firmware restart guarantees
    # a clean, stopped accelerometer state before we begin.
    print("homing...")
    gcode("G28", timeout=240)

    c = ssh(); sftp = c.open_sftp()

    def force_accel_stopped():
        """ACCELEROMETER_MEASURE is a toggle; an interrupted prior run can
        leave it running, which desyncs every capture. Detect state
        deterministically — a 'stop' writes a CSV, a 'start' does not — and
        leave it stopped so each single-script capture enters clean."""
        c.exec_command("rm -f /tmp/lis2dw-heal.csv")
        gcode("ACCELEROMETER_MEASURE CHIP=lis2dw NAME=heal")
        time.sleep(1.5)
        try:
            sftp.stat("/tmp/lis2dw-heal.csv")
            was_running = True          # the toggle produced a file => it was running
        except FileNotFoundError:
            was_running = False         # no file => it just started; stop it
        if not was_running:
            gcode("ACCELEROMETER_MEASURE CHIP=lis2dw NAME=heal")
            time.sleep(0.8)
        c.exec_command("rm -f /tmp/lis2dw-heal.csv")
        print(f"accelerometer reset (was {'running' if was_running else 'stopped'} -> stopped)")

    force_accel_stopped()
    energy = {}   # (pattern, on, accel) -> band energy
    specs = {}    # (pattern) -> (freq, psd) at graph_accel, shaper ON
    def capture(tag, pts, accel):
        """Run one pattern under an accelerometer window; return spectrum().
        The RK3308 writes the CSV lazily on measurement STOP, so wait for the
        remote file to appear and stop growing before pulling — a fixed sleep
        races the write and yields empty files."""
        remote = f"/tmp/lis2dw-{tag}.csv"
        c.exec_command(f"rm -f {remote}")
        gcode(pattern_script(tag, pts, args.vel, accel, args.cycles), timeout=240)
        last, stable = -1, 0
        for _ in range(40):                      # up to ~8 s for the write
            time.sleep(0.2)
            try:
                sz = sftp.stat(remote).st_size
            except FileNotFoundError:
                continue
            if sz == last and sz > 5000:
                stable += 1
                if stable >= 2:
                    break
            else:
                stable = 0
            last = sz
        local = os.path.join(outdir, f"{tag}.csv")
        sftp.get(remote, local)
        c.exec_command(f"rm -f {remote}")
        # sanity: a real multi-second window is thousands of samples. A few
        # hundred means a desynced/short capture — signal the caller to retry.
        n = sum(1 for line in open(local) if line and not line.startswith("#"))
        if n < 3000:
            return None
        return spectrum(local)

    try:
        for pat in pats:
            for on in (True, False):
                set_shaper(on)
                for accel in accels:
                    tag = f"mv_{pat}_{'on' if on else 'off'}_{accel}"
                    res = None
                    for attempt in (1, 2, 3):    # heal + retry on a short capture
                        try:
                            res = capture(tag, PATTERNS[pat], accel)
                        except Exception as ex:
                            print(f"  {tag}: {ex}")
                        if res:
                            break
                        if attempt < 3:
                            print(f"  {tag}: short capture, resetting accel + retrying")
                            force_accel_stopped()
                    if res:
                        e, f, psd = res
                        energy[(pat, on, accel)] = e
                        if on and accel == graph_accel:
                            specs[pat] = (f, psd)
                    label = "ON " if on else "OFF"
                    print(f"  {pat:9} {label} accel={accel:5d}  "
                          f"{energy.get((pat, on, accel), float('nan')):.3e}")
    finally:
        set_shaper(True)
        gcode(f"SET_VELOCITY_LIMIT ACCEL={cfg_accel}")
        c.close()

    write_report(outdir, pats, accels, energy, specs, saved, cfg_accel, graph_accel)
    make_graphs(outdir, pats, accels, energy, specs, graph_accel)
    print(f"\nreport + graphs written to {outdir}/")


def write_report(outdir, pats, accels, energy, specs, saved, cfg_accel, ga):
    lines = []
    lines.append("Movement-noise / shaper-verification report")
    lines.append(f"shaper: X {saved['shaper_type_x']}@{saved['shaper_freq_x']}  "
                 f"Y {saved['shaper_type_y']}@{saved['shaper_freq_y']}  "
                 f"max_accel {cfg_accel}")
    lines.append(f"residual metric: PSD energy in {BAND[0]:.0f}-{BAND[1]:.0f} Hz "
                 f"(lower = less ringing)\n")
    lines.append(f"{'pattern':9} {'accel':>6}  {'shaper ON':>11} {'shaper OFF':>11}  {'reduction':>9}")
    for pat in pats:
        for accel in accels:
            on = energy.get((pat, True, accel))
            off = energy.get((pat, False, accel))
            red = f"{(1-on/off)*100:.0f}%" if on and off else "?"
            lines.append(f"{pat:9} {accel:6d}  "
                         f"{(on if on else float('nan')):11.3e} "
                         f"{(off if off else float('nan')):11.3e}  {red:>9}")
        lines.append("")
    # in-band residual peak per pattern (shaper ON) — reveals a rattle frequency
    lines.append(f"residual peak frequency per pattern (shaper ON, accel {ga}):")
    for pat in pats:
        if pat in specs:
            lines.append(f"  {pat:9} peak @ {peak_in_band(*specs[pat]):.1f} Hz")
    lines.append("")
    lines.append("How to read this:")
    lines.append("- shaper ON should stay LOW and roughly FLAT as accel rises.")
    lines.append("- a pattern whose ON energy is much higher than the pure x/y")
    lines.append("  patterns has a direction-specific problem the shaper can't fix")
    lines.append("  (usually a mechanical rattle) — see its peak frequency above")
    lines.append("  and spectra.png. axis-aligned (x/y/square) low but diagonal/")
    lines.append("  triangle high => a belt-path rattle on that diagonal.")
    lines.append("- small ON-vs-OFF reduction => shaper not matched to the real mode.")
    open(os.path.join(outdir, "report.txt"), "w").write("\n".join(lines) + "\n")
    print("\n" + "\n".join(lines))


def make_graphs(outdir, pats, accels, energy, specs, ga):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    # 1) spectra overlay (shaper ON, representative accel)
    fig, ax = plt.subplots(figsize=(9, 5.5))
    for pat in pats:
        if pat in specs:
            f, psd = specs[pat]
            m = (f >= 10) & (f <= 140)
            ax.plot(f[m], psd[m], label=pat, linewidth=1.4)
    ax.axvspan(BAND[0], BAND[1], color="0.9", zorder=0, label=f"metric band {BAND[0]:.0f}-{BAND[1]:.0f}Hz")
    ax.set_xlabel("Frequency (Hz)"); ax.set_ylabel("Power spectral density")
    ax.set_title(f"Residual vibration per movement pattern (shaper ON, accel {ga})")
    ax.legend(fontsize=8); ax.grid(True, alpha=0.3)
    fig.tight_layout(); fig.savefig(os.path.join(outdir, "spectra.png"), dpi=110)
    plt.close(fig)

    # 2) summary bar chart: residual energy per pattern, ON vs OFF at graph accel
    fig, ax = plt.subplots(figsize=(9, 5.5))
    x = np.arange(len(pats)); w = 0.38
    on = [energy.get((p, True, ga), 0) for p in pats]
    off = [energy.get((p, False, ga), 0) for p in pats]
    ax.bar(x - w/2, off, w, label="shaper OFF", color="#d98c5f")
    ax.bar(x + w/2, on, w, label="shaper ON", color="#4f8ac9")
    ax.set_xticks(x); ax.set_xticklabels(pats)
    ax.set_ylabel(f"residual energy ({BAND[0]:.0f}-{BAND[1]:.0f} Hz)")
    ax.set_title(f"Residual vibration by movement pattern (accel {ga})")
    ax.legend(); ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout(); fig.savefig(os.path.join(outdir, "summary.png"), dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    main()
