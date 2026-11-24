# SPDX-License-Identifier: GPL-3.0-or-later
"""Give an otherwise unowned top-level G28 the existing Home request owner.

The original parsed command and registered handler are preserved. Stack
inspection is limited to G28; no per-line dispatcher or motion hook is added.
"""
import logging
import sys
import uuid


class RawHoming:
    def __init__(self, calibration):
        self.calibration = calibration
        self.original = None
        self.dispatch_code = None

    @property
    def installed(self):
        return self.original is not None

    def install(self):
        if self.installed:
            return
        gcode = self.calibration.gcode
        dispatch = getattr(gcode, '_process_commands', None)
        code = getattr(getattr(dispatch, '__func__', dispatch), '__code__', None)
        if code is None or not {'self', 'gcmd'}.issubset(code.co_varnames):
            logging.warning('Raw Home ownership unavailable: dispatcher context cannot be verified')
            return
        original = gcode.register_command('G28', None)
        if not callable(original):
            logging.warning('Raw Home ownership unavailable: no registered G28 handler')
            return
        try:
            gcode.register_command('G28', self.command)
        except Exception:
            gcode.register_command('G28', original)
            raise
        self.original, self.dispatch_code = original, code

    def _is_root_command(self, gcmd):
        root, frame = None, sys._getframe(1)
        try:
            for _ in range(80):
                if frame is None:
                    return root is gcmd
                if frame.f_code is self.dispatch_code and frame.f_locals.get('self') is self.calibration.gcode:
                    root = frame.f_locals.get('gcmd')
                frame = frame.f_back
            return False  # A deeper stack cannot prove a standalone command.
        finally:
            del frame

    def command(self, gcmd):
        calibration = self.calibration
        printer = calibration.printer
        # Nested macro/manager homing keeps its original caller's ownership.
        # The recursive G28 inside homing_override also takes this path.
        if (any(printer.lookup_object(owner, None) is not None for owner in ('openace', 'AFC'))
                or not self._is_root_command(gcmd)):
            return self.original(gcmd)
        sd = printer.lookup_object('virtual_sdcard', None)
        stats = printer.lookup_object('print_stats', None)
        now = printer.get_reactor().monotonic()
        if ((sd is not None and (sd.is_active() or sd.is_cmd_from_sd()))
                or stats is not None and stats.get_status(now).get('state') in ('printing', 'paused')):
            return self.original(gcmd)
        attempt = calibration._current_attempt
        if (calibration.active or calibration._saving or calibration._pending_cancel is not None
                or attempt is not None and attempt.get('state') == 'pending'):
            raise gcmd.error('Wait for the current operation to finish before standalone homing')
        material = printer.lookup_object('wm_material', None)
        active = getattr(material, '_material_operation_active', None)
        services = ([getattr(material, storage, None)
                     for name, storage in (('filament_operation', '_filament_service_component'),
                                           ('toolhead_operation', '_toolhead_service'))
                     if active(name)] if callable(active) else [])
        if services:
            # Deferred service callbacks have no outer G-code dispatcher frame.
            # Their G28 is still owned by that same immutable service/greenlet;
            # a different actor or stale service must retain the refusal.
            if any(service is None or not callable(getattr(service, 'wait_owner', None))
                   or service.wait_owner() is not service for service in services):
                raise gcmd.error('Wait for the current physical service before standalone homing')
            for service in services:
                service.check_operation_boundary('before service homing')
            return self.original(gcmd)
        parameters = gcmd.get_command_parameters()
        axes = '/'.join(axis for axis in 'XYZ' if axis in parameters) or 'X/Y/Z'
        binding = dict(HEX=b'G28'.hex(), SESSION=calibration.session,
                       REQUEST=uuid.uuid4().hex, TICKET=str(calibration._ticket_counter + 1), SEQUENCE='0')
        request = calibration.gcode.create_gcode_command('_WMP_HOME_COMMAND', '_WMP_HOME_COMMAND', binding)
        return calibration._run_operation(request, 'home',
            execute=lambda: self.original(gcmd), home_axes=axes, home_origin='raw')
