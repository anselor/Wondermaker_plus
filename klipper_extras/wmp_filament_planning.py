# SPDX-License-Identifier: GPL-3.0-or-later
"""Standalone filament procedure planning and service positioning."""
import copy
import hashlib
import json
import math

try:
    from .wmp_observation import _status_observation
    from .wmp_filament_types import MATERIALS, GENERIC_NOZZLE_RANGES, material_family, cross_family_purge, transition_temperature
except ImportError:
    from wmp_observation import _status_observation
    from wmp_filament_types import MATERIALS, GENERIC_NOZZLE_RANGES, material_family, cross_family_purge, transition_temperature

def service_progress_steps(head, context, phase_name="preparing"):
    """Describe the existing service path; this never schedules movement."""
    prefix = "" if phase_name == "preparing" else "return_"
    steps = []
    if context.get("needs_home"):
        steps.append((prefix + "homing", "Home X/Y"))
    attachment = context.get("attachment", {})
    current = attachment.get("head", "")
    if "head" in attachment and current != "h%d" % head:
        if current:
            steps.append((prefix + "docking", "Dock Head %d" % (int(current[1:]) + 1)))
        steps.append((prefix + "mounting", "Mount Head %d" % (head + 1)))
    steps.append((phase_name, "Position Head %d" % (head + 1)))
    return steps


