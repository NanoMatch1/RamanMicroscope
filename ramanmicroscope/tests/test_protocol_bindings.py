"""Simple binding test ensuring `Interface` exposes Protocol-typed drivers.

Acts as a guard that future refactors keep the attribute names stable
and still satisfy the structural Protocols (Phase 2A).
"""

from ramanmicroscope.interface import Interface
from ramanmicroscope.drivers import (
    ControllerProtocol,
    LaserProtocol,
    SpectrometerProtocol,
    CameraProtocol,
)


def test_interface_driver_bindings():
    itf = None
    try:
        itf = Interface(simulate=True, initialise_hardware=False)
        assert isinstance(itf.controller, ControllerProtocol)
        assert isinstance(itf.laser, LaserProtocol)
        assert isinstance(itf.spectrometer, SpectrometerProtocol)
        assert isinstance(itf.camera, CameraProtocol)
    finally:
        if itf and getattr(itf, 'camera', None):
            try:
                itf.camera.close_camera()
            except Exception:
                pass
