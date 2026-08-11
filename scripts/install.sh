#!/bin/bash
# Install the Wondermaker+ screen bridge. Runs ON the printer, as root.
#
# Touches exactly four things, all reversible by uninstall.sh:
#   1. creates  /opt/wondermaker_plus/
#   2. creates  /etc/systemd/system/wmp-screen.service
#   3. inserts  one `include` line into the fluidd nginx site (backed up first)
#   4. adds     an `iframe` webcam entry to Moonraker's database
set -euo pipefail

PREFIX=/opt/wondermaker_plus
NGINX_SITE=/etc/nginx/sites-available/fluidd
UNIT=/etc/systemd/system/wmp-screen.service
MARKER="# wondermaker_plus"
INCLUDE_LINE="    include ${PREFIX}/nginx-screen.conf; ${MARKER}"
MOONRAKER=http://127.0.0.1:7125
WEBCAM_NAME="Touchscreen"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

say() { echo "==> $*"; }
die() { echo "!! $*" >&2; exit 1; }

[ "$(id -u)" = 0 ] || die "must run as root"
[ -f "$SRC/device/wmp_screen.py" ] || die "payload not found under $SRC/device"

# --- 1. payload ------------------------------------------------------------
say "installing payload to $PREFIX"
mkdir -p "$PREFIX/backup"
cp -a "$SRC/device/wmp_screen.py" "$SRC/device/nginx-screen.conf" "$PREFIX/"
rm -rf "$PREFIX/www"
cp -a "$SRC/device/www" "$PREFIX/www"
echo "$(cat /home/t13dp/iso_version.txt 2>/dev/null | head -1)" > "$PREFIX/installed-against.txt"
date -u +"installed %Y-%m-%dT%H:%M:%SZ" >> "$PREFIX/installed-against.txt"

# --- 2. nginx --------------------------------------------------------------
if grep -qF "$MARKER" "$NGINX_SITE"; then
    say "nginx already patched, leaving it alone"
else
    say "backing up $NGINX_SITE"
    cp -a "$NGINX_SITE" "$PREFIX/backup/fluidd.orig"
    md5sum "$NGINX_SITE" > "$PREFIX/backup/fluidd.orig.md5"

    say "inserting include into fluidd server block"
    python3 - "$NGINX_SITE" "$INCLUDE_LINE" <<'PY'
import sys
path, line = sys.argv[1], sys.argv[2]
src = open(path).read()
idx = src.rstrip().rfind("}")          # final brace closes the server block
if idx == -1:
    sys.exit("could not find closing brace in %s" % path)
open(path, "w").write(src[:idx] + line + "\n" + src[idx:])
PY

    if ! nginx -t 2>/dev/null; then
        say "nginx rejected the config; rolling back"
        cp -a "$PREFIX/backup/fluidd.orig" "$NGINX_SITE"
        nginx -t || true
        die "nginx config test failed, original restored"
    fi
fi

# --- 3. service ------------------------------------------------------------
say "installing systemd unit"
cp -a "$SRC/device/wmp-screen.service" "$UNIT"
systemctl daemon-reload
systemctl enable wmp-screen.service >/dev/null 2>&1 || true
systemctl restart wmp-screen.service

say "reloading nginx"
systemctl reload nginx || systemctl restart nginx

# --- 4. moonraker webcam ---------------------------------------------------
say "registering '$WEBCAM_NAME' webcam with Moonraker"
for _ in $(seq 1 10); do
    curl -sf -m 3 "$MOONRAKER/server/info" >/dev/null && break
    sleep 1
done
curl -sf -m 5 -X POST "$MOONRAKER/server/webcams/item" \
    -H "Content-Type: application/json" \
    -d "{\"name\": \"$WEBCAM_NAME\",
         \"service\": \"iframe\",
         \"location\": \"printer\",
         \"icon\": \"mdiTelevision\",
         \"enabled\": true,
         \"aspect_ratio\": \"5:3\",
         \"target_fps\": 10,
         \"target_fps_idle\": 2,
         \"stream_url\": \"/wmp-screen/\",
         \"snapshot_url\": \"/wmp-screen/snapshot.jpg\",
         \"flip_horizontal\": false,
         \"flip_vertical\": false,
         \"rotation\": 0}" >/dev/null \
    || echo "!! moonraker registration failed (add the webcam by hand in Fluidd)"

# --- report ----------------------------------------------------------------
sleep 2
say "service status:"
systemctl is-active wmp-screen.service || true
curl -sf -m 5 -o /dev/null -w "    local  /snapshot.jpg -> HTTP %{http_code}\n" \
    http://127.0.0.1:8975/snapshot.jpg || echo "    local snapshot FAILED"
curl -sf -m 5 -o /dev/null -w "    nginx  /wmp-screen/  -> HTTP %{http_code}\n" \
    http://127.0.0.1/wmp-screen/ || echo "    nginx proxy FAILED"
say "done - open Fluidd and look for the '$WEBCAM_NAME' camera"
