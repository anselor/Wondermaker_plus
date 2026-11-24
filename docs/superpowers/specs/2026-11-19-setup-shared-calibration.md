# Setup guide uses the shared calibration worker

Local implementation on `work/r4-print-time-fixes`; offline qualification complete; device qualification pending.
No printer installation, restart or motion tests under the current goal.

## Source evidence and route

The frozen 1.1.13 guide selects mesh, vibration, PID and offsets in four
`calibration_selected` bytes. It previously ran `check_auto_level`,
`check_sharper`, `check_pid` and `check_knife_pairing` separately, with its own
SAVE_CONFIG/restart and navigation handling. The Maintenance worker already
runs those same selected types through the bound command owner, shared cancel
transport, checkpoint writer and cleanup receipts.

`unified_guide_calibration_event` now handles Start and Skip before the vendor
handler. Four selection toggles retain the original handler. Start validates
the live control and printer admission, copies only the four selection flags
and enters the existing Maintenance worker/progress page. The selected initial
status is 1/4/7/10, verified against actual Maintenance branch instructions for
all 15 nonempty selection masks. No printer configuration is copied.

Accurate offset selection offers the same wire-brush/printed-blob choice. Its
confirmed click re-enters this guide Start handler and receives the same
session/request/ticket and sequenced commands as a Maintenance start. Cancel
uses the existing out-of-band connection and cleanup owner. No guide-specific
mount, dock, home, probing, heating or persistence code is introduced.

The new hook is at `0x50b7f8`; its first four instructions are a relocatable
stack prologue. Its window and the two data symbols are generated/verified
from the supported ELF. All 16 old guide command send sites are frozen calls
to the stock sender. They are now withheld, and direct navigation to the old
guide progress page cannot launch its unbound workers. Queued/running shared
work also prevents a legacy guide-navigation checkpoint from racing the run.

## Closing, Skip, retry and completion

DONE closes a shared result to the guide's calibration selection page. It
never marks onboarding complete. Another explicit Start revalidates admission
and obtains a new binding; it does not reuse an old failure/worker ticket.

The stock Skip handler deletes `need_oobe` immediately. The replacement does
not run that shell command: Skip uses the existing checked handoff to managed
filament setup, whose explicit Finish owns marker removal. An unresolved
operation must not be bypassed through either handoff or Finish. No automatic
restart, retry or setup completion is introduced.

Standalone owned stages use the new checkpoints/rollback. If openACE/AFC is
already present, that component retains the external owner's original save
policy; it does not install checkpoint mutation hooks. An owner change after a
standalone stage began still invalidates its publication authority.

## Qualification

Offline tests execute actual Maintenance selection instructions, verify the
entry prologue/call sites and reproduce the generated profile. Native tests
exercise all selection masks, ticketed dispatch, a real Cancel header and its
dedicated request, the shared brush choice, stale/hidden/disabled controls,
busy/refused starts, failed enqueue and marker-preserving Skip. Existing
Maintenance, checkpoint, scrub and hook-transaction checks remain required.

The final backend regression batch passed 528 tests. Native lifecycle, hook
transaction and profile-generation qualification passed 4 tests. The ARM build
completed with SHA256 `ed6bbfd99f0f38de86e4c1a5aadf63c25b3456c9d70a7e43f0581153ef1518a4`.

Device qualification remains open: first-run selection and surrounding page
layout, all selected-type combinations, shared brush/re-check controls,
Cancel during each type, final restart/result, retry after failure and the
explicit filament Finish/marker behavior. Local tests are not a physical
qualification claim.
