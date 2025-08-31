from ramanmicroscope.interface import Interface
from ramanmicroscope.subsystems import LaserService

def test_laser_snapshot_and_set_power_safe():
    itf = Interface(simulate=True, initialise_hardware=False)
    try:
        itf.laser.initialise()
        service = LaserService(itf.laser)
        snap = service.snapshot(); assert 0 <= snap.warmup_pct <= 100
        assert service.set_power_safe(0.5)==0.5
        assert service.set_power_safe(7.0) is None
        assert service.set_power_safe(-1) is None
    finally:
        try: itf.camera.close_camera()
        except Exception: pass
