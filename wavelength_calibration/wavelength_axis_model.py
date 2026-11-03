"""
The wavelength axis model: which wavelength lands on which CCD pixel.

    wavelength(pixel, triax_steps) = triax_wavelength(triax_steps)
                                     + nm_per_pixel * (pixel - reference_pixel)
                                     + nm_per_pixel_squared * (pixel - reference_pixel)**2

- triax_wavelength(steps) is a polynomial in the TRIAX grating position: the
  wavelength the TRIAX puts on `reference_pixel`. It is the old `triax_to_wl`.
- nm_per_pixel is the reciprocal linear dispersion at the focal plane times
  the pixel pitch (about 6 nm/mm x 13 um for the 300 g/mm grating and PIXIS).
- nm_per_pixel_squared is an optional small curvature term: dispersion
  changes slightly across the chip because the diffraction angle does.

Why the reference pixel is a FIXED choice, not a fitted parameter: moving the
reference pixel by one pixel and shifting triax_wavelength by nm_per_pixel
describes exactly the same instrument, so the data cannot tell them apart.
We therefore choose where the TRIAX wavelength is defined (pixel 50 is the
long-standing convention, which keeps a laser line near the short-wavelength
edge so the Stokes Raman spectrum fills the chip) and fit everything else.

Why at least two different wavelengths are needed: walking ONE line across
the chip only measures the ratio of TRIAX steps to pixels; any combination of
dispersion and TRIAX slope with that ratio fits it. A second known wavelength
fixes the scale. fit_wavelength_axis refuses rank-deficient data and says so.
"""

from dataclasses import dataclass, field, asdict
import datetime

import numpy as np


class CalibrationFitError(ValueError):
    """The observations cannot determine the model; the message says why."""


@dataclass
class LineObservation:
    """One measurement: a line of known wavelength seen at a pixel, at a TRIAX position."""

    line_name: str
    apparent_wavelength_nm: float
    wavelength_uncertainty_nm: float
    triax_steps: int
    centre_pixel: float
    centre_uncertainty_pixels: float

    def as_dict(self):
        return asdict(self)


@dataclass
class WavelengthAxisModel:
    """Parameters of the wavelength axis; see the module docstring for the equation."""

    reference_pixel: float
    triax_to_wavelength_coefficients: list  # numpy poly1d order: highest power first
    nm_per_pixel: float
    nm_per_pixel_squared: float = 0.0
    metadata: dict = field(default_factory=dict)

    # -- evaluation ---------------------------------------------------------

    def triax_wavelength(self, triax_steps):
        """Wavelength (nm) the TRIAX puts on the reference pixel."""
        return np.poly1d(self.triax_to_wavelength_coefficients)(triax_steps)

    def wavelength_at(self, pixel, triax_steps):
        """Wavelength (nm) at a pixel index (scalar or array) for a TRIAX position."""
        pixel_offset = np.asarray(pixel, dtype=float) - self.reference_pixel
        return (self.triax_wavelength(triax_steps)
                + self.nm_per_pixel * pixel_offset
                + self.nm_per_pixel_squared * pixel_offset ** 2)

    def wavelength_axis(self, triax_steps, number_of_pixels):
        """One wavelength per detector column, columns 0 .. number_of_pixels-1."""
        return self.wavelength_at(np.arange(number_of_pixels), triax_steps)

    def pixel_of_wavelength(self, wavelength_nm, triax_steps):
        """Fractional pixel index where a wavelength lands (inverse of wavelength_at)."""
        wavelength_offset = wavelength_nm - self.triax_wavelength(triax_steps)
        if self.nm_per_pixel_squared == 0.0:
            return self.reference_pixel + wavelength_offset / self.nm_per_pixel
        roots = np.roots([self.nm_per_pixel_squared, self.nm_per_pixel, -wavelength_offset])
        real_roots = roots[np.isreal(roots)].real
        linear_estimate = wavelength_offset / self.nm_per_pixel
        return self.reference_pixel + real_roots[np.argmin(np.abs(real_roots - linear_estimate))]

    def triax_steps_for_wavelength(self, wavelength_nm, at_pixel=None):
        """
        TRIAX position that puts `wavelength_nm` on `at_pixel` (default: the reference pixel).

        This is the exact inverse of the model, not a separately fitted
        polynomial, so steps -> wavelength -> steps always round-trips.
        """
        if at_pixel is None:
            at_pixel = self.reference_pixel
        pixel_offset = at_pixel - self.reference_pixel
        target_triax_wavelength = (wavelength_nm - self.nm_per_pixel * pixel_offset
                                   - self.nm_per_pixel_squared * pixel_offset ** 2)
        coefficients = np.array(self.triax_to_wavelength_coefficients, dtype=float)
        if len(coefficients) == 2:
            return (target_triax_wavelength - coefficients[1]) / coefficients[0]
        shifted = coefficients.copy()
        shifted[-1] -= target_triax_wavelength
        roots = np.roots(shifted)
        real_roots = roots[np.isreal(roots)].real
        linear_estimate = (target_triax_wavelength - coefficients[-1]) / coefficients[-2]
        return real_roots[np.argmin(np.abs(real_roots - linear_estimate))]

    # -- storage --------------------------------------------------------------

    def to_dict(self):
        return {
            'reference_pixel': self.reference_pixel,
            'triax_to_wavelength_coefficients': [float(c) for c in self.triax_to_wavelength_coefficients],
            'nm_per_pixel': float(self.nm_per_pixel),
            'nm_per_pixel_squared': float(self.nm_per_pixel_squared),
            'metadata': self.metadata,
        }

    @classmethod
    def from_dict(cls, stored):
        return cls(
            reference_pixel=float(stored['reference_pixel']),
            triax_to_wavelength_coefficients=list(stored['triax_to_wavelength_coefficients']),
            nm_per_pixel=float(stored['nm_per_pixel']),
            nm_per_pixel_squared=float(stored.get('nm_per_pixel_squared', 0.0)),
            metadata=dict(stored.get('metadata', {})),
        )


