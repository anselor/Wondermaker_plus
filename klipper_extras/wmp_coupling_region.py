# SPDX-License-Identifier: GPL-3.0-or-later
"""Invocation-bound permission to finish coupling and retreat after ordinary Stop."""
import copy
import math


class CouplingRegions:
    def __init__(self, service):
        self.service = service
        self.material = service.material
        self.printer = self.material.printer
        self.scope = None

    def install(self):
        gcode = self.printer.lookup_object('gcode')
        for name, kind in (('_UNLOCK_TOOL', 'dock'), ('_LOCK_TOOL', 'pickup')):
            original = gcode.register_command(name, None)
            if original is None:
                continue
            if getattr(original, '_wmp_coupling_region', None) is self:
                gcode.register_command(name, original)
                continue
            original = getattr(original, '_wmp_coupling_original', original)
            def wrapped(gcmd, original=original, kind=kind):
                return self.invoke(original, kind, gcmd)
            wrapped._wmp_coupling_region = self
            wrapped._wmp_coupling_original = original
            gcode.register_command(name, wrapped)
            # The retained dispatcher decorates extended-command handlers.
            registered = getattr(gcode, 'ready_gcode_handlers', {}).get(name, wrapped)
            registered._wmp_coupling_region = self
            registered._wmp_coupling_original = original

    def _external(self):
        return any(self.printer.lookup_object(n, None) is not None for n in ('openace', 'AFC'))

    def _saved(self):
        return self.printer.lookup_object('save_variables').get_status(
            self.printer.get_reactor().monotonic()).get('variables', {})

    @staticmethod
    def _geometry(saved):
        return tuple(copy.deepcopy(saved.get('t%d_%s' % (h, field)))
                     for h in range(4) for field in ('position', 'offset'))

    def _fault_free(self):
        saved = self._saved()
        return (not self.printer.is_shutdown()
                and not getattr(self.printer, 'quick_stop_flag', False)
                and type(saved.get('fail_flag')) is int and saved['fail_flag'] == 0
                and not self._external())

    def invoke(self, original, kind, gcmd):
        if self._external():
            return original(gcmd)
        if self.scope is not None:
            raise gcmd.error('Another coupling invocation is still active')
        if not self._fault_free():
            raise gcmd.error('Resolve the printer fault before coupling')
        try:
            from .wmp_stop_points import check_operation_boundary
        except ImportError:
            from wmp_stop_points import check_operation_boundary
        check_operation_boundary(self.printer, 'before tool docking' if kind == 'dock' else 'before tool pickup')
        if self.material._print_cancel_active():
            raise gcmd.error('Print cancellation requested; coupling was not admitted')
        head = gcmd.get_int('T')
        if kind == 'dock' and head == 99:
            return original(gcmd)  # Empty-carriage UNLOCK has no dock approach/back-off.
        sd = self.printer.lookup_object('virtual_sdcard', None)
        stats = self.printer.lookup_object('print_stats', None)
        gc = self.printer.lookup_object('gcode')
        scope = dict(kind=kind, head=head, actor=self.service._current_actor(),
                     session=self.material.session_id,
                     generation=getattr(self.material, '_command_generation', 0),
                     owners=tuple((n, self.printer.lookup_object(n, None)) for n in
                                  ('wm_material', 'wmp_recovery', 'openace', 'AFC',
                                   'gcode', 'virtual_sdcard', 'print_stats')),
                     mutex=gc.get_mutex(), handle=getattr(sd, 'current_file', None),
                     filename=getattr(stats, 'filename', None),
                     from_sd=sd.is_cmd_from_sd() if sd is not None else False,
                     active=False, geometry=None)
        self.scope = scope
        try:
            return original(gcmd)
        finally:
            if self.scope is scope:
                self.scope = None  # Failure before END must not leak permission.

    def _owned(self, scope):
        if (scope is None or self.scope is not scope
                or self.service._current_actor() is not scope['actor']
                or getattr(self.material, '_toolhead_service', None) is not self.service
                or self.material.session_id != scope['session']
                or any(self.printer.lookup_object(n, None) is not owner for n, owner in scope['owners'])):
            return False
        gcode = self.printer.lookup_object('gcode')
        sd = self.printer.lookup_object('virtual_sdcard', None)
        stats = self.printer.lookup_object('print_stats', None)
        return (gcode.get_mutex() is scope['mutex'] and scope['mutex'].test()
                and getattr(sd, 'current_file', None) is scope['handle']
                and getattr(stats, 'filename', None) == scope['filename']
                and (sd.is_cmd_from_sd() if sd is not None else False) is scope['from_sd'])

    def _live_stop(self, scope):
        if not self._owned(scope) or not scope['active'] or not self._fault_free():
            return False
        cancellation = self.material._cancellation()
        live = getattr(cancellation, '_print_cancel_live_binding', None)
        record = getattr(cancellation, '_print_cancel', {})
        return (self.material._print_cancel_active() and scope['handle'] is not None
                and live is not None and live.get('session') == scope['session']
                and live.get('handle') is scope['handle'] and live.get('file') == scope['filename']
                and record.get('id') == live.get('cancel_id') and record.get('phase') == 'stopping'
                and getattr(cancellation, '_coupling_finish_generation', None) == scope['generation']
                and getattr(self.material, '_command_generation', 0) == scope['generation'] + 1
                and self._geometry(self._saved()) == scope['geometry'])

    def allows(self, gcmd):
        scope = self.scope
        if not self._live_stop(scope):
            return False
        if (gcmd.get('SESSION') != scope['session']
                or gcmd.get_int('GENERATION') not in (scope['generation'], scope['generation'] + 1)):
            return False
        name = getattr(gcmd, 'get_command', lambda: '')().upper()
        if name == '_WMP_COUPLING_STROKE':
            return gcmd.get_int('LOCK') == (1 if scope['kind'] == 'pickup' else 0)
        if name == '_WMP_CHECK_DOCK_SUPPORT':
            return scope['kind'] == 'dock' and gcmd.get_int('HEAD') == scope['head']
        if name == '_WMP_CHECK_PICKUP_RELEASE':
            return scope['kind'] == 'pickup' and gcmd.get_int('HEAD') == scope['head']
        if name == '_WMP_COUPLING_END':
            return gcmd.get('KIND') == scope['kind'] and gcmd.get_int('HEAD') == scope['head']
        return False

    def begin(self, gcmd):
        scope = self.scope
        if (not self._owned(scope) or scope['active'] or not self._fault_free()
                or self.material._print_cancel_active()
                or gcmd.get('SESSION') != scope['session']
                or gcmd.get_int('GENERATION') != scope['generation']
                or getattr(self.material, '_command_generation', 0) != scope['generation']
                or gcmd.get('KIND') != scope['kind'] or gcmd.get_int('HEAD') != scope['head']):
            raise gcmd.error('Coupling approach was not admitted by its original invocation')
        scope['geometry'] = self._geometry(self._saved())
        scope['active'] = True

    def end(self, gcmd):
        scope = self.scope
        if (not self._owned(scope) or not scope['active'] or not self._fault_free()
                or gcmd.get('KIND') != scope['kind'] or gcmd.get_int('HEAD') != scope['head']
                or self._geometry(self._saved()) != scope['geometry']):
            raise gcmd.error('Coupling completion ownership or printer state changed')
        self.material._check_command_generation(gcmd, coupling_region=True, coupling_owner=self.service)
        stopped_pickup = scope['kind'] == 'pickup' and self._live_stop(scope)
        if stopped_pickup:
            # The enclosing _CHECK_CHANGE_TOOL normally adopts this head. It
            # must not run after Stop (its offset application requests travel).
            # Preserve a coherent selected head/frame here without any motion.
            offset = scope['geometry'][scope['head'] * 2 + 1]
            if (not isinstance(offset, (list, tuple)) or len(offset) != 3
                    or any(type(v) not in (int, float) or not math.isfinite(v) for v in offset)):
                raise gcmd.error('Mounted head offset is unavailable after coupling')
            heater = 'extruder' if scope['head'] == 0 else 'extruder%d' % scope['head']
            for command in ('ACTIVATE_EXTRUDER EXTRUDER=' + heater,
                            'SAVE_VARIABLE VARIABLE=current_extruder VALUE=%d' % scope['head'],
                            'SET_GCODE_OFFSET X=%.17g Y=%.17g Z=%.17g MOVE=0' % tuple(offset)):
                if not self._live_stop(scope):
                    raise gcmd.error('Mounted head adoption lost its original command owner')
                self.printer.lookup_object('gcode').run_script_from_command(command)
            if not self._live_stop(scope):
                raise gcmd.error('Mounted head adoption lost its original command owner')
        scope['active'] = False
        if scope['kind'] == 'pickup' and not stopped_pickup:
            # Other owners already finish their own offset/extruder adoption
            # before their existing post-mount Stop checkpoint.
            return
        try:
            from .wmp_stop_points import check_operation_boundary
        except ImportError:
            from wmp_stop_points import check_operation_boundary
        dock = scope['kind'] == 'dock'
        check_operation_boundary(self.printer,
            'after verified tool docking' if dock else 'after verified tool pickup',
            phase='tool_docked' if dock else 'tool_picked_up',
            state='head docked and carriage backed off' if dock else 'head mounted and carriage backed off')
