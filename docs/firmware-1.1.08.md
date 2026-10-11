# System 1.1.08 integration record

WM+ was installed on vendor 1.1.08 on September 13, 2026. Configuration, calibration,
hardware identifiers, and saved settings were preserved. The first Klipper restart
failed to reset T0; a second firmware restart returned Ready. The client fingerprint
matched, Wi-Fi/fan patches loaded, and material and touchscreen services were active.

Later two-color print trials completed after mains power cuts with T0 and T2
probing heads, remapped tools, and corrected recovery coordinates. See
[the recovery record](print-mesh-recovery.md). The recorded suite after removal
of the cooling experiment passed 125 tests.

This is historical evidence. Current configuration requires
[1.1.13](firmware-1.1.13.md); use the [project README](../README.md) to install.

## Configuration decisions

The migration applied four verified vendor configuration changes to the earlier
sanitized installed-model snapshot. It kept model-specific includes and reference
files absent from the System package, without copying factory calibration or
contributor camera settings. Earlier baselines remain in versioned directories.

| Area | Integrated result |
|---|---|
| M104/M109 | Vendor 1.1.08 logical T remapping; omitted T uses the active physical heater; float targets and M109 S0 supported. |
| Tool temperature wait | Vendor wait on the physical active heater without setting another target. |
| PAUSE | Our mapping snapshot, then vendor identity reset, then heater shutdown; keep Y20 park. |
| Idle timeout | Vendor direct physical-heater shutdown, independent of duplicate logical mappings. |
| Door inputs | Vendor disabled gcode_button registrations in zru-s.cfg. |
| Existing W+ changes | Keep purge geometry, feedrate/wipe changes, tip shaping, insert-no-autoload, material include, accel cap, REHOME and optional probe-tool controls. |
| Calibration and camera settings | Keep parameterized NOZZLE_PREPARE temperature and existing camera settings. Contributor changes here were not official firmware deltas. |

Pause saves the original tool mapping before resetting it. Klipper renders a
macro's Jinja expressions before executing its generated commands, while nested
commands see state when they run. That distinction matters when changing order.

## Wi-Fi patch correction

The old 1.1.04 patch mislabeled three event branches: it disabled wrong-password
disconnection and missed repeated network-not-found. Decompilation and event-string
references corrected the selection for both reviewed clients.

In 1.1.08, `WifiManager::processEvent` is at `0x6607a8`; `disconnect` is at
`0x6633a8`. Disconnect sends `DISCONNECT` to the Wi-Fi service, stopping automatic
retries. The patch replaces the selected calls with no-operation instructions
(NOPs):

| Event | 1.1.04 call | 1.1.08 call | Expected instruction | Result |
|---|---|---|---|---|
| CONN_FAILED / timed out | `0x6604d8` | `0x660cb4` | `0x940009bd` | NOP |
| WRONG_KEY | `0x6605ec` | `0x660dc8` | `0x94000978` | Keep |
| ASSOC-REJECT | `0x660700` | `0x660edc` | `0x94000933` | NOP |
| NETWORK-NOT-FOUND (>3 events) | `0x660850` | `0x66102c` | `0x940008df` | NOP |

Checks identify the entire reviewed function and its loaded instructions before
editing. Unknown clients, altered functions, and an unexpected NOP in the
wrong-password branch are rejected. Intended existing NOPs are accepted.
Earlier static reports with the old labels are superseded by this table.

## Tool changes, calibration, and fan requests

The contributed XY-return idea was adapted to run after success and wiping,
using logical coordinates and preserving the new tool's flow. It lifts 2 mm,
returns at 200 mm/s, and does not return after failure.
[The tool-change record](toolchange-return.md) explains the sequence and tests.

Calibration and homed idle tool selection/wiping establish at least 7 mm clearance
in both physical and G-code coordinates. Screen calibration sends T0 before
`PROBE_CALIBRATE`, so the tool-selection check is needed even when T0 is already
mounted. This follows the inspected screen path, not a reconstruction of every
older collision report.

The screen's ABS material check repeatedly requests full filter-fan speed when
status reports zero. WM+ permits one automatic start per print and gives manual
screen choices priority. It also removes a redundant Off request for an absent
filter. Slicer fan commands and the fan driver remain unchanged.

