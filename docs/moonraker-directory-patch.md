# Moonraker responsiveness and HTTP error patches

The reviewed WM Moonraker file manager can block status requests while listing
configuration files. This patch yields between entries while retaining the
synchronous internal API, metadata and permission checks. Only the reviewed
method fingerprints are accepted. Other Moonraker versions need review first.

The dedicated installer is included in the unified delivery staging export.
`tools/deploy.py install preload` includes it as a dependency when installing the
unified screen on its exact supported client. Legacy C screen selections skip it.
It can also be selected explicitly:

```sh
python3 tools/deploy.py install moonraker
python3 tools/deploy.py status moonraker
python3 tools/deploy.py uninstall moonraker
```

The host installer handles both the directory and HTTP error patches. It records
both prior states in one recovery receipt before preparing or publishing either
source. Each file retains its own printer-side backup and service journal. `recover all --journal PATH` can recover a stopped Moonraker before
checking HTTP status for earlier components. A previously installed patch is
preserved when rolling back a later installation. `--no-restart` only defers the
final Klipper restart; it does not defer the Moonraker component's service lifecycle.
Uninstall leaves an unmanaged Moonraker source untouched.

## On-printer entry point

Copy these five modules together from the same exported source:

- `moonraker_directory_install.py`
- `moonraker_directory_service.py`
- `moonraker_directory_transaction.py`
- `moonraker_directory_patch.py`
- `moonraker_http_error_patch.py`

Run on the printer, with service-management privileges. Set `--home` to the
printer account's actual home and keep the transaction directory persistently.
For the test printer:

```sh
sudo python3 moonraker_directory_install.py install \
  --home /home/t13dp --state /home/t13dp/wmp/backups/moonraker-directory-managed
```

`prepare` verifies the source, saves the original and candidate, and compiles the
candidate with Moonraker's Python without publishing or restarting. `install`
prepares if needed, requires an idle Ready printer, stops Moonraker, publishes,
starts Moonraker, and verifies unchanged Klipper identity and filament state.
It never sends G-code or restarts Klipper. An already installed source is verified
without restarting Moonraker.

Use the same command with `restore` to restore the saved original. For an
interrupted operation, use `recover` to return to the source that preceded that
operation. A currently running operation retains its lock, so recovery cannot
compete with it. `status` reports the source and recorded service phase; a journal
phase alone does not establish that a process is stopped or a service is healthy.

If startup fails, the installer attempts to restore and start the prior source.
If recovery cannot be confirmed, it retains the receipt and reports failure.
Subsequent source edits are never deliberately overwritten. Keep the transaction
and original backup until restoration is no longer needed.

## Adopting the existing test-printer patch

The test printer's previously deployed patch has already been registered using
`--original-backup /home/t13dp/wmp/backups/moonraker-directory-20261108/original.py`.
Adoption accepts a backup only when rebuilding the reviewed patch from it exactly
matches the installed file. It does not replace the source or restart the service.
Do not substitute the superseded intermediate patch for the original backup.


## HTTP command-error responses

The reviewed vendor HTTP handler puts the complete Klipper error into the HTTP
status phrase. Multiline macro errors therefore break response serialization and
appear to callers as a disconnect. The separate HTTP patch retains the full error
and traceback in JSON, while using the standard status phrase (for example,
400 Bad Request). It does not change command execution or JSON-RPC.

The on-printer installer supports this independently:
```sh
sudo python3 moonraker_directory_install.py install --patch http-error \
  --home /home/t13dp --state /home/t13dp/wmp/backups/moonraker-http-error-managed
```

Use the same `--patch http-error` and state directory for `status`, `restore`
or `recover`. Never reuse the directory patch's state directory: receipts are
bound to their target file and are rejected for another target. Both patches use
the same idle admission, service stop/readiness and rollback protections.
Both patches are selected by the normal host `deploy.py` Moonraker component.
Rollback restores each patch to its own prior state, preserving preexisting
installations. Older directory-only recovery receipts still restore only that
file. Uninstall restores both managed sources and leaves unmanaged sources alone.
The test printer passed live HTTP verification and an idempotent combined host
installation; no additional manual HTTP-patch step is required.
