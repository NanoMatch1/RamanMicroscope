"""
Does the TRIAX put the same line on the same pixel every time it is sent to the same step?

A line walk visits the same planned TRIAX positions whenever the calibration in
use is the same, so repeated walks measure each (line, TRIAX step) pair more
than once. If the fitted pixel of a line differs between repeats, the TRIAX
is not where it reports: backlash, lost steps or a drive error. Such an error
moves every line at that position together, so it is estimated as one offset
per (walk, TRIAX position): the median over the lines at that position of the
line's pixel minus its median pixel over the repeats (the median keeps one
misidentified walk from dragging the others away).

A large offset that changes from one repeat to the next is random positioning
error. Offsets near zero mean the walks agree, so a poor wavelength fit comes
from something that repeats (the model, or a systematic drive error).

Pure and deterministic: nothing here touches hardware.
"""

import datetime
import json
import os
from dataclasses import dataclass, field

import numpy as np

from .line_walk import load_line_walk_observations

DEFAULT_TOLERANCE_PIXELS = 0.2
LIKELY_MISIDENTIFICATION_PIXELS = 5.0


@dataclass
class PositionRepeatability:
    """How well the repeats agree at one TRIAX position."""

    triax_steps: int
    number_of_lines: int
    offsets_pixels: dict       # walk label -> offset (pixels) of that walk from the repeat median
    spread_pixels: float       # standard deviation of the offsets over the walks
    line_scatter_pixels: float  # scatter of lines about the offset (nan when under 3 lines)
    suspect_offsets_pixels: dict = field(default_factory=dict)  # offsets too big to be the TRIAX; see module note