For maintainer reference, the 1.1.08 sites are `material_check=0x61a8cc`,
`set_air_fan_speed=0x53fe54`, and `parse_air_fan=0x638488`.
The sender wrapper keeps the verified four entry instructions and uses a mutex
so a concurrent automatic check cannot overtake manual Off. Full-file and
loaded-instruction checks skip unknown clients. The first fan profile supported
1.1.08; later releases added profiles. Current behavior and logs are in the
[patch guide](../client-preload/README.md).

## Temperature waits and removed cooling detour

General M109/M190, chamber M191, 140°C startup probing, and tool-change waits
retain their temperature bands. The 160°C calibration-wipe step can require either
heating or cooling, so it keeps a band too.

Only the final cooldowns in `NOZZLE_PREPARE` and `POP` changed to upper-only waits:
100°C target with 102.5°C maximum, and 102°C target with 104.5°C maximum. Both
heater and sensor use the mapped head. An undershoot does not trigger a reheat.
Those bounds apply to that wait command, not future heater operation.

The auxiliary-fan detour was measured and removed September 14. Cooldown from
220°C to 140°C averaged 44.0 seconds with the part fan and 44.6 with both fans.
Original cooling locations returned; independent wait and clearance fixes remain.
See [the experiment](cooling-assist.md).

## Community changes and review tools

The migration also added content previews and a three-way configuration helper.
The helper creates review candidates without changing stock/live and excludes
machine-owned files. It reports conflicts, file decisions, and lost WM+ markers.
The four submitted patches were reviewed separately because their intermediate
baselines contained machine-specific data and their final baseline missed a
vendor heater fix. Reformat-only changes were not imported.

First-tool probing became enabled by default after user-reported testing.
Separate per-print meshes and recorded tool mappings then made it usable with
recovery. The default mesh remains a T0 calibration.

## Validation limits

Config loading, remapped changes, first-tool probing, T0/T2 power-cut recovery,
and corrected checkpoint writing passed on the printer. Full nozzle-offset
calibration, deliberate Wi-Fi-failure/wrong-password cases, and a dedicated ABS
fan automatic/manual test remained separate checks. Local tests covered those
software policies without proving hardware behavior.

```bash
uv run --with pytest --with jinja2 --with unicorn python -m pytest -q tests
```

The tests cover heater mapping, pause backups, temperature waits, content previews,
calibration exclusions, migration failures, nested motion macros, fan policy, and
compiled client checks. Some tests need local vendor extracts and skip without them.

## Package and analysis evidence

| Official artifact | SHA-256 |
|---|---|
| 1.1.04 ZIP | `26420e14243a55ca9e243936db6e77850c94b04964969e235006583b5c0febf2` |
| 1.1.08 ZIP | `71b675bc561068f2e4c24ff40c68e0556d71c82d2734da942fa8505e9316265a` |
| 1.1.04 client | `6889c20f7fc2991a30c26322ca2d0996ddb2ed3f1b14eb39aa9e03163794a8c3` |
| 1.1.08 client | `4ee5cb53b38371417550b8f28a43e486dc8e1e47e6e4b5f43fc3fe6b4512bc1d` |

Packages came from the recorded
[vendor listing](https://wiki.wondermaker3d.com/en/ZR-Ultra-S/Standard-Operating-Procedures/Fireware-Download).
Debian metadata confirmed 1.1.04 and 1.1.08 after decryption.
Ghidra 12.1.2 was used for client comparison.

Local evidence, absent from a normal checkout:

- `analysis/fw_1.1.08_diff/` and `analysis/fw_1.1.0{4,8}_payload/`: inventory,
  extracted files, and comparisons.
- `analysis/fw_1.1.08_diff/implementation/ghidra/`: decompilation and event strings;
  `calibration-*.c` includes fan/calibration evidence. The auto-check button
  handler was at `0x4b4768`.
- `analysis/backups/`: pre/post-upgrade backups, each with 108 files and checksum manifest.
- `analysis/deployment-1.1.08-20260913/`: deployment checks.
