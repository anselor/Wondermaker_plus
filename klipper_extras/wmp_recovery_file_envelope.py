# SPDX-License-Identifier: GPL-3.0-or-later
"""Pure bounded file clearance analysis for the explicitly supported WM dialect.

No persistence or printer commands. Supported installations load these modules
from their installed files; live monkeypatching is outside this contract. Callers supply independently verified macro
and installed-transform source provenance and bind the result to the entire immutable job file.
"""
import hashlib
import json
import math
import re

MAX_BYTES = 256 * 1024 * 1024
MAX_LINE = 8192
NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)'
PARAM = re.compile(r'([A-Z])(' + NUMBER + r')')


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def macro_digest(body):
    # Match Klipper's config whitespace handling, not arbitrary macro semantics.
    lines = [line.strip() for line in body.splitlines()]
    return hashlib.sha256('\n'.join(line for line in lines if line).encode()).hexdigest()


def effect_contract(settings, transforms):
    """Qualify the known macro bodies and installed transform source bytes."""
    for name, digest in MACROS.items():
        source = settings.get('gcode_macro ' + name.lower(), {}).get('gcode')
        if not isinstance(source, str) or macro_digest(source) != digest:
            raise ValueError('File-derived recovery unsupported: changed/missing macro ' + name)
    if transforms != TRANSFORMS:
        raise ValueError('File-derived recovery unsupported: motion/mesh transform source changed')
    return {'version': 1, 'sha256': hashlib.sha256(canonical({'macros': MACROS, 'transforms': transforms})).hexdigest()}


def classified_command(line, started, ended):
    """Shared bounded-dialect syntax; callers own coordinates or tool sets."""
    if ended:
        raise ValueError("Command after PRINT_END")
    parts = line.split(None, 1)
    command, args = parts[0].upper(), parts[1].strip() if len(parts) > 1 else ''
    if command == 'START_PRINT':
        if started: raise ValueError('Repeated startup')
        tokens = args.split()
        if any(not re.fullmatch(r'[A-Z_]+=' + NUMBER, token) for token in tokens):
            raise ValueError('Unsupported startup parameters')
        values = dict(token.split('=', 1) for token in tokens)
        allowed = {'EXTRUDER','BED','CHAMBER','INITIAL_TOOL','MESH_MIN_X','MESH_MIN_Y','MESH_MAX_X','MESH_MAX_Y','PROBE_COUNT_X','PROBE_COUNT_Y','ADAPTIVE','ADAPTIVE_MARGIN'}
        if len(values) != len(tokens) or set(values)-allowed or not re.fullmatch('[0-3]', values.get('INITIAL_TOOL','0')):
            raise ValueError('Unsupported startup parameters')
        return command, values
    if command == 'PRINT_END' or re.fullmatch('T[0-3]', command):
        if args or not started: raise ValueError('Invalid end/tool selection')
        return command, {}
    if command == 'SET_VELOCITY_LIMIT':
        if any(not re.fullmatch(r'(?:VELOCITY|ACCEL|ACCEL_TO_DECEL|MINIMUM_CRUISE_RATIO|SQUARE_CORNER_VELOCITY)=' + NUMBER, token) for token in args.split()):
            raise ValueError('Unsupported velocity parameter')
        return command, {}
    values = {}
    for token in args.split():
        match = PARAM.fullmatch(token)
        if not match or match[1] in values: raise ValueError('Unsupported parameter syntax')
        value = float(match[2])
        if not math.isfinite(value): raise ValueError('Nonfinite parameter')
        values[match[1]] = value
    allowed = {'G21':'','G90':'','G91':'','M82':'','M83':'','M400':'',
               'G92':'E','G0':'XYZEF','G1':'XYZEF','M104':'ST','M109':'SRT',
               'M140':'S','M190':'SR','M106':'SP','M107':'P','M220':'S','M221':'S'}
    if command == 'G92' and set(values) != {'E'}: raise ValueError('Unsupported coordinate reset')
    if command not in allowed or set(values)-set(allowed[command]):
        raise ValueError('Unsupported command or parameter: ' + command)
    if command in ('G0','G1') and not started: raise ValueError('Move before startup')
    return command, values


class ToolUsage:
    """Complete supported-file membership, never print admission authority."""
    def __init__(self):
        self.tools = set()
        self.started = self.ended = False
        self.size = 0
        self.error = ''

    def feed(self, raw):
        self.size += len(raw)
        if self.error: return
        try:
            if len(raw) > MAX_LINE or self.size > MAX_BYTES:
                raise ValueError('File exceeds bounded supported tool scan')
            line = raw.split(b';', 1)[0].decode('ascii').strip()
            if not line: return
            command, values = classified_command(line, self.started, self.ended)
            if command == 'START_PRINT':
                self.started = True
                self.tools.add(int(values.get('INITIAL_TOOL', '0')))
            elif command == 'PRINT_END': self.ended = True
            elif re.fullmatch('T[0-3]', command): self.tools.add(int(command[1]))
        except (ValueError, UnicodeError) as error:
            self.error = str(error)

    def complete(self):
        if self.error or not self.started or not self.ended:
            raise ValueError(self.error or 'Complete START_PRINT/PRINT_END tool usage unavailable')
        return sorted(self.tools)


