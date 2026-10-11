# System 1.1.13 support

Firmware 1.1.13 adds collision detection during tool-alignment calibration.
WM+ includes the new vendor configuration and keeps its existing calibration
clearance moves. The touchscreen fixes have also been updated for this client.

**Install vendor 1.1.13 before applying the current WM+ configuration.** It requires
the new vendor calibration modules and cannot run as-is on 1.1.12.
WM+ does not install vendor firmware.

The package comparison and initial local checks were completed October 2, 2026.
The complete reviewed WM+ deployment was installed and checked on the printer
October 10, 2026. Print, tool-change, and calibration trials remain pending.

## What changed

Compared with 1.1.12, the package changes:

- The touchscreen executable, still 61,340,216 bytes.
- `change_extruder.cfg`: adds a `[collision_detect]` section.
- `offset_calibrate.cfg`: controls collision monitoring around calibration.
- Klipper calibration modules: adds `collision_detect.py` and replaces the
  compiled calibration core with readable `tools_calibrate_core.py`.
- Package version metadata.

Other packaged macros, Klipper files, screen assets, MCU firmware, services,
and installer scripts are byte-identical. This comparison found no fix for the
Wi-Fi, fan-request, recovery-coordinate, or openACE-resume faults in the reviewed
screen paths. It does not establish a screen-performance improvement.

One confirmed screen change makes the skip button initially visible in
`setup_screen_main`. That function is 20 bytes shorter, shifting later code
addresses. The WM+ patch profiles account for the new locations.

## What the collision detector protects

Monitoring is off when Klipper becomes ready. Adding `[collision_detect]` does
not enable protection throughout printing.

During `CALIBRATE_TOOL_OFFSET`, the macro finishes pickup, bed probing, and travel
to the sensor before enabling monitoring. It then locates the sensor or calibrates
the selected tool, disables monitoring, and returns to Y250. WM+ keeps both of its
existing clearance calls around this travel.

The calibration macro uses a **12 m/s² threshold, two consecutive hits, and
Klipper shutdown**. The section defaults are 25 m/s², two hits, and pause,
but the calibration macro overrides them each time.

A hit is a change in acceleration magnitude between consecutive samples. It is
not a limit on absolute acceleration and is not divided by elapsed time. Two
consecutive changes at or above the threshold schedule shutdown. A steady high
acceleration magnitude does not trigger this calculation.

The new calibration core also rejects guarded positioning and probing when an
XYZ probe endstop is already triggered. Error handlers release the collision
monitor before reporting failure. Some final/retract moves still use direct
`manual_move`; the checks do not cover every motion in every macro.

## Protection limits

- Sensor data reaches the host in 100 ms batches. The config's roughly 5 ms
  two-sample description is not a measurement of stopping time. Processing
  and physical stopping take additional time.
- The first 0.2 seconds are a warmup, timed from batch receipt rather than
  individual sample timestamps.
- This detects an impact during calibration. It does not plan paths around
  printed objects or protect all printing and service moves.
- The separate pause action requests pause through `pause_resume`; it may
  not run the full PAUSE macro. Calibration uses shutdown instead.

Threshold sensitivity and stopping performance have not been measured on this
printer. The previous calibration core was compiled, so this analysis does not
establish that every calibration calculation is equivalent to the old core.

## Checks and next printer validation

Local tests check actual C compatibility guards against the extracted client,
reject altered copies, and check patch instruction sites. Macro tests cover both
stock and WM+ collision-control order, T0/other-tool branches, and retained
clearance. Tests of the extracted vendor Python modules cover consecutive hits,
sensor release, cleanup after failure, and triggered-probe rejection.

The recorded suite at this integration passed 198 tests. Tests needing local
`analysis/` vendor files skip when those files are absent; configuration-rendering
checks do not. Passing these checks does not establish hardware performance.

