# R4 finish positioning and native UI refinements

Status: installed and scoped checks passed; not merged, pushed or tagged. Based on R4 ab18e32.

## Scope

Finish and Cancel share configurable physical-Z positioning: target Z125 mm,
minimum downward clearance 50 mm, capped at the configured bottom endstop.
User overrides survive repeated upgrades. A custom legacy fixed drop retains
its semantics; old package defaults migrate to the new controls. Persistent
and console configuration are documented in config/README.md.

After lowering drains, a homed and confirmed attached head parks beside the
left scrubber. Finish retains its existing XY-only wipe. Cancel adds no wiping,
extrusion, pickup or homing. A pending/pre-SD cancellation does not gain motion;
unknown attachment, coupling/fault flags and unavailable clearance skip parking.
The mesh is cleared before calculating the physical clearance and XY route.

Home uses the existing constructor refresh hook to attach its filament view
before first paint, retaining cached state across hidden navigation. A guarded
jump bypasses the stock filament-only refresh tail; temperature, fan, light and
GPIO work remains. This is a specific redundant-work removal, not evidence that
the intermittent printing CPU/stutter problem is solved.

About gains a native seventh list row for WonderMaker+, with a standard header
and Close action in the details view. Broader native UI replacement is deferred
to R5; see docs/roadmap/r5.md.

## Evidence so far

- Camera framing checked at physical Z25, Z50, Z60, Z75, Z77, Z100 and Z125.
  The user selected target Z125 and minimum drop 50 after viewing the positions.
- Positioning, migration, managed cancellation ordering and Klipper config
  validation: 200 passed. Existing finish/cancel macro subset: 29 passed.
- Actual frozen ARM Home refresh emulation: 12 passed, preserving all prefix
  calls and callee-saved registers while removing four stock filament updates.
- Earlier native widget lifecycle and factory-font header checks: 2 passed.
- Final ARM candidate built successfully, SHA256
  `cf4445717bfbb0f90c2632511f3200c67bd9ce12544240bb2951c00ad631038c`.
  Reviewed delivery staging created and screen package freshness check passed.

## Final checks and live acceptance

- Affected macro, material/cancellation and ARM hook regressions: **2,237 passed**
  with three pre-existing pytest warnings in 315.64 seconds.
- Final backend/light delivery package checks: **31 passed**.
- Calibration light policy, including open-door suppression and saved-preference
  restoration: **60 passed**.
- Final native lifecycle and factory-font header checks: **2 passed** in
  77.44 seconds, including first-row placement and explicit white label colours.
  No motion code changed with that UI revision.
- Initial install rejected a source change made while installation was running.
  Installer restored prior receipted component publications. The sealed retry
  completed successfully, with native GUI/status synchronization verified and
  Klipper Ready. No bed movement occurred during installation.
- Shared positioning helper accepted on the printer: bottom Z reference and XY
  home established normally, then physical Z50 -> Z125, ending X-13/Y275.
  E unchanged and all heater targets zero. Operator confirmed normal motion.
  This verifies the shared non-wiping helper, not a new full-print or Finish-wipe
  acceptance run. Evidence: analysis/finish-camera-ui-20261124/position-check.json.
- About details rendered with the standard title/Close header and concealed the
  stock contents. Native row text was initially dark; the correction explicitly
  sets white text and places WonderMaker+ first above the stock rows. Final live
  screenshot confirms readable white text and WonderMaker+ first above Device.
  Matching final installation completed with Klipper Ready and native GUI/status
  synchronization verified (screen PID 284768). Screenshot evidence:
  analysis/finish-camera-ui-20261124/about-first-row.jpg.

Calibration lighting forces the chamber light on during active calibration or
manual probe adjustment without saving a preference change. An open door
acknowledges attention requests; closing it does not restart the old signal.
This policy is tested locally; no new heated calibration was run for this batch.

Intermittent timing, CPU/stutter and USB disconnect attribution remain open
investigations. These refinements do not establish their cause or claim a fix.