class FilamentPlanning:
    def __init__(self, material):
        self.material = material

    def _filament_position_status(self, now):
        recovery = self.material.printer.lookup_object("wmp_recovery", None)
        if recovery is None:
            return {"ready": True}  # Legacy fixed-position service has no travel.
        try:
            axes = self.material.printer.lookup_object("toolhead").get_status(now).get("homed_axes", "")
            return {"ready": True, "home_xy": not all(axis in axes for axis in "xy")}
        except (AttributeError, KeyError, TypeError, ValueError):
            return {"ready": False, "reason": "Printer position is unavailable. Wait for fresh printer status."}


    @_status_observation
    def _service_context(self, head, now, allow_homing=False, allow_history=False, offset_heads=()):
        """Capture calibrated travel and whether stock homing is required."""
        if self.material._identification_pending(now):
            raise ValueError("Restart Klipper after head identification before filament service")
        def status(name):
            obj = self.material.printer.lookup_object(name, None)
            if obj is None:
                raise ValueError("Missing service dependency: " + name)
            return obj.get_status(now)
        th = status("toolhead")
        position = self._filament_position_status(now)
        if not position["ready"]:
            raise ValueError(position["reason"])
        needs_home = not all(axis in th.get("homed_axes", "") for axis in "xy")
        if needs_home and not allow_homing:
            raise ValueError("Homing did not establish a valid XY reference")
        attachment = self.material._attachment(now)
        if attachment["state"] not in ("attached", "empty"):
            raise ValueError("Head attachment sensors disagree")
        saved = status("save_variables").get("variables", {})
        if (not allow_history and saved.get("fail_flag", 0) != 0) or saved.get("is_nozzle_setting", 0) != 0:
            raise ValueError("Inspect the head, then retry Head identification if setup mode remains set; current: " + ("fail_flag=" + repr(saved.get("fail_flag", 0))[:80] if saved.get("fail_flag", 0) != 0 else "is_nozzle_setting=" + repr(saved.get("is_nozzle_setting", 0))[:80]))
        # get_status exposes the live saved-variable dictionary. Keep admission
        # geometry immutable across homing/service yields, including callers
        # that update a coordinate list in place rather than SAVE_VARIABLE.
        positions = copy.deepcopy([saved.get("t%d_position" % i) for i in range(4)])
        offsets = copy.deepcopy([saved.get("t%d_offset" % i) for i in range(4)])
        minimum, maximum = th["axis_minimum"], th["axis_maximum"]
        probe = saved.get("probe_tool", 0)
        if type(probe) is not int or not 0 <= probe < 4:
            raise ValueError("Invalid probe reference")
        current = attachment["head"]
        dock_heads = ({head} | ({int(current[1:])} if current else set())
                      if current != "h%d" % head else set())
        required_offsets = {head, probe} | set(offset_heads)
        if dock_heads and not (minimum[1] <= 270 <= 310 <= maximum[1]):
            raise ValueError("Dock staging path exceeds travel limits")
        for index in sorted(dock_heads):
            point = positions[index]
            if not isinstance(point, (list, tuple)) or len(point) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in point):
                raise ValueError("Invalid dock calibration for Head %d" % (index + 1))
            if not minimum[0] <= point[0] <= maximum[0] or not 310 <= point[1] <= maximum[1] - .4:
                raise ValueError("Dock calibration exceeds travel limits for Head %d" % (index + 1))
        for index in sorted(required_offsets):
            offset = offsets[index]
            if not isinstance(offset, (list, tuple)) or len(offset) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 20 for v in offset):
                raise ValueError("Invalid toolhead offsets for Head %d" % (index + 1))
        if not minimum[0] <= -13 <= maximum[0] or not minimum[1] <= 80 <= maximum[1]:
            raise ValueError("Purge position is outside travel limits")
        return {"attachment": attachment, "positions": positions, "offsets": offsets,
                "probe": probe, "needs_home": needs_home,
                "dock_heads": sorted(dock_heads), "offset_heads": sorted(required_offsets)}


    def _prepare_service(self, head, context, phase_name="preparing"):
        gcode = self.material.printer.lookup_object("gcode")
        run = gcode.run_script_from_command
        reactor = self.material.printer.get_reactor()
        heat_target = context.get("heat_target") if phase_name == "preparing" else None
        prefix = "" if phase_name == "preparing" else "return_"
        def phase(text, step=phase_name):
            self.material.filament_operation.update(message=text, phase=step)
        # Enter the first action, not the final positioning row. Otherwise the
        # UI marks docking/mounting complete before either has happened.
        self.material._filament_checkpoint(service_progress_steps(head, context, phase_name)[0][0])
        if context.get("needs_home", False):
            self.material._filament_checkpoint(prefix + "homing")
            phase("Homing X/Y", prefix + "homing")
            # XY-only homing must preserve the existing Z datum and probe head.
            run("G28 X Y\nM400")
            self.material._filament_checkpoint(prefix + "homing")
            now = reactor.monotonic()
            if not self.material._filament_context_valid(self.material.filament_operation, now):
                raise ValueError("Printer became busy during homing: " + getattr(self.material, "_filament_context_refusal", "context admission was not confirmed"))
            homed = self._service_context(head, now, offset_heads=context.get("offset_heads", ()))
            for key, indices in (("positions", "dock_heads"), ("offsets", "offset_heads")):
                if any(homed[key][index] != context[key][index]
                       for index in set(homed[indices]) & set(context[indices])):
                    raise ValueError("Toolhead calibration changed during homing")
            if homed["probe"] != context["probe"]:
                raise ValueError("Unexpected probe reference after homing")
            # Revalidate calibration and sensor evidence before service travel.
            if "restore_offset" in context:
                homed["restore_offset"] = context["restore_offset"]
            context = homed
        if heat_target is not None:
            # Heat the physical nozzle while docking/mounting and travelling.
            # Extrusion still waits for temperature after reaching the purge point.
            heater = "extruder" if head == 0 else "extruder%d" % head
            run("SET_HEATER_TEMPERATURE HEATER=%s TARGET=%.3f" % (heater, heat_target))
        current = context["attachment"]["head"]
        offset, reference = context["offsets"][head], context["offsets"][context["probe"]]
        restore_offset = context.get("restore_offset", tuple(a-b for a,b in zip(offset, reference)))
        restore = "SET_GCODE_OFFSET X=%.5f Y=%.5f Z=%.5f MOVE=0" % tuple(restore_offset)
        changed = current != "h%d" % head
        # Stop only in coherent frames: before clearing the old attached
        # head's offset, after verified docking, or after pickup bookkeeping.
        # Dock/purge moves still use the machine frame at the existing Z.
        if changed:
            if current:
                index = int(current[1])
                phase("Docking Head %d" % (index + 1), prefix + "docking")
                self.material._filament_checkpoint(prefix + "docking")
                run("G90\nSET_GCODE_OFFSET X=0 Y=0 Z=0 MOVE=0")
                run("_UNLOCK_TOOL T=%d SERVICE=1" % index)
                saved = self.material.printer.lookup_object("save_variables").get_status(
                    reactor.monotonic()).get("variables", {})
                if saved.get("fail_flag", 0) != 0:
                    raise ValueError("Head %d docking failed: current fail_flag=%r" %
                                     (index + 1, saved.get("fail_flag")))
                self.material._filament_checkpoint(prefix + "docking")
            phase("Mounting Head %d" % (head + 1), prefix + "mounting")
            self.material._filament_checkpoint(prefix + "mounting")
            run("G90\nSET_GCODE_OFFSET X=0 Y=0 Z=0 MOVE=0")
            run("_LOCK_TOOL T=%d SERVICE=1" % head)
            # Coupling, mandatory retreat and sensor verification finish before
            # observing Cancel. Preserve a real mounting fault as the error.
            saved = self.material.printer.lookup_object("save_variables").get_status(
                reactor.monotonic()).get("variables", {})
            if saved.get("fail_flag", 0) != 0:
                raise ValueError("Head %d mounting failed: current fail_flag=%r" %
                                 (head + 1, saved.get("fail_flag")))
        heater = "extruder" if head == 0 else "extruder%d" % head
        run("ACTIVATE_EXTRUDER EXTRUDER=%s\nSAVE_VARIABLE VARIABLE=current_extruder VALUE=%d" % (heater, head))
        if changed:
            # A stopped pickup must leave sensor identity, active extruder,
            # saved head and coordinate offset consistent, with no new travel.
            run(restore)
            self.material._filament_checkpoint(prefix + "mounting")
        phase("Moving to filament service position")
        self.material._filament_checkpoint(phase_name)
        run("G90\nSET_GCODE_OFFSET X=0 Y=0 Z=0 MOVE=0")
        run("_WMP_XY_TRAVEL X=-13 HOT=1\n_WMP_XY_TRAVEL Y=80 HOT=1\nM400")
        # Restore head-relative coordinates without travel after arriving.
        run(restore)
        self.material._filament_checkpoint(phase_name)


    def _filament_plan(self, head, action, now, ace_status_cache=None):
        self.material._require_no_recovery_attempt()
        if action not in ("load", "unload") or type(head) is not int or not 0 <= head <= 3:
            raise ValueError("Invalid filament procedure")
        if self.material.printer.lookup_object("openace", None) is not None:
            return self.material._openace_unload_plan(head, action, now, ace_status_cache)
        if self.material.printer.lookup_object("AFC", None) is not None:
            raise ValueError("AFC owns filament service; use its managed controls")
        pause_origin = None
        if not self.material._idle_for_filament_settings(now):
            pause_origin = self.material._paused_filament_origin(head, now)
        key = "h%d" % head
        service = self.material.printer.lookup_object("wmp_recovery", None) is not None
        context = self._service_context(head, now, allow_homing=True,
            allow_history=not self.material._material_operation_active("filament_operation"),
            offset_heads=(int(self.material._pause_origin["head"][1:]),) if pause_origin else ()) if service else None
        if pause_origin:
            origin = self.material._pause_origin
            allowed = set(origin.get("filament_required", [])) | {origin["head"]}
            if (not service or context["attachment"].get("state") != "attached"
                    or context["attachment"].get("head") not in allowed):
                raise ValueError("Paused service requires a confirmed recovery head mounted")
            original = int(origin["head"][1:])
            context["restore_offset"] = [v + dst - src for v, dst, src in
                zip(origin["offset"], context["offsets"][head], context["offsets"][original])]
            if head != original:
                context["return_head"] = original
                context["return_offset"] = list(origin["offset"])
        if not service and self.material._attachment(now) != {"state": "attached", "head": key}:
            raise ValueError("Take the selected head first; attachment must be confirmed")
        heater = "extruder" if head == 0 else "extruder%d" % head
        if not service and self.material.printer.lookup_object("toolhead").get_status(now).get("extruder") != heater:
            raise ValueError("Active extruder does not match the mounted head")
        profiles, revision = self.material._profiles()
        if key not in profiles:
            raise ValueError("Configure the external filament first")
        identity = profiles[key]
        if service:
            presence = self.material._loaded_filament_status(now).get(key, {}).get("state")
            if presence != ("empty" if action == "load" else "loaded"):
                raise ValueError("Filament sensor does not match the requested operation")
        if action == "unload":
            loaded = self.material._loaded_filament_status(now).get(key, {})
            if loaded.get("state") != "loaded":
                raise ValueError("The head sensor does not report filament")
            identity = loaded["identity"]
        material = identity["material"].upper()
        temperatures = {name.upper(): temp for name, temp in MATERIALS}
        recipe_material = material if material in temperatures else material_family(identity)
        if recipe_material not in temperatures:
            raise ValueError("No supported %s recipe for %s" % (action, identity["material"]))
        # Match the existing shaping classes. Do not derive a physical head
        # from box_modify or use the logical M104/M109 handlers here.
        base = material_family(identity)
        base = {"PCTG": "PETG", "PA6": "PA", "PA12": "PA"}.get(base, base)
        cls = "soft" if base in ("TPU", "TPE") else "petg" if base in ("PETG", "PET") else "abs" if base in ("ABS", "ASA", "HIPS", "WOOD") else "pla"
        target = temperatures[recipe_material] if action == "load" else {"PETG": 235, "PET": 235, "ABS": 280, "ASA": 280, "HIPS": 280, "PA": 280, "PC": 300}.get(base, 250)
        if action == "load" and identity.get("nozzle_temp", 0) > 0:
            target = identity["nozzle_temp"]
        previous_material, transition_note = None, ""
        if action == "load":
            previous_material = self.material._hotend_material_history().get(key)
            target, transition_note = transition_temperature(identity, previous_material, target)
        minimum, maximum = identity.get("nozzle_temp_min", 0), identity.get("nozzle_temp_max", 0)
        if action == "load" and material in GENERIC_NOZZLE_RANGES:
            minimum, maximum = GENERIC_NOZZLE_RANGES[material]
        if action == "unload":
            # Use the existing shaping class at a spool-supported temperature.
            # Bounds constrain the recipe, not the spool's load target.
            if minimum:
                target = max(target, minimum)
            if maximum:
                target = min(target, maximum)
        if minimum and target < minimum:
            raise ValueError("%s requires %g C; filament minimum is %g C" % (action.capitalize(), target, minimum))
        if maximum and target > maximum:
            raise ValueError("%s requires %g C; filament maximum is %g C" % (action.capitalize(), target, maximum))
        heater = "extruder" if head == 0 else "extruder%d" % head
        state = self.material.printer.lookup_object(heater).get_status(now)
        config = self.material.printer.lookup_object("configfile").get_status(now)["settings"][heater]
        maximum_heater_temp = float(config["max_temp"])
        if target > maximum_heater_temp:
            raise ValueError("Recipe requires %g C; %s maximum is %g C" %
                             (target, heater, maximum_heater_temp))
        actual = float(state.get("temperature", float("nan")))
        if not service and (state.get("can_extrude") is not True or state.get("target") != target
                or not math.isfinite(actual) or abs(actual - target) > 5):
            raise ValueError("Heat Head %d to %d C before %s" % (head + 1, target, action))
        if service and action == "load" and self.material.printer.lookup_object("gcode_macro WIPE_NOZZLE", None) is None:
            raise ValueError("Nozzle wipe macro is unavailable")
        if action == "unload" and self.material.printer.lookup_object("gcode_macro _TIP_SHAPE_MOVES", None) is None:
            raise ValueError("Tip shaping macro is unavailable")
        plan = {"head": key, "action": action, "source": "external:" + key,
                "session": self.material.session_id, "identity_revision": revision,
                "identity": identity, "target": target, "class": cls}
        if action == "load":
            # Bind review to nozzle history as well as the editable spool profile.
            plan["previous_material"] = previous_material
            plan["history_error"] = getattr(self.material, "_hotend_history_error", "")
            if plan["history_error"]:
                transition_note = (transition_note + " " + plan["history_error"]).strip()
            plan["transition_note"] = transition_note
            plan["temperature_description"] = "Load temperature: %g C." % target
            if transition_note:
                plan["temperature_description"] += " " + transition_note
        if pause_origin:
            plan["pause_origin"] = pause_origin
        if action == "load":
            normal_purge = getattr(self.material, "load_purge_mm", 50.)
            cross_material = cross_family_purge(identity, previous_material)
            purge = getattr(self.material, "cross_material_purge_mm", normal_purge) if cross_material else normal_purge
            plan.update(feed_mm=getattr(self.material, "load_feed_mm", 55.), purge_mm=purge,
                        purge_source="cross_material" if cross_material else "same_family")
        if service:
            plan["service"] = context
        plan["command_generation"] = getattr(self.material, "_command_generation", 0)
        plan["token"] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
        plan["description"] = ("Head %d stays at its current position. " % (head + 1)
            + ("Feed %g mm, then purge %g mm at 400 mm/min. " % (plan["feed_mm"], plan["purge_mm"]) if action == "load" else "Run the existing %s tip-shaping and withdrawal sequence. " % cls.upper())
            + "No homing, docking, XYZ travel or heater changes. Check the filament afterward.")
        if service:
            plan["description"] = (
                ("Home X/Y, then mount" if context["needs_home"] else "Mount")
                + " Head %d while heating to %d C, then park at the purge position. " % (head + 1, target)
                + ("Insert filament when prompted; feed %g mm, purge %g mm, then wipe the nozzle." % (plan["feed_mm"], plan["purge_mm"]) if action == "load"
                   else "Shape the filament tip and withdraw it."))
        if transition_note:
            plan["description"] += " " + transition_note
        return plan


