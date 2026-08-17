#!/usr/bin/env python3
"""Sync config/live/ with the printer's Klipper config.

    uv run python utils/config_sync.py diff
    uv run python utils/config_sync.py push [FILE ...] [--yes] [--no-restart]
    uv run python utils/config_sync.py pull DIR
    ... any mode with --ssh to use SFTP instead of Moonraker HTTP

diff: show which files differ between config/live/ and the printer.
push: upload changed files (all, or just the named ones), keeping a
      timestamped backup of each replaced file on the printer, then
      firmware-restart Klipper and verify it comes back Ready.
pull: download the printer's current config into DIR for inspection.

Transport is Moonraker's HTTP file API by default — no shell access, no
credentials, works for anything under printer_data/config. Pass --ssh to use
SFTP instead (needs paramiko: `uv run --with paramiko ...`); only useful if
Moonraker is down.

Runtime-state files (saved_variables.cfg, tmt1.ini, printer-*.cfg backups)
are never touched.
"""
import argparse, datetime, fnmatch, io, json, os, sys, time, urllib.error, urllib.request
import uuid as uuidlib

HOST = os.environ.get("WMP_PRINTER", "printer.local")
USER = os.environ.get("WMP_USER", "t13dp")
PASS = os.environ.get("WMP_PASS", "CHANGE_ME")
REMOTE_DIR = "/home/t13dp/printer_data/config"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(REPO, "config", "live")
EXCLUDE = ["printer-20*.cfg", "*.wmp-backup*", "saved_variables.cfg", "tmt1.ini"]


def excluded(name):
    return any(fnmatch.fnmatch(name, p) for p in EXCLUDE)


# ---------------------------------------------------------------- transports

class HttpTransport:
    """Moonraker file API: no shell, no credentials."""

    def _api(self, path, data=None, headers=None, method=None):
        req = urllib.request.Request(
            f"http://{HOST}{path}", data=data, headers=headers or {},
            method=method or ("POST" if data is not None else "GET"))
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read()

    def listdir(self):
        out = json.loads(self._api("/server/files/list?root=config"))
        return [f["path"] for f in out["result"] if "/" not in f["path"]]

    def read(self, name):
        try:
            return self._api(f"/server/files/config/{name}")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise FileNotFoundError(name)
            raise

    def write(self, name, data):
        boundary = uuidlib.uuid4().hex
        body = io.BytesIO()
        # NB: "path" would be a target SUBDIRECTORY, not the filename —
        # the file part's filename below names the file.
        body.write(f"--{boundary}\r\nContent-Disposition: form-data; "
                   f"name=\"root\"\r\n\r\nconfig\r\n".encode())
        body.write(f"--{boundary}\r\nContent-Disposition: form-data; "
                   f"name=\"file\"; filename=\"{name}\"\r\n"
                   f"Content-Type: application/octet-stream\r\n\r\n".encode())
        body.write(data)
        body.write(f"\r\n--{boundary}--\r\n".encode())
        self._api("/server/files/upload", body.getvalue(),
                  {"Content-Type": f"multipart/form-data; boundary={boundary}"})

    def copy(self, src, dst):
        self._api("/server/files/copy",
                  json.dumps({"source": f"config/{src}",
                              "dest": f"config/{dst}"}).encode(),
                  {"Content-Type": "application/json"})

    def close(self):
        pass


class SshTransport:
    """SFTP fallback for when Moonraker is down (needs paramiko)."""

    def __init__(self):
        import paramiko
        self.ssh = paramiko.SSHClient()
        self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.ssh.connect(HOST, username=USER, password=PASS, timeout=20)
        self.sftp = self.ssh.open_sftp()

    def listdir(self):
        return self.sftp.listdir(REMOTE_DIR)

    def read(self, name):
        try:
            with self.sftp.open(f"{REMOTE_DIR}/{name}") as f:
                return f.read()
        except IOError:
            raise FileNotFoundError(name)

    def write(self, name, data):
        with self.sftp.open(f"{REMOTE_DIR}/{name}", "w") as f:
            f.write(data)

    def copy(self, src, dst):
        chan = self.ssh.exec_command(
            f"cp {REMOTE_DIR}/{src} {REMOTE_DIR}/{dst}")[1].channel
        if chan.recv_exit_status() != 0:
            raise RuntimeError(f"backup copy failed for {src}")

    def close(self):
        self.ssh.close()


# ---------------------------------------------------------------- helpers

def changed_files(t):
    """(differs, missing_remote) comparing config/live to the printer."""
    differs, missing = [], []
    for name in sorted(os.listdir(LIVE)):
        path = os.path.join(LIVE, name)
        if not os.path.isfile(path) or excluded(name):
            continue
        local = open(path, "rb").read()
        try:
            remote = t.read(name)
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


def printing_now():
    try:
        req = urllib.request.urlopen(
            f"http://{HOST}/printer/objects/query?print_stats", timeout=10)
        return json.loads(req.read())["result"]["status"]["print_stats"]["state"] == "printing"
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ssh", action="store_true",
                    help="use SFTP instead of the Moonraker HTTP API")
    sub = ap.add_subparsers(dest="mode", required=True)
    sub.add_parser("diff")
    p = sub.add_parser("push")
    p.add_argument("files", nargs="*", help="only push these files")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--no-restart", action="store_true")
    g = sub.add_parser("pull")
    g.add_argument("dir")
    args = ap.parse_args()

    t = SshTransport() if args.ssh else HttpTransport()
    try:
        run(t, args)
    finally:
        t.close()


def run(t, args):
    if args.mode == "pull":
        os.makedirs(args.dir, exist_ok=True)
        n = 0
        for name in sorted(t.listdir()):
            if excluded(name):
                continue
            try:
                open(os.path.join(args.dir, name), "wb").write(t.read(name))
                n += 1
            except FileNotFoundError:
                pass
        print(f"pulled {n} files into {args.dir}")
        return

    differs, missing = changed_files(t)
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
    if printing_now():
        sys.exit("printer is printing; refusing to push (restart would kill the print)")
    print("will push:", ", ".join(targets))
    if not args.yes and input("proceed? [y/N] ").strip().lower() != "y":
        sys.exit("aborted")

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    for name in targets:
        if name in differs:
            backup = f"{name}.wmp-backup-{stamp}"
            t.copy(name, backup)
            print(f"  backed up {name} -> {backup}")
        t.write(name, open(os.path.join(LIVE, name), "rb").read())
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
