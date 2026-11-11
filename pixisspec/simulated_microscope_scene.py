# pixisspec/simulated_microscope_scene.py

"""
What the simulated PIXIS sees in simulate mode.

SimulatedPicamDevice samples a scene callable at the start and end of every exposure. This
is that callable for the whole simulated microscope: a laser line on the CCD when the
simulated laser is on and above threshold, background and read noise otherwise. A procedure
can install its own scene in `override_scene` -- the line walk installs a simulated Ar-Hg
lamp (wavelength_calibration.simulated_line_lamp) -- and must set it back to None afterwards.

The scene is the whole sensor (1024 x 1024 by default); the simulated camera cuts the ROI out
of it. The light falls on a band of rows, the slit image, centred on `slit_image_centre_row`
and tilted by `slit_image_tilt_rows_per_1000_columns` across the chip, as on the lab PIXIS
(rows ~790-820 on 2026-11-11). An installed scene should put its light there too
(`slit_image_rows_at_columns`).

(Moved here from the former SimulatedHardware class, which replaced RealHardware entirely in
simulate mode; now RealHardware runs on SimulatedPicamDevice and only the scene is simulated.)
"""

import numpy as np


class SimulatedMicroscopeScene:
    """Callable returning the image on the simulated CCD, shape (height, width)."""

    def __init__(self, interface, width=1024, height=1024, slit_image_centre_row=800.0,
                 slit_image_tilt_rows_per_1000_columns=0.0):
        self.interface = interface
        self.width = width
        self.height = height
        self.slit_image_centre_row = slit_image_centre_row
        self.slit_image_tilt_rows_per_1000_columns = slit_image_tilt_rows_per_1000_columns
        self.override_scene = None   # callable returning an image, e.g. a simulated line lamp

    def slit_image_rows_at_columns(self):
        """Centre row of the slit image in each column (tilt pivots on the chip's centre)."""
        columns = np.arange(self.width, dtype=float)
        return (self.slit_image_centre_row + self.slit_image_tilt_rows_per_1000_columns / 1000
                * (columns - self.width / 2))

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
        slit_rows = self.slit_image_rows_at_columns()[None, :]
        signal = (
            np.exp(-0.5 * ((X - laser_px)   / laser_width) ** 2) *
            np.exp(-0.5 * ((Y - slit_rows) / y_spread)   ** 2)
        )
        scale  = abs(np.random.normal(peak_height, peak_height * peak_sigma))
        return (signal * scale).astype(np.float32)
