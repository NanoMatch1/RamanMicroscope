"""
Wavelength reference calibration: the TRIAX spectrometer and PIXIS CCD together.

Every wavelength the instrument reports is read off the CCD wavelength axis,
so this calibration is the reference for everything downstream (live laser
calibration, grating calibrations, Raman shifts). It is calibrated against
spectral lines whose wavelengths are known independently of this software:
mercury lamp lines (in first or second diffraction order) or the Tiger laser
measured on a separate calibrated spectrometer.

Modules, in pipeline order (see docs/calibration.md for the physics):

- reference_lines        known lamp lines and the orders they appear in
- line_peaks             find and fit line peaks in a 1D spectrum, in PIXELS
- line_walk              step the TRIAX so each line walks across the chip
- wavelength_axis_model  the model wavelength(pixel, triax_steps), its fit,
                         and its storage in the master calibration file
- simulated_line_lamp    a lamp + spectrometer simulator with its own "true"
                         calibration, for tests and simulate mode

Everything except line_walk's hardware callables is pure and deterministic.
"""
