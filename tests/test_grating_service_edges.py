from ramanmicroscope.interface import Interface


def test_grating_rejects_out_of_range_low():
    itf = Interface(simulate=True, initialise_hardware=False, debug_skip=['camera'])
    try:
        low = itf.microscope.hard_limits['grating_wavelength'][0] - 5
        assert itf.microscope.go_to_grating_wavelength(low) is False
    finally:
        try:
            itf.camera.close_camera()
        except Exception:
            pass


def test_grating_rejects_out_of_range_high():
    itf = Interface(simulate=True, initialise_hardware=False, debug_skip=['camera'])
    try:
        high = itf.microscope.hard_limits['grating_wavelength'][1] + 5
        assert itf.microscope.go_to_grating_wavelength(high) is False
    finally:
        try:
            itf.camera.close_camera()
        except Exception:
            pass
