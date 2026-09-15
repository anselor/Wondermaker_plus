"""Execute blob-cleaning macros; hardware probing is modeled."""
import copy
import pytest
from test_toolchange_return import MotionModel


class BlobModel(MotionModel):
    def __init__(self, temperature=220, fan=.35, state='standby', z=3):
        super().__init__(state=state, z=z)
        self.p['toolhead']['axis_minimum'] = dict(x=-15,y=-3,z=-5)
        self.p['toolhead']['axis_maximum'].update(x=312,y=350)
        self.p['fan_generic auxiliary_fan'] = {'speed':fan}
        self.p['fan'] = {'speed':0}
        self.p['save_variables']['variables']['thr_number'] = 4
        for i in range(4):
            name = 'extruder' if i == 0 else f'extruder{i}'
            self.p[name] = {'temperature':temperature,'target':temperature}

    def run(self, name, **params):
        if name.upper() in ('T0','T1','T2','T3','_APPLY_PRE_Z_OFFSET'):
            self.events.append((name.upper(),params.copy()))
            return
        super().run(name, **params)

    def command(self, line):
        name = line.split()[0].upper()
        if name == 'G28':
            self.events.append((name,line))
            self.p['toolhead']['homed_axes'] = 'xyz'
            return
        super().command(line)
        if name == 'SET_FAN_SPEED':
            args = dict(w.split('=',1) for w in line.split()[1:])
            self.p['fan_generic '+args['FAN']]['speed'] = float(args['SPEED'])
        elif name == 'SET_HEATER_TEMPERATURE':
            args = dict(w.split('=',1) for w in line.split()[1:])
            self.p[args['HEATER']]['target'] = float(args['TARGET'])
        elif name == 'TEMPERATURE_WAIT':
            self.events.append(('WAIT_POSITION',copy.deepcopy(self.p['gcode_move']['gcode_position'])))
        elif name == 'PROBE':
            self.events.append(('PROBE_POSITION',copy.deepcopy(self.p['gcode_move']['gcode_position'])))
            gm = self.p['gcode_move']
            gm['gcode_position']['z'] = 0.
            gm['position']['z'] = gm['homing_origin']['z']
            self.p['toolhead']['position']['z'] = gm['position']['z']


@pytest.mark.parametrize('macro,lift', [('NOZZLE_PREPARE',80),('POP',25)])
def test_blob_cools_at_original_front_position_then_only_lifts(macro,lift):
    m = BlobModel()
    m.run(macro,T='0')
    position = next(value for name,value in m.events if name == 'WAIT_POSITION')
    expected = dict(x=150,y=1,z=1) if macro == 'NOZZLE_PREPARE' else dict(x=100,y=2,z=2)
    assert position == pytest.approx(expected)
    wait = next(i for i,(name,_) in enumerate(m.events) if name == 'WAIT_POSITION')
    moves = [value for name,value in m.events[wait:] if name == 'MOVE']
    assert len(moves) == 1
    assert moves[0]['gcode_position'] == pytest.approx(dict(position,z=lift))
    assert not any(name == 'SET_FAN_SPEED' for name,_ in m.events)
    assert m.p['fan_generic auxiliary_fan']['speed'] == .35


@pytest.mark.parametrize('macro', ['NOZZLE_PREPARE','POP'])
@pytest.mark.parametrize('state', ['printing','paused'])
def test_blob_maintenance_rejects_active_print_before_any_command(macro,state):
    m = BlobModel(state=state)
    with pytest.raises(ValueError,match='idle maintenance'):
        m.run(macro,T='0')
    assert [name for name,_ in m.events] == [macro]
