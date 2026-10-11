# System 1.1.12 comparison

This is the September 21, 2026 integration record. Current WM+ configuration
requires [1.1.13](firmware-1.1.13.md); use the [project README](../README.md) for
installation.

Compared with 1.1.08, 1.1.12 mainly changes touchscreen runout/resume handling.
It also re-enables two door-input registrations with empty handlers. The Wi-Fi,
fan, and recovery-coordinate faults remain in the reviewed paths, so WM+ keeps
those fixes and adds profiles for the relocated code.

The package was decrypted and extracted for comparison. No vendor installer
or printer deployment ran during this analysis.

## Package differences

Only these payload items changed:

- `TM_T1/bin/client`: 61,340,144 to 61,340,216 bytes.
- Factory and installed `zru-s.cfg`: re-enable Door_button1/2 on PA7/PB7.
- Remove a packaged `save_variables.cpython-312.pyc` cache file.
- Package version metadata.

Other Klipper source, macros, configuration, screen assets, MCU firmware,
update scripts, and services are byte-identical. WM+ stock/live configurations
adopt the door registrations. The earlier stock baseline is archived separately.

## Touchscreen behavior

Decompilation and symbol-size comparison identify seven changed application
functions. The client now:

- Records which physical head caused a runout/tangle and uses it in warnings
  and resume checks, rather than relying on whichever head is current later.
- Falls back to that head's saved resume temperature when the global pause
  temperature is below 175°C.
- Carries the faulting-head information through response parsing and popups.
- Sets `is_print_from_screen=true` when recovery begins.
- Adds `/by-id/` to the second barcode-scanner path.

The recovery writer still saves compensated `toolhead.position` XYZ and reuses
it as G-code XYZ. The new screen-origin flag does not fix that mismatch;
`recovery-fix` remains required. Its checks include the 16-byte recovery-start
addition. Wi-Fi and filter-fan logic retain their behavior at new addresses.

## Local validation

The recorded full suite passed 139 tests. Checks recognized reviewed clients,
rejected altered files, verified Wi-Fi branches and fan hook instructions,
and emulated recovery coordinate loads. New firmware still required printer
checks for startup with the door pins, ABS fan choices, Wi-Fi reconnection,
and a newly written recovery checkpoint.

## Artifact fingerprints

| Artifact | SHA-256 |
|---|---|
| Official ZIP | `c8a37467bdea43ab3d96afd3b53f794f12291a8834d0aa3bcc73e16fff39556f` |
| Encrypted payload | `629da5d07872de15b44e657ee48d1e14202afbf68104dae9a499e13888afd200` |
| Debian package | `c56ab4d258d367ad34360f67808b470d3ab1c7546a98a67639a626b6e5ec7e44` |
| Screen client | `574dc00926c8448b43e47c98bd988159892e6d5ba33f8b187ad04909dd1198ae` |
