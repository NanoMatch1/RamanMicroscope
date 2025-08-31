from ramanmicroscope.interface import Interface
from ramanmicroscope.subsystems import SpectrometerService

def test_spectrometer_service_snapshot_and_move():
    itf = Interface(simulate=True, initialise_hardware=False, debug_skip=['camera'])
    # initialise only spectrometer
    itf.spectrometer.initialise()
    service = SpectrometerService.from_interface(itf)
    snap1 = service.snapshot()
    assert isinstance(snap1.steps, int)
    # relative move
    new_steps = service.move_relative(50)
    assert isinstance(new_steps, int)
    snap2 = service.snapshot()
    assert snap2.steps == new_steps
    # go to same wavelength (should no-op)
    if snap2.wavelength_nm:
        service.go_to_wavelength(snap2.wavelength_nm)
