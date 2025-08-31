from ramanmicroscope.interface import Interface
from ramanmicroscope.instruments.cameras.tucsencam import TucsenCamera

def test_system_snapshot_dict_structure():
    # Reset camera singleton guard pre-instantiation (defensive for sequential test runs)
    try:
        TucsenCamera._instance_active = False  # type: ignore[attr-defined]
    except Exception:
        pass
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
