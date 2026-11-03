"""
The line walk: step the TRIAX so known lines walk across the CCD, and record
where each line lands.

At each TRIAX position the procedure acquires a spectrum, finds the lines,
identifies which known line each peak is, fits its centre in pixels and
records a LineObservation. The observations are what fit_wavelength_axis
needs; the walk itself knows nothing about fitting.

Hardware is injected as three plain callables, so the same code runs on the
bench, in simulate mode and in unit tests:

    move_triax_to_steps(target_steps)   absolute move, returns when done
    read_triax_steps() -> int           the TRIAX's own position report
    acquire_spectrum() -> 1D array      one value per CCD column

Identifying lines uses the CURRENT calibration only to predict roughly where
each line should be. Prediction errors of tens of pixels are expected (that
is why we are calibrating), so a common pixel shift is estimated from the
first spectrum by matching the pattern of detected peaks to the pattern of
predicted lines, then refined from every matched line after that.

The defaults (shift search +/-60 px, match tolerance 20 px) suit the
second-order mercury pair 809.3/815.6 nm, which sit ~80 px apart: a larger
search could mistake one line for the other. If the current calibration is
off by more than ~60 px, widen `largest_shift_pixels` and check the report;
a misidentified line shows up as a residual of several nm.

Backlash: positions are visited in increasing step order, starting from a
point `approach_steps` below the first one, so every measurement is reached
moving in the same direction.
"""

from dataclasses import dataclass, field
import datetime
import json
import logging

import numpy as np

from .line_peaks import find_line_peaks, fit_line_peak
from .wavelength_axis_model import LineObservation, WavelengthAxisModel


def estimate_pattern_shift(detected_pixels, predicted_pixels, match_tolerance_pixels, largest_shift_pixels):
    """
    The common pixel shift that best lines up detected peaks with predicted lines.

    Every (detected - predicted) difference within `largest_shift_pixels` is a
    candidate shift; the winner matches the most predicted lines within
    `match_tolerance_pixels`, ties going to the smaller shift. Returns None if
    nothing matches.
    """
    detected_pixels = np.asarray(detected_pixels, dtype=float)
    predicted_pixels = np.asarray(predicted_pixels, dtype=float)
    if detected_pixels.size == 0 or predicted_pixels.size == 0:
        return None

    candidate_shifts = (detected_pixels[:, None] - predicted_pixels[None, :]).ravel()
    candidate_shifts = candidate_shifts[np.abs(candidate_shifts) <= largest_shift_pixels]
    best_shift, best_match_count = None, 0
    for shift in sorted(candidate_shifts, key=abs):
        distances = np.abs(detected_pixels[:, None] - (predicted_pixels[None, :] + shift))
        match_count = int(np.sum(distances.min(axis=0) <= match_tolerance_pixels))
        if match_count > best_match_count:
            best_shift, best_match_count = float(shift), match_count
    return best_shift


@dataclass
class LineWalkPositionRecord:
    """What happened at one TRIAX position, kept for the report and for debugging."""

    requested_steps: int
    measured_steps: int
    detected_pixels: list
    matched_lines: list
    notes: list = field(default_factory=list)


@dataclass
class LineWalkResult:
    observations: list
    position_records: list
    final_pixel_shift: float


