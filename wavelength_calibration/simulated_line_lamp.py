"""
A simulated line lamp seen through the TRIAX onto the PIXIS.

The simulator owns its own TRUE wavelength axis model, separate from the
calibration under test. That separation is essential: the previous simulated
camera placed the laser using the software's own wavelength axis, so it could
only ever confirm the calibration it was given, never catch an error in it.
Tests here give the simulator a "true" model, start the software from a
deliberately wrong one, and check that calibration recovers the truth.
"""

import numpy as np

from .wavelength_axis_model import WavelengthAxisModel


def default_true_model():
    """A plausible PIXIS + TRIAX truth, offset from the shipped calibration on purpose."""
    return WavelengthAxisModel(
        reference_pixel=50.0,
        triax_to_wavelength_coefficients=[0.009096028148595274, -170.88512284432366 - 1.9],
        nm_per_pixel=0.0772,
        nm_per_pixel_squared=-2.0e-7,
        metadata={'note': 'simulated truth'},
    )


CCD_FULL_SCALE_COUNTS = 65535


class SimulatedLineLamp:
    """
    Generates spectra/frames of known lines for a given TRIAX position.

    Real lamp lines differ in brightness by more than an order of magnitude,
    so each line gets its own amplitude: `line_amplitudes` if given (one per
    line), otherwise a seeded random fraction (0.15-1) of `line_amplitude`.
    Output is clipped at the CCD's full scale, so bright lines can saturate.
    """

    def __init__(self, true_model, emitted_lines, line_amplitude=5000.0, line_amplitudes=None,
                 line_sigma_pixels=1.6, background_level=400.0, noise_standard_deviation=15.0,
                 number_of_pixels=1024, image_height=100, random_seed=0):
        self.true_model = true_model
        self.emitted_lines = list(emitted_lines)
        self.random_generator = np.random.default_rng(random_seed)
        if line_amplitudes is None:
            line_amplitudes = line_amplitude * self.random_generator.uniform(0.15, 1.0, len(self.emitted_lines))
        self.line_amplitudes = list(line_amplitudes)
        self.line_sigma_pixels = line_sigma_pixels
        self.background_level = background_level
        self.noise_standard_deviation = noise_standard_deviation
        self.number_of_pixels = number_of_pixels
        self.image_height = image_height

    def noiseless_spectrum(self, triax_steps):
        pixels = np.arange(self.number_of_pixels, dtype=float)
        spectrum = np.full(self.number_of_pixels, self.background_level)
        for line, amplitude in zip(self.emitted_lines, self.line_amplitudes):
            line_pixel = self.true_model.pixel_of_wavelength(line.apparent_wavelength_nm, triax_steps)
            spectrum += amplitude * np.exp(-0.5 * ((pixels - line_pixel) / self.line_sigma_pixels) ** 2)
        return spectrum

    def spectrum(self, triax_steps):
        noise = self.random_generator.normal(0.0, self.noise_standard_deviation, self.number_of_pixels)
        return np.clip(self.noiseless_spectrum(triax_steps) + noise, 0, CCD_FULL_SCALE_COUNTS)

    def image(self, triax_steps, slit_image_centre_row=None, slit_image_half_height_rows=15):
        """A 2D frame: the spectrum along columns, the slit image as a Gaussian along rows."""
        if slit_image_centre_row is None:
            slit_image_centre_row = self.image_height / 2
        rows = np.arange(self.image_height, dtype=float)
        row_profile = np.exp(-0.5 * ((rows - slit_image_centre_row) / slit_image_half_height_rows) ** 2)
        line_part = self.noiseless_spectrum(triax_steps) - self.background_level
        frame = self.background_level + row_profile[:, None] * line_part[None, :]
        frame += self.random_generator.normal(0.0, self.noise_standard_deviation, frame.shape)
        return np.clip(frame, 0, CCD_FULL_SCALE_COUNTS)
