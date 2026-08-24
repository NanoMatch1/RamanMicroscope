"""
Unit tests for the simulated Arduino MEGA command protocol.

These cover the envelope command format in isolation (no Interface, no
hardware): o...o multi-move, g...g get positions, c...c check moving,
s...s set positions, m...m hardware commands, hXY homing, and the
image/raman mode shortcuts.

For the end-to-end workflow test that drives the whole application, see
test_headless_simulation.py.

Run with:  python -m pytest test_controller_simulated.py -q
"""

import pytest

from simulation import SimulatedArduinoSerial

# The Arduino terminates every response with CRLF. Kept as a named constant
# so the protocol's line ending is stated once rather than repeated in every
# assertion.
CRLF = '\r\n'


@pytest.fixture
def sim():
    return SimulatedArduinoSerial()


def test_multi_move_and_get_positions(sim):
    # move module 1A +1000 and 2X +200
    sim.send_command('o1A1000 2X200o')
    # multi-move returns no text, but state should be updated
    assert sim.current['1']['A'] == 1000
    assert sim.current['2']['X'] == 200
    # get positions should reflect those values
    resp = sim.send_command('g1A 2Xg')
    assert resp == '1A:1000 2X:200' + CRLF


def test_check_moving_always_false(sim):
    # no real motion, so always false
    sim.current['3']['Y'] = 500
    resp = sim.send_command('c3Yc')
    assert resp == '3Y:false' + CRLF


def test_set_positions(sim):
    # set current position to a new value
    resp = sim.send_command('s4Z-500s')
    assert resp == 'Set motor 4Z position to -500' + CRLF
    assert sim.current['4']['Z'] == -500


def test_shutter_on_off(sim):
    # The m...m envelope carries no padding spaces: the parser partitions the
    # envelope contents on the first space, so 'm gsh on m' would yield an
    # empty command token.
    resp_on = sim.send_command('mgsh onm')
    assert resp_on == 'Shutter open.' + CRLF
    assert sim.g_shutter is True

    resp_off = sim.send_command('mgsh offm')
    assert resp_off == 'Shutter closed.' + CRLF
    assert sim.g_shutter is False


def test_led_on_off(sim):
    resp_on = sim.send_command('mled onm')
    assert resp_on == 'LED on' + CRLF
    assert sim.led1 and sim.led2

    resp_off = sim.send_command('mled offm')
    assert resp_off == 'LED off' + CRLF
    assert not sim.led1 and not sim.led2


def test_ldr_reading(sim):
    # customize the simulated LDR value
    sim.ldr_value = 1234
    resp = sim.send_command('mld0m')
    assert resp == 't1234' + CRLF


def test_homing(sim):
    # put motor at nonzero, then home
    sim.current['2']['Y'] = 999
    resp = sim.send_command('h2Y')
    assert resp == 'Homed motor 2Y at position 0' + CRLF
    assert sim.current['2']['Y'] == 0


def test_raman_and_image_mode(sim):
    """
    The firmware's bare 'ramanmode'/'imagemode' commands move motor 2A by
    +/-6000 steps. Asserted against the firmware, which is ground truth:
    arduino_mega_develop.ino ramanMode() does stepperA2.move(6000) and
    imageMode() does stepperA2.move(-6000).

    NOTE: this is a LEGACY firmware path -- the firmware itself labels it
    "// Legacy mode commands". The application never sends these strings;
    Microscope.raman_mode() moves 2A by +/-100000 via the o...o envelope
    instead. This test covers the protocol as the firmware implements it,
    not the path the microscope actually uses. See MODERNIZATION.md 2.3.
    """
    # ramanmode adds +6000 to 2A
    resp_raman = sim.send_command('ramanmode')
    assert resp_raman == 'Moving to Raman Mode...' + CRLF
    assert sim.current['2']['A'] == 6000

    # imagemode subtracts 6000 from 2A
    resp_image = sim.send_command('imagemode')
    assert resp_image == 'Moving to Image Mode...' + CRLF
    assert sim.current['2']['A'] == 0  # back where it started


def test_unrecognized_command(sim):
    resp = sim.send_command('foobar')
    assert resp == 'Unrecognized command format' + CRLF