class LineWalk:
    """Runs the line walk. See the module docstring for the procedure."""

    def __init__(self, move_triax_to_steps, read_triax_steps, acquire_spectrum,
                 planning_model, reference_lines, number_of_pixels=1024,
                 target_pixels=(100, 250, 400, 550, 700, 850, 950),
                 approach_steps=2000, minimum_signal_to_noise=10.0,
                 match_tolerance_pixels=20.0, largest_shift_pixels=60.0,
                 edge_margin_pixels=15, logger=None):
        self.move_triax_to_steps = move_triax_to_steps
        self.read_triax_steps = read_triax_steps
        self.acquire_spectrum = acquire_spectrum
        self.planning_model = planning_model
        self.reference_lines = list(reference_lines)
        self.number_of_pixels = number_of_pixels
        self.target_pixels = tuple(target_pixels)
        self.approach_steps = approach_steps
        self.minimum_signal_to_noise = minimum_signal_to_noise
        self.match_tolerance_pixels = match_tolerance_pixels
        self.largest_shift_pixels = largest_shift_pixels
        self.edge_margin_pixels = edge_margin_pixels
        self.logger = logger or logging.getLogger('LineWalk')

    def plan_triax_positions(self):
        """TRIAX positions (ascending) that put each line on each target pixel, per the planning model."""
        positions = {
            int(round(self.planning_model.triax_steps_for_wavelength(line.apparent_wavelength_nm, at_pixel=pixel)))
            for line in self.reference_lines for pixel in self.target_pixels
        }
        return sorted(positions)

    def _predicted_pixels(self, triax_steps):
        return np.array([self.planning_model.pixel_of_wavelength(line.apparent_wavelength_nm, triax_steps)
                         for line in self.reference_lines])

    def _measure_at_position(self, measured_steps, spectrum, pixel_shift, record):
        """Identify and fit lines in one spectrum. Returns (observations, centre - prediction offsets)."""
        detected_pixels = find_line_peaks(spectrum, minimum_signal_to_noise=self.minimum_signal_to_noise)
        record.detected_pixels = detected_pixels
        predicted_pixels = self._predicted_pixels(measured_steps) + pixel_shift

        observations, prediction_offsets = [], []
        for line, predicted_pixel in zip(self.reference_lines, predicted_pixels):
            if not (self.edge_margin_pixels <= predicted_pixel < self.number_of_pixels - self.edge_margin_pixels):
                continue
            candidates = [pixel for pixel in detected_pixels
                          if abs(pixel - predicted_pixel) <= self.match_tolerance_pixels]
            if not candidates:
                record.notes.append(f"{line.name} (order {line.diffraction_order}): no peak near pixel "
                                    f"{predicted_pixel:.0f}")
                continue
            if len(candidates) > 1:
                record.notes.append(f"{line.name}: {len(candidates)} peaks within tolerance, skipped as ambiguous")
                continue
            peak_fit = fit_line_peak(spectrum, candidates[0])
            if peak_fit is None or peak_fit.signal_to_noise < self.minimum_signal_to_noise:
                record.notes.append(f"{line.name}: peak fit failed or too weak")
                continue
            observations.append(LineObservation(
                line_name=f"{line.name} (order {line.diffraction_order})",
                apparent_wavelength_nm=line.apparent_wavelength_nm,
                wavelength_uncertainty_nm=line.wavelength_uncertainty_nm,
                triax_steps=int(measured_steps),
                centre_pixel=peak_fit.centre_pixel,
                centre_uncertainty_pixels=peak_fit.centre_uncertainty_pixels,
            ))
            prediction_offsets.append(peak_fit.centre_pixel - (predicted_pixel - pixel_shift))
            record.matched_lines.append(line.name)
        return observations, prediction_offsets

    def run(self, triax_positions=None):
        """Walk the TRIAX through `triax_positions` (default: the plan) and collect observations."""
        if triax_positions is None:
            triax_positions = self.plan_triax_positions()
        triax_positions = sorted(int(position) for position in triax_positions)
        if not triax_positions:
            raise ValueError("No TRIAX positions to visit: no reference line falls on the chip.")

        self.move_triax_to_steps(triax_positions[0] - self.approach_steps)

        pixel_shift = None
        all_prediction_offsets, observations, position_records = [], [], []
        for requested_steps in triax_positions:
            self.move_triax_to_steps(requested_steps)
            measured_steps = int(self.read_triax_steps())
            record = LineWalkPositionRecord(requested_steps=requested_steps, measured_steps=measured_steps,
                                            detected_pixels=[], matched_lines=[])
            position_records.append(record)
            if measured_steps != requested_steps:
                # The TRIAX may still be moving (move timed out): a frame now would smear the lines.
                record.notes.append(f"TRIAX reports {measured_steps}, requested {requested_steps}: "
                                    "position skipped")
                self.logger.warning(f"Line walk: TRIAX at {measured_steps}, requested {requested_steps}; skipped")
                continue
            spectrum = np.asarray(self.acquire_spectrum(), dtype=float)

            if pixel_shift is None:
                detected_pixels = find_line_peaks(spectrum, minimum_signal_to_noise=self.minimum_signal_to_noise)
                pixel_shift = estimate_pattern_shift(detected_pixels, self._predicted_pixels(measured_steps),
                                                     self.match_tolerance_pixels, self.largest_shift_pixels)
                if pixel_shift is not None:
                    self.logger.info(f"Line walk: lines sit {pixel_shift:+.1f} px from where the current "
                                     "calibration predicts")

            position_observations, prediction_offsets = self._measure_at_position(
                measured_steps, spectrum, pixel_shift or 0.0, record)
            observations.extend(position_observations)
            all_prediction_offsets.extend(prediction_offsets)
            if all_prediction_offsets:
                pixel_shift = float(np.median(all_prediction_offsets))
            self.logger.info(f"Line walk: TRIAX {measured_steps} -> matched {record.matched_lines or 'nothing'}")

        return LineWalkResult(observations=observations, position_records=position_records,
                              final_pixel_shift=pixel_shift if pixel_shift is not None else float('nan'))


def save_line_walk(path, result, planning_model, description=''):
    """Write the raw observations and position records to JSON (the input to the fit)."""
    contents = {
        'data_type': 'wavelength_axis_line_walk',
        'recorded_on': datetime.datetime.now().isoformat(timespec='seconds'),
        'description': description,
        'planning_model': planning_model.to_dict(),
        'final_pixel_shift': result.final_pixel_shift,
        'observations': [observation.as_dict() for observation in result.observations],
        'position_records': [record.__dict__ for record in result.position_records],
    }
    with open(path, 'w') as file:
        json.dump(contents, file, indent=2)


def load_line_walk_observations(path):
    """Read observations (and the planning model) back from a saved line walk."""
    with open(path) as file:
        contents = json.load(file)
    observations = [LineObservation(**stored) for stored in contents['observations']]
    planning_model = WavelengthAxisModel.from_dict(contents['planning_model'])
    return observations, planning_model, contents
