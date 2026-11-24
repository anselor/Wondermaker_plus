# Deferred filament service homing

A completed PA print was followed by three Head 3 Load attempts that failed at
Home X/Y with "Wait for the current physical service before standalone homing".
The printer was Ready, its print was complete and SD inactive, and axes were
unhomed. The filament worker itself was the active physical service.

Filament execution is deferred to a reactor callback after its admitting G-code
command returns. There is no longer an outer dispatcher frame on that stack.
The raw G28 wrapper incorrectly treated the service's own homing as a competing
standalone Home and rejected it. Previous raw-home coverage used nested macro
calls and missed this deferred-worker shape.

The wrapper now permits an active physical service's G28 only when its existing
immutable service scope still owns the current actor, request, session, head,
command generation and external-owner bindings. It checks cancellation before
calling the unchanged original homing handler. It does not create a second Home
attempt. Competing/stale actors and pending services remain refused; existing
calibration/print/external-owner checks remain in their original order.

Tests use the retained stock G-code dispatcher and actual filament/toolhead
scope implementations, with no outer command frame. They cover standby and
completed prints, changed actor/session/generation/operation/provider bindings,
pending state and cancellation before homing. No hardware motion is needed for
this regression test. The unchanged native library is retained; its backend
runtime dependency manifest and sealed source package are refreshed after
verifying the native source build ID and artifact are unchanged.

## Results

- Affected raw-home, tool service, Home/cancel, material, stop-point and macro
  regressions: **2,488 passed**, with three existing empty-match warnings, in
  211.07 seconds using four xdist workers. An initial serial run was replaced by
  this completed run and is not counted as completion evidence.
- Package/source delivery and release-hygiene checks: **71 passed** in 41.30
  seconds. The native binary remains
  `d23fb96bea5346cbcf66119c08ed0b3c0cbefd03f94fa9b81f93ed10a2ff4129`.
- Installed through the managed installer with zero configuration file changes.
  Klipper returned Ready, native GUI/status synchronized (screen PID 153958),
  and both changed helper files matched local SHA256 values read back from the
  printer. All heater targets were zero and SD inactive.
- No physical homing or filament loading was commanded by this verification.
  The operator's actual Load retry remains the live acceptance check.

Logs: /tmp/wmp-service-home-regression-parallel.log,
/tmp/wmp-service-home-package-tests.log and /tmp/wmp-service-home-install.log.
The earlier 6,914-case full baseline belongs to the initial R4 release; it is
not represented as a fresh full-suite run on this follow-up.
