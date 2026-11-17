# Standalone filament management

Decision, 2026-11-01: openACE remains optional. WM+ owns external filament
metadata and physical-head operations when openACE is absent. When installed,
openACE owns operations and metadata; WM+ calls its public commands. No fake AFC
printer object is registered and no competing command handler is replaced.

## State and persistence

`wm_material.filament_presence` reports the four physical filament switches.
Presence is separate from the persistent per-head loaded flag in
`wmp_filament_loaded.json`. Successful Load sets the flag; successful Unload or
a clear sensor clears it. Sensor present with a false flag means inserted, not
loaded. Restarting Klipper preserves the flag; missing/non-boolean sensor readings
remain unknown. A sensor identifies presence, not material, colour or whether the
tip has reached the nozzle. Manual operator assertions are debugging utilities;
normal UI workflows do not ask the user to confirm loaded/empty.

Attachment is derived from hall, coupling and all four dock switches. Exactly
one missing dock head plus locked coupling identifies the mounted head. Saved
`current_extruder` and the active motor are bookkeeping, not physical evidence.
Motion reconciles/checks motor selection separately.

Profiles are atomically persisted by the Klipper helper in `wmp_filaments.json`
next to the existing WM configuration. The touchscreen does not edit the vendor
INI. Empty heads retain the previous profile as an editor default, but their
cards display an outline circle, blank identity and Load. One editor supplies
brand/material list selectors and colour selection in both ownership modes.

## AFC compatibility

AFC is an ecosystem interface, not a Klipper-wide standard. Moonraker provides
Spoolman inventory/usage integration and a generic database API; it does not
provide a complete per-head filament workflow. Sources:

- https://moonraker.readthedocs.io/en/latest/external_api/integrations/#spoolman
- https://moonraker.readthedocs.io/en/latest/external_api/database/
- https://www.klipper3d.org/Status_Reference.html#filament_switch_sensor
- https://dev.afcproject.dev/klipper/internal/spool.html

WM+ publishes `lane_data` database rows named `wmplus_tool_0` through
`wmplus_tool_3`. Each logical tool follows the vendor physical mapping. Rows use
AFC field types: lane string, physical extruder index integer, colour #RRGGBB,
temperatures numeric, spool_id/weight null. `loaded` follows the reconciled per-head loaded state, not sensor presence alone.
Brand and temperature-range fields are extensions. The database is a client
compatibility projection, not a second authoritative store.

Commands (idle only, no movement/heating):

- `SET_COLOR LANE=wmplus_tool_0 COLOR=00A651`
- `SET_MATERIAL LANE=wmplus_tool_0 MATERIAL=PLA`
- `AFC_SET_SPOOL_TEMP LANE=wmplus_tool_0 EXTRUDER_TEMP=220 BED_TEMP=60`
- Optional WM+ extensions `MIN_TEMP=200 MAX_TEMP=230` on that temperature command.
- `WMP_SET_BRAND LANE=wmplus_tool_0 BRAND=Generic` (brand is not a standard AFC command).

Existing command names are declined, not overridden. openACE/real AFC presence
prevents WM+ command registration and publication. The publisher only removes
its own prefixed rows, uses a background network worker, and retries failed
publication. It exposes errors and declined commands in `wm_material.afc_metadata`.
Spoolman lookup, weight tracking, lane remapping and AFC transport commands are
not implemented by this compatibility layer.

## External load

Load opens a local filament draft with CANCEL / LOAD. Metadata save must be
confirmed by readback before starting the exact head's procedure. The operation
returns a receipt before long waits; progress is observable independently.

Standalone preparation requires a valid Z reference, finite calibrated dock
positions/offsets and sufficient clearance. It homes X/Y when needed using
`G28 X Y`; it never homes Z or uses logical T commands. Unknown Z remains a
refusal, not permission to home Z during filament service. It raises Z,
docks/mounts as necessary, verifies coupling and dock
sensors before leaving each phase, selects the physical motor, updates saved head
bookkeeping, and parks off-bed at X-13/Y80. Head offsets are applied without
movement. Heating has a 300-second limit; insertion waits up to 180 seconds for
the switch. Load feeds 55 mm, purges an initial 50 mm and wipes the nozzle.
These distances require physical material/color qualification. The loaded flag
is tracked separately from presence; successful Unload clears it even if the
switch still detects filament, and asks the user to remove filament. Service
completion shuts the heater off; failure attempts heater shutdown too.

