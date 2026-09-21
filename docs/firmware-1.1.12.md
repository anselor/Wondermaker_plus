# System 1.1.12 integration

Wondermaker System 1.1.12 was analyzed and reconciled on 2026-09-21 against
the integrated 1.1.08 baseline. The encrypted vendor archive was decrypted
with the existing XOR/AES tooling; Debian metadata confirms version 1.1.12.
No vendor installer or printer deployment was run during this analysis.

## Package inventory

The official ZIP SHA-256 is
`c8a37467bdea43ab3d96afd3b53f794f12291a8834d0aa3bcc73e16fff39556f`.
The encrypted payload is
`629da5d07872de15b44e657ee48d1e14202afbf68104dae9a499e13888afd200`,
the decrypted Debian package is
`c56ab4d258d367ad34360f67808b470d3ab1c7546a98a67639a626b6e5ec7e44`,
and the client is
`574dc00926c8448b43e47c98bd988159892e6d5ba33f8b187ad04909dd1198ae`.

Compared byte-for-byte with 1.1.08, the payload changes only:

- `TM_T1/bin/client` (61,340,144 to 61,340,216 bytes);
- factory and installed `zru-s.cfg`, re-enabling Door_button1/2 on PA7/PB7;
- removal of a stray packaged `save_variables.cpython-312.pyc` cache file;
- package version metadata from 1.1.08 to 1.1.12.

All Klipper source, macros, other configuration, touchscreen assets, MCU
firmware, update scripts, and service files are otherwise byte-identical.
The stock baseline archives `stock_1.1.08` and adopts the door registrations;
live adopts the same explicit vendor reversal. Their handlers remain empty.

## Client changes

Symbol sizes and Ghidra decompilation identify seven changed application
functions. The release:

- records the physical tool that caused a filament runout/tangle and uses it
  in the warning and resume checks, instead of relying on a later current tool;
- validates the global pause temperature and falls back to the faulting tool's
  saved resume temperature when it is below 175 C;
- carries that fault-tool state through G-code response parsing and popup text;
- sets `is_print_from_screen = true` when power-loss recovery starts;
- fixes the second barcode scanner path by adding `/by-id/`.

The power-loss checkpoint writer and loader retain their behavior and sizes.
The writer still serializes compensated `toolhead.position` XYZ and recovery
still reuses those values as G-code coordinates. Setting `is_print_from_screen`
does not address that coordinate-space mismatch, so recovery-fix remains
required. Its writer/loader/start guards were revalidated against 1.1.12,
including the 16-byte recovery-start addition.

The Wi-Fi event logic and air-filter request logic are semantically unchanged
but relocated by the relink. wifi-fix, fan-fix, and recovery-fix now retain
their 1.1.08 profiles and add exact 1.1.12 ELF/function/address profiles. Each
continues to fail closed on an unknown or modified executable.

## Validation and limits

Offline tests compile the real preload sources, recognize both reviewed
clients, reject modified binaries, validate every Wi-Fi branch target, verify
the fan callback site and sender prologue, and emulate recovery coordinate
loads. The complete project suite also checks the unchanged config and recovery
contracts; 139 tests pass. Hardware checks remain necessary after installing 1.1.12: Klipper
startup with the restored door pins, ABS filter automatic/manual behavior,
Wi-Fi failure recovery, and a newly created power-loss checkpoint/resume.
