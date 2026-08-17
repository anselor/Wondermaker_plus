#!/usr/bin/env python3
"""Sync config/live/ with the printer's Klipper config.

    uv run --with paramiko python utils/config_sync.py diff
    uv run --with paramiko python utils/config_sync.py push [FILE ...] [--yes] [--no-restart]
    uv run --with paramiko python utils/config_sync.py pull DIR

diff: show which files differ between config/live/ and the printer.
push: upload changed files (all, or just the named ones), keeping a
      timestamped backup of each replaced file on the printer, then
      firmware-restart Klipper and verify it comes back Ready.
pull: download the printer's current config into DIR for inspection.

Runtime-state files (saved_variables.cfg, tmt1.ini, printer-*.cfg backups)
are never touched.
"""
import argparse, datetime, fnmatch, json, os, sys, time, urllib.request

HOST = os.environ.get("WMP_PRINTER", "printer.local")
USER = os.environ.get("WMP_USER", "t13dp")
PASS = os.environ.get("WMP_PASS", "CHANGE_ME")
REMOTE = "/home/t13dp/printer_data/config"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(REPO, "config", "live")
EXCLUDE = ["printer-2026*.cfg", "printer-20*.cfg", "*.wmp-backup*",
           "saved_variables.cfg", "tmt1.ini"]


def ssh_connect():
    import paramiko
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, username=USER, password=PASS, timeout=20)
    return c


def excluded(name):
    return any(fnmatch.fnmatch(name, p) for p in EXCLUDE)


def changed_files(sftp):
    """Return (differs, missing_remote) comparing config/live to the printer."""
    differs, missing = [], []
    for name in sorted(os.listdir(LIVE)):
        path = os.path.join(LIVE, name)
        if not os.path.isfile(path) or excluded(name):
            continue
        local = open(path, "rb").read()
        try:
            with sftp.open(f"{REMOTE}/{name}") as f:
                remote = f.read()
        except FileNotFoundError:
            missing.append(name)
            continue
        if local != remote:
            differs.append(name)
    return differs, missing


def wait_ready(tries=12, delay=10):
    for _ in range(tries):
        try:
            req = urllib.request.urlopen(
                f"http://{HOST}/printer/objects/query?idle_timeout", timeout=10)
            state = json.loads(req.read())["result"]["status"]["idle_timeout"]["state"]
            if state in ("Idle", "Ready"):
                return True
        except Exception:
            pass
        time.sleep(delay)
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    sub.add_parser("diff")
    p = sub.add_parser("push")
    p.add_argument("files", nargs="*", help="only push these files")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--no-restart", action="store_true")
    g = sub.add_parser("pull")
    g.add_argument("dir")
    args = ap.parse_args()

    ssh = ssh_connect()
    sftp = ssh.open_sftp()

    if args.mode == "pull":
        os.makedirs(args.dir, exist_ok=True)
        n = 0
        for name in sorted(sftp.listdir(REMOTE)):
            if excluded(name):
                continue
            try:
                sftp.get(f"{REMOTE}/{name}", os.path.join(args.dir, name))
                n += 1
            except IOError:
                pass
        print(f"pulled {n} files into {args.dir}")
        return

    differs, missing = changed_files(sftp)
    if args.mode == "diff":
        for name in differs:
            print(f"M {name}")
        for name in missing:
            print(f"+ {name} (not on printer)")
        if not differs and not missing:
            print("config/live matches the printer")
        return

    # push
    targets = differs + missing
    if args.files:
        unknown = [f for f in args.files if f not in targets]
        if unknown:
            sys.exit(f"not changed or unknown: {', '.join(unknown)}")
        targets = args.files
    if not targets:
        print("nothing to push; config/live matches the printer")
        return
    print("will push:", ", ".join(targets))
    if not args.yes and input("proceed? [y/N] ").strip().lower() != "y":
        sys.exit("aborted")

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    for name in targets:
        if name in differs:
            backup = f"{REMOTE}/{name}.wmp-backup-{stamp}"
            ssh.exec_command(f"cp {REMOTE}/{name} {backup}")[1].channel.recv_exit_status()
            print(f"  backed up {name} -> {os.path.basename(backup)}")
        sftp.put(os.path.join(LIVE, name), f"{REMOTE}/{name}")
        print(f"  pushed {name}")

    if args.no_restart:
        print("skipping restart (--no-restart); changes load on next restart")
        return
    print("firmware-restarting Klipper...")
    urllib.request.urlopen(urllib.request.Request(
        f"http://{HOST}/printer/firmware_restart", data=b"{}",
        headers={"Content-Type": "application/json"}), timeout=60)
    time.sleep(15)
    if wait_ready():
        print("Klipper is Ready — push verified")
    else:
        print("WARNING: Klipper not Ready — check klippy.log; backups are "
              f"on the printer as *.wmp-backup-{stamp}")
        sys.exit(1)


if __name__ == "__main__":
    main()