def analyze(stream, execution, context, matrix, fade_target, proof, yield_hook=None):
    if context.get('file_effect_contract') != proof or proof.get('version') != 1:
        raise ValueError('No matching print-start macro/transform proof; file-derived clearance unavailable for this older or modified job')
    offsets, mapping = context.get('offsets'), execution.get('mapping')
    if (not isinstance(offsets, list) or len(offsets) != 4 or any(not isinstance(row, list) or len(row) != 3 or
            any(not finite(v) for v in row) for row in offsets) or not isinstance(mapping, list) or len(mapping) != 4
            or any(type(v) is not int or not 0 <= v < 4 for v in mapping)):
        raise ValueError('Invalid file-analysis head offsets/mapping')
    if (not isinstance(matrix, (list, tuple)) or not 2 <= len(matrix) <= 256 or
            not isinstance(matrix[0], (list, tuple)) or not 2 <= len(matrix[0]) <= 256 or
            any(not isinstance(row, (list, tuple)) or len(row) != len(matrix[0]) or any(not finite(v) for v in row) for row in matrix)
            or not finite(fade_target)):
        raise ValueError('Invalid file-analysis mesh/fade bound')
    head_name = execution.get('head', '')
    if head_name not in ('h0', 'h1', 'h2', 'h3') or type(context.get('tool')) is not int or context['tool'] not in range(4):
        raise ValueError('Invalid file-analysis current/probe head')
    current_head, probe = int(head_name[1]), context['tool']
    parser, logical = execution.get('parser_position'), execution.get('gcode_position')
    if any(not isinstance(v, list) or len(v) != 4 or any(not finite(x) for x in v) for v in (parser, logical)):
        raise ValueError('Invalid file-analysis checkpoint coordinates')
    anchor = parser[2] - logical[2] - (offsets[current_head][2] - offsets[probe][2])
    frame_upper = anchor + max(row[2] - offsets[probe][2] for row in offsets)
    # The execution fingerprint uses vendor grid values rounded to 6 decimals.
    # Cover sub-micron differences in raw interpolation sharing that fingerprint.
    mesh_upper = max(0., fade_target, max(max(row) for row in matrix)) + .000001
    # Startup purge is a reviewed macro effect, independent of slicer headers.
    ceiling = max(0., .4 + mesh_upper, .4 + frame_upper + mesh_upper)
    xyz = [None, None, None]
    absolute = absolute_e = True
    tool = None
    started = ended = boundary = False
    position = 0
    digest = hashlib.sha256()
    checkpoint = execution['file_position']
    while True:
        raw = stream.readline(MAX_LINE + 1)
        if not raw:
            break
        start = position
        position += len(raw)
        if len(raw) > MAX_LINE or position > MAX_BYTES:
            raise ValueError('File-derived recovery exceeds bounded line/file size at byte %d' % start)
        digest.update(raw)
        try:
            line = raw.decode('ascii').split(';', 1)[0].strip()
        except UnicodeError:
            # UTF-8 slicer comments are harmless; commands must remain ASCII.
            try: line = raw.split(b';', 1)[0].decode('ascii').strip()
            except UnicodeError: raise ValueError('Non-ASCII G-code at byte %d' % start)
        if line:
            if ended:
                raise ValueError('Command after PRINT_END at byte %d' % start)
            try:
                command, values = classified_command(line, started, ended)
            except ValueError as error:
                raise ValueError('File-derived recovery %s at byte %d' % (error, start)) from error
            def refuse(reason='unsupported command'):
                raise ValueError('File-derived recovery %s: %s at byte %d' % (reason, command, start))
            if command == 'START_PRINT':
                tool = int(values.get('INITIAL_TOOL','0')); started = True; xyz = [None,None,None]; absolute = True
            elif command == 'PRINT_END':
                ended = True
            elif re.fullmatch('T[0-3]', command):
                tool = int(command[1])
            elif command == 'SET_VELOCITY_LIMIT':
                pass
            else:
                if command in ('G21','G90','G91','M82','M83','M400'):
                    if values: refuse('unexpected parameters')
                    if command in ('G90','G91'): absolute = command == 'G90'
                    if command in ('M82','M83'): absolute_e = command == 'M82'
                elif command == 'G92':
                    if set(values) != {'E'}: refuse('unsupported coordinate reset (only G92 E is modeled)')
                elif command in ('G0','G1'):
                    if not started or set(values)-set('XYZEF'): refuse('unsupported move')
                    previous = list(xyz)
                    for i, axis in enumerate('XYZ'):
                        if axis in values:
                            if not absolute and xyz[i] is None: refuse('relative move before known coordinate')
                            xyz[i] = values[axis] if absolute else xyz[i] + values[axis]
                    # Count every E-bearing XYZ move, including retractions.
                    # This does not guess tool-dependent absolute E origins.
                    if 'E' in values and set(values)&set('XYZ'):
                        zs = [previous[2], xyz[2]]
                        if any(z is None for z in zs): refuse('deposition before known Z')
                        ceiling = max(ceiling, max(zs) + frame_upper + mesh_upper)
                elif command in ('M104','M109','M140','M190','M106','M107','M220','M221'):
                    allowed = {'M104':'ST','M109':'SRT','M140':'S','M190':'SR','M106':'SP','M107':'P','M220':'S','M221':'S'}[command]
                    if set(values)-set(allowed): refuse('unsupported non-motion parameters')
                else:
                    refuse()
        if position == checkpoint:
            if (tool is None or mapping[tool] != current_head or any(x is None for x in xyz)
                    or any(not math.isclose(x,y,abs_tol=1e-5) for x,y in zip(xyz, logical[:3]))
                    or absolute != execution.get('absolute_coordinates') or absolute_e != execution.get('absolute_extrude')):
                raise ValueError('Hashed-file prefix does not match saved checkpoint tool/coordinates/modes')
            boundary = True
        if yield_hook and position // 1048576 != start // 1048576:
            yield_hook()
    if not boundary or position != execution['file']['size'] or digest.hexdigest() != execution['file']['sha256']:
        raise ValueError('Whole-file hash/size or completed checkpoint boundary changed')
    return {'version':1, 'job_id':execution['job_id'], 'file_sha256':digest.hexdigest(), 'max_z':float(math.ceil(ceiling))}

