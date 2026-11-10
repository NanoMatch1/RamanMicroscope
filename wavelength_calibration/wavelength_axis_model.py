"""
The wavelength axis model: which wavelength lands on which CCD pixel.

    wavelength(pixel, triax_steps) = triax_wavelength(triax_steps)
                                     + nm_per_pixel_at(triax_steps) * (pixel - reference_pixel)
                                     + nm_per_pixel_squared * (pixel - reference_pixel)**2

    nm_per_pixel_at(triax_steps) = nm_per_pixel
                                   + nm_per_pixel_change_per_triax_step
                                     * (triax_steps - dispersion_reference_triax_steps)

- triax_wavelength(steps) is a polynomial in the TRIAX grating position: the
  wavelength the TRIAX puts on `reference_pixel`. It is the old `triax_to_wl`.
- nm_per_pixel is the reciprocal linear dispersion at the focal plane times
  the pixel pitch (about 6 nm/mm x 13 um for the 300 g/mm grating and PIXIS),
  at the TRIAX position `dispersion_reference_triax_steps`.
- nm_per_pixel_change_per_triax_step: the dispersion depends on the grating
  angle. Linear dispersion is d * cos(beta) / (m * f), with beta the
  diffraction angle, and beta grows as the grating turns towards longer
  wavelengths, so nm per pixel falls slowly from the blue end to the red end
  (measured 0.0774 -> 0.0771 nm/px over 700-880 nm, 2026-11-04). Over a
  690-930 nm walk, leaving this out puts up to ~0.15 nm of error at the far
  edge of the chip; see docs/calibration.md section 3.1.
- nm_per_pixel_squared is an optional small curvature term: dispersion
  changes slightly across the chip because the diffraction angle does.
- triax_step_offset (default 0) is added to the TRIAX's step count before
  the model is evaluated: drive position = reported steps + offset. If the
  TRIAX's step counter is shifted (steps lost, a re-initialisation), the shape
  of the calibration is unchanged and only this offset is re-measured
  (`speccalzero`). A full fit sets it to 0 and absorbs the zero in the
  polynomial.

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
    nm_per_pixel_change_per_triax_step: float = 0.0
    dispersion_reference_triax_steps: float = 0.0
    triax_step_offset: float = 0.0
    metadata: dict = field(default_factory=dict)

    # -- evaluation ---------------------------------------------------------

    def drive_position(self, triax_steps):
        """Where the drive really is, in the calibration's steps: reported steps + offset."""
        return np.asarray(triax_steps, dtype=float) + self.triax_step_offset

    def triax_wavelength(self, triax_steps):
        """Wavelength (nm) the TRIAX puts on the reference pixel."""
        return np.poly1d(self.triax_to_wavelength_coefficients)(self.drive_position(triax_steps))

    def nm_per_pixel_at(self, triax_steps):
        """Linear dispersion (nm per pixel) at the reference pixel for a TRIAX position."""
        return (self.nm_per_pixel + self.nm_per_pixel_change_per_triax_step
                * (self.drive_position(triax_steps) - self.dispersion_reference_triax_steps))

    def nm_per_triax_step(self, triax_steps):
        """How far one TRIAX step moves the wavelength on the reference pixel (nm)."""
        slope = np.polyder(np.poly1d(self.triax_to_wavelength_coefficients))
        return float(slope(self.drive_position(triax_steps)))

    def wavelength_at(self, pixel, triax_steps):
        """Wavelength (nm) at a pixel index (scalar or array) for a TRIAX position."""
        pixel_offset = np.asarray(pixel, dtype=float) - self.reference_pixel
        return (self.triax_wavelength(triax_steps)
                + self.nm_per_pixel_at(triax_steps) * pixel_offset
                + self.nm_per_pixel_squared * pixel_offset ** 2)

    def wavelength_axis(self, triax_steps, number_of_pixels):
        """One wavelength per detector column, columns 0 .. number_of_pixels-1."""
        return self.wavelength_at(np.arange(number_of_pixels), triax_steps)

    def pixel_of_wavelength(self, wavelength_nm, triax_steps):
        """Fractional pixel index where a wavelength lands (inverse of wavelength_at)."""
        wavelength_offset = wavelength_nm - self.triax_wavelength(triax_steps)
        nm_per_pixel = self.nm_per_pixel_at(triax_steps)
        if self.nm_per_pixel_squared == 0.0:
            return self.reference_pixel + wavelength_offset / nm_per_pixel
        roots = np.roots([self.nm_per_pixel_squared, nm_per_pixel, -wavelength_offset])
        real_roots = roots[np.isreal(roots)].real
        linear_estimate = wavelength_offset / nm_per_pixel
        return self.reference_pixel + real_roots[np.argmin(np.abs(real_roots - linear_estimate))]

    def triax_steps_for_wavelength(self, wavelength_nm, at_pixel=None):
        """
        TRIAX position that puts `wavelength_nm` on `at_pixel` (default: the reference pixel).

        This is the exact inverse of the model, not a separately fitted
        polynomial, so steps -> wavelength -> steps always round-trips.

        Off the reference pixel the dispersion term depends on the steps too,
        so the equation solved is a polynomial in steps:
            triax_wavelength(s) + (nm_per_pixel + change * (s - s_ref)) * dp
                + nm_per_pixel_squared * dp**2 - wavelength = 0
        """
        if at_pixel is None:
            at_pixel = self.reference_pixel
        pixel_offset = at_pixel - self.reference_pixel
        step_polynomial = np.array(self.triax_to_wavelength_coefficients, dtype=float)
        step_polynomial[-2] += self.nm_per_pixel_change_per_triax_step * pixel_offset
        step_polynomial[-1] += ((self.nm_per_pixel - self.nm_per_pixel_change_per_triax_step
                                 * self.dispersion_reference_triax_steps) * pixel_offset
                                + self.nm_per_pixel_squared * pixel_offset ** 2 - wavelength_nm)
        linear_estimate = -step_polynomial[-1] / step_polynomial[-2]
        if len(step_polynomial) == 2:
            return linear_estimate - self.triax_step_offset
        roots = np.roots(step_polynomial)
        real_roots = roots[np.isreal(roots)].real
        return real_roots[np.argmin(np.abs(real_roots - linear_estimate))] - self.triax_step_offset

    # -- storage --------------------------------------------------------------

    def to_dict(self):
        return {
            'reference_pixel': self.reference_pixel,
            'triax_to_wavelength_coefficients': [float(c) for c in self.triax_to_wavelength_coefficients],
            'nm_per_pixel': float(self.nm_per_pixel),
            'nm_per_pixel_squared': float(self.nm_per_pixel_squared),
            'nm_per_pixel_change_per_triax_step': float(self.nm_per_pixel_change_per_triax_step),
            'dispersion_reference_triax_steps': float(self.dispersion_reference_triax_steps),
            'triax_step_offset': float(self.triax_step_offset),
            'metadata': self.metadata,
        }

    @classmethod
    def from_dict(cls, stored):
        return cls(
            reference_pixel=float(stored['reference_pixel']),
            triax_to_wavelength_coefficients=list(stored['triax_to_wavelength_coefficients']),
            nm_per_pixel=float(stored['nm_per_pixel']),
            nm_per_pixel_squared=float(stored.get('nm_per_pixel_squared', 0.0)),
            nm_per_pixel_change_per_triax_step=float(stored.get('nm_per_pixel_change_per_triax_step', 0.0)),
            dispersion_reference_triax_steps=float(stored.get('dispersion_reference_triax_steps', 0.0)),
            triax_step_offset=float(stored.get('triax_step_offset', 0.0)),
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
    observation_groups: list = field(default_factory=list)  # a label per observation (its walk)
    group_offsets_nm: dict = field(default_factory=dict)    # each group's offset from the reference
    reference_group: str = ''

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
                        fit_dispersion_curvature=False, fit_dispersion_change_with_triax=False,
                        metadata=None, triax_step_uncertainty=0.0, observation_groups=None,
                        reference_group=None, separate_triax_from_ccd=False):
    """
    Weighted linear least-squares fit of the wavelength axis model.

    Each point is weighted by its combined uncertainty in nm: the reference
    wavelength uncertainty and the peak-centre uncertainty converted to nm
    with the dispersion (one refinement pass, since the dispersion is what
    is being fitted), plus, in quadrature, `triax_step_uncertainty` (1-sigma
    TRIAX positioning error in steps, converted to nm with the TRIAX slope).
    It defaults to 0; set it to the measured repeatability so reduced chi^2
    is meaningful when the TRIAX is the limiting error.

    The TRIAX polynomial is fitted in a centred, scaled step variable for
    numerical conditioning (steps are ~1e5) and converted back to raw-step
    coefficients for storage.

    fit_dispersion_change_with_triax adds one column, pixel_offset * scaled_steps:
    the dispersion is then fitted as nm_per_pixel at the centre of the walk
    plus a slope per TRIAX step, and the centre is stored as
    dispersion_reference_triax_steps. Use it for any walk that spans more
    than a few tens of nm (the Ar-Hg walk always does).

    `observation_groups` (one label per observation, e.g. the walk it came
    from) gives each group its own wavelength offset instead of one shared
    constant: walks taken before and after the TRIAX zero moved can then
    share the fit of the axis SHAPE. The stored model takes its zero from
    `reference_group` (default: the last group label, i.e. the latest walk
    when labels sort by time); `fit.group_offsets_nm` gives every group's
    offset relative to it.

    `separate_triax_from_ccd` fits in two stages (_fit_ccd_then_triax): the
    CCD terms first, with a free wavelength offset for every frame, then the
    TRIAX polynomial through those frame offsets. In one joint fit, a TRIAX
    error the polynomial cannot follow (the real drive departs from it by up
    to 0.19 nm) leaks into the shared CCD terms and bends the whole axis;
    with a free offset per frame it cannot, and it stays visible as the
    frames' departure from the polynomial.
    """
    observations = list(observations)
    _check_observations_can_determine_model(observations)
    if separate_triax_from_ccd:
        return _fit_ccd_then_triax(observations, reference_pixel, triax_polynomial_order,
                                   fit_dispersion_curvature, fit_dispersion_change_with_triax,
                                   metadata, observation_groups, reference_group)

    apparent_wavelengths = np.array([o.apparent_wavelength_nm for o in observations])
    triax_steps = np.array([o.triax_steps for o in observations], dtype=float)
    pixel_offsets = np.array([o.centre_pixel for o in observations]) - reference_pixel
    wavelength_uncertainties = np.array([o.wavelength_uncertainty_nm for o in observations])
    pixel_uncertainties = np.array([o.centre_uncertainty_pixels for o in observations])

    steps_centre = float(np.mean(triax_steps))
    steps_scale = float(np.ptp(triax_steps)) or 1.0
    scaled_steps = (triax_steps - steps_centre) / steps_scale

    groups = list(observation_groups) if observation_groups is not None \
        else ['all'] * len(observations)
    group_names = sorted(set(groups))
    reference_group = reference_group if reference_group is not None else group_names[-1]
    columns = {f'triax (scaled steps)^{power}': scaled_steps ** power
               for power in range(triax_polynomial_order, 0, -1)}
    columns.update(_constant_columns(groups, group_names))
    columns['nm_per_pixel'] = pixel_offsets
    if fit_dispersion_curvature:
        columns['nm_per_pixel_squared'] = pixel_offsets ** 2
    if fit_dispersion_change_with_triax:
        columns['nm_per_pixel x (scaled steps)'] = pixel_offsets * scaled_steps
    parameter_names = list(columns)
    design_matrix = np.column_stack(list(columns.values()))
    number_of_parameters = design_matrix.shape[1]
    if len(observations) <= number_of_parameters:
        raise CalibrationFitError(
            f"{len(observations)} observations for {number_of_parameters} parameters: take more "
            "TRIAX positions so the fit is over-determined and residuals mean something.")

    nm_per_pixel_estimate = 0.078
    # TRIAX positioning noise: a step error moves every line by (nm per step) * error.
    straightened = apparent_wavelengths - nm_per_pixel_estimate * pixel_offsets
    nm_per_step = abs(float(np.polyfit(triax_steps, straightened, 1)[0]))
    triax_uncertainties_nm = nm_per_step * triax_step_uncertainty
    for _refinement_pass in range(2):
        total_uncertainties_nm = np.sqrt(wavelength_uncertainties ** 2
                                         + (nm_per_pixel_estimate * pixel_uncertainties) ** 2
                                         + triax_uncertainties_nm ** 2)
        weighted_design = design_matrix / total_uncertainties_nm[:, None]
        weighted_target = apparent_wavelengths / total_uncertainties_nm
        if np.linalg.matrix_rank(weighted_design) < number_of_parameters:
            raise CalibrationFitError(
                "The observations are degenerate for this model (rank-deficient). "
                "Spread the line across more of the chip and use more TRIAX positions.")
        parameters, *_ = np.linalg.lstsq(weighted_design, weighted_target, rcond=None)
        nm_per_pixel_estimate = abs(parameters[parameter_names.index('nm_per_pixel')])

    residuals_nm = apparent_wavelengths - design_matrix @ parameters
    degrees_of_freedom = len(observations) - number_of_parameters
    reduced_chi_squared = float(np.sum((residuals_nm / total_uncertainties_nm) ** 2)
                                / degrees_of_freedom)
    covariance = np.linalg.inv(weighted_design.T @ weighted_design)
    parameter_uncertainties = np.sqrt(np.diag(covariance))
    fitted = dict(zip(parameter_names, parameters))
    raw_step_polynomial, group_offsets_nm = _triax_polynomial_in_raw_steps(
        fitted, triax_polynomial_order, group_names, reference_group, steps_centre, steps_scale)

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
        nm_per_pixel=float(fitted['nm_per_pixel']),
        nm_per_pixel_squared=float(fitted.get('nm_per_pixel_squared', 0.0)),
        nm_per_pixel_change_per_triax_step=float(fitted.get('nm_per_pixel x (scaled steps)', 0.0))
        / steps_scale,
        dispersion_reference_triax_steps=steps_centre if fit_dispersion_change_with_triax else 0.0,
        metadata=model_metadata,
    )
    return WavelengthAxisFit(
        model=model, observations=observations, residuals_nm=residuals_nm,
        reduced_chi_squared=reduced_chi_squared, parameter_names=parameter_names,
        parameter_values=parameters, parameter_uncertainties=parameter_uncertainties,
        observation_groups=groups, group_offsets_nm=group_offsets_nm,
        reference_group=reference_group,
    )


