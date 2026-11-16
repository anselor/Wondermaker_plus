# SPDX-License-Identifier: GPL-3.0-or-later
"""Existing external material-manager adapters; no integration policy changes."""
import copy
import hashlib
import json
import math
import re
import threading
import urllib.request
import urllib.error
import urllib.parse

try:
    from .wmp_filament_types import MATERIALS
except ImportError:
    from wmp_filament_types import MATERIALS

class MaterialOwners:
    def __init__(self, material):
        self.material = material

    def _afc_ready(self):
        self._afc_stopped = False
        self._afc_busy = False
        self._afc_last = None
        self._afc_error = ""
        self._afc_declined = []
        gcode = self.material.printer.lookup_object("gcode")
        owner = self.material.printer.lookup_object("openace", None) or self.material.printer.lookup_object("AFC", None)
        commands = gcode.get_status(self.material.printer.get_reactor().monotonic()).get("commands", {})
        for name in ("SET_COLOR", "SET_MATERIAL", "AFC_SET_SPOOL_TEMP", "WMP_SET_BRAND"):
            if owner or name in commands:
                self._afc_declined.append(name)
                continue
            gcode.register_command(name, self.cmd_AFC_METADATA, desc="Set standalone WM+ filament metadata; no motion")
        self.material.printer.get_reactor().register_timer(self._afc_tick, self.material.printer.get_reactor().NOW)


    def _afc_stop(self, *args):
        self._afc_stopped = True


    def _lane_data(self, now):
        previous = getattr(self.material, '_status_observation_cache', None)
        self.material._status_observation_cache = {} if previous is None else previous
        try:
            return self._lane_snapshot(now)
        finally:
            self.material._status_observation_cache = previous


    def _lane_snapshot(self, now):
        if self.material.printer.lookup_object("openace", None) or self.material.printer.lookup_object("AFC", None):
            return {}
        profiles, revision = self.material._profiles()
        presence = self.material._loaded_filament_status(now)
        saved = self.material.printer.lookup_object("save_variables", None)
        variables = saved.get_status(now).get("variables", {}) if saved else {}
        rows = {}
        for tool in range(4):
            head = variables.get("box_modify_t%d" % tool, tool)
            if type(head) is not int or not 0 <= head < 4:
                continue
            heater = "extruder" if head == 0 else "extruder%d" % head
            if self.material.printer.lookup_object(heater, None) is None:
                continue
            loaded = presence["h%d" % head]["state"] == "loaded"
            # Orca treats a nonempty material as presence, ignoring `loaded`.
            # Keep saved spool metadata canonical, but expose it only when sensed.
            identity = profiles.get("h%d" % head, {}) if loaded else {}
            rows["wmplus_tool_%d" % tool] = {
                "lane": str(tool), "extruder_index": head,
                "material": identity.get("material", ""), "color": identity.get("color", ""),
                "bed_temp": identity.get("bed_temp", 0),
                "nozzle_temp": identity.get("nozzle_temp", dict(MATERIALS).get(identity.get("material"), 0)),
                "spool_id": None, "weight": None, "unit": None, "unit_name": None, "slot": None,
                "name": " ".join(filter(None, (identity.get("brand"), identity.get("material")))),
                "loaded": loaded,
                "brand": identity.get("brand", ""),
                "nozzle_temp_min": identity.get("nozzle_temp_min", 0),
                "nozzle_temp_max": identity.get("nozzle_temp_max", 0),
            }
        return rows


    def cmd_AFC_METADATA(self, gcmd):
        if self.material.printer.lookup_object("openace", None) or self.material.printer.lookup_object("AFC", None):
            raise gcmd.error("Another filament manager owns this printer")
        now = self.material.printer.get_reactor().monotonic()
        lane = gcmd.get("LANE").strip()
        # Match openACE's public lane forms, resolving logical tools through the
        # same current mapping used to publish lane_data (not as physical IDs).
        match = re.fullmatch(r"(?:wmplus_tool_|[Tt])?([0-3])", lane)
        if match is None:
            raise gcmd.error("Unknown WM+ lane; use wmplus_tool_N, TN or N (0-3)")
        lane = "wmplus_tool_" + match.group(1)
        rows = self._lane_data(now)
        if lane not in rows:
            raise gcmd.error("Unknown WM+ lane")
        head = rows[lane]["extruder_index"]
        profiles, revision = self.material._profiles()
        identity = dict(profiles.get("h%d" % head, {"brand": "Generic", "material": "Unknown", "color": "#888888"}))
        command = gcmd.get_command()
        if command == "SET_COLOR":
            value = gcmd.get("COLOR")
            if not re.fullmatch(r"[0-9a-fA-F]{6}", value):
                raise gcmd.error("COLOR must be six hex digits without #")
            identity["color"] = "#" + value.upper()
        elif command == "SET_MATERIAL":
            identity["material"] = gcmd.get("MATERIAL")
            # Changing material invalidates the previous spool's temperature recipe.
            for key in ("nozzle_temp", "nozzle_temp_min", "nozzle_temp_max", "bed_temp"):
                identity.pop(key, None)
        elif command == "WMP_SET_BRAND":
            identity["brand"] = gcmd.get("BRAND")
        elif command == "AFC_SET_SPOOL_TEMP":
            for param, key in (("BED_TEMP", "bed_temp"), ("EXTRUDER_TEMP", "nozzle_temp"),
                               ("MIN_TEMP", "nozzle_temp_min"), ("MAX_TEMP", "nozzle_temp_max")):
                value = gcmd.get(param, None)
                if value is not None:
                    identity[key] = float(value)
        else:
            raise gcmd.error("Unsupported metadata command")
        # Reuse the native editor's atomic storage and idle/ownership validation.
        proxy = self.material.printer.lookup_object("gcode").create_gcode_command(
            "WMP_SET_FILAMENT", "", {"HEAD": str(head), "EXPECT": revision,
                                      "PROFILE": json.dumps(identity).encode().hex()})
        self.material.cmd_SET_FILAMENT(proxy)


    def _afc_tick(self, now):
        self.material._drain_async_completions(now)
        reactor = self.material.printer.get_reactor()
        if self._afc_stopped:
            return reactor.NEVER
        if not self._afc_busy:
            try:
                rows = self._lane_data(now)
                if rows != self._afc_last:
                    self._afc_busy = True
                    try:
                        threading.Thread(target=self._afc_publish, args=(rows,), daemon=True).start()
                    except Exception:
                        self._afc_busy = False
                        raise
            except Exception as error:
                self._afc_error = str(error)
        return now + 2.


    def _afc_publish(self, rows):
        # Network I/O never runs on Klipper's reactor. Touch only immutable rows
        # here; publish completion back on the reactor. Retire only known WM+ /
        # inactive openACE projection keys; unrelated AFC records are untouched.
        error = ""
        try:
            def call(method, query="", body=None, endpoint="/server/database/item"):
                if self._afc_stopped:
                    raise ValueError("Publisher stopped")
                req = urllib.request.Request("http://127.0.0.1:7125" + endpoint + query,
                    data=json.dumps(body).encode() if body is not None else None,
                    headers={"Content-Type": "application/json"}, method=method)
                with urllib.request.urlopen(req, timeout=2) as response:
                    return json.load(response)
            def owner_now():
                status = call("GET", "?wm_material=session_id,afc_metadata", endpoint="/printer/objects/query")["result"]["status"]["wm_material"]
                if status.get("session_id") != self.material.session_id:
                    raise ValueError("Filament publisher session changed")
                owner = status.get("afc_metadata", {}).get("owner")
                if owner not in ("standalone", "openace", "AFC"):
                    raise ValueError("Filament publisher ownership unavailable")
                return owner
            owner = owner_now()
            if rows and owner != "standalone":
                raise ValueError("Another filament manager owns this printer")
            def mutate(method, query="", body=None):
                if owner_now() != owner:
                    raise ValueError("Filament publisher ownership changed")
                return call(method, query, body)
            try:
                old = call("GET", "?namespace=lane_data").get("result", {}).get("value", {})
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    raise
                old = {}
            # Publish replacements before retiring stale cached projections.
            for key, value in rows.items():
                if old.get(key) != value:
                    mutate("POST", body={"namespace": "lane_data", "key": key, "value": value})
            for key in old:
                own_obsolete = re.fullmatch(r"wmplus_tool_[0-9]+", key) and key not in rows
                ace_obsolete = owner == "standalone" and re.fullmatch(r"openace_tool_[0-9]+", key)
                if own_obsolete or ace_obsolete:
                    mutate("DELETE", "?namespace=lane_data&key=" + urllib.parse.quote(key))
        except Exception as exc:
            error = str(exc)
        def finished(now):
            self._afc_busy = False
            self._afc_error = error
            if not error:
                self._afc_last = rows
        self.material._queue_async_completion(finished)


    def _openace_idle_status(self, now, ace_status_cache=None):
        stats = self.material.printer.lookup_object("print_stats").get_status(now)
        pause = self.material.printer.lookup_object("pause_resume").get_status(now)
        sd = self.material.printer.lookup_object("virtual_sdcard")
        if (stats.get("state") not in ("standby", "complete", "cancelled")
                or pause.get("is_paused") is not False or sd.is_active() or sd.is_cmd_from_sd()):
            raise ValueError("Use the recovery flow during an active or paused print")
        # One read per status publication; command dispatch passes no cache and
        # therefore always validates against a fresh owner snapshot.
        if ace_status_cache is not None and "status" in ace_status_cache:
            ace = ace_status_cache["status"]
        else:
            ace = self.material.printer.lookup_object("openace").get_status(now)
            if ace_status_cache is not None:
                ace_status_cache["status"] = ace
        if "job" not in ace or (ace["job"] is not None
                and (not isinstance(ace["job"], dict) or ace["job"].get("active") is not False)):
            raise ValueError("An openACE print map is active or unavailable; use recovery controls")
        if "operation" not in ace or ace["operation"] is not None:
            raise ValueError("Wait for the current openACE operation")
        if type(ace.get("session_id")) is not int or type(ace.get("config_revision")) is not int:
            raise ValueError("openACE session or configuration is unavailable")
        return ace


    def _openace_load_plans(self, head, now, ace_status_cache=None):
        self.material._require_no_recovery_attempt()
        ace = self._openace_idle_status(now, ace_status_cache)
        key = "h%d" % head
        loaded = ace.get("loaded", {}).get(key, {})
        routes = ace.get("default_tool_map", {})
        managed = any(isinstance(r, dict) and r.get("head") == key and r.get("unit") for r in routes.values())
        if not managed:
            owner_load = copy.deepcopy(loaded)
            loaded = self.material._sensor_filament_status(now).get(key, {})
            # Presence at the inlet is not a completed load. Let the owning
            # backend prepare/feed an inserted strand when it records empty;
            # never use presence to resolve an unknown or already-loaded head.
            inserted = (isinstance(owner_load, dict) and owner_load.get("state") == "empty"
                        and loaded.get("state") == "loaded")
            if loaded.get("state") != "empty" and not inserted:
                raise ValueError("Head must be empty or contain an inserted, unloaded filament; resolve openACE state before loading")
        elif not isinstance(loaded, dict) or loaded.get("state") != "empty":
            raise ValueError("The head sensor must report empty before loading")
        if not managed:
            identity = copy.deepcopy(ace.get("management", {}).get("identity_settings", {}).get(key, {}).get("values", {}))
            target = identity.get("nozzle_temp", identity.get("temp", 0))
            if type(target) not in (int, float) or not math.isfinite(target) or target <= 0:
                raise ValueError("Set a filament temperature before loading")
            plan = {"owner": "openace", "direct": True, "head": key, "action": "load",
                    "source": "external:" + key, "target": target,
                    "destination": {"head": key, "unit": None, "slot": None},
                    "session": self.material.session_id, "ace_session": ace["session_id"],
                    "config_revision": ace["config_revision"], "loaded": loaded,
                    "owner_load": owner_load, "identity": identity}
            plan["command_generation"] = getattr(self.material, "_command_generation", 0)
            plan["token"] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
            plan["description"] = "Mount and heat Head %d. Insert filament when prompted." % (head + 1)
            return [plan]
        plans, sources = [], set()
        routes = ace.get("default_tool_map", {})
        for tool in range(32):
            route = routes.get(str(tool), {})
            if not isinstance(route, dict):
                continue
            unit, slot = route.get("unit"), route.get("slot")
            if (route.get("head") != key or not isinstance(unit, str) or not unit
                    or type(slot) is not int or not 0 <= slot <= 3
                    or str(tool) in ace.get("blocked_tools", {})):
                continue
            if ace.get("devices", {}).get("units", {}).get(unit, {}).get("connected") is not True:
                continue
            source = "%s:%d" % (unit, slot)
            if source in sources:
                continue
            identity = ace.get("inventory", {}).get(source)
            if (not isinstance(identity, dict) or not isinstance(identity.get("material"), str)
                    or not identity["material"] or not isinstance(identity.get("color"), str)):
                continue
            sources.add(source)
            plan = {"owner": "openace", "head": key, "action": "load", "source": source,
                    "tool": tool, "destination": {"head": key, "unit": unit, "slot": slot},
                    "session": self.material.session_id, "ace_session": ace["session_id"],
                    "config_revision": ace["config_revision"], "loaded": copy.deepcopy(loaded), "identity": copy.deepcopy(identity)}
            plan["command_generation"] = getattr(self.material, "_command_generation", 0)
            plan["token"] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
            plan["description"] = ("Load %s into Head %d using Tool T%d through openACE. " % (source, head + 1, tool)
                + "This can select/park the head, heat, feed and prime filament. "
                + "The backend owns movement and readiness checks. This does not start or resume a print.")
            plans.append(plan)
        if not plans:
            raise ValueError("No connected ACE slot with a configured filament is available for this head; external loading needs its separate preparation flow")
        return plans


    def _openace_unload_plan(self, head, action, now, ace_status_cache=None):
        if action != "unload":
            raise ValueError("Select a source-specific openACE Load plan")
        ace = self._openace_idle_status(now, ace_status_cache)
        key = "h%d" % head
        loaded = ace.get("loaded", {}).get(key, {})
        if not isinstance(loaded, dict):
            raise ValueError("openACE loaded state is unavailable")
        destination = loaded.get("destination", {})
        direct = isinstance(destination, dict) and destination.get("unit") is None and destination.get("slot") is None
        if direct:
            raise ValueError("This openACE version does not support managed unloading of externally fed filament")
        if (loaded.get("state") != "loaded" or loaded.get("verified") is not True
                or not isinstance(destination, dict) or destination.get("head") != key
                or (not direct and (not isinstance(destination.get("unit"), str) or not destination["unit"]
                or type(destination.get("slot")) is not int or not 0 <= destination["slot"] <= 3))):
            raise ValueError("A verified ACE-loaded source is required for this unload")
        source = "external:" + key if direct else "%s:%d" % (destination["unit"], destination["slot"])
        plan = {"owner": "openace", "head": key, "action": "unload", "source": source,
                "session": self.material.session_id, "ace_session": ace["session_id"],
                "config_revision": ace["config_revision"], "loaded": copy.deepcopy(loaded)}
        plan["command_generation"] = getattr(self.material, "_command_generation", 0)
        plan["token"] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
        plan["description"] = ("Unload Head %d from %s through openACE. " % (head + 1, source)
            + "This can select/park the head, heat, shape the tip and retract with ACE assistance. "
            + "This is not a distance-only retract. It does not eject the spool or resume a print.")
        return plan


    def _openace_filament_context(self, plan, now):
        # Preparation and the insertion wait yield to the reactor. A reviewed
        # plan must not authorize feeding into a replacement owner/job/config.
        binding = (getattr(self, "_openace_filament_cancel", None)
                   or getattr(self, "_openace_filament_recovery", None))
        if (binding is not None and self.material.printer.lookup_object("openace", None) is not binding["owner"]
                or plan.get("session") != self.material.session_id
                or not self.material._filament_context_valid(plan, now)):
            raise ValueError("Filament service context changed")
        ace = self._openace_idle_status(now)
        identity = (ace.get("management", {}).get("identity_settings", {}).get(plan["head"], {}).get("values", {})
                    if plan.get("direct") else ace.get("inventory", {}).get(plan.get("source"), {}))
        if (ace["session_id"] != plan["ace_session"]
                or ace["config_revision"] != plan["config_revision"]
                or plan["action"] == "load" and identity != plan["identity"]):
            raise ValueError("openACE filament context changed; review again")
        return ace


    def _finish_openace_filament_stop(self, plan, head):
        reactor = self.material.printer.get_reactor()
        run = self.material.printer.lookup_object("gcode").run_script_from_command
        self._openace_filament_context(plan, reactor.monotonic())
        self.material.filament_operation.update(phase="draining", steps=[
            {"phase": "draining", "label": "Wait for motion to stop"},
            {"phase": "cooling", "label": "Turn heater off"},
            {"phase": "verifying", "label": "Verify openACE stop"}])
        run("M400")
        self._openace_filament_context(plan, reactor.monotonic())
        self.material.filament_operation["phase"] = "cooling"
        heater = "extruder" if head == 0 else "extruder%d" % head
        run("SET_HEATER_TEMPERATURE HEATER=%s TARGET=0" % heater)
        self.material.filament_operation["phase"] = "verifying"
        ace = self._openace_filament_context(plan, reactor.monotonic())
        devices = ace.get("devices", {})
        abort = devices.get("abort", {})
        if (abort.get("requested") is not False or abort.get("scopes") != []
                or devices.get("stop_pending") != {}
                or self.material.printer.lookup_object(heater).get_status(reactor.monotonic()).get("target") != 0):
            raise ValueError("openACE stop or heater shutdown is not confirmed")
        # Stopped motion is separate from the owner's filament assessment.
        self.material.filament_operation.update(state="failed", cancelled=True, stopped=True, recovered=True,
            message="Stopped; heater off. Check openACE filament state before loading again.")


    def _openace_print_plan(self, gcmd, request, recheck=False):
        sd = self.material._print_admission(gcmd, openace=True)
        if not isinstance(request, dict) or set(request) != {
                "id", "session", "owner", "ace_session", "config_revision",
                "pairs", "file", "leveling"} or request["owner"] != "openace":
            raise ValueError("Invalid openACE print request fields")
        ticket = request["id"]
        if not isinstance(ticket, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", ticket):
            raise ValueError("Invalid print request ID")
        if request["session"] != self.material.session_id:
            raise ValueError("Printer session changed; refresh preview")
        if not recheck and (ticket in self.material._print_requests or len(self.material._print_requests) >= 1024):
            raise ValueError("Print request already attempted or capacity reached")
        if type(request["leveling"]) is not bool:
            raise ValueError("Invalid leveling option")
        ace = self.material.printer.lookup_object("openace").get_status(
            self.material.printer.get_reactor().monotonic())
        for key, expected in (("session_id", request["ace_session"]),
                              ("config_revision", request["config_revision"])):
            if type(expected) is not int or type(ace.get(key)) is not int or ace[key] != expected:
                raise ValueError("openACE configuration or session changed")
        if "operation" not in ace or ace["operation"] is not None:
            raise ValueError("An openACE operation is active or unavailable")
        pairs = request["pairs"]
        if not isinstance(pairs, list) or not pairs or len(pairs) > 32:
            raise ValueError("Invalid openACE print mapping")
        seen = set()
        routes = ace.get("default_tool_map", {})
        for pair in pairs:
            if (not isinstance(pair, list) or len(pair) != 2
                    or any(type(v) is not int or not 0 <= v <= 31 for v in pair)
                    or pair[0] in seen or str(pair[1]) not in routes):
                raise ValueError("Invalid or unavailable virtual tool mapping")
            seen.add(pair[0])
        # openACE's public start wrapper owns material/preflight validation and
        # freezes these virtual routes. WM+ never updates box_modify here.
        # The structured standalone filename transport does not alter the
        # separately owned openACE command transport's existing restrictions.
        if isinstance(request.get("file"), dict) and isinstance(request["file"].get("path"), str):
            if any(char in request["file"]["path"] for char in "#;"):
                raise ValueError("Unsupported print filename")
        full, identity = self.material._print_file(sd, request["file"])
        return None, full, identity