# Reviewed stock-transform and delivered macro effects, not arbitrary names.
TRANSFORMS = {'bed_mesh': 'a003072f5b0884fdc94cc53c7cb3a8ee970e66591d8a3dbeb83abad4e1b530f7',
 'gcode_move': 'c65edf115d2170182959fa3f06fb554e6d05fba7875409fd9fec7f52d20873ff'}
MACROS = {'BED_MESH_CALIBRATE': 'a8e427576c00d47d42734ad1b2ee3a3e44174001ae78a3ef9662a5d27efca972',
 'BED_MESH_PROFILE': 'c940b1137b0353060f3d2afd3c91a6ae1087411c9e4087acf47cee9d82023365',
 'E_axis_move': '0ce073e297d0667343180e4d176df4cfa616794107b0f31900ece92383e1483c',
 'LOCK': '947e9b5612503fc42d57fc7e08c7b068685b3ad2a6af28654808f1bb53c068c0',
 'M104': 'c17c29905ec12b7a5558667785340455ca84c049189f6d3cdbf9af77fea64eb8',
 'M106': '695a112ac3288d9b8c4b2e1fb3459bd4f0c2eb18c27c4e4d4bc0751685f689a9',
 'M107': '52d90226e4c2ee3e77e26afcbcb93642c94d1cfd001136ba2857a3addac3ae59',
 'M109': 'f24f3719ef46f83740d0d37c51ba4f40cf11c01bb6f393a6d9b47305ca203759',
 'M190': '2085a4d0b675fb982ff7df78959a6d65cf6ee2938792ec54b71a753213503bf9',
 'M221': '5fae08e19a1ff1d5b908033159bd77024a0a5e1304ee49f56ddda740346bde6f',
 'PAUSE': 'aa9b1875673676c6bb9ac21ca4583ba9b0d7e135713c717c632e23ab7b369dff',
 'PRINT_END': 'a50bacb8ee0cb9d0ae88360598c50c06246256c6e2a046358ca0231ea67cc7d2',
 'RESET_FLOW_EXTRUDER': 'de7604820e2d4ac07bda71c721f184539ee6b914ae0fd40b5887e0fc0480e4c5',
 'START_PRINT': 'eed46f7b31b343ddb17674844b1595211cec92cde0be50b8ddc1795e44faa792',
 'T0': 'c0d34e22efdbfdbe61b6a8aebbfb11fdb6904da0523a0a362890da0e0c6fd829',
 'T1': '8b5d1a64be635a646957ee39e5d0a982769e8dd0aa2a9266df64a1ff63ab9a8d',
 'T2': 'b363c6ebdf4a7b56e2b757ee0525b5c659289f83099947bf45c78a512dd83a03',
 'T3': '100982e709549e70d2adec3e4187963c5f38756161ad4e440df2a7e2912d03bf',
 'UNLOCK': '8b39edaeef41b764341c8a87c692882f57f49472a990a79a1f093798f75dbefc',
 'UNLOCK_TOOL_FINISH': 'a290e3b161cd9cbc097f6c29e5a16f880f1526ac664464ff09ab54e644300dd2',
 'WIPE_NOZZLE': '0c57073cc7d495e1dbcffadb3dd1fc384b2ab84cfcf5847841a424931f9a1d1d',
 '_CHANGE_TOOL': 'c02a44844df4626c9c1b36ea3841e3d4777d1bd2be862cbac691df3fb34740cd',
 '_CHANGING_TOOL': 'd328c2d5e0ad1d1a9458705d6c67252bdae402024e517d69c215cfa4a6867743',
 '_CHECK_AND_LOCK': 'afae2f4d9266703134b38e02e3d196eff1923e617dbcbbedace8c5ee6ba341ed',
 '_CHECK_AND_UNLOCK': '4c089f602e3059bcb6a82834c3ec7944acd8c26c0e687f34d7b28dbcfcbb7186',
 '_CHECK_CHANGE_TOOL': '92c1a48322672550c6bdfbf1479ecf0bfd80a35e8ba0b05c44b5f9a8500c192d',
 '_CHECK_CHANGE_TOOL_AGAIN': '1a13bb77f05507db06c53210d5abb8d66bee038a4d24af99c574ce6ba2e24eaa',
 '_CHECK_T_SEQUENCE': '46ce7be73d491ddb0f1df2994d341624cf5f23e8b8d25470f52daecc3b8c5b23',
 '_ENABLE_SENSOR': 'd6fec5f6362847e2fe7f5411d10c9a382500e44f8796c3ea6549f1cdb3af1889',
 '_LOCK_CHECK': 'f0ddd66e7c1ffebe267dfb04b5c02409b6ac6d7e771fdcbfb95ad7f892b8a7c5',
 '_LOCK_TOOL': '8bfb13044ca7b9964cbdf2d8c3eda11ffdb7875013f5a19a38ffe87cc93fe59f',
 '_LOCK_TOOL_FINISH': 'aca105d157c4b38e7a570edaa54f0c5eaaec96ba494da2b2d95ef4aa3fea8133',
 '_OFFSET_SET': 'b9c8f8c2f06456c3909f306ee02618a7b66ebcb4c5e4c6ebe601dc7232f1bbb9',
 '_UNLOCK_TOOL': '89ca443d96c0719b0c6cb610cdc953606c50f0676e1b85459f6d359ca054fa1b',
 '_WAIT_TOOL_TEMPERATURE': 'e473d8f078be682a9f15c413a7c77d707773d07f56c04a52181688edba957d72',
 '_WMP_ABORT_DOCKING': 'f10414b038b0e38918d7f05bf089c2e10286c86fcf7a507ba59a409e794b3b44',
 '_WMP_CALIBRATION_CLEARANCE': '198fbd7b8a9dc0e1fc1ed3fd429e2fe45430ec28a8d8fe1e8a0b14094193de1c',
 '_WMP_PRINT_CONTEXT_CLEAR': '8767679d745b68ba596910ed93de13aab43176280b1e7ca8b079d07aa9f7c61e',
 '_WMP_PRINT_CONTEXT_COMMIT': '7ffa276bc03a4641ccf857b085607c3738eee290df1ab1852505255a3c8ca8d0',
 '_WMP_PRINT_END_CLEARANCE_AND_WIPE': 'c2a0ba1ffe8ba5892c9234e1bac7f6be11aa36dd5f220002eb2b8f95d0bb7f05',
 # Clearance refusal now pauses at a typed, non-extruding stage boundary.
 # Successful stock movement/offset effects are unchanged; explicit retries
 # preserve the original return context and never replay completed wiping.
 '_WMP_TOOL_RETURN_BEGIN': '8c794eec2350652e75ea46ace1eb3f0f832682a25914708b1dddf271b16e1a75',
 '_WMP_TOOL_RETURN_FINISH': '5dadaa283de49c84b3f9f75b38209ee67a7a581dd3bcf9199fb0e3f93c7e5e33',
 '_check_current_extruder_value': '13de8759f4b80eeb054ef0e77b6a49634a66dcf6fe1788477c39ce47bd5602a2',
 '_check_hall_sensor': '1c674898d630f7826dab40ecdaf6e5ac6def92d12f17f8e9a4a2662614900778',
 '_check_tool_exist': '9863f9466d26cae0b6f63d4c78315cd25c026b764162f9ad370f493525aa9862',
 '_descend_z': 'bab8fa237afce501260a5eaabdf3594b05653c074720dfea8dfe0761ef05cc9a',
 '_raise_z': '10c1de99ba42069e64ec6c25a36dd8732d85be7d3cc36787c54035ae7e7031e2'}
