"""Contract tests for driver Protocols (Phase 2).

These are intentionally light-weight and run only in simulate mode to
avoid touching real hardware. They assert that the concrete objects
attached to the public `Interface` satisfy structural Protocols and
exercise a minimal happy path for each driver.
"""

from __future__ import annotations

import math
import pytest

from ramanmicroscope.interface import Interface
from ramanmicroscope.drivers import (
    ControllerProtocol,
    LaserProtocol,
    SpectrometerProtocol,
    CameraProtocol,
)


@pytest.fixture(scope="module")
def sim_interface():
    # Full hardware initialise in simulate mode (fast) so drivers are ready.
    interface = Interface(simulate=True, initialise_hardware=True)
    yield interface
    # Best-effort camera shutdown (simulated)
    try:
        interface.camera.close_camera()
    except Exception:
        pass


def test_controller_protocol(sim_interface):
    ctrl = sim_interface.controller
    assert isinstance(ctrl, ControllerProtocol)
    # Send a benign command pattern that simulation understands (positions request with empty set OK)
    res = ctrl.send_command('g1A g2Xg')  # shaped like a position request
    assert res is not None


def test_laser_protocol(sim_interface):
    laser = sim_interface.laser
    assert isinstance(laser, LaserProtocol)
    # Warmup in simulation often returns 100 instantly; just call accessors
    setpoint = laser.get_power_setpoint()
    current = laser.get_power()
    assert isinstance(setpoint, float)
    assert isinstance(current, float)
    # Set a safe low power
    laser.set_power(0.05)
    assert math.isclose(laser.current_power, 0.05, rel_tol=0.2)


def test_spectrometer_protocol(sim_interface):
    spec = sim_interface.spectrometer
    assert isinstance(spec, SpectrometerProtocol)
    pos = spec.get_spectrometer_position()
    assert isinstance(pos, int)
    # Relative move small (simulation just updates value)
    spec.move_grating_relative(10)


def test_camera_protocol(sim_interface):
    cam = sim_interface.camera
    assert isinstance(cam, CameraProtocol)
    # Acquire one frame (simulation returns ndarray or similar)
    frame = cam.grab_frame()
    assert frame is not None
    # Change exposure time
    cam.set_exposure_time(0.1)
    assert cam.acqtime == 0.1
    # ROI change round-trip
    prev = cam.roi
    cam.set_roi(prev)  # no-op but valid
