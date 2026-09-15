# System 1.1.08 integration

Repository migration prepared 2026-09-13 from the official 1.1.04 and
1.1.08 System packages. After the user installed vendor 1.1.08, W+ was
deployed on 2026-09-13. The official client SHA-256 matched, the live config
matched config/live, and both fan/Wi-Fi patches reported success in the
running client. The material helper and touchscreen endpoints were active.
The first Klipper restart failed to reset T0; a second FIRMWARE_RESTART
returned Ready. Calibration, device IDs and saved-variable values were
preserved. That initial deployment did not include motion or heating trials.
Subsequent two-color prints and mains-power recovery passed with T0 and T2
probing references, including swapped mappings and corrected checkpoints.
The final suite passes 125 tests. See [recovery validation](print-mesh-recovery.md)
and the removed [cooling experiment](cooling-assist.md) for results and limits.

Private pre/post-upgrade backups are under `analysis/backups/`; deployment
evidence is under `analysis/deployment-1.1.08-20260913/`. Each backup contains
108 files with a verified archive and checksum manifest.

## Baselines and provenance

`config/stock` is a **real directory** for the latest baseline.
`config/stock_1.1.04` preserves the previous directory byte-for-byte;
`config/stock_1.0.71` is retained. The 1.1.08 baseline applies only the four
verified config deltas to the prior sanitized installed snapshot. This
keeps model-specific includes and ancillary reference configs that the
System package does not supply. It does not copy factory calibration or
one contributor's camera settings.

| Official artifact | SHA-256 |
|---|---|
| 1.1.04 ZIP | `26420e14243a55ca9e243936db6e77850c94b04964969e235006583b5c0febf2` |
| 1.1.08 ZIP | `71b675bc561068f2e4c24ff40c68e0556d71c82d2734da942fa8505e9316265a` |
| 1.1.04 client | `6889c20f7fc2991a30c26322ca2d0996ddb2ed3f1b14eb39aa9e03163794a8c3` |
| 1.1.08 client | `4ee5cb53b38371417550b8f28a43e486dc8e1e47e6e4b5f43fc3fe6b4512bc1d` |