def _constant_columns(groups, group_names):
    """One constant column, or one per group (walk) when there are several groups."""
    if len(group_names) == 1:
        return {'triax (scaled steps)^0': np.ones(len(groups))}
    return {f'offset {group}': np.array([float(label == group) for label in groups])
            for group in group_names}


def _triax_polynomial_in_raw_steps(fitted, triax_polynomial_order, group_names, reference_group,
                                   steps_centre, steps_scale):
    """The fitted TRIAX polynomial in raw steps (zero from the reference group), group offsets."""
    if len(group_names) == 1:
        constant = fitted['triax (scaled steps)^0']
        group_offsets_nm = {}
    else:
        constant = fitted[f'offset {reference_group}']
        group_offsets_nm = {group: float(fitted[f'offset {group}'] - constant)
                            for group in group_names}
    scaled_step_polynomial = np.poly1d([fitted[f'triax (scaled steps)^{power}']
                                        for power in range(triax_polynomial_order, 0, -1)]
                                       + [constant])
    raw_steps = np.poly1d([1.0 / steps_scale, -steps_centre / steps_scale])
    return scaled_step_polynomial(raw_steps), group_offsets_nm


def _fit_ccd_then_triax(observations, reference_pixel, triax_polynomial_order,
                        fit_dispersion_curvature, fit_dispersion_change_with_triax, metadata,
                        observation_groups, reference_group):
    """
    Two-stage fit (see fit_wavelength_axis, separate_triax_from_ccd).

    Stage 1, the CCD: wavelength = offset_frame + nm_per_pixel * dp [+ squared * dp^2]
    [+ change * dp * s], one free offset per frame (group, TRIAX position), weighted by the point
    uncertainties.
    Stage 2, the TRIAX: the frame offsets (wavelength on the reference pixel at each position)
    fitted with the polynomial in scaled steps, one constant per group.
    """
    apparent_wavelengths = np.array([o.apparent_wavelength_nm for o in observations])
    triax_steps = np.array([o.triax_steps for o in observations], dtype=float)
    pixel_offsets = np.array([o.centre_pixel for o in observations]) - reference_pixel
    groups = list(observation_groups) if observation_groups is not None \
        else ['all'] * len(observations)
    group_names = sorted(set(groups))
    reference_group = reference_group if reference_group is not None else group_names[-1]
    steps_centre = float(np.mean(triax_steps))
    steps_scale = float(np.ptp(triax_steps)) or 1.0
    scaled_steps = (triax_steps - steps_centre) / steps_scale

    # Stage 1: the CCD terms, with a free offset per frame.
    frames = sorted(set(zip(groups, triax_steps.astype(int))))
    frame_index = {frame: index for index, frame in enumerate(frames)}
    observation_frames = np.array([frame_index[(group, int(steps))]
                                   for group, steps in zip(groups, triax_steps)])
    ccd_columns = {'nm_per_pixel': pixel_offsets}
    if fit_dispersion_curvature:
        ccd_columns['nm_per_pixel_squared'] = pixel_offsets ** 2
    if fit_dispersion_change_with_triax:
        ccd_columns['nm_per_pixel x (scaled steps)'] = pixel_offsets * scaled_steps
    frame_columns = (observation_frames[:, None] == np.arange(len(frames))[None, :]).astype(float)
    design = np.column_stack([frame_columns] + list(ccd_columns.values()))
    if len(observations) <= design.shape[1]:
        raise CalibrationFitError(
            f"{len(observations)} observations for {len(frames)} frame offsets and "
            f"{len(ccd_columns)} CCD terms: each frame needs at least two lines, and some frames "
            "more, for the CCD axis to be determined.")
    nm_per_pixel_estimate = 0.078
    for _refinement_pass in range(2):
        uncertainties_nm = np.sqrt(
            np.array([o.wavelength_uncertainty_nm for o in observations]) ** 2
            + (nm_per_pixel_estimate * np.array([o.centre_uncertainty_pixels
                                                 for o in observations])) ** 2)
        weighted_design = design / uncertainties_nm[:, None]
        if np.linalg.matrix_rank(weighted_design) < design.shape[1]:
            raise CalibrationFitError(
                "The CCD axis is not determined: too few frames with two or more lines spread "
                "across the chip.")
        stage_one, *_ = np.linalg.lstsq(weighted_design, apparent_wavelengths / uncertainties_nm,
                                        rcond=None)
        nm_per_pixel_estimate = abs(stage_one[len(frames)])
    stage_one_covariance = np.linalg.inv(weighted_design.T @ weighted_design)
    stage_one_uncertainties = np.sqrt(np.diag(stage_one_covariance))
    ccd_values = dict(zip(ccd_columns, stage_one[len(frames):]))
    ccd_uncertainties = stage_one_uncertainties[len(frames):]

    # Stage 2: the TRIAX polynomial through the frame offsets.
    frame_offsets = stage_one[:len(frames)]
    frame_groups = [group for group, _ in frames]
    frame_scaled_steps = (np.array([steps for _, steps in frames], dtype=float) - steps_centre) \
        / steps_scale
    triax_columns = {f'triax (scaled steps)^{power}': frame_scaled_steps ** power
                     for power in range(triax_polynomial_order, 0, -1)}
    triax_columns.update(_constant_columns(frame_groups, group_names))
    triax_design = np.column_stack(list(triax_columns.values()))
    if len(frames) < triax_design.shape[1]:
        raise CalibrationFitError(f"{len(frames)} frames for {triax_design.shape[1]} TRIAX terms: "
                                  "walk over more TRIAX positions.")
    # The frame offsets carry the TRIAX drive error, which is far larger than their statistical
    # uncertainty; weighting by that uncertainty alone lets the best frames pull the polynomial.
    frame_weights = 1.0 / np.sqrt(stage_one_uncertainties[:len(frames)] ** 2 + 0.01 ** 2)
    weighted_triax_design = triax_design * frame_weights[:, None]
    triax_values_array, *_ = np.linalg.lstsq(weighted_triax_design, frame_offsets * frame_weights,
                                             rcond=None)
    triax_covariance = np.linalg.pinv(weighted_triax_design.T @ weighted_triax_design)
    raw_step_polynomial, group_offsets_nm = _triax_polynomial_in_raw_steps(
        dict(zip(triax_columns, triax_values_array)), triax_polynomial_order, group_names,
        reference_group, steps_centre, steps_scale)

    dispersion_change = ccd_values.get('nm_per_pixel x (scaled steps)', 0.0) / steps_scale
    model = WavelengthAxisModel(
        reference_pixel=float(reference_pixel),
        triax_to_wavelength_coefficients=[float(c) for c in raw_step_polynomial.coeffs],
        nm_per_pixel=float(ccd_values['nm_per_pixel']),
        nm_per_pixel_squared=float(ccd_values.get('nm_per_pixel_squared', 0.0)),
        nm_per_pixel_change_per_triax_step=float(dispersion_change),
        dispersion_reference_triax_steps=steps_centre if fit_dispersion_change_with_triax else 0.0)
    group_offset_of_observation = np.array([group_offsets_nm.get(group, 0.0) for group in groups])
    model_wavelengths = np.array([model.wavelength_at(o.centre_pixel, o.triax_steps)
                                  for o in observations])
    residuals_nm = apparent_wavelengths - group_offset_of_observation - model_wavelengths
    number_of_parameters = len(ccd_columns) + len(triax_columns)
    reduced_chi_squared = float(np.sum((residuals_nm / uncertainties_nm) ** 2)
                                / max(len(observations) - number_of_parameters, 1))
    model.metadata = {
        'fitted_on': datetime.date.today().isoformat(),
        'number_of_observations': len(observations),
        'residual_rms_nm': float(np.sqrt(np.mean(residuals_nm ** 2))),
        'reduced_chi_squared': reduced_chi_squared,
        'fit_method': 'CCD terms with a free offset per frame, then the TRIAX polynomial through '
                      'the frame offsets',
        **(metadata or {}),
    }
    return WavelengthAxisFit(
        model=model, observations=observations, residuals_nm=residuals_nm,
        reduced_chi_squared=reduced_chi_squared,
        parameter_names=list(triax_columns) + list(ccd_columns),
        parameter_values=np.concatenate([triax_values_array, list(ccd_values.values())]),
        parameter_uncertainties=np.concatenate([np.sqrt(np.diag(triax_covariance)),
                                                ccd_uncertainties]),
        observation_groups=groups, group_offsets_nm=group_offsets_nm,
        reference_group=reference_group)


def largest_axis_difference_nm(first_model, second_model, triax_steps_values, number_of_pixels=1024):
    """Largest wavelength disagreement between two models over the chip and TRIAX positions given."""
    differences = [np.max(np.abs(first_model.wavelength_axis(steps, number_of_pixels)
                                 - second_model.wavelength_axis(steps, number_of_pixels)))
                   for steps in triax_steps_values]
    return float(np.max(differences))
