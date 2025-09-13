from ramanmicroscope.interface import Interface


def test_go_to_monochromator_wavelength_service():
    itf = Interface(simulate=True, initialise_hardware=False, debug_skip=['camera'])
    try:
        wl = 600.0
        assert itf.microscope.go_to_monochromator_wavelength(wl) is True
    finally:
        try:
            itf.camera.close_camera()
        except Exception:
            pass
