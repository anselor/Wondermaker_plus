# Installation, updates and factory removal

This lifecycle applies to the revised r4 installer. It restores factory software
and executable configuration while preserving machine geometry and calibrated
hardware settings. It does not flash MCU firmware or reset Wi-Fi credentials.
Uploaded G-code and user material/profile data are separate from installed code.

## Updating selected components

Use SSH and component selections with the unified package:

```sh
uv run --with paramiko --with jinja2 python tools/deploy.py install config --preflight-only
uv run --with paramiko --with jinja2 python tools/deploy.py install config
```

The unified `config`, `material` and `preload` components form one matched
installation group. Selecting any one automatically includes the others and
`moonraker`. This also makes a partial config selection work on a fresh stock
printer, where the required light/screen patch does not exist yet. Independent
`touchscreen`, `shaper` and `moonraker` selections remain supported. The installer prints implicit additions and checks
the complete selection before publishing anything. Unchanged helper content is
not rewritten. `--files` and HTTP `--config-only` belong to older packages; the
unified package uses a managed behavior include and preserves hardware files.

## Originals and update rollback are different

Original snapshots survive repeated updates. A previous WM+ generation never
becomes the factory original. Helper ownership is shared: removing one component
retains files still owned by another. Unknown pre-existing helper content is
preserved as a pre-existing original; exact known WM+ releases are recorded as
WM+-created payloads, whose factory state is absence.

The helper inventory is `.wmp-helper-ownership.json` in Klipper's extras
directory. Screen originals and installed hashes are recorded in
`~/wmp/.wmp-preload-ownership.json`. The bridge's factory file/service/camera
record is `/opt/wondermaker_plus-transactions/factory-baseline`. These records
are data, not scripts. Do not edit or copy them to another printer.

Per-install journals provide rollback to the immediately preceding generation.
They are not factory snapshots. Helper rollback bytes stay in the protected
installer receipt, avoiding a new loose helper backup on every update. Preload
and configuration transaction evidence remains available for interruption
recovery; deleting it early can prevent rollback. Existing legacy backups are
not automatically trusted or bulk-deleted.

## Removing components

Check the intended removal first:

```sh
uv run --with paramiko --with jinja2 python tools/deploy.py uninstall all --preflight-only
uv run --with paramiko --with jinja2 python tools/deploy.py uninstall all
```

Preflight does not remove components or restart services. It checks all selected
components before the first removal. An unresolved edited dependency or original
stops removal. Removing config while a dependent screen remains installed is
refused; include `preload` in that selection. Material-only removal similarly
refuses to break active managed configuration.

The removal order restores configuration before restarting the stock screen.
Recognized legacy inline r3/r4 macro behavior returns to the vendor behavior;
hardware sections, extruder calibration and `SAVE_CONFIG` tuning stay intact.
Known published daemon configuration is restored and its daemon restarted.
Unknown user daemon configuration is preserved. Generated files with no custom
sections are removed, with their prior bytes retained in the recovery receipt.
Custom sections are preserved; active unproven WM+ dependencies cause an
incomplete result rather than silent success.

The screen bridge restores original files, service states, webcam identity and
recorded timelapse selection. Its explicit uninstall uses the same transaction
machinery as rollback. Legacy installs have no reliable original timelapse
selection, so migration preserves the current selection instead of inventing one.
An nginx backup is accepted only when the exact WM+ insertion explains the
current file. API failures and unexplained edits stop removal.

The shaper restore verifies every backup against the supported vendor source
before replacing any source file, then rebuilds the helper and restarts Klipper.
Retired preload names are tracked and are not loaded into a new screen process.
Factory removal restores original resources rather than reinstalling an earlier
WM+ binary.

## Older releases and interrupted work

Migration evidence is an inert catalog of executable-option and helper hashes
from published r4 ancestry, including r3. The vendor shipped active-config and factory-reset macro variants are both
recognized from the retained 1.1.13 payload. Unknown edits are not classified by a
filename or WM+ marker alone. Review a reported conflict before retrying; do not
select the newest `.wmp-backup` and assume it is factory content.

Release maintenance must regenerate the catalog from the last published r4
commit before retiring previously shipped helpers:

```sh
python tools/build_legacy_config_catalog.py --published-ref COMMIT
python tools/reseal_screen_package.py
```

Review the resulting provenance and package changes. Recovery of a new receipt
requires this installer or a compatible newer version; older helper rollback
code does not understand the added metadata field. Legacy five-field receipts
remain supported. See [installation recovery](installation-recovery.md).

## Verifying the factory motion baseline

Before comparison prints, while idle:

```sh
uv run --with paramiko --with jinja2 python tools/verify_factory_state.py --output factory-state.json
```

This sends no G-code, restarts no service and reads no MCU flash. It checks 23
retained vendor motion source hashes, 17 critical macro contracts, the stock
screen binary, absence of mapped WM+ libraries and active WM+ configuration,
and that the live helper matches the current rebuilt helper. It also checks
that Klipper started after source restoration. A failure means the comparison
baseline is unverified; investigate it before printing.

This verifies the stated motion/software scope, not every file in the operating
system. It preserves the distinction between vendor software and user tuning.
Inactive receipts, material data and archives do not mean WM+ code is running.
