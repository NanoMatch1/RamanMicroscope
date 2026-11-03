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

The line catalogue
------------------
`catalogue_lines` must hold EVERY line that can land on the chip, including
ones that are not used as references (unresolved blends, second- and
third-order lines). A line the walk doesn't know about can be mistaken for
a known line nearby. Only lines with usable_as_reference=True are recorded.

Planning
--------
The chip spans ~79 nm. The TRIAX slides it across the range of the usable
lines in steps of 1/samples_per_line of its width, so each line is seen at
about samples_per_line different places on the chip. With a lamp full of
lines this takes ~25 positions, instead of one set of positions per line.

Identifying lines
-----------------
The CURRENT calibration predicts where each line should be. Prediction errors
of tens of pixels are expected (that is why we are calibrating), but the
slope is close, so the error is mostly a common shift. The shift is found on
the first spectrum by pattern matching: the shift that lines up the most
detected peaks with predicted lines (within a few pixels) wins. It is then
refined from every matched line.

A line is used at a position only if:
- no other catalogue line is predicted within `minimum_resolved_separation_pixels`
  (closer lines blend and pull the fitted centre);
- exactly the nearest detected peak is within `match_tolerance_pixels`, and
  that peak's nearest predicted line is this one (mutual nearest neighbours);
- the peak is not saturated (a clipped top biases the fit), and its
  signal-to-noise passes the threshold.