With openACE, preparation and finishing use `OPENACE_LOAD_DIRECT HEAD=...` and
`DONE=1`, with sensor insertion between them. ACE slot loads continue through
`OPENACE_SELECT`; an ACE-assigned head has no external Load control.

Software tests are not physical qualification. Dock travel, coupling, insertion,
purge and unload need supervised printer acceptance before this is called
motion-qualified. A failed/uncertain physical operation must not be retried
implicitly by navigation or reconnect.

### Material recipe qualification matrix — 8 November

Source audit: `wm_material.py::_filament_plan`, `MATERIALS`, and
`macros.cfg::_TIP_SHAPE_MOVES`. These are the implemented starting recipes,
not evidence of successful physical service for each listed material. The Load
temperature below is the default before spool overrides and residual-material
transition selection. Unload uses the listed shaping target, checked against
explicit spool bounds and the heater's configured maximum minus 5 C.

| Material | Default Load (C) | Unload (C) | Shared shaping routine |
|---|---:|---:|---|
| PLA, PLA Silk, PLA Matte, PLA Metal | 220 | 250 | pla |
| ABS, ABS Matte | 250 | 280 | abs |
| PETG, PETG Matte | 250 | 235 | petg |
| PVA | 220 | 250 | pla |
| TPE, TPU | 230 | 250 | soft |
| Marble | 220 | 250 | pla |
| HIPS | 250 | 280 | abs |
| PET | 300 | 235 | petg |
| Wood | 220 | 250 | abs |
| ASA | 260 | 280 | abs |
| PA, PA6, PA12 | 260 | 280 | pla |
| PC | 270 | 300 | pla |
| PCTG | 260 | 235 | petg |
| PP | 240 | 250 | pla |

All 22 built-in names can produce plans with the stock 320 C heater limit and
otherwise valid service state. PA/PC/PP/PVA/Marble currently share the `pla`
shaping path; there is no independently qualified material-specific shaping
routine for them. This reuse must not be reported as physical qualification.
The accepted live Load evidence is H3 Sunlu PLA Matte (55 mm feed, 50 mm purge,
wipe), with user observation. That same-filament reload does not qualify a color
or material transition. The later cancelled H3 Unload proves STOP during heating,
not successful tip shaping or withdrawal. D03/D05/G07 remain open.

Material names outside the built-in table (including PLA-CF, PA6-GF and Custom)
are refused even if metadata supplies a temperature. Missing shaping/wipe macros,
conflicting explicit temperature bounds and heater-margin violations also refuse
service. Disjoint old/new temperature ranges refuse automatic Load rather than
invent a transition recipe. A catalogue choice is metadata availability, not a
promise that the physical material or every transition has been qualified.

## Pending: material-transition temperature

User requirement, 8 November: Load must account for residual material from the
previously loaded filament, including high-to-low and low-to-high temperature
changes. The original implementation selected a target from only the incoming
identity/recipe. Deployed r89 and later retain hotend history and use generic
shared ranges as described below. Physical transitions and disjoint-range
recipes remain pending; the incoming-only behavior is historical.

Retain a separate last-loaded material identity and temperature range across
Unload, sensor clearing, metadata edits and restart. An editable incoming spool
profile is not evidence of the material remaining in the hotend. Record the
incoming identity when actual feed occurs; an interrupted purge may leave mixed
residue and must not silently claim a completed material transition.

Choose a qualified transition target using both usable ranges: toward the upper
end for lower-temperature material and the lower end for higher-temperature
material where these ranges overlap. Do not invent an average for disjoint
ranges or silently exceed a material/heater limit. Such combinations need an
explicit transition recipe; unknown prior material/ranges must be represented
honestly. Show the selected target in the preparation/progress UI. Test both
directions, same-material reload, edited incoming identity, restart persistence,
unknown history, disjoint ranges and interrupted purge. Qualify actual material
transitions physically; the H3 same-PLA run does not establish this coverage.

Local implementation progress: `wmp_hotend_materials.json` now stores bounded,
validated per-head material snapshots separately from spool metadata and loaded
flags. Before feed dispatch it atomically records possible mixed residue; after
successful purge it records the incoming material. Unknown prior residue remains
explicit during incomplete feed/purge. Unload and sensor clearing do not erase
this history. Load review tokens include the prior record. Corrupt history
refuses admission, and persistence failure prevents feed. This code is not yet
deployed and does not yet choose the transition temperature; range policy, UI
presentation and release preservation checks remain open. The full backend suite
passes 352 tests (`hotend-history-backend.xml`), including the new history and
interruption cases. This is software evidence, not mixed-material qualification.

