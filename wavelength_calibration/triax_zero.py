"""
Quick re-zero: the TRIAX step counter moved, the calibration's shape did not. Measure the shift.

When the TRIAX is re-initialised, or loses steps, every wavelength shifts by
the same number of steps while the shape of the calibration (dispersion, the
TRIAX's own drive pattern) stays as it was. A full walk is not needed: a few
frames of the Ar-Hg lamp fix the shift, and it is stored as the model's
`triax_step_offset` (drive position = reported steps + offset).

The TRIAX drive is not a smooth polynomial in steps (~0.1 nm from one
position to the next, 2026-11-10), so one frame compared with the polynomial
would be off by up to ~20 steps. A model fitted from walks (since 2026-11-11)
stores the measured offset at each calibration position
(`triax_position_offsets_nm` in its metadata), and the re-zero revisits
exactly those drive positions:

    measured offset (nm) = drive pattern there + nm_per_step * step shift

so the step shift follows from each frame without the pattern's error. The
first pass lands up to the old shift away from the stored positions; if the
shift is more than `refine_threshold_steps` a second pass goes back to the
corrected positions. The frames must agree on one shift: if they do not, more
than the zero has changed, and the gate says to run the full calibration.

Hardware is injected as callables, as for the line walk.
"""

from dataclasses import dataclass, field, replace
import datetime
import logging

import numpy as np

from .calibration_checks import CalibrationEvidence, any_failed, format_check_report
from .line_identification import SpectrumFrame, identify_walk
from .line_walk import LineWalkPositionRecord, LineWalkResult, describe_frame_in_record

POSITION_TABLE_KEY = 'triax_position_offsets_nm'


@dataclass
class ZeroMeasurement:
    frame_offsets_steps: dict   # TRIAX counter position -> step shift measured there
    frame_offsets_nm: dict      # TRIAX counter position -> wavelength offset from the model
    step_offset: float          # the shift: median over the frames
    spread_steps: float         # largest minus smallest frame shift
    nm_per_step: float
    used_position_table: bool
    identification: object = None  # WalkIdentification of the last pass

    def corrected_model(self, model, report_name=''):
        """The model with the shift added to its triax_step_offset (the shape is unchanged)."""
        metadata = dict(model.metadata)
        metadata.update({'zeroed_on': datetime.date.today().isoformat(),
                         'zero_step_change': round(self.step_offset, 2),
                         'zero_spread_steps': round(self.spread_steps, 2)})
        if report_name:
            metadata['zero_report'] = report_name
        return replace(model, triax_step_offset=float(model.triax_step_offset + self.step_offset),
                       metadata=metadata)


@dataclass
class ZeroRun:
    measurement: ZeroMeasurement
    passes: int
    walk_result: LineWalkResult  # the frames of the last pass, recorded like a line walk
    position_records_all_passes: list = field(default_factory=list)


def position_table(model):
    """{drive position: offset nm} stored with the model, or {} (fitted before 2026-11-11)."""
    stored = model.metadata.get(POSITION_TABLE_KEY, {})
    return {int(float(steps)): float(offset) for steps, offset in stored.items()}


def plan_zero_drive_positions(model, catalogue_lines, number_of_pixels=1024, count=3,
                              edge_margin_pixels=40, candidate_wavelength_range_nm=(700.0, 920.0)):
    """
    Drive positions for the re-zero: `count` of them, spread over the range, each with as many
    usable lines on the chip as possible. From the stored calibration positions when there are any.
    """
    table = position_table(model)
    if table:
        candidates = sorted(table)
    else:
        wavelengths = np.linspace(*candidate_wavelength_range_nm, 25)
        candidates = sorted({int(round(model.drive_position(model.triax_steps_for_wavelength(nm))))
                             for nm in wavelengths})
    usable = [line.apparent_wavelength_nm for line in catalogue_lines if line.usable_as_reference]

    def lines_on_chip(drive_steps):
        counter_steps = drive_steps - model.triax_step_offset
        pixels = [model.pixel_of_wavelength(wavelength, counter_steps) for wavelength in usable]
        return sum(edge_margin_pixels <= pixel < number_of_pixels - edge_margin_pixels
                   for pixel in pixels)

    groups = [group for group in np.array_split(np.array(candidates), count) if group.size]
    return sorted(int(max(group, key=lines_on_chip)) for group in groups)