After installation, verify Klipper Ready, patch logs for the current screen
process, optional openACE detection, and a normal tool-offset calibration.
Do not deliberately cause a collision as a validation test.
For interrupted prints, read the [checkpoint upgrade limits](../client-preload/README.md#upgrading-with-an-interrupted-print)
first.

### Printer deployment checked on October 10, 2026

All four components passed full preflight before installation. The first attempt
correctly stopped without applying changes when the temporary nginx check could
not find installed modules. The check now retains nginx's normal prefix while
using the prospective configuration copy; full preflight then passed.

Configuration, touchscreen, material helper, and the four reviewed preload
patches were installed. Klipper returned Ready after the final firmware restart.
Checks confirmed:

- The configuration matches `config/live`; all four head identities, saved
  variables, `tmt1.ini`, and the openACE configuration were preserved.
- Recovery and material helpers are loaded, as is the collision configuration.
  All four extruder heater targets are zero.
- The running client's Wi-Fi, fan, recovery, and openACE patch logs confirm
  successful application to 1.1.13.
- Installed helper and screen files match the local sources. The page served by
  nginx matches the updated browser decoder, and the JPEG snapshot displays the
  four-head home screen.
- A live 800×480 screen baseline decoded successfully through nginx: 40,658
  compressed bytes, received and reconstructed in approximately 0.2 seconds.

Fresh before/after snapshots and screen captures are retained locally in ignored
`analysis/deploy-1113-20261010/`. The local suite passed 228 tests; after correcting
the nginx preflight and the quiet-stream verification reader, the 39 relevant
preflight, installer, and screen tests passed again.

The experimental head-configuration guard was excluded from this initial deployment,
then installed separately at the owner's request on the same date. Its running
log and live callback jump were verified; actual fault behavior remains unobserved.
These checks establish installation and idle operation, not print quality,
tool-change behavior, or calibration performance. No motion, heating, extrusion,
or deliberate fault was commanded during this deployment validation.

## Package evidence and configuration merge

The recorded [official release note](https://wiki.wondermaker3d.com/en/Firmware-File/ZRU-Version/Version1113)
announces tool-alignment collision protection. The package came from the
[official listing](https://wiki.wondermaker3d.com/en/ZR-Ultra-S/Standard-Operating-Procedures/Fireware-Download).
It was decrypted and extracted without running the installer. Debian metadata
identifies `TM-T1-System` 1.1.13 for arm64.

| Artifact | SHA-256 |
|---|---|
| Official ZIP | `cd89c9864d72b27f64ff958101502513c2fb6763b3e15ab3c8cfa4839384408f` |
| Decrypted Debian package | `e98ba3bd597b866a0b5639ae2fee88d9dce8846a7b07e4542863ca6e65f0fc6f` |
| Screen client | `b60c96c5caf980a127a3d284e5ac98e799dfd79691cb1a52aafd06fd818c4715` |

`config/stock_1.1.12/` preserves the previous sanitized baseline.
`config/stock/` adds the verified vendor changes to that installed-model baseline,
retaining its reference files and includes. It is not a factory-calibration copy.
Vendor CRLF line endings were normalized for comparison.

The live calibration merge was reviewed manually because the vendor changed a
block containing WM+ clearance edits. Both clearance calls, the openACE include,
and the existing rollback-assist Off hook remain. Raw packages, executable,
and extracted modules are in ignored `analysis/`; tracked snapshots contain
configuration only.

## Patch reference for maintainers

| Patch dependency | 1.1.13 address |
|---|---|
| Fan material check | `0x61a9a8` |
| Fan parser / redundant OFF call / sender | `0x6387dc` / `0x63891c` / `0x53ff30` |
| Recovery writer / loader / start | `0x62f810` / `0x62c5ec` / `0x62d91c` |
| G-code sender | `0x614338` |
| Screen resume preparation | `0x51a7b4` |
| Wi-Fi processEvent / disconnect | `0x660cfc` / `0x6638fc` |

Fan, recovery, and openACE profiles use full-file FNV-1a fingerprint
`0x3ed764ac9cdaa82d`. Wi-Fi uses function fingerprint `0x4c5b0e42b09fd41b`.
Older reviewed profiles remain available. Unknown or modified clients are skipped.

The Wi-Fi patch still preserves wrong-password handling. Recovery still writes
logical G-code XYZ and validates companion format markers. openACE behavior still
requires detection of the running `openace` object. See the
[touchscreen patch guide](../client-preload/README.md) for user-visible behavior.

## Head-count reset observed on 2026-10-10

Read-only inspection of the printer's client log identified an explicit vendor
reset, rather than a WM+ config upload. Times below are the printer's log times.

At 22:19:26–27, the client received a shutdown associated with `ZRU-B005`
(Toolhead 3 multi-material-unit communication error) and ran `unlock_extruder`.
It cleared the CAN UUIDs for heads 1–3, copied `TM_T1/other/printer1.cfg` over the
active printer.cfg, wrote `1` to `TM_T1/other/current_thr_number.txt`, and ran
`replace_save_config.sh`. That script also deletes saved calibration sections
for the excluded extruders. The operation appeared twice in overlapping log
entries. This establishes destructive configuration writes by the vendor client;
it does not establish why the initial communication fault occurred.

At 22:25:41–44, the upgrade/startup CAN query failed while opening `can0` with
`OSError: [Errno 19] No such device`. The client nevertheless read the old count
file as `1`; it logged previous count `4`, current count `1`. At 22:26:07 it
issued `SAVE_VARIABLE VARIABLE=thr_number VALUE=1`, resetting recovery records
and removing `just_updated`. Read-back showed all three count representations
at one and the other extruder includes commented out. `can0` was up at the time
of the later read-only investigation.

Binary inspection confirms the destructive callback is `_ZL15unlock_extruderv`
at `0x633fc4` in the reviewed 1.1.13 client. `parse_webhooks` schedules it when
`state_message` contains any of `ZRU-B003` through `ZRU-B006`. These are
multi-material communication error codes. The callback is not limited to a
verified, intentional removal of physical heads. It is also present in 1.1.12
at `0x633fd8`, and the vendor CAN discovery script is byte-identical between
those releases. A transient failure can therefore become a persistent one-head
configuration, and a failed discovery does not invalidate the stale count.

WM+ config synchronization excludes saved_variables.cfg, tmt1.ini, and the
machine-owned `wm_zru_*.cfg` files. Its existing preload patches do not hook
this destructive callback. The observed writer is the vendor client. Whether
WM+ or openACE contributed indirectly to the initiating communication failure
remains unproven; the CAN interface was demonstrably absent during the later
upgrade query.

No configuration, service, or hardware state was changed during the investigation.
Recovery must account for the erased UUIDs and potentially removed calibration,
not merely set `thr_number` back to four. A future fix should preserve physical
head configuration on communication faults and require successful discovery
before replacing the persistent count. Neither fix was implemented by this audit.


The follow-up restoration on 2026-10-10 recovered all four identities and returned
Klipper to Ready with openACE and all four existing 1.1.13 patches loaded. Kernel
logs also identified an upstream USB-hub interruption preceding the MCU timeouts.
See [restoration evidence and non-destructive recovery design](head-communication-recovery.md).
The new head-configuration guard is locally tested and remains undeployed.