@dataclass
class TriaxRepeatability:
    """
    Result of comparing repeated line walks.

    An offset larger than `misidentification_pixels` is far more likely a line
    identified as its neighbour in one walk than TRIAX positioning, so it is
    listed as a suspect and kept out of the verdict and the statistics. The
    verdict is INCONCLUSIVE when most offsets are suspects.
    """

    walk_labels: list
    positions: list
    tolerance_pixels: float
    nm_per_pixel: float
    steps_per_pixel: float
    ignored_observations: int = 0
    notes: list = field(default_factory=list)
    misidentification_pixels: float = LIKELY_MISIDENTIFICATION_PIXELS

    def _accepted_offsets(self):
        return [offset for position in self.positions for offset in position.offsets_pixels.values()]

    @property
    def number_of_suspect_offsets(self):
        return sum(len(position.suspect_offsets_pixels) for position in self.positions)

    @property
    def largest_offset_pixels(self):
        """Largest offset that is not a suspected misidentification (nan when there is none)."""
        offsets = self._accepted_offsets()
        return max(abs(offset) for offset in offsets) if offsets else float('nan')

    @property
    def rms_offset_pixels(self):
        offsets = self._accepted_offsets()
        return float(np.sqrt(np.mean(np.square(offsets)))) if offsets else float('nan')

    @property
    def verdict(self):
        """'REPEATABLE', 'NOT REPEATABLE', or 'INCONCLUSIVE' (nothing to compare, or mostly suspect offsets)."""
        accepted = len(self._accepted_offsets())
        if accepted == 0 or self.number_of_suspect_offsets > accepted:
            return 'INCONCLUSIVE'
        return 'REPEATABLE' if self.largest_offset_pixels <= self.tolerance_pixels else 'NOT REPEATABLE'

    @property
    def repeatable(self):
        """True when every walk agrees with the others to within the tolerance at every position."""
        return self.verdict == 'REPEATABLE'

    def report_lines(self):
        """Human-readable summary: verdict, then the offset of every walk at every position."""
        if not self.positions:
            return list(self.notes) or ["No (line, TRIAX step) pair was measured in more than one walk."]
        lines = [
            f"TRIAX repeatability over {len(self.walk_labels)} walks, {len(self.positions)} positions: "
            f"{self.verdict}",
        ]
        if self._accepted_offsets():
            lines.append(
                f"largest offset {self.largest_offset_pixels:.3f} px "
                f"({self.largest_offset_pixels * self.nm_per_pixel:.4f} nm, "
                f"~{self.largest_offset_pixels * self.steps_per_pixel:.1f} TRIAX steps), "
                f"rms {self.rms_offset_pixels:.3f} px, tolerance {self.tolerance_pixels:.3f} px")
        lines.extend([
            "offset of each walk from the median of the walks, pixels (+ = line to higher pixel; "
            "* = suspected misidentification, not counted):",
            f"{'TRIAX':>8} {'lines':>5} " + " ".join(f"{index + 1:>8}" for index in range(len(self.walk_labels)))
            + f" {'spread':>7}",
        ])
        for position in self.positions:
            cells = []
            for label in self.walk_labels:
                if label in position.suspect_offsets_pixels:
                    cells.append(f"{position.suspect_offsets_pixels[label]:>+7.3f}*")
                elif label in position.offsets_pixels:
                    cells.append(f"{position.offsets_pixels[label]:>+8.3f}")
                else:
                    cells.append(f"{'-':>8}")
            lines.append(f"{position.triax_steps:>8} {position.number_of_lines:>5} " + " ".join(cells)
                         + f" {position.spread_pixels:>7.3f}")
        lines.append("walks: " + ", ".join(f"{index + 1} = {label}" for index, label in enumerate(self.walk_labels)))
        lines.extend(self.notes)
        return lines

    def to_dict(self):
        return {
            'data_type': 'triax_repeatability',
            'recorded_on': datetime.datetime.now().isoformat(timespec='seconds'),
            'verdict': self.verdict,
            'repeatable': self.repeatable,
            'tolerance_pixels': self.tolerance_pixels,
            'misidentification_pixels': self.misidentification_pixels,
            'largest_offset_pixels': self.largest_offset_pixels,
            'rms_offset_pixels': self.rms_offset_pixels,
            'number_of_suspect_offsets': self.number_of_suspect_offsets,
            'nm_per_pixel': self.nm_per_pixel,
            'steps_per_pixel': self.steps_per_pixel,
            'walks': self.walk_labels,
            'positions': [
                {'triax_steps': position.triax_steps, 'number_of_lines': position.number_of_lines,
                 'offsets_pixels': position.offsets_pixels,
                 'suspect_offsets_pixels': position.suspect_offsets_pixels,
                 'spread_pixels': position.spread_pixels,
                 'line_scatter_pixels': position.line_scatter_pixels}
                for position in self.positions],
            'notes': self.notes,
        }


