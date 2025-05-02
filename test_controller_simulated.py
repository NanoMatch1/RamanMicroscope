import pytest
from simulated_controller import SimulatedArduinoController

@pytest.fixture
def sim():
    return SimulatedArduinoController()

def test_multi_move_and_get_positions(sim):
    # move module 1A +1000 and 2X +200
    sim.send_command('o1A1000 2X200o')
    # multi‐move returns no text, but state should be updated
    assert sim.current['1']['A'] == 1000
    assert sim.current['2']['X'] == 200
    # get positions should reflect those values
    resp = sim.send_command('g1A 2Xg')
    assert resp == '1A:1000 2X:200\n'

def test_check_moving_always_false(sim):
    # no real motion, so always false
    sim.current['3']['Y'] = 500
    resp = sim.send_command('c3Yc')
    assert resp == '3Y:false\n'

def test_set_positions(sim):
    # set current position to a new value
    resp = sim.send_command('s4Z-500s')
    assert resp == 'Set motor 4Z position to -500\n'
    assert sim.current['4']['Z'] == -500

def test_shutter_on_off(sim):
    # open shutter
    resp_on = sim.send_command('m gsh on m')
    assert resp_on == 'Shutter open.\n'
    assert sim.g_shutter is True
    # close shutter
    resp_off = sim.send_command('m gsh off m')
    assert resp_off == 'Shutter closed.\n'
    assert sim.g_shutter is False

def test_led_on_off(sim):
    # turn LEDs on
    resp_on = sim.send_command('m led on m')
    assert resp_on == 'LED on\n'
    assert sim.led1 and sim.led2
    # turn LEDs off
    resp_off = sim.send_command('m led off m')
    assert resp_off == 'LED off\n'
    assert not sim.led1 and not sim.led2

def test_ldr_reading(sim):
    # customize the simulated LDR value
    sim.ldr_value = 1234
    resp = sim.send_command('m ld0 m')
    assert resp == 't1234\n'

def test_homing(sim):
    # put motor at nonzero, then home
    sim.current['2']['Y'] = 999
    resp = sim.send_command('h2Y')
    assert resp == 'Homed motor 2Y at position 0\n'
    assert sim.current['2']['Y'] == 0

def test_raman_and_image_mode(sim):
    # ramanmode adds +6000 to 2A
    resp_r = sim.send_command('ramanmode')
    assert resp_r == 'Moving to Raman Mode...\n'
    assert sim.current['2']['A'] == 6000
    # imagemode subtracts 6000 from 2A
    resp_i = sim.send_command('imagemode')
    assert resp_i == 'Moving to Image Mode...\n'
    assert sim.current['2']['A'] == 0  # back where it started

def test_unrecognized_command(sim):
    resp = sim.send_command('foobar')
    assert resp == 'Unrecognized command format\n'
