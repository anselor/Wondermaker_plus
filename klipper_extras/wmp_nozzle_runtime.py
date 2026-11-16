# SPDX-License-Identifier: GPL-3.0-or-later
"""Live host-side nozzle geometry; no vendor source changes or printer restart."""
import math


def active_settings(printer, settings):
    """Copy only nozzle sections; configfile.settings is a startup snapshot."""
    result = dict(settings)
    for head in range(4):
        name = 'extruder' + (str(head) if head else '')
        diameter = getattr(printer.lookup_object(name, None), 'nozzle_diameter', None)
        if type(diameter) in (int, float) and math.isfinite(diameter) and diameter > 0:
            result[name] = dict(settings.get(name, {}), nozzle_diameter=diameter)
    return result


def runtime_changes(extruder, diameter, explicit):
    """Match PrinterExtruder's constructor defaults, preserving explicit limits."""
    before = {key: getattr(extruder, key, None) for key in (
        'nozzle_diameter', 'filament_area', 'max_extrude_ratio', 'max_e_velocity', 'max_e_accel')}
    if any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in before.values()):
        raise ValueError('Live Klipper nozzle geometry is unavailable')
    if not math.isfinite(diameter) or not 0 < diameter <= 2 * math.sqrt(before['filament_area'] / math.pi):
        raise ValueError('Nozzle diameter exceeds the configured filament diameter')
    scale = (diameter / before['nozzle_diameter']) ** 2
    changes = {'nozzle_diameter': diameter}
    for option, field in (('max_extrude_cross_section', 'max_extrude_ratio'),
                          ('max_extrude_only_velocity', 'max_e_velocity'),
                          ('max_extrude_only_accel', 'max_e_accel')):
        if option not in explicit:
            changes[field] = before[field] * scale
    if any(not math.isfinite(value) or value <= 0 for value in changes.values()):
        raise ValueError('Calculated nozzle extrusion limits are invalid')
    return changes


class NozzleRuntime:
    def __init__(self, printer, saved):
        self.printer, self.saved = printer, saved
        self.pending, self.errors, self.timer = {}, {}, None

    def supported(self, name):
        extruder = self.printer.lookup_object(name, None)
        try:
            runtime_changes(extruder, getattr(extruder, 'nozzle_diameter', 0), {})
            return callable(getattr(self.printer.lookup_object('toolhead', None), 'flush_step_generation', None))
        except ValueError:
            return False

    def prepare(self, name, diameter):
        config = self.printer.lookup_object('configfile').get_status(
            self.printer.get_reactor().monotonic())
        return runtime_changes(self.printer.lookup_object(name), diameter,
                               config.get('config', {}).get(name, {}))

    def busy(self, now):
        printer = self.printer
        state = printer.lookup_object('print_stats').get_status(now).get('state')
        paused = printer.lookup_object('pause_resume').get_status(now).get('is_paused', False)
        sd = printer.lookup_object('virtual_sdcard')
        recovery = printer.lookup_object('wmp_recovery', None)
        calibration = recovery.get_status(now).get('calibration_active', False) if recovery else False
        return state not in ('standby', 'complete', 'cancelled', 'error') or paused or sd.is_active() or calibration

    def committed(self, name, diameter, now):
        self.errors.pop(name, None)
        extruder = self.printer.lookup_object(name)
        if abs(extruder.nozzle_diameter - diameter) < .000001:
            self.pending.pop(name, None)
            return
        self.pending[name] = diameter
        try:
            if not self.busy(now):
                self._apply_pending()
            else:
                reactor = self.printer.get_reactor()
                if self.timer is None:
                    self.timer = reactor.register_timer(self._tick, now + 1.)
                else:
                    reactor.update_timer(self.timer, now + 1.)
        except Exception as error:
            self.pending.pop(name, None)
            self.errors[name] = str(error)

    def _apply_pending(self):
        # Called only by the saving command or the timer under the gcode mutex.
        for name, diameter in list(self.pending.items()):
            try:
                if self.saved(name) != diameter:
                    raise ValueError('Saved nozzle settings changed before application; reopen the editor')
                changes = self.prepare(name, diameter)
                self.printer.lookup_object('toolhead').flush_step_generation()
                extruder = self.printer.lookup_object(name)
                before = {field: getattr(extruder, field) for field in changes}
                try:
                    for field, value in changes.items():
                        setattr(extruder, field, value)
                except Exception:
                    for field, value in before.items():
                        setattr(extruder, field, value)
                    raise
                self.errors.pop(name, None)
            except Exception as error:
                self.errors[name] = str(error)
            finally:
                self.pending.pop(name, None)

    def _tick(self, now):
        reactor = self.printer.get_reactor()
        try:
            if getattr(self.printer, 'is_shutdown', lambda: False)():
                self.pending.clear()
                return reactor.NEVER
            with self.printer.lookup_object('gcode').get_mutex():
                if not self.busy(now):
                    self._apply_pending()
        except Exception as error:
            self.errors.update({name: str(error) for name in self.pending})
            self.pending.clear()
        return now + 1. if self.pending else reactor.NEVER
