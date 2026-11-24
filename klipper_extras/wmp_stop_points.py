# SPDX-License-Identifier: GPL-3.0-or-later
"""Stop points: end long operations early at known safe places after Cancel.

A pending managed print cancel (wmp_print_cancel) bound to the open job is the
stop request. Macros call _WMP_STOP_POINT at safe phases and open a stop-wait
region with _WMP_STOP_WAITS so vendor heat waits end within one poll. A stop
raises a G-code error that unwinds the job; the cancel cleanup then runs as for
any other cancel. Inert while openACE or AFC owns filament operations.
"""
import logging
import math
import re


def finish_cancelled_toolchange(printer, owned):
    """Clear only an owned, drained and mechanically confirmed transient flag.

    No homing, coupling, heater or motor commands. Call from the unwound
    command owner's cleanup, never from the out-of-band Stop callback.
    """
    def guard():
        if owned() is not True:
            raise ValueError('Tool-change cleanup ownership is unavailable')
    def ready_guard():
        guard()
        if (printer.is_shutdown() or getattr(printer, 'quick_stop_flag', False)
                or any(printer.lookup_object(name, None) is not None
                       for name in ('openace', 'AFC'))):
            raise ValueError('Tool-change cleanup ownership is unavailable')
    def read(name):
        guard()
        obj = printer.lookup_object(name, None)
        result = obj.get_status(printer.get_reactor().monotonic()) if obj is not None else {}
        guard()
        return result
    variables = read('save_variables').get('variables', {})
    flag = variables.get('changing_tool')
    if flag is None or type(flag) is int and flag == 0:
        return 'not_needed'
    if type(flag) is not int or flag != 1:
        raise ValueError('Tool-change transient flag is invalid')
    ready_guard()
    toolhead = printer.lookup_object('toolhead', None)
    wait = getattr(toolhead, 'wait_moves', None)
    if not callable(wait):
        raise ValueError('Tool-change motion completion is unavailable')
    wait()
    ready_guard()
    variables = read('save_variables').get('variables', {})
    count = variables.get('thr_number')
    if (type(variables.get('changing_tool')) is not int or variables['changing_tool'] != 1
            or type(variables.get('fail_flag')) is not int or variables['fail_flag'] != 0
            or type(count) is not int or not 1 <= count <= 4):
        raise ValueError('Tool-change transient or coupling state changed during cleanup')
    hall = read('custom_hall').get('Raw')
    lock = read('filament_switch_sensor sensor_b').get('filament_detected')
    docks = [read('filament_switch_sensor docked%d' % n).get('filament_detected')
             for n in range(count)]
    if (type(hall) not in (int, float) or not math.isfinite(hall)
            or not 3450 <= hall <= 6000 or any(type(value) is not bool for value in docks)):
        raise ValueError('Tool-change attachment readback is unavailable')
    # Identification may intentionally discover a different UUID order. Use
    # physical sensors here, not the mapping it has not yet published.
    attached = hall < 4700 and lock is True and docks.count(False) == 1
    released = hall >= 4700 and lock is False and all(docks)
    if not (attached or released):
        raise ValueError('Tool-change attachment is not confirmed after draining')
    ready_guard()
    latest = read('save_variables').get('variables', {})
    if any(type(latest.get(key)) is not int or latest[key] != expected
           for key, expected in (('changing_tool', 1), ('fail_flag', 0), ('thr_number', count))):
        raise ValueError('Tool-change transient or coupling state changed during sensor readback')
    ready_guard()
    printer.lookup_object('gcode').run_script_from_command(
        'SAVE_VARIABLE VARIABLE=changing_tool VALUE=0')
    cleared = read('save_variables').get('variables', {}).get('changing_tool')
    ready_guard()
    if type(cleared) is not int or cleared != 0:
        raise ValueError('Tool-change transient cleanup was not confirmed')
    return 'cleared'


