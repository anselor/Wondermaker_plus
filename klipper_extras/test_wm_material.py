from wm_material import parse_slot_materials, material_name, material_temp

SAMPLE = """[printer]
model=2

[slot]
; orca-color0=#8ED8F8
color0=18
material0=0
; orca-color1=#FF0000
color1=3
material1=3
material2 = 12
material3=bogus

[nozzle]
type0=0
"""


def test_parses_slots_and_skips_bad_values():
    assert parse_slot_materials(SAMPLE) == {0: 0, 1: 3, 2: 12}


def test_ignores_material_keys_outside_slot_section():
    assert parse_slot_materials("[other]\nmaterial0=5\n") == {}


def test_names_and_temps():
    assert material_name(3) == "PETG" and material_temp(3) == 250
    assert material_name(12) == "TPU" and material_temp(12) == 230
    assert material_name(-1) == "Unknown" and material_temp(99) == 0