Local temperature-selection follow-up: reviewed Load plans now include previous
material history and a transition explanation. With explicit old/new ranges,
cooler incoming material uses the upper shared limit and hotter incoming material
uses the lower shared limit. Every known mixed-residue component constrains the
intersection; unknown additional residue does not bypass known incompatible
ranges. Same-material reload retains its normal target. Missing prior history is
reported as unknown with the incoming service target. Known material changes
without ranges and disjoint ranges currently refuse automatic Load. This is not
yet deployable for the built-in catalogue: reviewed default ranges, UI explanation
in the external Load editor, preservation/delivery checks, and handling of
non-overlapping material transitions remain open. No hardware temperatures were
changed by these edits. Full backend suite: 358 passed, plus one subsequent plan
integration test (`transition-temperature-backend.xml`, `transition-temperature-plan.xml`).

Reference investigation: OrcaSlicer generic PETG inherits from
[fdm_filament_pet](https://raw.githubusercontent.com/SoftFever/OrcaSlicer/main/resources/profiles/BBL/filament/fdm_filament_pet.json),
which defines 220–260 C, while
[Generic PETG @base](https://raw.githubusercontent.com/SoftFever/OrcaSlicer/main/resources/profiles/BBL/filament/Generic%20PETG%20@base.json)
overrides the upper limit to 270 C. These are slicer preset values, not qualified
WM+ transition recipes; they have not been adopted as universal material limits.

Local UI follow-up: the backend publishes `temperature_description` as part of
its reviewed Load plan; projection retains that optional string. The external
Load editor displays it for the current material. Editing thermal settings
replaces the old target with a recalculation message, avoiding a stale target
claim; stale connection/identity and position errors retain precedence. Changes
to this text update the editor layout without adding raw telemetry to its redraw
key. Native lifecycle and real status projection tests pass (2 cases in
`transition-ui.xml`); selected history/transition backend tests pass (13 cases in
`transition-selected.xml`). Deployment remains pending built-in ranges and the
remaining transition behavior. Installer preservation tests now explicitly
include the new history file alongside existing filament data.

### Built-in transition range defaults (deployed r89 and later)

Source snapshot: [OrcaSlicer e23af6d7b075ab6e317485551c7cbee33d1b4c4b BBL filament presets](https://github.com/SoftFever/OrcaSlicer/tree/e23af6d7b075ab6e317485551c7cbee33d1b4c4b/resources/profiles/BBL/filament).
Extracted values and exact per-file URLs are recorded in
`analysis/validation/2026-11-08-main-track/upstream-material-ranges.json`.
These are WM+ generic starting defaults, not manufacturer-specific guarantees or
physically qualified transition recipes. The chosen plan explicitly labels use
of generic ranges. Per the agreed swap policy, generic material bounds take
precedence over spool-specific printing bounds for Load transitions and target
validation. Spool bounds remain fallback data for materials without a generic
range; configured heater limits still apply. Unload shaping is unchanged.

| WM+ material | Generic nozzle range (C) | Source / mapping |
|---|---|---|
| PLA, PLA Silk, PLA Matte, PLA Metal | 190–240 | PLA inherits common; WM+ applies family default to named variants |
| ABS, ABS Matte | 240–280 | ABS; family default for Matte |
| ASA | 240–280 | ASA |
| PETG, PETG Matte | 220–260 | PET preset (its filament type is PETG); family default for Matte |
| PCTG | 220–260 | PCTG |
| TPU | 200–250 | TPU |
| PVA | 190–240 | PVA inherits common |
| HIPS | 220–270 | HIPS |
| PA, PA6, PA12 | 260–300 | PA; family defaults for PA6/PA12 |
| PC | 260–290 | PC |
| PP | 220–250 | PP |
| PET, TPE, Marble, Wood | No generic range adopted | Existing WM+ service temperature is a single known point; plan labels this limitation |

Generic defaults now allow ordinary built-in material changes without profile
import. For example, generic PLA/ABS intersects at 240 C even when the saved PLA
printing maximum is 225 C; the swap uses the generic PLA range. Disjoint ranges still need
a separate transition recipe; this behavior remains an open completion item,
not a claim that all material combinations work. Unknown prior history remains
explicit; incoming-only temperature cannot certify clearance of unknown residue.
Full backend suite passes 366 tests (`builtin-transition-ranges.xml`).

Generic swap policy regression: 366 backend tests pass (`generic-swap-policy.xml`),
including a load plan with a 225 C spool printing maximum selecting 240 C from
the generic transition range. Deployed in r89; physical mixed-material
qualification remains pending.

## Purge amount ownership — 9 November

OrcaSlicer and the user own purge calibration. WM+ must consume the applicable
configured transition purge when supplied and avoid duplicate sliced purge.
Manual Load currently has no Orca project context and uses `[wm_material]`
`load_purge_mm` (default 50 mm). This is a configurable fallback, not a universal
transition calibration. Keep gear-to-nozzle feed distance separate. The remaining
slicer handoff and unit/mapping requirements are tracked in the current
[completion checklist](standalone-completion.md#purge-ownership-and-remaining-handoff--9-november).

## Cross-family purge fallback and future guided G-code swaps — 9 November

`[wm_material] cross_material_purge_mm` configures purge length in mm of input
filament for different material families, mixed-family residue, or unknown prior
residue. It replaces, rather than adds to, the normal `load_purge_mm` amount.
When omitted it inherits `load_purge_mm`, preserving existing behavior without
inventing a calibrated cross-material value. Both settings accept 1–300 mm.
PLA/PLA Matte/PLA Silk share a family; PETG/PCTG, ABS/ASA and PA6/PA12 remain
distinct. Feed-to-nozzle distance is independent. Selected purge amount/source
are part of the reviewed plan and its token; changing the amount invalidates an
old review. This implementation is deployed as r111; live Klipper settings confirm the
inherited default and existing filament records survived installation.

The purpose of the Orca handoff includes future manual filament swaps requested
from G-code. Such a request should enter the existing guided paused swap flow,
show the requested incoming material, brand and color when the G-code explicitly
provides them, and identify the target physical head through the current print
mapping. Missing information must remain unknown and editable rather than
guessed from a tool number. A generic pause alone does not establish an incoming
filament identity. Reuse paused origin preservation and completion-gated resume;
never home Z during the swap. Cancellation/failure must leave the print paused.

A transition-specific purge supplied by the slicer should take precedence over
the WM+ family fallback. Preserve explicit zero, units and accounting for purge
already emitted in the file. Do not also run that same purge in the guided flow.
If no applicable slicer value is available, choose `cross_material_purge_mm` for
cross/unknown residue and `load_purge_mm` for same-family residue. The G-code
contract/parser and guided request entry point remain future work; ordinary
metadata editing must not trigger a swap, motion, heating or automatic resume.

### Recovery priming configuration (local implementation)

`[wm_material] recovery_purge_mm` sets the standalone power-loss recovery prime
in mm of input filament (1–300), defaulting to `load_purge_mm`. It does not change
manual-load feed distance, cross-material purge policy or the slicer's transition
purge settings. The recovery path remains undeployed pending complete return and
continuation integration and physical qualification.

`[wm_material] recovery_clearance_mm` sets the required recovery gap (1–50 mm,
local default 10 mm). Admission subtracts the durable highest deposition ceiling
and the span of all four calibrated head Z offsets from the actual positive-Z
endstop position. The default is not a physically qualified clearance guarantee.
A missing/mismatched envelope or insufficient gap blocks preparation; saved nozzle
height and axis maximum are not substitutes. This setting does not enable Z
homing for ordinary Load/Unload.


### Existing stock settings and filament

When `wmp_filaments.json` is absent, the helper reads material and colour from
`tmt1.ini` and resolves logical slots through `box_modify_t0..3`. Exact
`; orca-colorN=#RRGGBB` annotations take precedence over solid palette colours.
Conflicting slot identities and textured colours without an exact annotation
remain unset. The first filament save preserves all imported head records;
an existing WM+ settings file remains authoritative. On first installation,
when neither WM+ identity nor loaded-state files exist, settled sensor readings
adopt the loaded state of valid stock head records while idle. This happens only
once, including when every configured head is empty. Existing WM+ loaded-state
records are never replaced by this adoption.

An idle head's filament properties can be edited even while loaded. Use
**Load** or **Unload** to change filament; saving its properties does not load
or unload it.

A successful **Save** closes the filament or nozzle editor and returns to its
calling screen. **Back** leaves without saving, with an unsaved-change notice
when applicable. A failed save keeps the editor open and reports the error.
Opening Nozzle Type from General keeps the editor on that screen, so closing it
does not navigate to Toolheads or change the selected toolhead.