@dataclass
class WavelengthAxisFit:
    """A fitted model plus everything needed to judge whether to trust it."""

    model: WavelengthAxisModel
    observations: list
    residuals_nm: np.ndarray
    reduced_chi_squared: float
    parameter_names: list
    parameter_values: np.ndarray
    parameter_uncertainties: np.ndarray

    @property
    def residual_rms_nm(self):
        return float(np.sqrt(np.mean(self.residuals_nm ** 2)))

    @property
    def residual_max_nm(self):
        return float(np.max(np.abs(self.residuals_nm)))

    def report_lines(self):
        """Human-readable fit summary, one string per line."""
        lines = [
            f"points: {len(self.observations)}, distinct lines: "
            f"{len({round(o.apparent_wavelength_nm, 4) for o in self.observations})}",
            f"residual rms {self.residual_rms_nm:.4f} nm, max {self.residual_max_nm:.4f} nm, "
            f"reduced chi^2 {self.reduced_chi_squared:.2f}",
        ]
        for name, value, uncertainty in zip(self.parameter_names, self.parameter_values,
                                            self.parameter_uncertainties):
            lines.append(f"  {name:>28} = {value:.6g} +/- {uncertainty:.2g}")
        return lines


def _check_observations_can_determine_model(observations):
    distinct_wavelengths = {round(o.apparent_wavelength_nm, 4) for o in observations}
    if len(distinct_wavelengths) < 2:
        raise CalibrationFitError(
            "At least two different known wavelengths are needed. Walking one line "
            "across the chip only fixes the ratio of TRIAX steps to pixels, not the "
            "dispersion itself (see wavelength_axis_model module docstring).")
    distinct_triax_positions = {o.triax_steps for o in observations}
    if len(distinct_triax_positions) < 2:
        raise CalibrationFitError(
            "At least two TRIAX positions are needed to calibrate the TRIAX slope "
            "(steps per nm); all observations were taken at one position.")


