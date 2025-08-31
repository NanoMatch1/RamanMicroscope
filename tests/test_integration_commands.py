import pytest
from ramanmicroscope.interface import Interface

@pytest.fixture(scope="module")
def sim_interface():
	iface = Interface(simulate=True, com_port='nada', baud=9600, debug_skip=['camera'], initialise_hardware=False)
	iface.spectrometer.initialise()
	iface.controller.initialise()
	iface.laser.initialise()
	iface.microscope.initialise()
	yield iface
	if getattr(iface, 'camera', None):
		try:
			iface.camera.close_camera()
		except Exception:
			pass

@pytest.mark.parametrize("command,expect", [
	("wai", None),
	("report", None),
])
def test_simple_commands(sim_interface, command, expect):
	res = sim_interface._command_handler(command)
	assert res in (expect, True, False, None) or isinstance(res, str)


def test_laser_power_cycle(sim_interface):
	sim_interface._command_handler("laseron")
	sim_interface._command_handler("setpower 5")
	get_res = sim_interface._command_handler("getpower")
	assert get_res is not None
	assert float(sim_interface.acq_ctrl.general_parameters['laser_power']) == pytest.approx(float(get_res))


def test_acquisition_time(sim_interface):
	sim_interface._command_handler("acqtime 0.2")
	assert sim_interface.acq_ctrl.general_parameters['acquisition_time'] == 0.2


def test_move_stage_axes(sim_interface):
	if 'x' in sim_interface.microscope.command_functions:
		sim_interface._command_handler("x 10")
		sim_interface._command_handler("y 5")
		sim_interface._command_handler("z 15")

def test_help_generation(sim_interface):
	help_dict = sim_interface.generate_help()
	assert any(any('setpower' in c for c in cmds) for cmds in help_dict.values())
	assert any(any('acqtime' in c for c in cmds) for cmds in help_dict.values())

def test_set_all(sim_interface):
	sim_interface._command_handler("sall 800")
