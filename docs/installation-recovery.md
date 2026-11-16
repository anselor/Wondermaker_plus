# Recovering an interrupted installation

`tools/deploy.py install` restores earlier components itself when a later
component fails. This page covers an installation that stopped before it could
do that, for example after a lost connection.

Run recovery only while the printer is idle.

## Restore from the installer journal

Each installation writes a journal under `.wmp-install-journals/` in the
checkout and prints its path. The journal holds a receipt for every completed
component and names any component whose outcome is unknown. It can contain
configuration snapshots, is readable only by its owner, and is excluded from
Git.

Set `INSTALL_JOURNAL` to the printed path and run:

```bash
uv run --with paramiko python tools/deploy.py recover all --journal "$INSTALL_JOURNAL"
```

Recovery restores the recorded components in reverse order and records each
restoration in the journal, so it can be run again after a failure.

Recovery refuses:

- a journal in use by another installer or recovery process;
- a journal written for a different printer or user;
- a component interrupted before it saved its undo plan;
- a receipt it does not support, including configuration installed by earlier
  WM+ releases, which recorded no receipt.

Do not edit a journal to mark a component as successful.

## What each component restores

| Component | Restored | Services restarted |
|---|---|---|
| `config` | Configuration files and Klipper helpers, from the backup recorded before publication | None |
| `material` | Helper files, including a partially published set | None |
| `moonraker` | Original Moonraker sources | Moonraker |
| `preload` | Screen libraries and service override | Screen program, which restarts Klipper |
| `touchscreen` | Screen-bridge files, camera settings and service states | Screen bridge |
| `shaper` | Stock Klipper input shaper files | Klipper |

When `preload` is restored, recovery restarts the screen program and waits for
Klipper to report Ready. A failed restart stays pending in the journal; run the
same command again. Without a `preload` receipt, recovery restarts nothing
except the services listed above. Restart Klipper and confirm it is Ready
before printing.

Recovery after an interruption has been tested per component. It has not been
tested for every combination of components and interruption points.

## Restore only the touchscreen bridge

An interrupted `touchscreen` installation also leaves a journal on the printer.
Set `JOURNAL_PATH` to the path printed by the failed installer and run:

```bash
uv run --with paramiko python tools/deploy.py recover touchscreen --journal "$JOURNAL_PATH"
```

This restores the screen-bridge files, camera settings and service states. It
does not restart Klipper or resume the installation. It refuses to overwrite
files edited since the installation. Keep the journal if recovery reports an
error.

### Printer address changes

New SSH installation journals bind the OS identity `/etc/machine-id` and the printer user.
This identifies the installed operating system, not guaranteed physical hardware:
cloned factory images can share a machine ID. Verify the destination printer,
especially when using a legacy journal or a cloned system.
Recovery accepts a different hostname or IP when that device identity and user
still match. It refuses a different machine even if the old IP was reused.
HTTP-only config journals retain their existing host binding.

Legacy journals have no device identity. A same-address recovery upgrades their
binding after reading the current identity. For a changed address, first verify
that this is the original printer and read `cat /etc/machine-id` over SSH. Then
set `WMP_PRINTER` to its new address and `WMP_USER` to the original user, and run:

```sh
python tools/deploy.py rebind-journal all --journal PATH --from-host OLD_ADDRESS --confirm-machine-id MACHINE_ID
```

For legacy journals, this is your explicit confirmation of the old/new destination,
not proof inferred from matching component snapshots: it changes only the
local journal binding and retains the old binding in its history. The installer
independently reads the new destination's machine ID and requires an exact match
to your confirmation. It does not restore files, restart services, or run recovery.
An already recorded different machine ID cannot be overridden with this command.
Run `recover all --journal PATH` separately when you intend to execute recovery.
