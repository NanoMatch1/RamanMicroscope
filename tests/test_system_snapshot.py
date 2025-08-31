from ramanmicroscope.interface import Interface

def test_system_snapshot_dict_structure():
    itf = Interface(simulate=True, initialise_hardware=False, debug_skip=['camera'])
    try:
        # init only laser and spectrometer for snapshot (camera skipped)
        itf.laser.initialise(); itf.spectrometer.initialise();
        snap = itf.system_snapshot()
        assert set(['laser','spectrometer','acquisition']).issubset(snap.keys())
        # laser snapshot should be dict with expected keys when initialised
        if snap['laser']:
            for k in ['status','power','setpoint','warmup_pct','shutter']:
                assert k in snap['laser']
    finally:
        try: itf.camera.close_camera()
        except Exception: pass
