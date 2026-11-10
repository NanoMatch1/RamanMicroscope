"""
The line walk: step the TRIAX so known lines walk across the CCD, and record
a spectrum at every position.

The walk only ACQUIRES. Which line is which is decided afterwards, from all
the spectra at once (line_identification), and the saved file keeps every
spectrum, so a walk can be re-identified at any time with a better line table
or method. `speccalfit` always re-identifies from the spectra; the
identification stored in the file is the record of what was concluded when
the walk was taken.

Hardware is injected as plain callables, so the same code runs on the bench,
in simulate mode and in unit tests:

    move_triax_to_steps(target_steps)   absolute move, returns when done
    read_triax_steps() -> int           the TRIAX's own position report
    acquire_spectrum() -> 1D array      one value per CCD column
    read_frame_conditions() -> dict     optional: sensor temperature etc. at each frame

The line catalogue
------------------
`catalogue_lines` must hold EVERY line that can land on the chip, including
ones that are not used as references (second-order mercury, weak argon,
blends): a line the identification does not know about can be mistaken for a
known line nearby (reference_lines module docstring). Only lines with
usable_as_reference=True are fitted.

Planning
--------
The chip spans ~79 nm. The TRIAX slides it across the range of the usable
lines in steps of 1/samples_per_line of its width, so each line is seen at
about samples_per_line different places on the chip. The plan comes from the
calibration in use; `planning_margin_nm` extends it at both ends so the
usable lines are still covered if that calibration is off by a few nm.

Backlash: positions are visited in increasing step order, starting from a
point `approach_steps` below the first one, so every measurement is reached
moving in the same direction. A position the TRIAX does not report reaching
is skipped (the grating may still be moving).
"""

from dataclasses import asdict, dataclass, field
import datetime
import json
import logging
import os

import numpy as np

from .line_identification import (IdentificationSettings, SpectrumFrame, identify_single_line_walk,
                                  identify_walk)
from .reference_lines import ReferenceLine, argon_mercury_lamp_lines
from .wavelength_axis_model import LineObservation, WavelengthAxisModel

LINE_WALK_FORMAT_VERSION = 2
DEFAULT_SATURATION_LEVEL = 65000.0  # what walks marked saturated columns with, before format 2


@dataclass
class LineWalkPositionRecord:
    """
    What happened at one TRIAX position, kept for the report and for debugging.

    `spectrum` is the spectrum the identification worked on (one value per
    column, after collapsing the frame and marking saturated columns), so a
    saved walk can be re-examined without the instrument.
    """

    requested_steps: int
    measured_steps: int
    detected_pixels: list = field(default_factory=list)
    matched_lines: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    spectrum: list = field(default_factory=list)
    status: str = ''
    recorded_at: str = ''
    conditions: dict = field(default_factory=dict)


@dataclass
class LineWalkResult:
    observations: list
    position_records: list
    identification: object = None  # line_identification.WalkIdentification


DEFAULT_SAMPLES_PER_LINE = 6  # each line seen at ~6 places on the chip


