#!/usr/bin/env python3
"""Resonance calibration workflow for the Wondermaker U1.

    uv run --with paramiko --with numpy python utils/resonance.py analysis
    uv run --with paramiko --with numpy python utils/resonance.py analysis --offline resonance/2026-08-15
    uv run --with paramiko --with numpy python utils/resonance.py apply --dry-run
    uv run --with paramiko --with numpy python utils/resonance.py apply [--accel N] [--yes]

analysis: homes the printer, runs four TEST_RESONANCES sweeps (both CoreXY
belt diagonals, X, Y), archives the raw accelerometer CSVs under
resonance/<date>/, and reports belt imbalance, rattle bands, and per-axis
shaper fits next to what the printer currently has configured.

apply: picks the lightest shaper per axis under a residual-vibration
threshold from the newest archived dataset and writes it into printer.cfg's
SAVE_CONFIG block. Non-destructive: timestamped backups on the printer and
locally, a confirm prompt, and post-restart verification with automatic
rollback if Klipper does not come back.

Klipper's own analysis code (GPL) is fetched from the printer on first run
and cached in utils/.klippy_cache/ rather than committed to this repo.
"""
import argparse, datetime, json, os, re, sys, time, urllib.request

HOST = os.environ.get("WMP_PRINTER", "printer.local")
USER = os.environ.get("WMP_USER", "t13dp")
PASS = os.environ.get("WMP_PASS", "CHANGE_ME")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(REPO, "utils", ".klippy_cache")
PRINTER_CFG = "/home/t13dp/printer_data/config/printer.cfg"

# Sweep name -> (TEST_RESONANCES AXIS argument, raw_data filename fragment)
SWEEPS = {
    "beltA": ("1,1", "axis=1.000,1.000"),
    "beltB": ("1,-1", "axis=1.000,-1.000"),
    "x": ("X", "_x_"),
    "y": ("Y", "_y_"),
}
RESIDUAL_THRESHOLD = 0.005   # 0.5% residual vibration
IMBALANCE_FLAG_HZ = 2.0
RATTLE_BANDS = [(60, 80), (115, 135)]


# ---------------------------------------------------------------- printer io

def moonraker(path, payload=None, timeout=30):
    req = urllib.request.Request(
        f"http://{HOST}{path}",
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def gcode(script, timeout=400):
    return moonraker("/printer/gcode/script", {"script": script}, timeout)


def ssh_connect():
    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASS, timeout=20)
    return c


def printer_state():
    r = moonraker("/printer/objects/query?idle_timeout&print_stats", timeout=10)
    s = r["result"]["status"]
    return s["idle_timeout"]["state"], s["print_stats"]["state"]


def wait_ready(tries=20, delay=15):
    for _ in range(tries):
        try:
            state, _ = printer_state()
            if state in ("Idle", "Ready"):
                return True
        except Exception:
            pass
        time.sleep(delay)
    return False


def home():
    # First home after boot/idle occasionally fails (ZRU-C002); retry once.
    for attempt in (1, 2):
        try:
            gcode("G28", timeout=240)
            return
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:200]
            if attempt == 2:
                sys.exit(f"homing failed twice, aborting: {msg}")
            print(f"  homing failed ({msg.strip()[:100]}), retrying once...")
            time.sleep(5)


# ---------------------------------------------------------------- analysis

def ensure_klippy_cache(ssh=None):
    extras = os.path.join(CACHE, "extras")
    wanted = ["shaper_calibrate.py", "shaper_defs.py"]
    if all(os.path.exists(os.path.join(extras, f)) for f in wanted):
        return
    print("fetching Klipper analysis modules from printer...")
    os.makedirs(extras, exist_ok=True)
    open(os.path.join(extras, "__init__.py"), "w").close()
    own = ssh is None
    if own:
        ssh = ssh_connect()
    sftp = ssh.open_sftp()
    for f in wanted:
        sftp.get(f"/home/t13dp/klipper/klippy/extras/{f}",
                 os.path.join(extras, f))
    if own:
        ssh.close()


def load_helper():
    sys.path.insert(0, CACHE)
    import numpy  # noqa: F401  (fail early with a clear error)
    from extras import shaper_calibrate
    return shaper_calibrate


def spectrum(helper_mod, csv_path):
    import numpy as np
    rows = []
    with open(csv_path) as f:
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.split(",")
            if len(parts) >= 4:
                try:
                    rows.append([float(x) for x in parts[:4]])
                except ValueError:
                    pass
    helper = helper_mod.ShaperCalibrate(printer=None)

    class Data:
        def get_samples(self):
            return rows
    cal = helper.process_accelerometer_data(Data())
    cal.normalize_to_frequencies()
    return helper, cal, np.array(cal.freq_bins), np.array(cal.psd_sum)


