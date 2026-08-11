#!/bin/bash
# Remove the Wondermaker+ screen bridge and restore the printer to stock.
# Runs ON the printer, as root. Safe to re-run.
set -uo pipefail

PREFIX=/opt/wondermaker_plus
NGINX_SITE=/etc/nginx/sites-available/fluidd
UNIT=/etc/systemd/system/wmp-screen.service
MARKER="# wondermaker_plus"
MOONRAKER=http://127.0.0.1:7125
WEBCAM_NAME="Touchscreen"

say() { echo "==> $*"; }

[ "$(id -u)" = 0 ] || { echo "!! must run as root" >&2; exit 1; }

# --- 1. moonraker ----------------------------------------------------------
say "removing '$WEBCAM_NAME' webcam from Moonraker"
curl -sf -m 5 -X DELETE \
    "$MOONRAKER/server/webcams/item?name=$WEBCAM_NAME" >/dev/null \
    || echo "   (not registered, or Moonraker unreachable)"

# --- 2. service ------------------------------------------------------------
say "stopping and removing service"
systemctl stop wmp-screen.service 2>/dev/null
systemctl disable wmp-screen.service 2>/dev/null
rm -f "$UNIT"
systemctl daemon-reload

# --- 3. nginx --------------------------------------------------------------
if grep -qF "$MARKER" "$NGINX_SITE" 2>/dev/null; then
    if [ -f "$PREFIX/backup/fluidd.orig" ]; then
        say "restoring $NGINX_SITE from backup"
        cp -a "$PREFIX/backup/fluidd.orig" "$NGINX_SITE"
    else
        say "backup missing; stripping the inserted line instead"
        sed -i "/${MARKER}\$/d" "$NGINX_SITE"
    fi
    if nginx -t 2>/dev/null; then
        systemctl reload nginx || systemctl restart nginx
    else
        echo "!! nginx config test failed after restore - inspect $NGINX_SITE" >&2
    fi
else
    say "nginx already clean"
fi

# --- 4. payload ------------------------------------------------------------
say "removing $PREFIX"
rm -rf "$PREFIX"

say "verifying"
ss -lntp 2>/dev/null | grep -q ":8975" \
    && echo "!! something is still listening on 8975" \
    || echo "    port 8975 closed"
curl -sf -m 5 -o /dev/null -w "    fluidd / -> HTTP %{http_code}\n" \
    http://127.0.0.1/ || echo "!! fluidd not responding"
say "done - printer restored to stock"
