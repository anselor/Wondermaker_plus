# Raw G28 shares the Home cancellation owner

Local implementation on `work/r4-print-time-fixes`; offline qualification complete; physical qualification pending. No printer access, installation or physical qualification.

## Backend admission and unchanged motion

On Ready, `RawHoming` wraps the already-registered G28 handler. It retains that
handler and passes it the original parsed command object. Axis flags, P values,
line parameters and the vendor homing override are not reconstructed or
reordered. The adapter reuses the existing ticket-bound Home command owner,
selective heater ownership, out-of-band Cancel endpoint and held-position
cleanup. It creates no new motion implementation or cancellation flag.

Only an otherwise unowned top-level G28 acquires a new ticket. A bounded stack
inspection identifies the outermost actual `_process_commands` command in the
current greenlet. Nested macros, manager commands and homing_override recursion
keep their caller and original handler. A current print/paused print or external
manager retains its existing ownership. Pending calibration/service work or an
unresolved next-ticket Cancel prevents a competing standalone Home. If the
Python dispatcher context cannot be verified, installation is skipped and the
raw-ownership protocol is not advertised.

The G-code dispatcher is not hooked: no frame inspection runs for G1 or other
commands, and no polling or idle work is added. Registration is idempotent and
restores the old handler if replacement registration fails.

The Home attempt publishes validated axes and origin for presentation. A real
fault flag takes precedence over a simultaneous Cancel, leaving the fault and
an unconfirmed held outcome intact. Normal cancellation is observed only at
existing safe boundaries outside native G28's motor-disable error handler.

## Shared touchscreen control

The existing Home dialog observes a fresh, pending backend Home with matching
session/request/ticket. It sends no G28 and consumes no ticket. Cancel uses the
same dedicated transport and existing endpoint. The normal shared GUI status
snapshot supplies this observation; the dialog adds no HTTP status requests or
full-status copies on every idle tick.

A new backend Home replaces an old DONE pane without requiring dismissal first.
It can also replace a prior Home's lost-response wait when the server has
committed that same or a newer ticket to another request. The old request cannot
execute under the immutable ticket rules; no command is retried. Older snapshots
cannot retake the dialog. A non-Home local worker reservation remains intact.
Only fresh matching terminal status or a confirmed session change retires the
observed Home. DONE dismisses the dialog and sends no command.

## Offline evidence and remaining qualification

Tests run the retained stock G-code dispatcher, including traditional parameter
parsing, line-number input, macro recursion and actual normal command-error
handling. They cover parameter preservation, existing owners, pending-owner
refusal, cancellation, registration rollback and retirement of an older UI
request. Native lifecycle tests cover backend observation without extra G-code,
validation of fresh ownership, bound Cancel, DONE, a new Home over an old result,
older-snapshot rejection and a lost-response Home replaced by server authority.

Final expanded homing/calibration/checkpoint/scrub regression: 361 passed.
Native lifecycle/hook/profile qualification: 4 passed, with the final extended
lifecycle outcome run separately passing 1 test. Matching package/installer
checks: 248 passed. The source seal is current. ARM artifact SHA256:
`9a15b0841f1f33e38cb3d4f2e8f997ddc6b8fde4ed79c4144a8284c1c01c7a72`.
Device qualification remains open: console G28 and G28 Pn, each axis choice,
Cancel between native stages, UI replacement/reconnect cases and coexistence
with print/calibration/filament owners. Standalone mount/dock Cancel controls
are documented in `2026-11-19-standalone-toolhead-cancel.md`. No installation or push.