class LineWalk:
    """Runs the line walk. See the module docstring for the procedure."""

    def __init__(self, move_triax_to_steps, read_triax_steps, acquire_spectrum,
                 planning_model, catalogue_lines, number_of_pixels=1024,
                 samples_per_line=DEFAULT_SAMPLES_PER_LINE, approach_steps=2000,
                 planning_margin_nm=3.0, edge_margin_pixels=15, saturation_level=None,
                 read_frame_conditions=None, identification_settings=None, logger=None):
        self.move_triax_to_steps = move_triax_to_steps
        self.read_triax_steps = read_triax_steps
        self.acquire_spectrum = acquire_spectrum
        self.planning_model = planning_model
        self.catalogue_lines = list(catalogue_lines)
        self.number_of_pixels = number_of_pixels
        self.samples_per_line = samples_per_line
        self.approach_steps = approach_steps
        self.planning_margin_nm = planning_margin_nm
        self.edge_margin_pixels = edge_margin_pixels
        self.saturation_level = saturation_level
        self.read_frame_conditions = read_frame_conditions or (lambda: {})
        self.identification_settings = identification_settings or IdentificationSettings()
        self.logger = logger or logging.getLogger('LineWalk')

    @property
    def usable_lines(self):
        return [line for line in self.catalogue_lines if line.usable_as_reference]

    def plan_triax_positions(self):
        """TRIAX positions (ascending) that slide the chip across the usable lines; see module docstring."""
        usable_wavelengths = [line.apparent_wavelength_nm for line in self.usable_lines]
        if not usable_wavelengths:
            return []
        nm_per_pixel = abs(self.planning_model.nm_per_pixel)
        chip_width_nm = nm_per_pixel * (self.number_of_pixels - 1)
        edge_margin_nm = nm_per_pixel * self.edge_margin_pixels
        chip_start_step_nm = chip_width_nm / self.samples_per_line
        first_chip_start_nm = (min(usable_wavelengths) - chip_width_nm + edge_margin_nm
                               - self.planning_margin_nm)
        last_chip_start_nm = max(usable_wavelengths) - edge_margin_nm + self.planning_margin_nm
        chip_starts_nm = np.arange(first_chip_start_nm, last_chip_start_nm + chip_start_step_nm / 2,
                                   chip_start_step_nm)
        positions = {int(round(self.planning_model.triax_steps_for_wavelength(chip_start_nm, at_pixel=0)))
                     for chip_start_nm in chip_starts_nm}
        return sorted(positions)

    def run(self, triax_positions=None):
        """Walk the TRIAX through `triax_positions` (default: the plan), acquire, then identify."""
        if triax_positions is None:
            triax_positions = self.plan_triax_positions()
        triax_positions = sorted(int(position) for position in triax_positions)
        if not triax_positions:
            raise ValueError("No TRIAX positions to visit: no usable reference line in the catalogue.")

        self.move_triax_to_steps(triax_positions[0] - self.approach_steps)
        position_records, frames = [], []
        for position_number, requested_steps in enumerate(triax_positions, start=1):
            self.move_triax_to_steps(requested_steps)
            measured_steps = int(self.read_triax_steps())
            record = LineWalkPositionRecord(requested_steps=requested_steps,
                                            measured_steps=measured_steps)
            position_records.append(record)
            if measured_steps != requested_steps:
                record.status = 'SKIPPED'
                record.notes.append(f"TRIAX reports {measured_steps}, requested {requested_steps}: "
                                    "position skipped (the grating may still be moving)")
                self.logger.warning(f"Line walk: TRIAX at {measured_steps}, requested {requested_steps}; skipped")
                continue
            spectrum = np.asarray(self.acquire_spectrum(), dtype=float)
            record.recorded_at = datetime.datetime.now().isoformat(timespec='seconds')
            record.conditions = dict(self.read_frame_conditions())
            record.spectrum = [round(float(value), 1) for value in spectrum]
            frame = SpectrumFrame(label=str(measured_steps), triax_steps=measured_steps,
                                  spectrum=spectrum, saturation_level=self.saturation_level)
            frames.append((record, frame))
            self.logger.info(f"Line walk: position {position_number} of {len(triax_positions)} "
                             f"(TRIAX {measured_steps}) recorded")

        identification = identify_frames(
            [frame for _, frame in frames], self.catalogue_lines, self.planning_model,
            self.number_of_pixels, self.identification_settings)
        for (record, _), frame_result in zip(frames, identification.frames):
            describe_frame_in_record(record, frame_result)
        return LineWalkResult(observations=identification.observations,
                              position_records=position_records, identification=identification)


def identify_frames(frames, catalogue_lines, prior_model, number_of_pixels, settings=None):
    """Pattern identification for a lamp walk; dominant-peak identification for a one-line walk."""
    if len(catalogue_lines) == 1:
        return identify_single_line_walk(frames, catalogue_lines[0], number_of_pixels, settings)
    return identify_walk(frames, catalogue_lines, prior_model, number_of_pixels, settings)


def describe_frame_in_record(record, frame_result):
    """Copy one frame's identification into its position record (what the file shows a person)."""
    record.status = frame_result.status
    record.detected_pixels = [round(peak.centre_pixel, 2) for peak in frame_result.peaks]
    record.matched_lines = [assignment.line.name for assignment in frame_result.assignments]
    record.notes = list(frame_result.reasons) + list(frame_result.skipped_lines)


def identification_record(identification):
    """The part of a walk's identification kept in the file (observations are kept separately)."""
    return {
        'summary': identification.summary_lines(),
        'prior_offset_at_mid_walk_nm': identification.trend_offset_nm,
        'prior_offset_change_over_walk_nm': identification.trend_change_nm,
        'strong_peaks_explained': identification.trend_score,
        'strong_peaks_total': identification.strong_peak_total,
        'runner_up_strong_peaks_explained': identification.runner_up_score,
        'settings': asdict(identification.settings),
    }


