from ramanmicroscope.interface import Interface
from ramanmicroscope.subsystems import AcquisitionService

def test_acquisition_service_snapshot_and_average():
    itf = Interface(simulate=True, initialise_hardware=False)
    try:
        itf.camera.initialise()
        svc = AcquisitionService.from_interface(itf)
        snap = svc.snapshot(); assert snap.exposure_s == itf.camera.acqtime
        new_exp = svc.set_exposure(0.05); assert new_exp == 0.05
        avg = svc.grab_average(n=2)
        assert avg is not None
    finally:
        try: itf.camera.close_camera()
        except Exception: pass