def check_operation_boundary(printer, label, phase='operation_boundary', state='Operation stopped at a safe boundary; motors not disabled'):
    """Shared cancellation observation outside native homing/coupling strokes.

    Never call this from inside stock G28's command-error handler. Calibration
    and print owners validate their own live bindings; no unbound global flag
    or hardware command is introduced by this helper.
    """
    material = printer.lookup_object('wm_material', None)
    lifecycle = getattr(material, '_plr_lifecycle_component', None)
    if lifecycle is not None:
        try:
            lifecycle.check_operation_boundary(label)
        except ValueError as error:
            # Recovery guards also run outside G-code and use ValueError.
            # At a nested command boundary that must be a normal command
            # unwind, not the dispatcher's internal-error shutdown path.
            raise getattr(printer, 'command_error', ValueError)(str(error)) from error
    stops = getattr(material, '_stop_points_component', None)
    if stops is not None:
        stops.check_resume_boundary(label)
    recovery = printer.lookup_object('wmp_recovery', None)
    identification = getattr(recovery, 'identification', None)
    if identification is not None:
        identification.check_operation_boundary(label)
    calibration = getattr(recovery, 'calibration', None)
    editor = getattr(calibration, 'probe_editor', None)
    if editor is not None:
        # An already executing standalone preparation must unwind on handoff,
        # without applying its cleanup to a new manager. Otherwise inert.
        editor.check_operation_boundary(label)
    if any(printer.lookup_object(owner, None) is not None for owner in ('openace', 'AFC')):
        return
    if calibration is not None:
        calibration.check_cancel(label)
    material = printer.lookup_object('wm_material', None)
    # Do not instantiate a component or perform any status/journal work while
    # idle. The executing service carries its own immutable command scope.
    service = getattr(material, '_filament_service_component', None)
    check_service = getattr(service, 'check_operation_boundary', None)
    if callable(check_service):
        check_service(label)
    toolheads = getattr(material, '_toolhead_service', None)
    check_toolheads = getattr(toolheads, 'check_operation_boundary', None)
    if callable(check_toolheads):
        check_toolheads(label)
    check = getattr(material, 'check_stop_point', None)
    if callable(check):
        check(phase, label, state)


