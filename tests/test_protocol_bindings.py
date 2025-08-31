from ramanmicroscope.interface import Interface
from ramanmicroscope.drivers import ControllerProtocol, LaserProtocol, SpectrometerProtocol, CameraProtocol

def test_interface_driver_bindings():
    itf = Interface(simulate=True, initialise_hardware=False)
    try:
        assert isinstance(itf.controller, ControllerProtocol)
        assert isinstance(itf.laser, LaserProtocol)
        assert isinstance(itf.spectrometer, SpectrometerProtocol)
        assert isinstance(itf.camera, CameraProtocol)
    finally:
        try: itf.camera.close_camera()
        except Exception: pass