def top_peaks(freq, psd, lo=10, hi=140, n=4, min_sep=4.0):
    m = (freq >= lo) & (freq <= hi)
    fm, pm = freq[m], psd[m]
    idx = [i for i in range(1, len(pm) - 1) if pm[i] > pm[i - 1] and pm[i] > pm[i + 1]]
    idx.sort(key=lambda i: -pm[i])
    out = []
    for i in idx:
        if all(abs(fm[i] - f) > min_sep for f, _ in out):
            out.append((float(fm[i]), float(pm[i])))
        if len(out) == n:
            break
    return out


def band_energy(freq, psd, lo, hi):
    import numpy as np
    m = (freq >= lo) & (freq <= hi)
    return float(np.trapezoid(psd[m], freq[m]))


def fit_shapers(helper_mod, helper, cal):
    """Return list of CalibrationResult-likes (name, freq, vibrs, smoothing, max_accel)."""
    results = []

    def log(msg):
        pass
    try:
        # matches this firmware's scripts/calibrate_shaper.py invocation
        best, all_shapers = helper.find_best_shaper(
            cal, shapers=None, damping_ratio=None, scv=5.0,
            shaper_freqs=None, max_smoothing=None,
            test_damping_ratios=None, max_freq=133.33, logger=log)
    except TypeError:  # older klipper: positional (cal, max_smoothing, logger)
        best, all_shapers = helper.find_best_shaper(cal, None, log)
    for s in all_shapers:
        results.append(s)
    return best, results


def latest_files(directory):
    """Newest raw_data CSV per sweep kind in a directory."""
    found = {}
    for name in os.listdir(directory):
        if not (name.startswith("raw_data") and name.endswith(".csv")):
            continue
        path = os.path.join(directory, name)
        for kind, (_, frag) in SWEEPS.items():
            if frag in name:
                # beltA's fragment is a substring of nothing else, but X's
                # "_x_" must not steal belt files (they contain "axis=").
                if kind in ("x", "y") and "axis=" in name:
                    continue
                if kind not in found or os.path.getmtime(path) > os.path.getmtime(found[kind]):
                    found[kind] = path
    return found


def run_sweeps(outdir):
    state, pstate = printer_state()
    if pstate == "printing":
        sys.exit("printer is printing; refusing to run sweeps")
    print(f"printer state: {state}; homing...")
    home()
    tag = datetime.datetime.now().strftime("%H%M%S")
    for kind, (axis, _) in SWEEPS.items():
        print(f"  sweep {kind} (AXIS={axis})...")
        gcode(f"TEST_RESONANCES AXIS={axis} OUTPUT=raw_data NAME=wmp{tag}")
    os.makedirs(outdir, exist_ok=True)
    ssh = ssh_connect()
    sftp = ssh.open_sftp()
    pulled = 0
    for name in sftp.listdir("/tmp"):
        if name.startswith("raw_data") and f"wmp{tag}" in name:
            sftp.get(f"/tmp/{name}", os.path.join(outdir, name))
            pulled += 1
    ssh.close()
    print(f"  pulled {pulled} CSVs into {outdir}")
    if pulled != len(SWEEPS):
        sys.exit(f"expected {len(SWEEPS)} raw files, got {pulled}")
    return latest_files(outdir)


def read_current_config(text=None):
    if text is None:
        ssh = ssh_connect()
        sftp = ssh.open_sftp()
        with sftp.open(PRINTER_CFG) as f:
            text = f.read().decode()
        ssh.close()
    cur = {}
    for key in ("shaper_type_x", "shaper_freq_x", "shaper_type_y", "shaper_freq_y"):
        m = re.search(rf"#\*# {key} = (.+)", text)
        cur[key] = m.group(1).strip() if m else None
    m = re.search(r"^max_accel:\s*(\S+)", text, re.M)
    cur["max_accel"] = m.group(1) if m else None
    return cur, text