class StopPoints:
    STOP_POINTS = {
        "resume_heated": ("after resume heating", "paused print; resume heating finished; return not started"),
        "resume_wipe_ready": ("before resume wiping", "paused print; resume return and wiping not started"),
        "resume_wiped": ("after resume wiping", "paused print; wipe finished; return not started"),
        "resume_return_ready": ("before paused-position return", "paused print; travel to return approach finished"),
        "resume_returned": ("after paused-position return", "paused print; return finished; SD continuation not started"),
        "start_admitted": ("print start admitted", "not homed by this job; nothing moved or heated by this job"),
        "before_homing": ("before homing", "not homed by this job; heaters may be on"),
        "homed": ("after homing", "homed; probe head attached and locked"),
        "before_mesh": ("before bed mesh", "homed; probe head attached; bed mesh not yet measured"),
        "mesh_saved": ("after bed mesh", "homed; bed mesh saved; probe head attached"),
        "before_initial_tool": ("before print tool selection", "homed; probing head remains attached"),
        "initial_tool_ready": ("after print tool selection", "print head selected and attached"),
        "purged": ("after purge", "first tool picked up; purge finished"),
    }
    STOP_ERROR_PREFIX = "Print cancellation requested; stopped "
    # Recorded by the bed mesh hook, not a macro stop point.
    MESH_PHASE = "mesh_probing"
    MESH_STATE = "homed; probe head attached and raised; bed mesh not saved"

    def __init__(self, material):
        self.material = material
        self._stop_waits = None
        self._resume_scope = None
        self._wait_wrappers_installed = False
        self._stop_note_error_installed = False

    def install(self):
        """Register the stop commands and wrappers; called from klippy:ready."""
        gcode = self.material.printer.lookup_object("gcode")
        gcode.register_command("_WMP_STOP_POINT", self.material.cmd_STOP_POINT)
        gcode.register_command("_WMP_STOP_WAITS", self.material.cmd_STOP_WAITS)
        self.material._install_wait_wrappers()
        self.material._install_mesh_stop()
        self.material._install_stop_note_error()
        self._install_resonance_stop()
        toolheads = getattr(self.material, '_toolheads', None)
        if callable(toolheads):
            toolheads().coupling_regions().install()

    def _install_resonance_stop(self):
        tester = self.material.printer.lookup_object('resonance_tester', None)
        original = getattr(tester, '_run_test', None)
        if not callable(original) or getattr(original, '_wmp_resonance_stop', False):
            return
        try:
            from .wmp_resonance_stop import ResonanceStop, install_calculation_stop
        except ImportError:
            from wmp_resonance_stop import ResonanceStop, install_calculation_stop
        install_calculation_stop(original)
        wrapped = ResonanceStop(self, tester, original)
        wrapped._wmp_resonance_stop = True
        tester._run_test = wrapped

    def _calibration_wait_owner(self):
        """Only the bound calibration command greenlet may manage its wait.

        Reactor callbacks run in other greenlets while a command is suspended.
        An unrelated wait must keep vendor semantics even during calibration.
        Cleanup also runs in the command context, but must finish its own park.
        """
        if self._stop_owner_present():
            return None
        recovery = self.material.printer.lookup_object('wmp_recovery', None)
        calibration = getattr(recovery, 'calibration', None)
        attempt = getattr(calibration, 'executing', None)
        if (attempt is None or not getattr(calibration, 'active', False)
                or attempt is not getattr(calibration, '_current_attempt', None)
                or attempt.get('state') != 'pending'
                or attempt.get('cancel_cleanup', {}).get('state') == 'running'):
            return None
        tracker = getattr(calibration, '_heater_ownership', None)
        if (tracker is None or not tracker.enabled
                or tracker.contexts.get(tracker.current_actor()) != attempt['request']):
            return None
        return calibration

    def _toolhead_wait_owner(self):
        service = getattr(self.material, '_toolhead_service', None)
        return service.wait_owner() if service is not None and not self._stop_owner_present() else None

    def _check_calibration_wait(self, label):
        self.check_resume_boundary(label)
        service = getattr(self.material, '_toolhead_service', None)
        if service is not None:
            service.check_operation_boundary(label)
        calibration = self._calibration_wait_owner()
        if calibration is not None:
            calibration.check_cancel(label)

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

    @staticmethod
    def _current_actor():
        from greenlet import getcurrent
        return getcurrent()

    def _resume_owned(self, scope, check_generation=True):
        material = self.material
        printer = material.printer
        sd = printer.lookup_object('virtual_sdcard', None)
        stats = printer.lookup_object('print_stats', None)
        return (self._resume_scope is scope
                and printer.lookup_object('wm_material', None) is material
                and not self._stop_owner_present()
                and material.session_id == scope['session']
                and (not check_generation or getattr(material, '_command_generation', 0) == scope['generation'])
                and sd is scope['sd'] and stats is scope['stats']
                and getattr(sd, 'current_file', None) is scope['handle']
                and not getattr(scope['handle'], 'closed', False)
                and getattr(stats, 'filename', None) == scope['file'])

    def check_resume_boundary(self, label):
        scope = self._resume_scope
        if scope is None or self._current_actor() is not scope['actor']:
            return
        # Accepted print Cancel fences command generations itself. It may
        # stop this same job, but cannot authorize any further resume action.
        if (not self._resume_owned(scope, check_generation=False)
                or not self._resume_owned(scope) and self.material.stop_requested() is None):
            raise self.material.printer.lookup_object('gcode').error(
                'Resume ownership changed; no further resume actions allowed')
        self.material.check_stop_point('resume_boundary', label,
            'Paused print resume stopped at a safe boundary; motors not disabled')

    def run_resume_waits(self, execute):
        """Command-lifetime wait cancellation, independent of progress telemetry."""
        printer = self.material.printer
        sd = printer.lookup_object('virtual_sdcard', None)
        stats = printer.lookup_object('print_stats', None)
        handle = getattr(sd, 'current_file', None)
        if (self._resume_scope is not None or self._stop_owner_present()
                or handle is None or getattr(handle, 'closed', False) or stats is None):
            return execute()
        scope = dict(actor=self._current_actor(), session=self.material.session_id,
                     generation=getattr(self.material, '_command_generation', 0),
                     sd=sd, stats=stats, handle=handle, file=stats.filename)
        self._resume_scope = scope
        try:
            self.check_resume_boundary('before resume')
            return execute()
        finally:
            if self._resume_scope is scope:
                self._resume_scope = None

    def stop_waits_open(self):
        scope = self._resume_scope
        if scope is not None and self._current_actor() is scope['actor']:
            self.check_resume_boundary('before resume heater wait')
            return True
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
        head = re.fullmatch(r"extruder([0-3]?)", name)
        label = ("Head %d" % (int(head[1] or 0) + 1) if head else
                 {"heater_bed": "bed", "heater_generic chamber": "chamber"}.get(name, name))
        try:
            self.material._record_stop_point(phase, ("heating " + label)[:160],
                                             (name + " wait interrupted; cleanup turns heaters off")[:160])
        except Exception:
            logging.exception("Unable to record stop point %s", phase)
        return error("Print cancellation requested; stopped while heating " + label)

    def _stop_mesh(self, measured, total):
        """Close the wait region, record the stop and return the error to raise."""
        self._stop_waits = None
        label = "bed mesh, %d of %d points measured" % (measured, total)
        try:
            self.material._record_stop_point(self.MESH_PHASE, label[:160], self.MESH_STATE)
        except Exception:
            logging.exception("Unable to record stop point %s", self.MESH_PHASE)
        return self.material.printer.lookup_object("gcode").error(
            "Print cancellation requested; stopped during " + label)

    def _install_mesh_stop(self):
        """Stop BED_MESH_CALIBRATE between probe points after Cancel.

        Wraps the vendor ProbePointsHelper owned by bed_mesh (extras/probe.py),
        which raises the head to horizontal_move_z before _move_next() moves to
        the next point. Its final point calls _invoke_callback() instead, so
        that boundary must be guarded too. Only bed_mesh's helper is wrapped,
        so G28 and other probe users never stop here (a G28 error turns the
        motors off). The gcode error
        reaches the vendor dispatcher, whose gcode:command_error event ends the
        probe session; the bed_mesh finalize callback never runs, so no partial
        mesh is built or saved. Managed for an open print stop-wait region or
        the executing bound calibration command.
        """
        mesh = self.material.printer.lookup_object("bed_mesh", None)
        manager = getattr(getattr(mesh, "bmc", None), "probe_mgr", None)
        helper = getattr(manager, "probe_helper", None)
        original = getattr(helper, "_move_next", None)
        finalize = getattr(helper, "_invoke_callback", None)
        if (not callable(original) or not callable(finalize)
                or getattr(original, "__wrapped__", None) is not None
                or getattr(finalize, "__wrapped__", None) is not None):
            return
        material = self.material
        def check_boundary(probe_num, label):
            self._check_calibration_wait(label)
            if material.stop_waits_open() and material.stop_requested() is not None:
                points = getattr(helper, "probe_points", None) or ()
                raise self._stop_mesh(min(probe_num, len(points)), len(points))
        def move_next(probe_num):
            check_boundary(probe_num, 'between bed mesh points')
            return original(probe_num)
        def invoke_callback(results):
            check_boundary(len(results), 'before bed mesh finalization')
            return finalize(results)
        move_next.__wrapped__ = original
        invoke_callback.__wrapped__ = finalize
        helper._move_next = move_next
        helper._invoke_callback = invoke_callback

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

        Waits in an open print stop-wait region or the executing bound
        calibration command are managed. The loops mirror PrinterHeaters
        (extras/heaters.py), preserving vendor behavior without a cancel.
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
                if not material.stop_waits_open() and self._calibration_wait_owner() is None and self._toolhead_wait_owner() is None:
                    return original_wait(heater)
                if printer.get_start_args().get("debugoutput") is not None:
                    return
                name = heater.get_name() if callable(getattr(heater, "get_name", None)) else heater.name
                toolhead = printer.lookup_object("toolhead")
                gcode = printer.lookup_object("gcode")
                reactor = printer.get_reactor()
                if material.stop_requested() is not None:
                    raise self._stop_heat_wait(name, gcode.error)
                self._check_calibration_wait('before heater wait')
                eventtime = reactor.monotonic()
                while (printer.quick_stop_flag == False and not printer.is_shutdown()
                       and heater.check_busy(eventtime)):
                    self._check_calibration_wait('during heater wait')
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
            if not material.stop_waits_open() and self._calibration_wait_owner() is None and self._toolhead_wait_owner() is None:
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
            self._check_calibration_wait('before temperature wait')
            eventtime = reactor.monotonic()
            while printer.quick_stop_flag == False and not printer.is_shutdown():
                self._check_calibration_wait('during temperature wait')
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
        self.check_resume_boundary(self.STOP_POINTS[phase][0])
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