def fit_wavelength_axis(observations, reference_pixel=50.0, triax_polynomial_order=1,
                        fit_dispersion_curvature=False, metadata=None):
    """
    Weighted linear least-squares fit of the wavelength axis model.

    Each point is weighted by its combined uncertainty in nm: the reference
    wavelength uncertainty and the peak-centre uncertainty converted to nm
    with the dispersion (one refinement pass, since the dispersion is what
    is being fitted).

    The TRIAX polynomial is fitted in a centred, scaled step variable for
    numerical conditioning (steps are ~1e5) and converted back to raw-step
    coefficients for storage.
    """
    observations = list(observations)
    _check_observations_can_determine_model(observations)

    apparent_wavelengths = np.array([o.apparent_wavelength_nm for o in observations])
    triax_steps = np.array([o.triax_steps for o in observations], dtype=float)
    pixel_offsets = np.array([o.centre_pixel for o in observations]) - reference_pixel
    wavelength_uncertainties = np.array([o.wavelength_uncertainty_nm for o in observations])
    pixel_uncertainties = np.array([o.centre_uncertainty_pixels for o in observations])

    steps_centre = float(np.mean(triax_steps))
    steps_scale = float(np.ptp(triax_steps)) or 1.0
    scaled_steps = (triax_steps - steps_centre) / steps_scale

    step_columns = [scaled_steps ** power for power in range(triax_polynomial_order, -1, -1)]
    pixel_columns = [pixel_offsets] + ([pixel_offsets ** 2] if fit_dispersion_curvature else [])
    design_matrix = np.column_stack(step_columns + pixel_columns)
    number_of_parameters = design_matrix.shape[1]
    if len(observations) <= number_of_parameters:
        raise CalibrationFitError(
            f"{len(observations)} observations for {number_of_parameters} parameters: "
            "take more TRIAX positions so the fit is over-determined and residuals mean something.")

    nm_per_pixel_estimate = 0.078
    for _refinement_pass in range(2):
        total_uncertainties_nm = np.sqrt(wavelength_uncertainties ** 2
                                         + (nm_per_pixel_estimate * pixel_uncertainties) ** 2)
        weighted_design = design_matrix / total_uncertainties_nm[:, None]
        weighted_target = apparent_wavelengths / total_uncertainties_nm
        if np.linalg.matrix_rank(weighted_design) < number_of_parameters:
            raise CalibrationFitError(
                "The observations are degenerate for this model (rank-deficient). "
                "Spread the line across more of the chip and use more TRIAX positions.")
        parameters, *_ = np.linalg.lstsq(weighted_design, weighted_target, rcond=None)
        nm_per_pixel_estimate = abs(parameters[triax_polynomial_order + 1])

    residuals_nm = apparent_wavelengths - design_matrix @ parameters
    degrees_of_freedom = len(observations) - number_of_parameters
    reduced_chi_squared = float(np.sum((residuals_nm / total_uncertainties_nm) ** 2) / degrees_of_freedom)
    covariance = np.linalg.inv(weighted_design.T @ weighted_design)
    parameter_uncertainties = np.sqrt(np.diag(covariance))

    scaled_step_polynomial = np.poly1d(parameters[:triax_polynomial_order + 1])
    raw_step_polynomial = scaled_step_polynomial(np.poly1d([1.0 / steps_scale, -steps_centre / steps_scale]))
    nm_per_pixel = float(parameters[triax_polynomial_order + 1])
    nm_per_pixel_squared = float(parameters[triax_polynomial_order + 2]) if fit_dispersion_curvature else 0.0

    model_metadata = {
        'fitted_on': datetime.date.today().isoformat(),
        'number_of_observations': len(observations),
        'residual_rms_nm': float(np.sqrt(np.mean(residuals_nm ** 2))),
        'reduced_chi_squared': reduced_chi_squared,
    }
    model_metadata.update(metadata or {})
    model = WavelengthAxisModel(
        reference_pixel=float(reference_pixel),
        triax_to_wavelength_coefficients=[float(c) for c in raw_step_polynomial.coeffs],
        nm_per_pixel=nm_per_pixel,
        nm_per_pixel_squared=nm_per_pixel_squared,
        metadata=model_metadata,
    )

    parameter_names = ([f'triax (scaled steps)^{power}' for power in range(triax_polynomial_order, -1, -1)]
                       + ['nm_per_pixel'] + (['nm_per_pixel_squared'] if fit_dispersion_curvature else []))
    return WavelengthAxisFit(
        model=model, observations=observations, residuals_nm=residuals_nm,
        reduced_chi_squared=reduced_chi_squared, parameter_names=parameter_names,
        parameter_values=parameters, parameter_uncertainties=parameter_uncertainties,
    )


def largest_axis_difference_nm(first_model, second_model, triax_steps_values, number_of_pixels=1024):
    """Largest wavelength disagreement between two models over the chip and TRIAX positions given."""
    differences = [np.max(np.abs(first_model.wavelength_axis(steps, number_of_pixels)
                                 - second_model.wavelength_axis(steps, number_of_pixels)))
                   for steps in triax_steps_values]
    return float(np.max(differences))