def measure_triax_zero(frames, model, catalogue_lines, expected_offsets_nm, number_of_pixels=1024,
                       settings=None):
    """
    The step shift from re-zero frames. `expected_offsets_nm`: counter position -> the drive
    pattern's offset at the drive position aimed at (0 where unknown).
    """
    identification = identify_walk(frames, catalogue_lines, model, number_of_pixels, settings)
    offsets_steps, offsets_nm = {}, {}
    for frame in identification.identified_frames:
        if not frame.observations:
            continue
        residuals = [observation.apparent_wavelength_nm
                     - float(model.wavelength_at(observation.centre_pixel, observation.triax_steps))
                     for observation in frame.observations]
        offset_nm = float(np.mean(residuals))
        offsets_nm[frame.triax_steps] = offset_nm
        expected_nm = expected_offsets_nm.get(frame.triax_steps, 0.0)
        offsets_steps[frame.triax_steps] = (offset_nm - expected_nm) \
            / model.nm_per_triax_step(frame.triax_steps)
    shifts = list(offsets_steps.values())
    measured_positions = list(offsets_steps) or [frame.triax_steps for frame in frames]
    steps_for_slope = float(np.median(measured_positions))
    return ZeroMeasurement(
        frame_offsets_steps=offsets_steps, frame_offsets_nm=offsets_nm,
        step_offset=float(np.median(shifts)) if shifts else 0.0,
        spread_steps=float(np.ptp(shifts)) if len(shifts) > 1 else float('inf'),
        nm_per_step=abs(model.nm_per_triax_step(steps_for_slope)),
        used_position_table=bool(position_table(model)), identification=identification)


def _acquire_frames(counter_positions, pass_number, move_triax_to_steps, read_triax_steps,
                    acquire_spectrum, read_frame_conditions, saturation_level, approach_steps):
    """Visit the positions in increasing order, after backing off below them: records, frames."""
    move_triax_to_steps(min(counter_positions) - approach_steps)
    records, frames = [], []
    for counter_steps in sorted(counter_positions):
        move_triax_to_steps(counter_steps)
        measured_steps = int(read_triax_steps())
        record = LineWalkPositionRecord(requested_steps=counter_steps,
                                        measured_steps=measured_steps)
        records.append(record)
        if measured_steps != counter_steps:
            record.status = 'SKIPPED'
            record.notes.append(f"TRIAX reports {measured_steps}, requested {counter_steps}: "
                                "position skipped")
            continue
        spectrum = np.asarray(acquire_spectrum(), dtype=float)
        record.recorded_at = datetime.datetime.now().isoformat(timespec='seconds')
        record.conditions = dict(read_frame_conditions())
        record.spectrum = [round(float(value), 1) for value in spectrum]
        frames.append(SpectrumFrame(label=f'zero pass {pass_number} {counter_steps}',
                                    triax_steps=counter_steps, spectrum=spectrum,
                                    saturation_level=saturation_level))
    return records, frames


