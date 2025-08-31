from ramanmicroscope.interface import Interface

def test_go_to_grating_wavelength_service():
    itf = Interface(simulate=True, initialise_hardware=False, debug_skip=['camera'])
    try:
        # ensure calibration loaded; simulate hardware init minimal
        wl = 550.0
        assert itf.microscope.go_to_grating_wavelength(wl) is True
    finally:
        try: itf.camera.close_camera()
        except Exception: pass
