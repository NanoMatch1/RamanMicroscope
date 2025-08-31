from ramanmicroscope.interface import Interface

def test_go_to_spectrometer_wavelength_routes_service():
    itf = Interface(simulate=True, initialise_hardware=False, debug_skip=['camera'])
    try:
        itf.spectrometer.initialise()
        start = itf.spectrometer.get_spectrometer_position()
        # choose small delta wavelength using calibration if available
        svc = itf.spectrometer_service
        # If calibration present, pick current wavelength else fallback numeric
        target_wl = None
        snap = svc.snapshot()
        if snap.wavelength_nm:
            target_wl = snap.wavelength_nm + 0.1  # tiny shift
        else:
            # approximate by arbitrary nm; service will fallback if cannot convert
            target_wl = 600.0
        assert itf.microscope.go_to_spectrometer_wavelength(target_wl) is True
    finally:
        try: itf.camera.close_camera()
        except Exception: pass
