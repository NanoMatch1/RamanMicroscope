import pytest
import sys
import os

from ramanmicroscope.interface import Interface

# Basic integrated test harness executing representative commands through the command handler.
# Uses simulate=True so all hardware paths use internal simulation logic.

@pytest.fixture(scope="module")
def sim_interface():
    iface = Interface(simulate=True, com_port='COM_TEST', baud=9600, debug_skip=['camera'], initialise_hardware=False)
    # Initialise only minimal components needed for commands that rely on hardware init
    # For now call initialise on spectrometer/controller/laser (camera skipped intentionally)
    iface.spectrometer.initialise()
    iface.controller.initialise()
    iface.laser.initialise()
    iface.microscope.initialise()
    return iface

@pytest.mark.parametrize("command,expect", [
    ("wai", None),          # where_am_i prints status; return may be None
    ("report", None),       # toggles/reporting
])
def test_simple_commands(sim_interface, command, expect):
    res = sim_interface._command_handler(command)
    # Just ensure handler didn't raise & returns sane sentinel
    assert res in (expect, True, False, None) or isinstance(res, str)


def test_laser_power_cycle(sim_interface):
    # set power then read back
    set_res = sim_interface._command_handler("setpower 5")
    get_res = sim_interface._command_handler("getpower")
    assert get_res is not None
    # Accept approximate match since simulation may coerce
    assert float(sim_interface.acq_ctrl.general_parameters['laser_power']) == pytest.approx(float(get_res))


def test_acquisition_time(sim_interface):
    sim_interface._command_handler("acqtime 0.2")
    assert sim_interface.acq_ctrl.general_parameters['acquisition_time'] == 0.2


def test_move_stage_axes(sim_interface):
    # Expect motion command via direct motor map shorthand (e.g., x 10)
    if 'x' in sim_interface.microscope.command_functions:
        sim_interface._command_handler("x 10")
        # Cannot easily assert position without reading from controller; just ensure no exception


def test_help_generation(sim_interface):
    help_dict = sim_interface.generate_help()
    # Ensure a couple of known commands documented
    assert any(any('setpower' in c for c in cmds) for cmds in help_dict.values())
    assert any(any('acqtime' in c for c in cmds) for cmds in help_dict.values())
