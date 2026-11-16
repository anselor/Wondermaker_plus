# SPDX-License-Identifier: GPL-3.0-or-later
"""Required source-side runtime dependencies; not an overwrite/install list.

Configuration files describe the matching baseline. Deployment must reconcile
printer-specific values, includes and SAVE_CONFIG rather than copying printer.cfg.
"""
RUNTIME_INPUTS = (
    'klipper_extras/wm_material.py',
    'klipper_extras/wmp_orca_profiles.py',
    'klipper_extras/wmp_nozzles.py',
    'klipper_extras/wmp_saved_variables.py',
    'klipper_extras/wmp_recovery_retirement.py',
    'klipper_extras/wmp_recovery_file_envelope.py',
    'klipper_extras/wmp_recovery.py',
    'klipper_extras/wmp_identification.py',
    'klipper_extras/wmp_case_light.py',
    'klipper_extras/wm_material.cfg',
    'config/live/macros.cfg',
    'config/live/change_macros.cfg',
    'config/live/offset_calibrate.cfg',
    'config/live/fz-wipe-nozzle.cfg',
    'config/live/printer.cfg',
    'config/live/case_light.cfg',
    'config/live/extruder0.cfg',
    'config/live/extruder1.cfg',
    'config/live/extruder2.cfg',
    'config/live/extruder3.cfg',
)
