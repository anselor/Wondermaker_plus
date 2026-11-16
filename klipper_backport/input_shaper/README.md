# Input shaper backport

Replaces the printer's input shaper, shaper calibration, and resonance test
code with the current upstream Klipper versions. The rest of the vendor
Klipper tree is not modified.

Requires SSH and sudo. Installed by `tools/deploy.py` as the `shaper`
component, which `install all` includes.

## Versions

| | Version |
|---|---|
| Vendor Klipper base (firmware 1.1.04 to 1.1.13) | `v0.12.0-276-gca815f52c`, 2024-08-08 |
| Source of the files in this directory | `v0.13.0-827-g29d4ec2d6`, 2026-11-10 |

The vendor ships the six replaced files unmodified from its base (some with
CRLF line endings).

## Files

Paths are relative to `~/klipper/klippy/` on the printer.

| File | Local changes |
|---|---|
| `extras/shaper_defs.py` | none |
| `extras/shaper_calibrate.py` | none |
| `mathutil.py` | none (upstream only added functions) |
| `extras/input_shaper.py` | scan window update uses the vendor toolhead API; dual carriage handler removed |
| `extras/resonance_tester.py` | toolhead compatibility helpers |
| `chelper/kin_shaper.c` | `input_shaper_get_step_generation_window()` retained |

Local changes are enclosed in `>>> wondermaker+ begin: shaper-backport-*`
blocks.

Not replaced:

- `extras/lis2dw.py`. Upstream changed its MCU command format; the vendor MCU
  firmware and the vendor `collision_detect` module depend on the vendor file.
- `toolhead.py`, `chelper/__init__.py`. Both carry vendor changes.

### Compatibility changes

- `motion_queuing` does not exist in the vendor base. `input_shaper.py`
  reports step generation window changes through
  `toolhead.note_step_generation_scan_time()`, as the vendor version does.
- `ToolHead.set_max_velocities()` and `limit_next_junction_speed()` do not
  exist in the vendor base. `resonance_tester.py` sets the acceleration limit
  directly and wraps `Move.calc_junction()` for the duration of a resonance
  test. The wrapper is removed when the test ends or fails. Normal printing
  does not execute it.
- `input_shaper_update_sk()` is compiled but not declared in the vendor
  `chelper/__init__.py`. Only dual carriage printers use it.

## Behaviour changes

- `ei`, `2hump_ei`, and `3hump_ei` have new definitions. Existing settings
  with these types produce different motion after installation. Recalibrate.
- `zv`, `mzv`, and `zvd` produce identical stepper output.
- `damping_ratio` is limited per shaper type.
- `TEST_RESONANCES` and `SHAPER_CALIBRATE` use the sweeping test by default
  (`sweeping_accel: 400`, `sweeping_period: 1.2`). `sweeping_period: 0` in
  `[resonance_tester]` selects the previous pulse-only test.
- `[resonance_tester]` defaults: `accel_per_hz` 75 to 60, `max_freq` 133.33
  to 135.
- Automatic calibration ranks shapers differently and avoids recommending
  `zv` when another shaper fits.
- A Z axis shaper exists and is disabled unless `shaper_freq_z` is set.
- The touchscreen shaper calibration runs `SHAPER_CALIBRATE` and therefore
  uses the new test and ranking.

## Install

```
uv run --with paramiko --with jinja2 python tools/deploy.py install shaper --preflight-only
uv run --with paramiko --with jinja2 python tools/deploy.py install shaper
uv run --with paramiko python tools/deploy.py status shaper
uv run --with paramiko python tools/deploy.py uninstall shaper
```

`tools/shaper_backport.py` runs the same steps on its own with `status`,
`install [--dry-run]` and `uninstall`.

Checks, performed before anything is replaced:

1. Klipper is ready and no print is active or paused.
2. Each target file is the known stock file (either line ending) or the
   backport. Anything else is refused.
3. The vendor `toolhead.py` and `chelper/__init__.py` contain the interfaces
   the backport calls.
4. The stock files are copied to `~/wmp-shaper-backport/` with a manifest.
5. The C helper builds. The vendor C sources and the backport `kin_shaper.c`
   are copied to `~/wmp-shaper-backport/build/`, compiled there with the
   printer's gcc and the vendor build command, and loaded to confirm the
   required functions resolve. This takes about 90 seconds. An identical input
   set reuses the previous build.

`--preflight-only` and `--dry-run` stop here.

Installation:

1. Replaces the six files, then installs the built `c_helper.so` so that
   Klipper does not rebuild it at startup.
2. Restarts `klipper.service`. When `preload` is installed in the same run,
   the head-configuration guard is verified first.
3. Restores the stock files and restarts again if Klipper does not reach
   ready.

A `FIRMWARE_RESTART` is not sufficient: it does not reload Python modules.

`uninstall` restores the recorded stock files byte for byte and restarts the
service. Klipper rebuilds the stock C helper during that start.

## Vendor firmware updates

A vendor update overwrites `~/klipper`. Afterwards `status` reports `stock`.
Run `install` again. If the update changes the Klipper base, the checks fail
and this directory must be revised against the new base. Until then, select
the other components by name instead of `all`.

## Verification

Offline, with the vendor `klippy` tree from firmware 1.1.13 in Klipper batch
mode against a host-simulated MCU dictionary built at the vendor base commit:

| Check | Result |
|---|---|
| Stepper output, `mzv`/`mzv` and `zv`/`zvd`, vendor vs backport | byte identical |
| Stepper output, `ei` family, vendor vs backport | differs (new definitions) |
| Sweeping test, junction wrapper vs the upstream `toolhead.py` change | byte identical |
| Sweeping test with the junction wrapper disabled | differs (wrapper is effective) |
| `SHAPER_CALIBRATE` with a synthetic accelerometer | completes on both trees |

On one printer with firmware 1.1.13, 2026-11-13:

| Check | Result |
|---|---|
| Install, uninstall and reinstall through `tools/deploy.py` | Klipper ready each time |
| Staged C helper build | 91 s; reused build 1 s; no rebuild at Klipper start |
| `TEST_RESONANCES` on X, Y and both diagonals | completed |
| Touchscreen Vibration Compensation (`SHAPER_CALIBRATE`, `SAVE_CONFIG`) | completed and saved |

Not tested: printing with the new shapers, the Z shaper, other printers.

`tests/test_shaper_backport.py` covers the installer, the deploy component and
the junction wrapper.
