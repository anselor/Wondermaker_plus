# SPDX-License-Identifier: GPL-3.0-or-later
"""Standalone Orca/AFC-compatible lane-to-tool mapping; no hardware movement."""
import re


class OrcaMapping:
    def __init__(self, material):
        self.material = material

    def register(self):
        printer = self.material.printer
        if any(printer.lookup_object(owner, None) is not None for owner in ('openace', 'AFC')):
            return
        gcode = printer.lookup_object('gcode')
        commands = gcode.get_status(printer.get_reactor().monotonic()).get('commands', {})
        for name, handler in (('RESET_AFC_MAPPING', self.reset), ('SET_MAP', self.set_map)):
            if name not in commands:
                gcode.register_command(name, handler, desc='Set standalone print tool mapping; no motion')

    def _admit(self, gcmd):
        try:
            self.material._print_admission(gcmd)
            self.material._begin_explicit_physical_action('print mapping')
        except ValueError as error:
            raise gcmd.error(str(error)) from error
        return self.material.printer.lookup_object('gcode')

    def _write(self, gcmd, gcode, tool, head):
        for suffix in ('', '_backup'):
            name = 'box_modify_t%d%s' % (tool, suffix)
            gcode.run_script_from_command('SAVE_VARIABLE VARIABLE=%s VALUE=%d' % (name, head))
            now = self.material.printer.get_reactor().monotonic()
            values = self.material.printer.lookup_object('save_variables').get_status(now)['variables']
            if values.get(name) != head:
                raise gcmd.error('Mapping write not confirmed: %s=%r; expected %d' % (name, values.get(name), head))

    def reset(self, gcmd):
        gcode = self._admit(gcmd)
        for tool in range(4):
            self._write(gcmd, gcode, tool, tool)
        gcmd.respond_info('Print tool mapping reset: T0/T1/T2/T3 use Heads 1/2/3/4')

    def set_map(self, gcmd):
        lane = gcmd.get('LANE', '').strip()
        target = gcmd.get('MAP', '').strip()
        source = re.fullmatch(r'(?:wmplus_tool_|[Tt])?([0-3])', lane)
        tool = re.fullmatch(r'[Tt]([0-3])', target)
        if source is None or tool is None:
            raise gcmd.error('SET_MAP requires LANE=wmplus_tool_0..3 and MAP=T0..T3')
        head, index = int(source.group(1)), int(tool.group(1))
        gcode = self._admit(gcmd)
        self._write(gcmd, gcode, index, head)
        gcmd.respond_info('Print mapping: T%d uses Head %d' % (index, head + 1))
