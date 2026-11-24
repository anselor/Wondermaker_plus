# SPDX-License-Identifier: GPL-3.0-or-later
"""Keep stock print statistics across physical extruder coordinate changes.

Only ACTIVATE_EXTRUDER is observed. No movement, step-generation, PA, timer or
per-G-code-line hooks are added. Stock pause/resume and restored totals remain
owned by print_stats.
"""
import logging
from functools import wraps


def install(printer):
    gcode = printer.lookup_object('gcode')
    stats = printer.lookup_object('print_stats', None)
    if stats is None:
        return False
    if getattr(stats, '_wmp_tool_frame_accounting', False):
        return True
    commands = getattr(gcode, 'mux_commands', None)
    mux = commands.get('ACTIVATE_EXTRUDER') if isinstance(commands, dict) else None
    if not mux or mux[0] != 'EXTRUDER' or not mux[1]:
        logging.warning('WM+ filament accounting: extruder command is unavailable')
        return False
    originals = dict(mux[1])
    # Custom handlers may extrude, yield or change more than the E frame.
    # Leave those owners alone rather than discarding their work on rebase.
    if any(getattr(handler, '__name__', '') != 'cmd_ACTIVATE_EXTRUDER'
           or getattr(handler, '__self__', None) is None
           for handler in originals.values()):
        logging.warning('WM+ filament accounting: custom extruder handlers left unchanged')
        return False

    def wrap(original):
        @wraps(original)
        def activate(gcmd):
            now = printer.get_reactor().monotonic()
            if stats.print_start_time is not None and stats.last_pause_time is None:
                stats._update_filament_usage(now)
            try:
                return original(gcmd)
            finally:
                # The retained handler has now emitted activate_extruder and
                # gcode_move has adopted the incoming E coordinate frame.
                # Also rebase on a failed/no-op activation: no fictitious E
                # delta is introduced and stock errors still propagate.
                stats.last_epos = stats.gcode_move.get_status(
                    printer.get_reactor().monotonic())['position'].e
        return activate

    mux[1].update({key: wrap(original) for key, original in originals.items()})
    stats._wmp_tool_frame_accounting = True
    return True