def compare_repeated_walks(labelled_observations, nm_per_pixel=0.0775, steps_per_pixel=8.5,
                           tolerance_pixels=DEFAULT_TOLERANCE_PIXELS,
                           misidentification_pixels=LIKELY_MISIDENTIFICATION_PIXELS):
    """
    Compare the fitted pixels of the same lines at the same TRIAX steps across walks.

    `labelled_observations` is a list of (label, observations), one per walk.
    A (line, TRIAX step) pair counts only when at least two walks measured it.
    Offsets over `misidentification_pixels` are kept apart as suspects (see TriaxRepeatability).
    `nm_per_pixel` and `steps_per_pixel` only convert the pixel offsets for the report.
    """
    labels = [label for label, _observations in labelled_observations]
    centres = {}  # (line name, triax steps) -> {walk label: centre pixel}
    for label, observations in labelled_observations:
        for observation in observations:
            key = (observation.line_name, int(observation.triax_steps))
            centres.setdefault(key, {}).setdefault(label, float(observation.centre_pixel))

    deviations = {}  # triax steps -> walk label -> [deviation of each line from its repeat median]
    ignored = 0
    for (_line_name, triax_steps), per_walk in centres.items():
        if len(per_walk) < 2:
            ignored += 1
            continue
        reference_centre = float(np.median(list(per_walk.values())))  # robust to one misidentified walk
        for label, centre in per_walk.items():
            deviations.setdefault(triax_steps, {}).setdefault(label, []).append(centre - reference_centre)

    positions = []
    for triax_steps in sorted(deviations):
        offsets, suspect_offsets, scatters, lines_seen = {}, {}, [], 0
        for label, walk_deviations in deviations[triax_steps].items():
            offset = float(np.median(walk_deviations))
            if abs(offset) > misidentification_pixels:
                suspect_offsets[label] = offset
            else:
                offsets[label] = offset
                if len(walk_deviations) >= 3:
                    scatters.append(float(np.std(np.array(walk_deviations) - offset)))
            lines_seen = max(lines_seen, len(walk_deviations))
        positions.append(PositionRepeatability(
            triax_steps=triax_steps, number_of_lines=lines_seen, offsets_pixels=offsets,
            spread_pixels=float(np.std(list(offsets.values()), ddof=1)) if len(offsets) > 1 else float('nan'),
            line_scatter_pixels=float(np.mean(scatters)) if scatters else float('nan'),
            suspect_offsets_pixels=suspect_offsets))

    notes = []
    suspect_positions = [position.triax_steps for position in positions if position.suspect_offsets_pixels]
    if suspect_positions:
        count = sum(len(position.suspect_offsets_pixels) for position in positions)
        notes.append(f"{count} offset(s) over {misidentification_pixels:g} px at TRIAX {suspect_positions} were "
                     "left out of the verdict: more likely a line identified as its neighbour in one walk than "
                     "TRIAX positioning. Check those walks' DEBUG notes and spectra.")
    if ignored:
        notes.append(f"{ignored} (line, TRIAX step) pair(s) were seen in only one walk and are not compared.")
    if not positions:
        notes.append("No (line, TRIAX step) pair was measured in more than one walk. "
                     "Repeat walks must start from the same calibration so they visit the same TRIAX steps.")
    return TriaxRepeatability(walk_labels=labels, positions=positions, tolerance_pixels=float(tolerance_pixels),
                              nm_per_pixel=float(nm_per_pixel), steps_per_pixel=float(steps_per_pixel),
                              ignored_observations=ignored, notes=notes,
                              misidentification_pixels=float(misidentification_pixels))


def compare_repeated_walk_files(line_walk_paths, tolerance_pixels=DEFAULT_TOLERANCE_PIXELS):
    """Load saved line walks and compare them; the conversions use the first walk's planning model."""
    labelled_observations, planning_model = [], None
    for path in line_walk_paths:
        observations, walk_planning_model, _contents = load_line_walk_observations(path)
        labelled_observations.append((os.path.basename(str(path)), observations))
        planning_model = planning_model or walk_planning_model
    nm_per_pixel, steps_per_pixel = 0.0775, 8.5
    all_steps = [o.triax_steps for _label, observations in labelled_observations for o in observations]
    if planning_model is not None and all_steps:
        nm_per_pixel = abs(planning_model.nm_per_pixel)
        slope_polynomial = np.polyder(np.poly1d(planning_model.triax_to_wavelength_coefficients))
        nm_per_step = abs(float(slope_polynomial(float(np.median(all_steps)))))
        if nm_per_step > 0:
            steps_per_pixel = nm_per_pixel / nm_per_step
    return compare_repeated_walks(labelled_observations, nm_per_pixel=nm_per_pixel,
                                  steps_per_pixel=steps_per_pixel, tolerance_pixels=tolerance_pixels)


def save_triax_repeatability(directory, result):
    """Write the offsets to a timestamped JSON file in `directory` (created). Returns the path."""
    os.makedirs(directory, exist_ok=True)
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    path = os.path.join(directory, f'triax_repeatability_{timestamp}.json')
    repeat_number = 1
    while os.path.exists(path):
        repeat_number += 1
        path = os.path.join(directory, f'triax_repeatability_{timestamp}_{repeat_number}.json')
    with open(path, 'w') as file:
        json.dump(result.to_dict(), file, indent=2)
    return path
