# SPDX-License-Identifier: GPL-3.0-or-later
"""Stop points: end long operations early at known safe places after Cancel.

A pending managed print cancel (wmp_print_cancel) bound to the open job is the
stop request. Macros call _WMP_STOP_POINT at safe phases and open a stop-wait
region with _WMP_STOP_WAITS so vendor heat waits end within one poll. A stop
raises a G-code error that unwinds the job; the cancel cleanup then runs as for
any other cancel. Inert while openACE or AFC owns filament operations.
"""
import logging
import re


class StopPoints:
    STOP_POINTS = {
        "start_admitted": ("print start admitted", "not homed by this job; nothing moved or heated by this job"),
        "before_homing": ("before homing", "not homed by this job; heaters may be on"),
        "homed": ("after homing", "homed; probe head attached and locked"),
        "before_mesh": ("before bed mesh", "homed; probe head attached; bed mesh not yet measured"),
        "mesh_saved": ("after bed mesh", "homed; bed mesh saved; probe head attached"),
        "before_initial_tool": ("before first tool pickup", "homed; no tool picked up"),
        "initial_tool_ready": ("after first tool pickup", "first tool picked up and ready"),
        "purged": ("after purge", "first tool picked up; purge finished"),
    }
    STOP_ERROR_PREFIX = "Print cancellation requested; stopped "

    def __init__(self, material):
        self.material = material
        self._stop_waits = None
        self._wait_wrappers_installed = False
        self._stop_note_error_installed = False

    def install(self):
        """Register the stop commands and wrappers; called from klippy:ready."""
        gcode = self.material.printer.lookup_object("gcode")
        gcode.register_command("_WMP_STOP_POINT", self.material.cmd_STOP_POINT)
        gcode.register_command("_WMP_STOP_WAITS", self.material.cmd_STOP_WAITS)
        self.material._install_wait_wrappers()
        self.material._install_stop_note_error()

    def _stop_owner_present(self):
        printer = self.material.printer
        return any(printer.lookup_object(owner, None) is not None for owner in ("openace", "AFC"))

    def stop_requested(self):
        """Return the bound pending cancel for the open job, else None. No side effects."""
        material = self.material
        if not material._print_cancel_active() or self._stop_owner_present():
            return None
        live = getattr(material._cancellation(), "_print_cancel_live_binding", None)
        if live is None or live.get("session") != material.session_id:
            return None
        sd = material.printer.lookup_object("virtual_sdcard", None)
        stats = material.printer.lookup_object("print_stats", None)
        if sd is None or stats is None:
            return None
        if live.get("file") != stats.filename or live.get("handle") is not sd.current_file:
            return None
        return {"scope": "print", "cancel_id": live["cancel_id"]}

    def stop_waits_open(self):
        region = self._stop_waits
        sd = self.material.printer.lookup_object("virtual_sdcard", None)
        if region is None or sd is None or self._stop_owner_present():
            return False
        return (sd.current_file is not None and region["session"] == self.material.session_id
                and region["handle"] is sd.current_file)

    def _close_stop_waits(self, *args):
        self._stop_waits = None

    def _record_stop_point(self, phase, label, state):
        # Version 3 only adds stop_point to the version 2 record; stages stay.
        cancellation = self.material._cancellation()
        record = cancellation._print_cancel
        record["version"] = 3
        record["stop_point"] = {"phase": phase, "label": label, "state": state}
        cancellation._record_print_cancel()

    def check_stop_point(self, phase, label, state):
        if self.material.stop_requested() is None:
            return
        self._stop_waits = None
        try:
            # The journal reader rejects fields over 160 characters.
            self.material._record_stop_point(phase, label[:160], state[:160])
        except Exception:
            logging.exception("Unable to record stop point %s", phase)
        raise self.material.printer.lookup_object("gcode").error(
            "Print cancellation requested; stopped at " + label)

    def _stop_heat_wait(self, name, error):
        """Close the wait region, record the stop and return the error to raise."""
        self._stop_waits = None
        phase = ("heating_" + re.sub(r"[^a-z0-9_]", "_", name.lower()))[:48]
        try:
            self.material._record_stop_point(phase, ("heating " + name)[:160],
                                             (name + " wait interrupted; cleanup turns heaters off")[:160])
        except Exception:
            logging.exception("Unable to record stop point %s", phase)
        return error("Print cancellation requested; stopped while heating " + name)

    def _install_stop_note_error(self):
        """Record a stop-point unwind as a cancelled print, not a failed one.

        The SD worker reports the stop raise through print_stats.note_error(),
        which clears print_start_time, so the cleanup's later note_cancel() is a
        no-op and history would show an error. Only our stop texts with a live
        cancel still bound to this job (session, file, handle) are translated;
        stop_requested() is None with openACE/AFC present.
        """
        stats = self.material.printer.lookup_object("print_stats", None)
        if stats is None or self._stop_note_error_installed:
            return
        original = getattr(stats, "note_error", None)
        if not callable(original) or not callable(getattr(stats, "note_cancel", None)):
            return
        self._stop_note_error_installed = True
        def note_error(message):
            if (isinstance(message, str) and message.startswith(self.STOP_ERROR_PREFIX)
                    and self.material.stop_requested() is not None):
                return stats.note_cancel()
            return original(message)
        stats.note_error = note_error

    def _install_wait_wrappers(self):
        """Wrap the vendor heat waits so a pending cancel ends them within one poll.

        Only waits started while the stop-wait region is open are managed; the
        loops mirror PrinterHeaters (extras/heaters.py) so the vendor behaviour
        is unchanged when no cancel is pending.
        """
        if self._wait_wrappers_installed:
            return
        self._wait_wrappers_installed = True
        printer = self.material.printer
        pheaters = printer.lookup_object("heaters", None)
        gcode = printer.lookup_object("gcode")
        if pheaters is None:
            return
        material = self.material
        original_wait = getattr(pheaters, "_wait_for_temperature", None)
        if callable(original_wait):
            def wait_for_temperature(heater):
                if not material.stop_waits_open():
                    return original_wait(heater)
                if printer.get_start_args().get("debugoutput") is not None:
                    return
                name = heater.get_name() if callable(getattr(heater, "get_name", None)) else heater.name
                toolhead = printer.lookup_object("toolhead")
                gcode = printer.lookup_object("gcode")
                reactor = printer.get_reactor()
                if material.stop_requested() is not None:
                    raise self._stop_heat_wait(name, gcode.error)
                eventtime = reactor.monotonic()
                while (printer.quick_stop_flag == False and not printer.is_shutdown()
                       and heater.check_busy(eventtime)):
                    toolhead.get_last_move_time()
                    gcode.respond_raw(pheaters._get_temp(eventtime))
                    if material.stop_requested() is not None:
                        raise self._stop_heat_wait(name, gcode.error)
                    eventtime = reactor.pause(eventtime + 1.)
                if printer.quick_stop_flag:
                    gcode.respond_info("quick Stop, break")
            pheaters._wait_for_temperature = wait_for_temperature
        original = gcode.register_command("TEMPERATURE_WAIT", None)
        if original is None:
            return
        def temperature_wait(gcmd):
            if not material.stop_waits_open():
                return original(gcmd)
            sensor_name = gcmd.get("SENSOR")
            if sensor_name not in pheaters.available_sensors:
                raise gcmd.error("Unknown sensor '%s'" % (sensor_name,))
            min_temp = gcmd.get_float("MINIMUM", float("-inf"))
            max_temp = gcmd.get_float("MAXIMUM", float("inf"), above=min_temp)
            if min_temp == float("-inf") and max_temp == float("inf"):
                raise gcmd.error("Error on 'TEMPERATURE_WAIT': missing MINIMUM or MAXIMUM.")
            if printer.get_start_args().get("debugoutput") is not None:
                return
            if sensor_name in pheaters.heaters:
                sensor = pheaters.heaters[sensor_name]
            else:
                sensor = printer.lookup_object(sensor_name)
            toolhead = printer.lookup_object("toolhead")
            reactor = printer.get_reactor()
            if material.stop_requested() is not None:
                raise self._stop_heat_wait(sensor_name, gcmd.error)
            eventtime = reactor.monotonic()
            while printer.quick_stop_flag == False and not printer.is_shutdown():
                temp, target = sensor.get_temp(eventtime)
                if temp >= min_temp and temp <= max_temp:
                    return
                toolhead.get_last_move_time()
                gcmd.respond_raw(pheaters._get_temp(eventtime))
                if material.stop_requested() is not None:
                    raise self._stop_heat_wait(sensor_name, gcmd.error)
                eventtime = reactor.pause(eventtime + 1.)
            if printer.quick_stop_flag:
                gcmd.respond_info("quick Stop, break")
        help_text = getattr(pheaters, "cmd_TEMPERATURE_WAIT_help", "Wait for a temperature on a sensor")
        gcode.register_command("TEMPERATURE_WAIT", temperature_wait, desc=help_text)

    def cmd_STOP_POINT(self, gcmd):
        phase = gcmd.get("PHASE", "")
        if phase not in self.STOP_POINTS:
            raise gcmd.error("Unknown stop point PHASE=%s" % phase)
        self.material.check_stop_point(phase, *self.STOP_POINTS[phase])

    def cmd_STOP_WAITS(self, gcmd):
        value = gcmd.get("ENABLE", "")
        if value not in ("0", "1"):
            raise gcmd.error("ENABLE must be 0 or 1")
        if value == "0":
            self._stop_waits = None
            return
        sd = self.material.printer.lookup_object("virtual_sdcard", None)
        self._stop_waits = {"session": self.material.session_id,
                            "handle": getattr(sd, "current_file", None)}