The [vendor listing](https://wiki.wondermaker3d.com/en/ZR-Ultra-S/Standard-Operating-Procedures/Fireware-Download)
links the new firmware. Both ZIPs were decrypted using the existing local
analysis tooling; package control versions confirm 1.1.04/1.1.08. Full
inventories, extracted files and per-file diffs remain in ignored
`analysis/fw_1.1.08_diff/` and `analysis/fw_1.1.0{4,8}_payload/`.

## W+ reconciliation

| Area | Integrated result |
|---|---|
| M104/M109 | Vendor 1.1.08 logical T remapping; omitted T uses the active physical heater; float targets and M109 S0 supported. |
| Tool temperature wait | Vendor wait on the physical active heater without setting another target. |
| PAUSE | Our mapping snapshot, then vendor identity reset, then heater shutdown; keep Y20 park. |
| Idle timeout | Vendor direct physical-heater shutdown, independent of duplicate logical mappings. |
| Door inputs | Vendor disabled gcode_button registrations in zru-s.cfg. |
| Existing W+ changes | Keep purge geometry, feedrate/wipe changes, tip shaping, insert-no-autoload, material include, accel cap, REHOME and optional probe-tool controls. |
| Calibration and camera settings | Keep parameterized NOZZLE_PREPARE temperature and existing camera settings. Contributor changes here were not official firmware deltas. |

PAUSE Jinja expressions read the original mapping while the macro renders;
nested M104 calls see the reset mapping when they execute. Snapshot-first
ordering makes this clear, but merely putting an inline snapshot later in
the same macro would not make it read post-reset state.

## Touchscreen binary patch

At the start of this migration, the existing address-based modification was wifi-fix;
the screen bridge and material extra have no client instruction offsets
to relocate. Their vendor Python payloads are unchanged between releases.

Ghidra 12.1.2 decompiled `WifiManager::processEvent` and `disconnect` in
both clients. ELF string references identify each event branch and confirm
that disconnect sends `DISCONNECT` to wpa_supplicant. In 1.1.08,
processEvent is at `0x6607a8`, disconnect at `0x6633a8`.

| Event | 1.1.04 call | 1.1.08 call | Expected instruction | Result |
|---|---|---|---|---|
| CONN_FAILED / timed out | `0x6604d8` | `0x660cb4` | `0x940009bd` | NOP |
| WRONG_KEY | `0x6605ec` | `0x660dc8` | `0x94000978` | Keep |
| ASSOC-REJECT | `0x660700` | `0x660edc` | `0x94000933` | NOP |
| NETWORK-NOT-FOUND (>3 events) | `0x660850` | `0x66102c` | `0x940008df` | NOP |

This corrects the old patch's branch labels and selection: it previously
patched WRONG_KEY and missed repeated NETWORK-NOT-FOUND. The implementation
supports both known clients, checks their complete function fingerprint,
and validates all loaded instructions before changing anything. The C
guard tests confirm that unknown executables, a modified vendor function,
and an unexpected WRONG_KEY NOP are rejected. Intended existing NOPs are
accepted. No new runtime library dependency is added.

Ghidra output and annotated string references are retained locally under
`analysis/fw_1.1.08_diff/implementation/ghidra/`. The earlier static reports
that repeated the old branch labels are superseded by this mapping.

## Community contributions adopted

- Preserve versioned historical stock directories, with a normal latest
  stock directory as requested. No symlink convention.
- Adapt the three-way migration helper to **review candidates only**.
  It never writes live or promotes stock, excludes machine-owned state,
  reports conflicts/file decisions/lost markers, and refuses to publish
  any candidate after a Git/input error.
- Add `config_sync.py diff --patch` and `deploy.py status config --diff`.
  Include new-file content and correct missing-final-newline markers;
  retain calibration and UUID ownership exclusions.
- Reconcile the contributed heater/PAUSE changes with the independently
  verified package deltas, including the idle-timeout fix their series missed.

The four submitted patches were reviewed in isolation rather than imported
as commits: their intermediate baselines contained real machine identifiers
and calibration, and their final baseline omitted a vendor heater fix.

## Community motion and fan fixes

**First-tool probing and recovery:** first-tool probing is now enabled by
default following user-reported testing; explicit saved opt-outs remain.
Per-print meshes are isolated from default calibration in `wmp_print`.
The inspected vendor power-loss sequence restores the saved probing tool
and snapshot through config macros, with matching-file/calibration checks.
See [print-mesh-recovery.md](print-mesh-recovery.md) for the integration,
legacy-record limitation and outstanding physical recovery validation.

**XY return:** The contributed intent is implemented after reconciling
success/retry handling, new-tool offsets/flow, and the later wipe. Capture
logical XYZ once, retain the print lift, return after verified success and
wipe at 200 mm/s, then lower Z. Failed changes cannot trigger a return.
See [the implementation and sequence tests](toolchange-return.md).

**Calibration clearance:** `_WMP_CALIBRATION_CLEARANCE` establishes a minimum
of 7 mm in both G-code and physical coordinates, never lowering an already
higher position. This uses the existing vendor Z-homing clearance; it is
not a measured guarantee of every printer's nozzle/wiper geometry.
NOZZLE_PREPARE, CALIBRATE_TOOL_OFFSET and CALIBRATE_TOOL_Z_OFFSET invoke it
before selecting tools and again before their XY probing travel after
offset changes. Direct calls require homed XYZ. PROBE_CALIBRATE retains its
existing G28 for missing homing and then calls the helper. Homed idle tool
selection and wiping also establish this clearance. The print toolchange
lift remains 2 mm.

Ghidra identifies the 1.1.08 auto-check calibration button handler at
`0x4b4768`: optional G28 when homed_axes is empty, then T0, then
PROBE_CALIBRATE. Therefore lifting only inside PROBE_CALIBRATE would miss
movement caused by the earlier T0. The idle tool-selection guard covers
that ordering even when T0 is already loaded. This establishes a current
software path; it does not identify the exact older-firmware incident in
the contributor's report.

**Air-fan backlog:** Fixed at the touchscreen source in
`client-preload/fan-fix/wmp_fanfix.c`, without disabling the filter.
Ghidra shows `material_check` (`0x61a8cc`) requesting 100% through
`set_air_fan_speed(int)` (`0x53fe54`) when printing ABS, filter installed,
and reported speed zero. Status updates can overwrite its optimistic
local speed assignment while the command is blocked, allowing repeated
requests. `parse_air_fan` (`0x638488`) also redundantly sends OFF when the
reported fan is already zero and the filter is absent.

The replacement automatic check consumes one allowance per print before
sending. It does not re-arm on zero feedback, pause/resume, missing state
or host error/reconnect. Known terminal print states while Klipper is
ready re-arm for the next print. An already-running fan consumes the
allowance too. Explicit touchscreen fan requests during printing/paused
consume it immediately and pass through unchanged, so manual OFF or a
selected speed is respected even before the first automatic check. This
once-per-print policy was explicitly agreed during review. A mutex serializes
automatic and explicit touchscreen dispatch so a concurrent manual OFF cannot
be overtaken by the automatic check. The preload build links pthread. Slicer commands
remain untouched; subsequent fan-off commands are not fought by polling.

The redundant status-callback OFF call is removed. The air_filter installed
flag and actual fan implementation remain unchanged. No global Klipper
request-queue modification is included: bounding this automatic sender
removes this source of accumulation. Reproducing the reported crash timing
is not a prerequisite for the fix or its acceptance.

The fan preload supports the exact official 1.1.08 ELF only, with a full-file
fingerprint and loaded-code comparison before any edit. It replaces the
automatic check and wraps the explicit sender using AArch64 jumps. The
sender trampoline preserves the four verified position-independent entry
instructions, then executes the unchanged vendor body. Unknown/modified
clients are skipped. Logs: `/tmp/wmp_fanfix.log`; disable switch:
`WMP_FANFIX_DISABLE=1`. Ghidra decompilation/string evidence is retained in
ignored `analysis/fw_1.1.08_diff/implementation/ghidra/calibration-*.c`.

## Scoped cooling waits

Keep the existing Klipper-style M109/M190 temperature waits and the vendor
M191 band wait. No R parameter or heating-only reinterpretation of S is
introduced. START_PRINT's 140°C probing band and tool-change temperature
bands are also retained.

The German report's temperature example is START_PRINT's 140°C wait; its
160 figures refer to XY speed in mm/s. The actual 160°C waits occur before
wiping in NOZZLE_CALIBRATE_TOOL_OFFSET and after extrusion in EXTRUDE_FILAMENT.
The calibration sequence can reach that step from a 100°C cooldown, requiring
heating, or from a hotter starting state, requiring cooling. Retain its band
wait. The post-extrusion wipe wait also retains its existing band. Waiting
for a controlled preparation temperature is legitimate; a long wait exposing
the fan-request backlog does not establish that its temperature bounds are
wrong. Nozzle ooze and repeatable preparation conditions are reasons to retain
the probing/wiping targets; exact optimal values are not established here.

Only two deliberate cooldown steps in `offset_calibrate.cfg` use explicit
standard Klipper commands: NOZZLE_PREPARE sets its mapped heater target to
100°C and waits with MAXIMUM=102.5; POP sets 102°C and waits with
MAXIMUM=104.5. These retain the previous targets and upper tolerances, but
do not wait for reheating if temperature undershoots. Heater and sensor
use the same logical-to-physical mapping as the preceding tool selection.
The surrounding fan-on/fan-off sequence is preserved. MINIMUM/MAXIMUM are
local conditions for that TEMPERATURE_WAIT invocation, not persistent heater
limits. No clearing command is needed. A later target-setting command replaces
the cooldown target normally. A regression test executes the bundled vendor
wait handler for cooldown followed by heating on the same heater/host objects.

## Chamber-fan cooling experiment removed

The temporary chamber-fan boost and cooling-position changes were removed on
2026-09-14 after three runs per condition measured 44.0 seconds with the part
fan alone and 44.6 seconds with both fans (220→140°C). Loading/calibration and
blob cleaning use their original cooling locations. The independent scoped
cooldown waits and calibration-clearance safeguards remain.
See [measurements and rollback scope](cooling-assist.md).

## Validation status and remaining checks

Config loading, normal remapped tool changes, first-tool probing, mains-power
recovery with T0/T2 references, and the corrected checkpoint writer have passed
on the printer. The chamber-fan cooling experiment was measured and removed.

Full nozzle-offset calibration and deliberate Wi-Fi failure/wrong-password
scenarios remain separate acceptance checks. Automatic ABS filter startup and
manual overrides across status refreshes and pause/resume also need a dedicated
hardware check; the request policy and binary guards have offline coverage.
The preloads build and load on the printer's ARM CPU. Known recovery clearance
and checkpoint-sampling limits are documented in the recovery notes.

## Local validation

```sh
uv run --with pytest --with jinja2 --with unicorn python -m pytest -q tests
```

Tests cover duplicate-mapping heater shutdown, PAUSE backups, no-T/explicit-T
temperature behavior, wait guards, content preview and calibration exclusion,
candidate merge conflicts/errors/ownership, nested toolchange/calibration
sequences, automatic fan request limits and manual precedence, and compiled
C binary guards. Vendor-source/binary checks use local extracted artifacts
and skip when those artifacts are absent. Compilation on the host and offline command
checks do not replace an AArch64 runtime/reconnection test on the printer.