def analyze(files, current=None):
    """Compute and print the report; return per-axis fits for apply mode."""
    helper_mod = load_helper()
    data = {}
    for kind, path in files.items():
        helper, cal, freq, psd = spectrum(helper_mod, path)
        data[kind] = dict(helper=helper, cal=cal, freq=freq, psd=psd,
                          peaks=top_peaks(freq, psd), path=path)

    print("\n=== Belt balance (CoreXY diagonals) ===")
    fits = {}
    if "beltA" in data and "beltB" in data:
        fa, pa = data["beltA"]["peaks"][0]
        fb, pb = data["beltB"]["peaks"][0]
        gap = abs(fa - fb)
        tension_pct = abs((max(fa, fb) / min(fa, fb)) ** 2 - 1) * 100
        print(f"belt A (1,1):  main peak {fa:5.1f} Hz  (power {pa:.2e})")
        print(f"belt B (1,-1): main peak {fb:5.1f} Hz  (power {pb:.2e})")
        print(f"gap: {gap:.1f} Hz  ->  ~{tension_pct:.0f}% tension difference"
              f"  [{'IMBALANCED — adjust the looser (lower-Hz) belt' if gap > IMBALANCE_FLAG_HZ else 'OK'}]")
        ratio = max(pa, pb) / min(pa, pb)
        if ratio > 2.0:
            print(f"note: peak power differs {ratio:.1f}x between belts — "
                  "uneven damping or one belt much looser")

    print("\n=== Rattle check (band energy vs belt band) ===")
    for kind in ("beltA", "beltB", "x", "y"):
        if kind not in data:
            continue
        d = data[kind]
        main = d["peaks"][0][0]
        belt_e = band_energy(d["freq"], d["psd"], main - 6, main + 6)
        notes = []
        for lo, hi in RATTLE_BANDS:
            e = band_energy(d["freq"], d["psd"], lo, hi)
            r = e / belt_e if belt_e else 0
            if r > 1.0:
                notes.append(f"{lo}-{hi} Hz SEVERE ({r:.1f}x belt band)")
            elif r > 0.5:
                notes.append(f"{lo}-{hi} Hz elevated ({r:.1f}x belt band)")
        print(f"{kind:6s}: main {main:5.1f} Hz | "
              + ("; ".join(notes) if notes else "clean"))
        if notes and kind == "beltA":
            print("        (1,1-diagonal rattle -> check the upper belt's motor "
                  "mount/idlers; spool spindles rattle here too)")

    print("\n=== Shaper fits ===")
    for axis in ("x", "y"):
        if axis not in data:
            continue
        d = data[axis]
        best, all_s = fit_shapers(helper_mod, d["helper"], d["cal"])
        fits[axis] = all_s
        print(f"[{axis.upper()}]")
        for s in all_s:
            mark = " <- klipper pick" if s.name == best.name else ""
            print(f"  {s.name:9s} @ {s.freq:5.1f} Hz  residual {s.vibrs*100:4.1f}%"
                  f"  max_accel<={s.max_accel:.0f}{mark}")
        rec = pick_shaper(all_s)
        print(f"  recommendation (lightest under {RESIDUAL_THRESHOLD*100:.1f}%): "
              f"{rec.name} @ {rec.freq:.1f} Hz (accel<={rec.max_accel:.0f})")

    if current:
        print("\n=== Currently configured on printer ===")
        print(f"X: {current['shaper_type_x']} @ {current['shaper_freq_x']}   "
              f"Y: {current['shaper_type_y']} @ {current['shaper_freq_y']}   "
              f"max_accel: {current['max_accel']}")
    return fits


def pick_shaper(all_shapers):
    """Lightest (least smoothing) shaper whose residual is under threshold;
    fall back to lowest-residual if none qualifies."""
    order = ["zv", "mzv", "ei", "2hump_ei", "3hump_ei"]
    by_name = {s.name: s for s in all_shapers}
    for name in order:
        s = by_name.get(name)
        if s is not None and s.vibrs <= RESIDUAL_THRESHOLD:
            return s
    return min(all_shapers, key=lambda s: s.vibrs)


# ---------------------------------------------------------------- apply

