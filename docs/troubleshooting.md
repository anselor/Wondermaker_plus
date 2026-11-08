# Troubleshooting

## Failed automated reset of MCU 'mcu'

This error was reported after a vendor System 1.1.13 upgrade. The USB–CAN adapter
briefly disconnected during the controller reset. Waiting for it to reconnect,
then running `FIRMWARE_RESTART`, returned that printer to Ready.

If this happens during setup, with no print in progress:

If you have not reapplied WM+ after the vendor upgrade, install the
[`preload` component](../client-preload/README.md#install-check-and-remove) before
another controller reset. Installation works while Klipper reports an error or
shutdown; it does not require getting Klipper Ready first.

1. Check that the printer still has its expected heads. If heads have disappeared,
   stop and check the [head-configuration notes](head-communication-recovery.md).
2. From an SSH session on the printer, run `ip link show can0`. Wait until `can0`
   is present and its flags include `UP`.
3. In Fluidd's console, run `FIRMWARE_RESTART` once. Check that Klipper returns
   Ready and all expected heads are present before printing.

If `can0` does not return, or the restart fails again, save `klippy.log` and the
output of `dmesg` for troubleshooting. This error alone does not establish that
a controller needs reflashing or that head identities need changing.

WM+'s head-configuration guard blocks the screen's destructive head-reset callback.
It does not repair the CAN connection or the MCU reset failure.

Source: [upgrade report #3](https://github.com/anselor/Wondermaker_plus/issues/3).
