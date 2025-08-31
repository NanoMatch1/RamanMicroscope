"""Contract tests for driver Protocols (Phase 2)."""
from __future__ import annotations
import math, pytest
from ramanmicroscope.interface import Interface
from ramanmicroscope.drivers import ControllerProtocol, LaserProtocol, SpectrometerProtocol, CameraProtocol

@pytest.fixture(scope="module")
def sim_interface():
    interface = Interface(simulate=True, initialise_hardware=True)
    yield interface
    try:
        interface.camera.close_camera()
    except Exception:
        pass

def test_controller_protocol(sim_interface):
    ctrl = sim_interface.controller
    assert isinstance(ctrl, ControllerProtocol)
    res = ctrl.send_command('g1A g2Xg')
    assert res is not None

def test_laser_protocol(sim_interface):
    laser = sim_interface.laser
    assert isinstance(laser, LaserProtocol)
    setpoint = laser.get_power_setpoint(); current = laser.get_power()
    assert isinstance(setpoint, float) and isinstance(current, float)
    laser.set_power(0.05)
    assert math.isclose(laser.current_power, 0.05, rel_tol=0.2)

def test_spectrometer_protocol(sim_interface):
    spec = sim_interface.spectrometer
    assert isinstance(spec, SpectrometerProtocol)
    pos = spec.get_spectrometer_position(); assert isinstance(pos, int)
    spec.move_grating_relative(10)

def test_camera_protocol(sim_interface):
    cam = sim_interface.camera
    assert isinstance(cam, CameraProtocol)
    frame = cam.grab_frame(); assert frame is not None
    cam.set_exposure_time(0.1); assert cam.acqtime == 0.1
    cam.set_roi(cam.roi)