The fit window is narrowed to half the distance to the nearest other peak,
so a neighbour's tail stays out of it. Every rejection is recorded in the
position's notes.

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
                 planning_model, catalogue_lines, number_of_pixels=1024,
                 samples_per_line=6, approach_steps=2000, minimum_signal_to_noise=10.0,
                 pattern_tolerance_pixels=3.0, match_tolerance_pixels=4.0, largest_shift_pixels=60.0,
                 minimum_resolved_separation_pixels=8.0, edge_margin_pixels=15,
                 saturation_level=None, logger=None):
        self.move_triax_to_steps = move_triax_to_steps
        self.read_triax_steps = read_triax_steps
        self.acquire_spectrum = acquire_spectrum
        self.planning_model = planning_model
        self.catalogue_lines = list(catalogue_lines)
        self.number_of_pixels = number_of_pixels
        self.samples_per_line = samples_per_line
        self.approach_steps = approach_steps
        self.minimum_signal_to_noise = minimum_signal_to_noise
        self.pattern_tolerance_pixels = pattern_tolerance_pixels
        self.match_tolerance_pixels = match_tolerance_pixels
        self.largest_shift_pixels = largest_shift_pixels
        self.minimum_resolved_separation_pixels = minimum_resolved_separation_pixels
        self.edge_margin_pixels = edge_margin_pixels
        self.saturation_level = saturation_level
        self.logger = logger or logging.getLogger('LineWalk')

    @property
    def usable_lines(self):
        return [line for line in self.catalogue_lines if line.usable_as_reference]

    def plan_triax_positions(self):
        """TRIAX positions (ascending) that slide the chip across the usable lines; see module docstring."""
        usable_wavelengths = [line.apparent_wavelength_nm for line in self.usable_lines]
        if not usable_wavelengths:
            return []
        chip_width_nm = abs(self.planning_model.nm_per_pixel) * (self.number_of_pixels - 1)
        edge_margin_nm = abs(self.planning_model.nm_per_pixel) * self.edge_margin_pixels
        chip_start_step_nm = chip_width_nm / self.samples_per_line
        first_chip_start_nm = min(usable_wavelengths) - chip_width_nm + edge_margin_nm
        last_chip_start_nm = max(usable_wavelengths) - edge_margin_nm
        chip_starts_nm = np.arange(first_chip_start_nm, last_chip_start_nm + chip_start_step_nm / 2,
                                   chip_start_step_nm)
        positions = {int(round(self.planning_model.triax_steps_for_wavelength(chip_start_nm, at_pixel=0)))
                     for chip_start_nm in chip_starts_nm}
        return sorted(positions)

    def _predicted_pixels(self, triax_steps):
        """Predicted pixel of every catalogue line, by the planning model (no shift applied)."""
        return np.array([self.planning_model.pixel_of_wavelength(line.apparent_wavelength_nm, triax_steps)
                         for line in self.catalogue_lines])

    def _measure_at_position(self, measured_steps, spectrum, pixel_shift, record):
        """Identify and fit the usable lines in one spectrum. Returns (observations, prediction offsets)."""
        detected_pixels = np.array(find_line_peaks(spectrum, minimum_signal_to_noise=self.minimum_signal_to_noise))
        record.detected_pixels = [int(pixel) for pixel in detected_pixels]
        predicted_pixels = self._predicted_pixels(measured_steps) + pixel_shift

        observations, prediction_offsets = [], []
        for line_index, line in enumerate(self.catalogue_lines):
            predicted_pixel = predicted_pixels[line_index]
            if not line.usable_as_reference:
                continue
            if not (self.edge_margin_pixels <= predicted_pixel < self.number_of_pixels - self.edge_margin_pixels):
                continue

            other_predicted = np.delete(predicted_pixels, line_index)
            nearest_other_line_distance = float(np.min(np.abs(other_predicted - predicted_pixel))) \
                if other_predicted.size else np.inf
            if nearest_other_line_distance < self.minimum_resolved_separation_pixels:
                record.notes.append(f"{line.label}: another line within {nearest_other_line_distance:.1f} px, "
                                    "skipped as unresolved")
                continue

            if detected_pixels.size == 0:
                record.notes.append(f"{line.label}: no peaks detected")
                continue
            distances_to_detected = np.abs(detected_pixels - predicted_pixel)
            nearest_detected_index = int(np.argmin(distances_to_detected))
            peak_pixel = int(detected_pixels[nearest_detected_index])
            if distances_to_detected[nearest_detected_index] > self.match_tolerance_pixels:
                record.notes.append(f"{line.label}: no peak within {self.match_tolerance_pixels:.0f} px "
                                    f"of predicted {predicted_pixel:.0f}")
                continue
            if int(np.argmin(np.abs(predicted_pixels - peak_pixel))) != line_index:
                record.notes.append(f"{line.label}: peak at {peak_pixel} is closer to another line's prediction")
                continue

            other_detected = np.delete(detected_pixels, nearest_detected_index)
            nearest_other_peak_distance = float(np.min(np.abs(other_detected - peak_pixel))) \
                if other_detected.size else np.inf
            clear_distance_pixels = min(nearest_other_peak_distance, nearest_other_line_distance, 24.0)
            half_window_pixels = int(np.clip(clear_distance_pixels // 2, 4, 12))
            if self.saturation_level is not None:
                window = spectrum[max(0, peak_pixel - half_window_pixels):peak_pixel + half_window_pixels + 1]
                if np.max(window) >= self.saturation_level:
                    record.notes.append(f"{line.label}: saturated, skipped (shorten the exposure)")
                    continue

            peak_fit = fit_line_peak(spectrum, peak_pixel, half_window_pixels=half_window_pixels)
            if peak_fit is None or peak_fit.signal_to_noise < self.minimum_signal_to_noise:
                record.notes.append(f"{line.label}: peak fit failed or too weak")
                continue
            observations.append(LineObservation(
                line_name=line.label,
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
            raise ValueError("No TRIAX positions to visit: no usable reference line in the catalogue.")

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
                                                     self.pattern_tolerance_pixels, self.largest_shift_pixels)
                if pixel_shift is None:
                    record.notes.append("no line pattern recognised yet; position not used")
                    continue
                self.logger.info(f"Line walk: lines sit {pixel_shift:+.1f} px from where the current "
                                 "calibration predicts")

            position_observations, prediction_offsets = self._measure_at_position(
                measured_steps, spectrum, pixel_shift, record)
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