def apply_mode(args):
    base = os.path.join(REPO, "resonance")
    if args.data:
        dataset = args.data
    else:
        dirs = sorted(d for d in os.listdir(base)
                      if os.path.isdir(os.path.join(base, d)))
        if not dirs:
            sys.exit("no datasets under resonance/ — run analysis first")
        dataset = os.path.join(base, dirs[-1])
    files = latest_files(dataset)
    if "x" not in files or "y" not in files:
        sys.exit(f"dataset {dataset} lacks X/Y sweeps — run analysis first")
    print(f"using dataset: {dataset}")
    ensure_klippy_cache()
    current, text = read_current_config()
    fits = analyze(files, current)

    new = {}
    for axis in ("x", "y"):
        s = pick_shaper(fits[axis])
        new[f"shaper_type_{axis}"] = s.name
        new[f"shaper_freq_{axis}"] = f"{s.freq:.1f}"
        new[f"accel_ceiling_{axis}"] = s.max_accel

    print("\n=== Proposed change ===")
    for axis in ("x", "y"):
        print(f"{axis.upper()}: {current[f'shaper_type_{axis}']} @ "
              f"{current[f'shaper_freq_{axis}']}  ->  "
              f"{new[f'shaper_type_{axis}']} @ {new[f'shaper_freq_{axis}']}")
    if args.accel:
        print(f"max_accel: {current['max_accel']} -> {args.accel}")
    else:
        ceil = min(new["accel_ceiling_x"], new["accel_ceiling_y"])
        print(f"max_accel: unchanged ({current['max_accel']}); shaper ceilings "
              f"suggest keeping print accel <= {ceil:.0f} (pass --accel to set)")

    if args.dry_run:
        print("\n--dry-run: no changes made")
        return
    if not args.yes:
        if input("\napply to printer? [y/N] ").strip().lower() != "y":
            print("aborted")
            return

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    ssh = ssh_connect()
    sftp = ssh.open_sftp()
    backup_remote = f"{PRINTER_CFG}.wmp-backup-{stamp}"
    ssh.exec_command(f"cp {PRINTER_CFG} {backup_remote}")[1].channel.recv_exit_status()
    local_backup = os.path.join(dataset, f"printer.cfg.backup-{stamp}")
    with open(local_backup, "w") as f:
        f.write(text)
    print(f"backups: {backup_remote} (printer), {local_backup} (local)")

    edited = text
    for axis in ("x", "y"):
        edited = re.sub(rf"#\*# shaper_type_{axis} = .*",
                        f"#*# shaper_type_{axis} = {new[f'shaper_type_{axis}']}", edited)
        edited = re.sub(rf"#\*# shaper_freq_{axis} = .*",
                        f"#*# shaper_freq_{axis} = {new[f'shaper_freq_{axis}']}", edited)
    if args.accel:
        edited = re.sub(r"^max_accel:.*", f"max_accel: {args.accel}", edited, flags=re.M)
    for axis in ("x", "y"):
        assert f"shaper_type_{axis} = {new[f'shaper_type_{axis}']}" in edited
    with sftp.open(PRINTER_CFG, "w") as f:
        f.write(edited)
    print("printer.cfg written; restarting Klipper...")
    moonraker("/printer/firmware_restart", {}, timeout=120)
    time.sleep(20)
    if not wait_ready(tries=10, delay=10):
        print("Klipper did not come back — restoring backup!")
        ssh.exec_command(f"cp {backup_remote} {PRINTER_CFG}")[1].channel.recv_exit_status()
        moonraker("/printer/firmware_restart", {}, timeout=120)
        ssh.close()
        sys.exit("rolled back; printer.cfg restored from backup")
    ssh.close()

    live = moonraker("/printer/objects/query?configfile=settings", timeout=15)
    isp = live["result"]["status"]["configfile"]["settings"].get("input_shaper", {})
    ok = (isp.get("shaper_type_x") == new["shaper_type_x"]
          and isp.get("shaper_type_y") == new["shaper_type_y"])
    print(f"verified live: X={isp.get('shaper_type_x')} @ {isp.get('shaper_freq_x')}, "
          f"Y={isp.get('shaper_type_y')} @ {isp.get('shaper_freq_y')} "
          f"[{'OK' if ok else 'MISMATCH — inspect manually'}]")


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    a = sub.add_parser("analysis", help="run sweeps (or reuse CSVs) and report")
    a.add_argument("--offline", metavar="DIR",
                   help="skip the printer; analyze existing CSVs in DIR")
    p = sub.add_parser("apply", help="write best-fit shapers to printer.cfg")
    p.add_argument("--data", metavar="DIR", help="dataset dir (default: newest)")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--accel", type=int, help="also set [printer] max_accel")
    p.add_argument("--yes", action="store_true", help="skip confirm prompt")
    args = ap.parse_args()

    if args.mode == "analysis":
        if args.offline:
            ensure_klippy_cache()
            files = latest_files(args.offline)
            if not files:
                sys.exit(f"no raw_data CSVs in {args.offline}")
            current = None
        else:
            ensure_klippy_cache()
            outdir = os.path.join(REPO, "resonance",
                                  datetime.date.today().isoformat())
            files = run_sweeps(outdir)
            current, _ = read_current_config()
        for kind, path in sorted(files.items()):
            print(f"{kind}: {os.path.basename(path)}")
        analyze(files, current)
    else:
        apply_mode(args)


if __name__ == "__main__":
    main()
