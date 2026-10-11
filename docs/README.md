# Documentation

Start with the [project README](../README.md) for compatibility, connection settings,
and installation.

## Guides

| Guide | Read it when you want to… |
|---|---|
| [Printer configuration](../config/README.md) | Install config, preserve calibration, or understand changed macros |
| [Touchscreen in Fluidd](touchscreen.md) | View and control the physical screen from your browser |
| [Touchscreen patches](../client-preload/README.md) | Check Wi-Fi, fan, recovery, or openACE patch behavior |
| [Power-loss recovery](print-mesh-recovery.md) | Understand what recovery restores and what it cannot guarantee |
| [Resonance tools](../utils/README.md) | Measure vibration and tune input shaping |
| [OrcaSlicer print options](orca-print-dialog-integration.md) | Set bed-leveling and timelapse behavior from the slicer |

## Firmware comparisons

The current configuration targets [System 1.1.13](firmware-1.1.13.md).
[1.1.12](firmware-1.1.12.md) and [1.1.08](firmware-1.1.08.md) describe earlier
integrations. Test counts and deployment results in those records belong to the
dates shown; they are not current installation instructions.

## Design and test records

- [Tool-change return](toolchange-return.md): sequence, coordinate handling, and tests.
- [Start-print review](start-print-review.md): startup behavior and proposed optimizations.
- [Bottom-Z investigation](z-recovery-investigation.md): measurements behind the recovery design.
- [Cooling experiment](cooling-assist.md): measurements that led to its removal.
- [Earlier design ideas](design-ideas.md): implemented, deferred, and removed proposals.

Some records link evidence under `analysis/`. Those files are local and are not
included in a normal checkout.

[Documentation and message audit](communications-audit.md) records the October 2026
wording changes, checks, and protocol text that must stay exact.
