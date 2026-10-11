# Preserve head configuration when communication fails

A communication timeout means Klipper has lost contact with a controller. It does
not establish that a physical head was intentionally removed. Treating these as
the same event caused the 2026-10-10 one-head configuration incident.

## Evidence from the printer

The kernel recorded a fault on the upstream USB hub at monotonic time
1763663.791: `disabled by hub (EMI?), re-enabling...`. The CAN adapter and the
other USB devices under that hub disconnected and re-enumerated. Klipper first
logged `Network is down`, then head T2 timed out, followed by the other
controllers. The vendor labels that T2 timeout `ZRU-B005`; despite the label's
multi-material-unit wording, it is raised by the normal T2 MCU timeout handler,
not an openACE-specific fault.

The owner also reports similar faults occurring randomly during normal printing,
so the underlying transport issue cannot be attributed only to update/restart
operations. The retained kernel history contains seven instances of the same upstream-port
disable warning. USB topology confirms that the CAN adapter, camera, and a
downstream serial/storage hub share this path. This was a real, bus-wide transport
interruption. It suggests investigation of
USB hub power, connections, and signal integrity/interference, but does not
identify a failed component. In [Linux 5.10 hub.c](https://github.com/torvalds/linux/blob/v5.10/drivers/usb/core/hub.c#L5081-L5095),
the diagnostic is emitted for an unexpectedly disabled port; the EMI wording
is a possible explanation, not a measurement proving electromagnetic interference. It also does not establish that WM+ or openACE
caused the hub reset. Current zero CAN error counters cannot rule out earlier
faults: the interface was recreated. Later disconnects of only the CAN adapter
coincide with controller restart/setup operations and its temporary USB serial
bootloader enumeration; those are a different pattern from the upstream-hub event.

The vendor client compounded the timeout by clearing head UUIDs 1–3, copying
printer1.cfg, deleting saved calibration sections for excluded heads, and setting
all persistent head counts to one. Its later CAN query failed with no can0 device,
yet it accepted the stale count. The callback was scheduled twice in overlapping
log entries. See the [firmware incident record](firmware-1.1.13.md).

## Restoration completed

The printer's original four UUIDs were restored from the corrected 2026-09-14
snapshot after matching head 0 and checking that three saved snapshots agreed on
the complete physical order. Fresh backups of the damaged state were saved under
ignored `analysis/head-restore-20261010/` before writes. Existing tool offsets and
the current SAVE_CONFIG calibration were preserved; only UUID fields and the
three head-count records were repaired. The reviewed 1.1.13 WM+ configuration
was reapplied with the vendor client temporarily stopped.

The first firmware restart could not configure a previously excluded controller
that was still in shutdown. A second restart, now addressing all restored heads,
cleared that state. Klipper returned Ready with four extruders and openACE loaded.
The vendor client was restarted with all four existing 1.1.13 preload patches,
and all head-count records remained four. The collision detector is configured;
it has no get_status method and therefore is not listed by Moonraker's object
status API. Preflight now checks its loaded config section instead.

No homing, tool pickup, extrusion, or print was commanded as part of restoration.
Print/tool-change validation is separate from configuration and connection checks.

## First guard: block destructive automatic reset

`client-preload/head-config-guard/wmp_head_config_guard.c` is a locally tested
prototype. It redirects the vendor's `unlock_extruder` callback to a handler
that records the communication fault without changing physical configuration.
It uses the reviewed whole-file hash and verifies all 2016 loaded callback bytes
before installing the jump. Profiles cover 1.1.08, 1.1.12, and 1.1.13. Modified or
unknown clients are rejected. The usual preload installer discovers the library;
status reads `/tmp/wmp_head-config-guard.log`.

The guard does not suppress MCU shutdowns, claim missing hardware is present,
restart controllers, home axes, or resume a print. Resolve the cause, then restart
Klipper deliberately. A real disconnected head still prevents normal operation.
Explicit operator configuration of genuinely changed hardware remains separate.
The guard was installed on this printer on 2026-10-10 after native preflight
and its three local compatibility tests passed. The running 1.1.13 client logged
successful application. Reading its live callback entry confirmed the 16-byte
jump and that its target lies in the loaded guard library. After the vendor
startup sequence completed, Klipper was Ready and idle with four heads and zero
extruder heater targets. The previous libraries and service override, plus
verification evidence, are retained in ignored
`analysis/deploy-head-guard-20261010/`.

No communication fault was deliberately induced. Behavior when an actual fault
invokes the guarded callback remains to be observed during normal operation.

## Remaining work for complete non-destructive recovery

1. Keep a printer-specific, validated hardware manifest with the intended UUID
   order and last-good calibration. Physical topology is operator configuration,
   not a value to infer from a timeout.
2. Capture USB/CAN state, affected MCU, and recent logs before any retry. Distinguish
   one head timing out from the whole adapter or hub disappearing.
3. Harden vendor startup/discovery separately. A query for **unassigned** CAN nodes
   is not a count of all heads: it can report zero while Klipper already owns four
   working controllers. Failed or incomplete discovery must not replace the
   configured topology, even if it sees a smaller positive count.
4. Permit only a bounded, explicit restart while idle, after the interface is up
   and the cause is resolved. Revalidate every configured MCU before Ready. If a
   print was interrupted by an MCU shutdown, position is untrusted; do not treat
   reconnection as permission to resume, home over a part, or continue extrusion.
5. Require explicit operator confirmation for an intentional head-count change.
   Never erase identities or calibration to make a communication error disappear.

The prototype covers the observed destructive callback. It does not yet guard
all writes made by vendor discovery scripts or the firmware installer, so it is
not a complete recovery system.

## USB/EMI follow-up with board photos

The supplied photographs are of a ZR screen board, marked WM-ZR-M V1.0 and
TM T1 V2.3.1 (20250716), not a confirmed photograph of this Ultra's board. They
show an RK3308B SoC, Winbond memory, an FN-Link F89FTSM13 radio module, power
conversion sections, and a lower multi-pin connector labelled with USB D+/D−
pairs, grounds, 5V and VIN. These labels identify useful inspection points; they
do not prove the Ultra uses the same board or locate the failing hub conclusively.
VIN must not be assumed to be the same rail as the labelled 5V pin.

Read-only sysfs inspection of the actual printer found:

- The affected upstream hub is 1a40:0801; its children include the STM32F407 CAN
  bridge, the UVC camera, and a Genesys Logic 05e3:0610 downstream hub containing
  the USB serial device and flash drive.
- All exposed USB over-current counters are zero.
- The root controller and both hubs allow runtime PM (`auto`), but report zero
  accumulated suspended time. The CAN bridge has runtime PM set to `on`.
- Hubs advertise self-powered configurations. These are USB descriptors, not
  measurements of supply isolation or voltage stability. The camera advertises
  500 mA maximum consumption; this is not its measured current draw.

These observations make recorded over-current trips and recent runtime suspend
less persuasive explanations. They do not rule out brief supply dips, connector
faults, signal-integrity problems, or interference. Kernel/controller firmware
bugs also remain possible. The upstream-port warning means a connected port lost
its enable state; the kernel's EMI wording is a hypothesis rather than an EMI
measurement. A pure host scheduling delay would not by itself explain the recorded
hub-wide disconnect/re-enumeration sequence.

The photographed FN-Link module uses SDIO and 2.4 GHz Wi-Fi according to
[the manufacturer's specification](https://de.fn-link.com/FG89FTSM13-W3-Wi-Fi-Modul-pd44926760.html).
It is not a USB child merely because it occupies the same board. Its presence and
antenna routing do not prove that Wi-Fi transmission is causing the resets.

Suggested investigation order, without changing hardware while printing:

1. Identify the actual Ultra board, hub location, power path, and upstream USB
   cable/connector. Inspect and reseat accessible connections with power removed.
2. Log hub-reset events persistently and correlate them with motor activity,
   heater switching, camera use, and peripheral insertion/removal.
3. Run controlled peripheral-isolation trials, one change at a time: remove an
   unused flash drive and compare operation with camera streaming disabled. An
   improvement narrows candidates but does not by itself separate current draw,
   traffic, and interference.
4. If available, measure the relevant 5V supply at the hub and screen board with
   an oscilloscope during operation. Average multimeter readings can miss brief
   disturbances. Confirm pin roles and grounds before probing; no blind power
   injection or assumptions about VIN.

No USB power-management settings, Wi-Fi settings, or hardware wiring were changed
by this follow-up. Read-only results are retained in ignored
`analysis/head-restore-20261010/usb-power-settings.json`.
