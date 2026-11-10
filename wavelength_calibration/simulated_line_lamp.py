"""
A simulated line lamp seen through the TRIAX onto the PIXIS.

The simulator owns its own TRUE wavelength axis model, separate from the
calibration under test. That separation is essential: the previous simulated
camera placed the laser using the software's own wavelength axis, so it could
only ever confirm the calibration it was given, never catch an error in it.
Tests here give the simulator a "true" model, start the software from a
deliberately wrong one, and check that calibration recovers the truth.

A simulator that only emits the lines the software expects cannot fail the
way the bench does: the first line walk passed every test here while 72 of
91 lines it recorded on the bench were weak neighbours of the lines it
thought they were. So `realistic_line_amplitudes` gives EVERY line in the
table a brightness from its NIST intensity (weak argon lines and mercury in
second order included), and `triax_drive_error_nm` lets the true TRIAX depart
from a smooth polynomial in steps, as the real one does.
"""

import numpy as np

from .wavelength_axis_model import WavelengthAxisModel


def default_true_model():
    """
    A plausible PIXIS + TRIAX truth, offset from the shipped calibration on purpose.

    The dispersion falls with TRIAX position as the real one does (about
    0.0777 -> 0.0773 nm/px from 700 to 900 nm for the 300 g/mm grating; see
    the wavelength_axis_model docstring). A simulator without it passed every
    test while the first real Ar-Hg walk gave reduced chi^2 in the thousands.
    """
    return WavelengthAxisModel(
        reference_pixel=50.0,
        triax_to_wavelength_coefficients=[0.009096028148595274, -170.88512284432366 - 1.9],
        nm_per_pixel=0.0772,
        nm_per_pixel_squared=-2.0e-7,
        nm_per_pixel_change_per_triax_step=-2.0e-8,
        dispersion_reference_triax_steps=107_000.0,
        metadata={'note': 'simulated truth'},
    )


CCD_FULL_SCALE_COUNTS = 65535

# Peak heights seen on 2026-11-10 relative to NIST intensity: the strongest argon line (NIST
# 35000) near full scale; mercury lines (NIST 12000 for 435.8 / 404.7 nm) at a few % of that
# (the blue reaches the CCD in second order only, through optics made for the near infrared).
ARGON_COUNTS_PER_NIST_INTENSITY = 1.6
MERCURY_COUNTS_PER_NIST_INTENSITY = 0.3


def realistic_line_amplitudes(lines, brightness_scale=1.0):
    """Peak heights (counts) for every line from its NIST intensity, times `brightness_scale`."""
    amplitudes = []
    for line in lines:
        counts_per_intensity = MERCURY_COUNTS_PER_NIST_INTENSITY if line.element == 'Hg' \
            else ARGON_COUNTS_PER_NIST_INTENSITY
        intensity = line.relative_intensity or 1000.0
        amplitudes.append(brightness_scale * counts_per_intensity * intensity)
    return amplitudes


def periodic_triax_drive_error(amplitude_nm=0.15, period_steps=12000.0, phase_steps=0.0):
    """A drive error that is not a polynomial in steps, about the size measured on 2026-11-10."""
    def drive_error_nm(triax_steps):
        return amplitude_nm * np.sin(2 * np.pi * (triax_steps - phase_steps) / period_steps)
    return drive_error_nm


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
                 number_of_pixels=1024, image_height=100, random_seed=0, triax_drive_error_nm=None):
        self.true_model = true_model
        self.triax_drive_error_nm = triax_drive_error_nm or (lambda triax_steps: 0.0)
        self.triax_counter_error_steps = 0  # drive position = reported steps + this (lost steps)
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
        triax_steps = triax_steps + self.triax_counter_error_steps
        drive_error_nm = self.triax_drive_error_nm(triax_steps)
        for line, amplitude in zip(self.emitted_lines, self.line_amplitudes):
            line_pixel = self.true_model.pixel_of_wavelength(
                line.apparent_wavelength_nm - drive_error_nm, triax_steps)
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