def save_line_walk(path, result, planning_model, description='', reference_kind=None,
                   catalogue_lines=(), instrument=None):
    """
    Write the walk to JSON: every spectrum, the conditions it was taken in, and the identification.

    `reference_kind` says which lines a later re-identification uses (catalogue_for_saved_walk):
    'arhg' (the current lamp table, so table improvements reach old walks), 'external' (the
    walk's one line) or 'catalogue' (exactly the `catalogue_lines` stored with the walk).
    Default: 'external' for one line, 'catalogue' for any other stored list, 'arhg' for none.
    `instrument` is a dict describing the set-up (software version, simulate mode, camera
    settings, saturation level, ...); see Microscope._describe_instrument_for_calibration.
    """
    catalogue_lines = list(catalogue_lines)
    if reference_kind is None:
        if len(catalogue_lines) == 1:
            reference_kind = 'external'
        else:
            reference_kind = 'catalogue' if catalogue_lines else 'arhg'
    contents = {
        'data_type': 'wavelength_axis_line_walk',
        'format_version': LINE_WALK_FORMAT_VERSION,
        'recorded_on': datetime.datetime.now().isoformat(timespec='seconds'),
        'description': description,
        'reference_kind': reference_kind,
        'instrument': instrument or {},
        'planning_model': planning_model.to_dict(),
        'catalogue_lines': [asdict(line) for line in catalogue_lines],
        'identification': (identification_record(result.identification)
                           if result.identification else {}),
        'observations': [observation.as_dict() for observation in result.observations],
        'position_records': [asdict(record) for record in result.position_records],
    }
    with open(path, 'w') as file:
        json.dump(contents, file, indent=2)


@dataclass
class SavedLineWalk:
    """A line walk file, read back."""

    path: str
    contents: dict
    planning_model: WavelengthAxisModel
    reference_kind: str          # 'arhg', 'external' or 'catalogue' (save_line_walk)
    frames: list                 # SpectrumFrame, one per recorded position with a spectrum
    stored_observations: list    # what the walk recorded when it was taken

    @property
    def label(self):
        return os.path.basename(str(self.path))

    @property
    def instrument(self):
        return self.contents.get('instrument', {})

    @property
    def format_version(self):
        return int(self.contents.get('format_version', 1))

    @property
    def recorded_in_simulate_mode(self):
        """True or False when the file says; None for files from before format 2 (not recorded)."""
        return self.instrument.get('simulate') if 'simulate' in self.instrument else None


def load_line_walk(path):
    """Read a saved walk (format 1 or 2)."""
    with open(path) as file:
        contents = json.load(file)
    saturation_level = contents.get('instrument', {}).get('saturation_level',
                                                          DEFAULT_SATURATION_LEVEL)
    frames = [SpectrumFrame(label=str(record['measured_steps']),
                            triax_steps=int(record['measured_steps']),
                            spectrum=np.asarray(record['spectrum'], dtype=float),
                            saturation_level=saturation_level)
              for record in contents['position_records']
              if record.get('spectrum') and record['measured_steps'] == record['requested_steps']]
    reference_kind = contents.get('reference_kind') or \
        ('external' if str(contents.get('description', '')).startswith('external') else 'arhg')
    return SavedLineWalk(
        path=str(path), contents=contents,
        planning_model=WavelengthAxisModel.from_dict(contents['planning_model']),
        reference_kind=reference_kind, frames=frames,
        stored_observations=[LineObservation(**stored) for stored in contents['observations']])


def catalogue_for_saved_walk(saved_walk):
    """The lines to identify a saved walk against: the current lamp table, or the walk's own."""
    stored_lines = saved_walk.contents.get('catalogue_lines')
    if saved_walk.reference_kind in ('external', 'catalogue') and stored_lines:
        return [ReferenceLine(**stored) for stored in stored_lines]
    if saved_walk.reference_kind == 'external':
        observation = saved_walk.stored_observations[0]
        return [ReferenceLine(name=observation.line_name.split(' (')[0],
                              wavelength_nm=observation.apparent_wavelength_nm,
                              wavelength_uncertainty_nm=observation.wavelength_uncertainty_nm)]
    return argon_mercury_lamp_lines()


def identify_saved_walk(saved_walk, prior_model=None, number_of_pixels=1024, settings=None):
    """Re-identify a saved walk from its spectra (prior: the calibration it was planned with)."""
    return identify_frames(saved_walk.frames, catalogue_for_saved_walk(saved_walk),
                           prior_model or saved_walk.planning_model, number_of_pixels, settings)


def load_line_walk_observations(path):
    """
    Observations of a saved walk, RE-IDENTIFIED from its spectra with the current method and
    line table (files without spectra fall back to the observations stored in them). Returns
    (observations, planning model, file contents).
    """
    saved_walk = load_line_walk(path)
    if saved_walk.frames:
        observations = identify_saved_walk(saved_walk).observations
    else:
        observations = saved_walk.stored_observations
    return observations, saved_walk.planning_model, saved_walk.contents
