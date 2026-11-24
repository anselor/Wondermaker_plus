# Standalone mount/dock cancellation

Local implementation on `work/r4-print-time-fixes`. Printer installation and
supervised physical qualification remain outstanding.

## Admission and execution

`wmp/toolhead/cancel` records intent on the reactor without the G-code mutex.
It requires the current operation's session, request ID, head and action, an
unchanged command generation and manager identities, and running state. It does
not move, change temperatures, disable motors, or enqueue a G-code Cancel.

The admitted callback retains its original operation object and immutable
binding. Only its executing greenlet observes the request through the shared
`check_operation_boundary` helper. A callback from a different greenlet cannot
consume the request. Changed ownership prevents further service work and removes
cleanup authority. An old callback cannot rewrite a replacement operation.

Mount and dock still call `_CHANGE_TOOL` and `PARK_CURRENT_TOOL`. Their shared
stop points and homing boundaries are reused; no second coupling implementation
is introduced. LOCK/UNLOCK strokes, mandatory release retreat and attachment
bookkeeping finish before observation. Heater waits on the executing service
path observe cancellation once per existing one-second poll, including ordinary
paused-print repair. Unrelated waits retain vendor behavior.

## Cancellation outcome

Before dispatch, Cancel produces a refused/not-started receipt without any
hardware command. After dispatch, cancellation drains accepted motion with M400
under the G-code mutex, rechecking ownership before and after the drain. It holds
position and publishes an unknown outcome with a held cancellation receipt.
Attachment verification remains available through the existing recovery action.
There is no inferred attachment, automatic park, pickup retry, offset guess,
heater-target change, or motor disable. Existing paused-print heater targets and
physical coordinate frame are retained. Verification does not retire a real
stock toolhead fault; that fault must be resolved first.

Sensor, shutdown, quick-stop and print-cancellation faults take precedence over
Cancel. Failure while draining or loss of cleanup ownership does not claim a
confirmed hold. Restarted interrupted receipts retain the existing unknown and
attachment-reconciliation behavior.

## Screen and transport

The current mount/dock progress header reuses the filament procedure Stop control
and existing procedure transport. There is no new thread, status query or poll.
It is enabled only with fresh, matching operation identity/action/session and
`toolhead_cancel_protocol=1`. Old helpers do not get a queued-G-code fallback.
The HTTP whitelist permits only the exact endpoint with the existing 2 KiB bound.

A lost initial HTTP response does not authorize repeating a mount/dock command.
A fresh matching running receipt restores pending state and the Stop control.
Changed or stale receipts cannot enable it. Cancellation remains pending until
the backend reports a terminal result; HTTP acceptance alone is not completion.

## Qualification

Host tests cover pre-dispatch cancellation, both actions at shared boundaries,
foreign callbacks, identity/session/generation/manager replacement, real faults,
cleanup invalidation, retained stock G-code dispatch, heater-wait stopping,
protocol and freshness gates, exact HTTP routing and lost-response readback.
Native LVGL tests exercise the existing header control and its event binding.

Required later on the printer: cancel before dispatch, between axes, after a
complete old-head dock, before/after wiping and during a paused heater wait;
verify no mid-stroke interruption, no unwanted park/driver disable/temperature
change, correct frame and attachment reconciliation. These are not claimed by
host tests. No printer access or push is part of this change.

Local results: broad material/Home/calibration backend regression 1,769 passed,
2 skipped (three pre-existing empty-regex assertion warnings). The final focused
toolhead batch passed 120 checks, including retained stock dispatch, bounded
heater waits and cleanup ownership races. Native lifecycle/standalone delivery/
hook/profile checks passed 5 tests; final standalone delivery rerun passed 1.
Exact localhost HTTP endpoint test passed 1; shared macro checks passed 35.
Package qualification is recorded in the repair tracker when the final delivery
export is validated. These results do not replace supervised physical testing.
