"""
A simulated stage 1 bench: what the CCD sees with the halogen lamp through stage 1's edge, or
with the Ar-Hg lamp, for tests and simulate mode.

The bench has its own "true" g1 calibration (true_g1_to_edge_nm, the edge's wavelength against
the g1 count) and a wavelength axis that reads high by axis_error_nm(triax_steps), as the TRIAX's
does by a different amount at each position (RAM-F3). So an analysis that recovers
true_g1_to_edge_nm has corrected the axis with the Ar-Hg frames, and one that does not is off by
the axis error.

Halogen frames: a thin band along the slit (Gaussian in rows, slanting with wavelength), whose
light passes on the long-wavelength side of the edge (an error-function step of edge_width_nm
FWHM), on a flat stray-light background, a bias and read noise. Ar-Hg frames: the argon lines
(NIST wavelengths and intensities) over a wide range of rows, not through the edge, as on
2026-11-18 (RAM-F5).

g2 pointing (optional: true_g1_to_g2_centre set): the beam leaving stage 1 points through the
pinhole's centre when g2 is at true_g1_to_g2_centre(g1 count); each step away from that turns it
by one "pointing step". The band moves band_rows_per_g2_step rows along the slit per pointing
step (the frame-flipping periscope), and, with the pinhole in, the light is a window in pointing
steps: a beam of Gaussian profile (beam_sigma_steps) through a pinhole pinhole_width_steps wide.
pointing_steps_per_nm adds a pointing that changes with wavelength away from the edge (g1 and
g2 not exactly matched). Without true_g1_to_g2_centre, g2 changes nothing, as in the edge tests.

Images are built for the axis the frame will be saved with (frame_axis_nm, one wavelength per
column), so the simulation and the saved frame agree by construction.
"""

from dataclasses import dataclass, field

import numpy as np
from scipy.special import ndtr

from wavelength_calibration.reference_lines import ARGON_LINES_NIST

HALOGEN = 'halogen'
ARGON_MERCURY = 'arhg'
GAUSSIAN_FWHM_PER_SIGMA = 2.3548


def default_axis_error_nm(triax_steps):
    """A fixed pattern with TRIAX position, about +0.3 +/- 0.15 nm, like the TRIAX's."""
    return 0.3 + 0.15 * np.sin(float(triax_steps or 0) / 4000.0)


@dataclass
class SimulatedStage1Bench:
    true_g1_to_edge_nm: tuple = (-6.7e-05, -0.442, 805.7)
    edge_width_nm: float = 0.8
    band_row: float = 598.0
    band_rows_per_nm: float = 0.25
    band_sigma_rows: float = 3.5
    band_peak_counts: float = 2500.0        # per row, at the band's centre
    stray_light_counts: float = 600.0
    bias_counts: float = 600.0
    noise_counts: float = 8.0
    argon_peak_counts: float = 8000.0       # the brightest argon line, per row
    argon_rows: tuple = (300, 700)
    argon_line_sigma_nm: float = 0.22
    lamp: str = HALOGEN
    axis_error_nm: object = default_axis_error_nm   # callable: TRIAX steps -> how far (nm) the
                                                    # axis reads high
    true_g1_to_g2_centre: tuple = None      # g2 count centring the beam, against g1 count
    band_rows_per_g2_step: float = 4.0
    pinhole_in: bool = False
    pinhole_width_steps: float = 3.0
    beam_sigma_steps: float = 4.0
    pointing_steps_per_nm: float = 0.0
    random_seed: int = 1
    _random: object = field(default=None, repr=False)

    def __post_init__(self):
        self._random = np.random.default_rng(self.random_seed)

    def true_edge_nm(self, g1_count):
        return float(np.polyval(self.true_g1_to_edge_nm, g1_count))

    def true_g2_centre(self, g1_count):
        """The g2 count that points the beam (at the edge's wavelength) through the pinhole."""
        return float(np.polyval(self.true_g1_to_g2_centre, g1_count))

    def pointing_error_steps(self, g1_count, g2_count, true_wavelength_nm):
        """Per wavelength, how many g2 steps the beam points away from the pinhole's centre."""
        return g2_count - self.true_g2_centre(g1_count) + self.pointing_steps_per_nm * \
            (np.asarray(true_wavelength_nm) - self.true_edge_nm(g1_count))

    def pinhole_transmission(self, pointing_error_steps):
        half_width = self.pinhole_width_steps / 2
        return ndtr((pointing_error_steps + half_width) / self.beam_sigma_steps) - \
            ndtr((pointing_error_steps - half_width) / self.beam_sigma_steps)

    def image(self, g1_count, frame_axis_nm, triax_steps, image_height=1024, g2_count=None):
        """The frame the CCD would read: (image_height, len(frame_axis_nm)) counts. g2_count
        matters only with the pointing model (true_g1_to_g2_centre)."""
        true_wavelength_nm = np.asarray(frame_axis_nm, dtype=float) - \
            self.axis_error_nm(triax_steps)
        rows = np.arange(image_height, dtype=float)[:, None]
        if self.lamp == ARGON_MERCURY:
            light = self._argon_image(true_wavelength_nm, rows)
        else:
            light = self._halogen_image(g1_count, true_wavelength_nm, rows, g2_count)
        noise = self._random.normal(0.0, self.noise_counts, light.shape)
        return (light + self.bias_counts + noise).astype(np.float32)

    def _halogen_image(self, g1_count, true_wavelength_nm, rows, g2_count=None):
        edge_sigma_nm = self.edge_width_nm / GAUSSIAN_FWHM_PER_SIGMA
        passed = ndtr((true_wavelength_nm - self.true_edge_nm(g1_count)) / edge_sigma_nm)
        lamp_spectrum = 1.0 + 0.002 * (true_wavelength_nm - 800.0)
        band_centre = self.band_row + self.band_rows_per_nm * (true_wavelength_nm - 800.0)
        if self.true_g1_to_g2_centre is not None and g2_count is not None:
            pointing = self.pointing_error_steps(g1_count, g2_count, true_wavelength_nm)
            band_centre = band_centre + self.band_rows_per_g2_step * pointing
            if self.pinhole_in:
                passed = passed * self.pinhole_transmission(pointing)
        band = np.exp(-0.5 * ((rows - band_centre[None, :]) / self.band_sigma_rows) ** 2)
        return self.band_peak_counts * band * (passed * lamp_spectrum)[None, :] + \
            self.stray_light_counts

    def _argon_image(self, true_wavelength_nm, rows):
        brightest = max(intensity for _, intensity in ARGON_LINES_NIST)
        spectrum = np.zeros_like(true_wavelength_nm)
        for line_nm, intensity in ARGON_LINES_NIST:
            spectrum += (intensity / brightest) * np.exp(
                -0.5 * ((true_wavelength_nm - line_nm) / self.argon_line_sigma_nm) ** 2)
        first_row, last_row = self.argon_rows
        row_profile = ((rows >= first_row) & (rows <= last_row)).astype(float)
        return self.argon_peak_counts * row_profile * spectrum[None, :]
