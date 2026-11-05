# pixisspec/simulated_microscope_scene.py

"""
What the simulated PIXIS sees in simulate mode.

SimulatedPicamDevice samples a scene callable at the start and end of every exposure. This
is that callable for the whole simulated microscope: a laser line on the CCD when the
simulated laser is on and above threshold, background and read noise otherwise. A procedure
can install its own scene in `override_scene` -- the line walk installs a simulated Ar-Hg
lamp (wavelength_calibration.simulated_line_lamp) -- and must set it back to None afterwards.

(Moved here from the former SimulatedHardware class, which replaced RealHardware entirely in
simulate mode; now RealHardware runs on SimulatedPicamDevice and only the scene is simulated.)
"""

import numpy as np


class SimulatedMicroscopeScene:
    """Callable returning the image on the simulated CCD, shape (height, width)."""

    def __init__(self, interface, width=1024, height=100):
        self.interface = interface
        self.width = width
        self.height = height
        self.override_scene = None   # callable returning an image, e.g. a simulated line lamp

    def __call__(self):
        if self.override_scene is not None:
            return self.override_scene()
        return self._generate_simulated_image()

    def _generate_simulated_image(self):
        """Background, read noise, and the laser line when the simulated laser is on."""
        background   = 400
        noise        = np.random.randint(-30, 30, (self.height, self.width))
        laser_signal = self._generate_simulated_laser_signal()
        return background + laser_signal + noise

    def _generate_simulated_laser_signal(self, laser_width=3, y_spread=15, peak_height=20000,
                                         peak_sigma=0.1):
        """Generate a Gaussian laser line on the simulated CCD."""
        width, height = self.width, self.height
        try:
            laser_on = (
                self.interface.laser.status == 'ON'
                and self.interface.laser.current_power >= 3
            )
        except Exception:
            laser_on = False

        if not laser_on:
            return np.zeros((height, width), dtype=np.float32)

        try:
            wavelength_axis = self.interface.microscope.wavelength_axis
            laser_wavelength = (
                self.interface.microscope.laser_wavelength_calibrated
                or next(iter(
                    self.interface.microscope.laser_wavelengths.values()
                ), 785)
            )
            laser_px = int(np.argmin(np.abs(wavelength_axis - laser_wavelength)))
        except Exception:
            laser_px = width // 2

        Y, X = np.meshgrid(np.arange(height), np.arange(width), indexing='ij')
        signal = (
            np.exp(-0.5 * ((X - laser_px)   / laser_width) ** 2) *
            np.exp(-0.5 * ((Y - height / 2) / y_spread)   ** 2)
        )
        scale  = abs(np.random.normal(peak_height, peak_height * peak_sigma))
        return (signal * scale).astype(np.float32)
