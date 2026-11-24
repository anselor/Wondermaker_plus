# Filament service stops between physical stages

Local implementation on `work/r4-print-time-fixes`; offline qualification complete; physical qualification pending. No printer access, installation or supervised motion qualification.

## Shared ownership and observation

Load/unload already uses a session/id/head-bound out-of-band Cancel endpoint.
Its command now carries an execution scope containing the exact operation
object, session, request, head, command generation, manager identities and
command greenlet. The common operation-boundary observer recognizes this
scope alongside existing calibration and managed-print owners. An unrelated
reactor greenlet cannot consume its Cancel. No component is instantiated,
journal written, or status requested by the idle observation path.

The running command remains the cleanup owner. A replacement request, manager,
session or generation cannot receive the old request's heater or motion cleanup.
Ownership is checked again after the cleanup M400, which can yield. A tagged
shared tool fault that retires exactly its own next generation retains this
same operation's cool-down authority, without clearing the fault or relabeling
it as Cancel. The actual error remains primary.

A stop raised through a nested G-code handler uses Klipper's normal command
error with a typed cancellation marker. The service recognizes that marker at
its outer cleanup boundary. A regression runs the retained stock dispatcher to
prove normal Cancel does not become an internal-error shutdown.

## Physical boundaries and coordinate frames

Preparation now checks before and after complete docking, before pickup, after
pickup bookkeeping, before service positioning and after position/offset
restoration. The existing shared XY helper checks between native axis homes.
The same preparation implementation covers returning to the original paused
head, with its existing return-stage prefix.

Lock/unlock strokes, required retreat and sensor checks remain uninterrupted.
A real docking or pickup fault is checked before observing a pending Cancel.
After pickup, active extruder, saved head and head-relative coordinate offset
are reconciled with MOVE=0 before a new stop point can run. Purge travel then
uses the machine frame and restores the selected frame before the next stop
point. A cancelled mount therefore cannot continue to purge or leave a newly
attached head with the empty-carriage bookkeeping/frame.

No homing, synthetic position, Z travel, automatic docking or XYZ motor-disable
command is added to cancellation cleanup. The existing M400/selected-heater-off
receipt still distinguishes confirmed stopping from an unknown outcome.
The new scope and stop points do not take over openACE/AFC workflows.

## Qualification and remaining work

Focused tests cover Cancel during XY homing, after docking, after completed
pickup bookkeeping and after positioning; they check no later stage runs and
verify the held head/frame. Other tests cover foreign reactor actors, replacement
operations before and during cleanup, tagged coupling faults, original error
precedence, normal command-error dispatch and paused/cross-head service results.
The synchronous material harness injects actor identity explicitly; it does
not pretend to run a real Klipper greenlet scheduler.

The first full material run exposed twelve private-call fixtures without the
session/request records that real admission creates. Those fixtures now supply
explicit records; the affected fifteen parametrized cases pass. The final material/shared-boundary/Home/calibration regression batch passed
1,701 tests, with 2 skips and 3 pre-existing empty-regex assertion warnings.
The retained-dispatcher test confirms no internal-error shutdown for a nested
normal Cancel. The ARM build completed (unchanged native UI SHA256
`9b3dcc51b6340cb056e0bb02854d4dbf1464c35c90a716ae050c8f173a2ca69d`);
the delivery export verifies its updated backend bindings against the exact
stock client. Matching package/installer checks passed 244 tests, and the source seal is current.

Still open: attended physical qualification and remaining unmanaged operation
entry paths. Standalone mount/dock Cancel admission/UI is now covered by
`2026-11-19-standalone-toolhead-cancel.md`. Raw top-level G28 is covered
by `2026-11-19-raw-home-ownership.md`. Existing load/unload UI Cancel and
its endpoint are reused; no extra progress screen or polling loop is introduced.