def run_triax_zero(move_triax_to_steps, read_triax_steps, acquire_spectrum, model, catalogue_lines,
                   number_of_pixels=1024, approach_steps=2000, saturation_level=None,
                   read_frame_conditions=None, settings=None, refine_threshold_steps=10.0,
                   logger=None):
    """Acquire at the re-zero positions (twice if the shift is large) and measure the step shift."""
    logger = logger or logging.getLogger('TriaxZero')
    read_frame_conditions = read_frame_conditions or (lambda: {})
    table = position_table(model)
    drive_positions = plan_zero_drive_positions(model, catalogue_lines, number_of_pixels)
    step_shift_estimate, all_records = 0.0, []
    for pass_number in (1, 2):
        counter_targets = {int(round(drive - model.triax_step_offset - step_shift_estimate)): drive
                           for drive in drive_positions}
        records, frames = _acquire_frames(counter_targets, pass_number, move_triax_to_steps,
                                          read_triax_steps, acquire_spectrum, read_frame_conditions,
                                          saturation_level, approach_steps)
        expected = {counter: table.get(drive, 0.0) for counter, drive in counter_targets.items()}
        measurement = measure_triax_zero(frames, model, catalogue_lines, expected, number_of_pixels,
                                         settings)
        all_records += records
        logger.info(f"TRIAX re-zero pass {pass_number}: shift {measurement.step_offset:+.1f} steps "
                    f"from {len(measurement.frame_offsets_steps)} frame(s), spread "
                    f"{measurement.spread_steps:.1f} steps")
        if pass_number == 2 or abs(measurement.step_offset) <= refine_threshold_steps or not table:
            break
        step_shift_estimate = measurement.step_offset
    frame_by_steps = {frame.triax_steps: frame for frame in measurement.identification.frames}
    for record in records:
        if record.measured_steps in frame_by_steps and record.status != 'SKIPPED':
            describe_frame_in_record(record, frame_by_steps[record.measured_steps])
    walk_result = LineWalkResult(observations=measurement.identification.observations,
                                 position_records=records,
                                 identification=measurement.identification)
    return ZeroRun(measurement=measurement, passes=pass_number, walk_result=walk_result,
                   position_records_all_passes=all_records)


def zero_evidence(zero_run, model, instrument=None, running_in_simulate_mode=False,
                  number_of_pixels=1024):
    """What the 'zero' gate checks look at (calibration_checks)."""
    return CalibrationEvidence(
        kind='zero', walk_labels=['re-zero'], identifications=[zero_run.measurement.identification],
        instruments=[instrument or {}],
        frame_conditions=[[record.conditions for record in zero_run.walk_result.position_records]],
        format_versions=[2], current_model=model, zero=zero_run.measurement,
        running_in_simulate_mode=running_in_simulate_mode, number_of_pixels=number_of_pixels)


def write_zero_report(report_path, zero_run, check_results, model, applied_text=None):
    """Write the re-zero report (status, gates, per-frame shifts, identification). Returns it."""
    measurement = zero_run.measurement
    if applied_text:
        status = applied_text
    elif any_failed(check_results):
        status = "NOT APPLIED: a gate check failed (see below)"
    else:
        status = "NOT APPLIED (check only)"
    shift_nm = measurement.step_offset * measurement.nm_per_step
    table_state = 'used' if measurement.used_position_table else 'not available'
    new_offset = model.triax_step_offset + measurement.step_offset
    report = [
        "TRIAX quick re-zero (speccalzero); see docs/calibration.md",
        f"written: {datetime.datetime.now().isoformat(timespec='seconds')}",
        f"status: {status}",
        f"measured shift: {measurement.step_offset:+.2f} steps ({shift_nm:+.4f} nm) from "
        f"{len(measurement.frame_offsets_steps)} frame(s), spread {measurement.spread_steps:.2f} "
        f"steps, {zero_run.passes} pass(es); TRIAX position table {table_state}",
        f"model TRIAX step offset: {model.triax_step_offset:+.2f} -> {new_offset:+.2f}"
        f"{'' if applied_text else ' (if applied)'}",
        "",
        *format_check_report(check_results),
        "",
        "identification by walk:",
        *[f"  {line}" for line in measurement.identification.summary_lines()],
        "frame shifts (steps): " + ", ".join(
            f"TRIAX {steps}: {shift:+.2f}"
            for steps, shift in measurement.frame_offsets_steps.items()),
    ]
    report_text = "\n".join(report) + "\n"
    with open(report_path, 'w') as file:
        file.write(report_text)
    return report_text
