"""
Fit saved line walks, check the result, and (only when asked, and only if no
gate fails) write it into the master calibration file.

Promotion is a separate, explicit step on purpose: a line walk produces a
file, the fit produces a report, and a person decides. The previous master
file is always backed up before it is overwritten.

Every fit re-identifies the lines from the walks' saved spectra
(line_walk.identify_saved_walk), so a walk is always judged with the current
method and line table, and gives each walk its own TRIAX zero (the latest walk
sets the stored one). The fit report holds the gate checks
(calibration_checks), each walk's frame-by-frame identification and every
residual, so a failed calibration can be diagnosed from the report alone.
An applied model names its report in its metadata ('fit_report') and carries
the TRIAX position table the quick re-zero needs ('triax_position_offsets_nm').
"""

from dataclasses import asdict, dataclass
import datetime
import json
import os
import shutil

from .calibration_checks import (CalibrationEvidence, any_failed, decompose_fit_residuals,
                                 format_check_report, run_checks)
from .line_walk import identify_saved_walk, load_line_walk
from .triax_zero import POSITION_TABLE_KEY
from .wavelength_axis_model import CalibrationFitError, WavelengthAxisModel, fit_wavelength_axis

MASTER_GROUP_NAME = 'wavelength_axis'


@dataclass
class FitOptions:
    """What the fit includes; the speccalfit options map onto these."""

    curvature: bool = False
    triax_polynomial_order: int = 1
    dispersion_change: bool = True
    triax_step_uncertainty: float = 0.0
    separate_triax_from_ccd: bool = True  # two-stage fit (see fit_wavelength_axis)


@dataclass
class WalkFitOutcome:
    """A fit (None if it could not be made), the evidence it rests on, and the gate results."""

    fit: object
    evidence: CalibrationEvidence
    check_results: list

    @property
    def gates_failed(self):
        return any_failed(self.check_results)


def fit_and_check_line_walk_files(line_walk_paths, current_model, fit_options=None,
                                  reference_pixel=None, running_in_simulate_mode=False,
                                  number_of_pixels=1024, limits=None, identification_settings=None):
    """Re-identify, fit and check saved walks; `line_walk_paths` in time order (last sets zero)."""
    fit_options = fit_options or FitOptions()
    reference_pixel = current_model.reference_pixel if reference_pixel is None else reference_pixel
    walks = [load_line_walk(path) for path in line_walk_paths]
    identifications = [identify_saved_walk(walk, number_of_pixels=number_of_pixels,
                                           settings=identification_settings)
                       for walk in walks]
    observations, groups = [], []
    for walk, identification in zip(walks, identifications):
        observations += identification.observations
        groups += [walk.label] * len(identification.observations)

    # One-line walks (an external laser) cannot separate the CCD from the TRIAX: joint fit only.
    frames_with_two_or_more = sum(len(frame.observations) >= 2 for identification in identifications
                                  for frame in identification.frames)
    two_stage = (fit_options.separate_triax_from_ccd and not fit_options.triax_step_uncertainty
                 and frames_with_two_or_more >= 3)
    fit, fit_error = None, ''
    try:
        fit = fit_wavelength_axis(
            observations, reference_pixel=reference_pixel,
            triax_polynomial_order=fit_options.triax_polynomial_order,
            fit_dispersion_curvature=fit_options.curvature,
            fit_dispersion_change_with_triax=fit_options.dispersion_change,
            triax_step_uncertainty=fit_options.triax_step_uncertainty,
            separate_triax_from_ccd=two_stage,
            observation_groups=groups if len(walks) > 1 else None,
            reference_group=walks[-1].label if walks else None,
            metadata={'source_line_walks': [walk.label for walk in walks],
                      'verified_against_external_reference': True,
                      'line_identification': 'pattern match over the whole walk'})
        fit.model.metadata[POSITION_TABLE_KEY] = {
            str(int(steps)): round(offset, 4)
            for steps, offset in decompose_fit_residuals(fit).position_offsets_nm.items()}
    except CalibrationFitError as error:
        fit_error = str(error)

    evidence = CalibrationEvidence(
        kind='fit', walk_labels=[walk.label for walk in walks], identifications=identifications,
        instruments=[walk.instrument for walk in walks],
        frame_conditions=[[record.get('conditions', {})
                           for record in walk.contents['position_records']] for walk in walks],
        format_versions=[walk.format_version for walk in walks], current_model=current_model,
        fit=fit, fit_error=fit_error, fit_options=asdict(fit_options),
        running_in_simulate_mode=running_in_simulate_mode, number_of_pixels=number_of_pixels)
    return WalkFitOutcome(fit=fit, evidence=evidence, check_results=run_checks(evidence, limits))


def fit_line_walk_files(line_walk_paths, reference_pixel=50.0, fit_dispersion_curvature=False,
                        fit_dispersion_change_with_triax=True, triax_polynomial_order=1,
                        triax_step_uncertainty=0.0):
    """Re-identify and fit saved walks, without the gates. Raises CalibrationFitError if no fit."""
    reference = WavelengthAxisModel(reference_pixel=reference_pixel, nm_per_pixel=0.0775,
                                    triax_to_wavelength_coefficients=[0.0, 0.0])
    options = FitOptions(curvature=fit_dispersion_curvature,
                         triax_polynomial_order=triax_polynomial_order,
                         dispersion_change=fit_dispersion_change_with_triax,
                         triax_step_uncertainty=triax_step_uncertainty)
    outcome = fit_and_check_line_walk_files(line_walk_paths, reference, options)
    if outcome.fit is None:
        raise CalibrationFitError(outcome.evidence.fit_error)
    return outcome.fit


def new_fit_report_path(report_directory):
    """A timestamped path for the next fit report (the directory is created)."""
    os.makedirs(report_directory, exist_ok=True)
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    report_path = os.path.join(report_directory, f'wavelength_axis_fit_{timestamp}.txt')
    repeat_number = 1
    while os.path.exists(report_path):  # two fits in the same second must not overwrite
        repeat_number += 1
        report_path = os.path.join(report_directory,
                                   f'wavelength_axis_fit_{timestamp}_{repeat_number}.txt')
    return report_path


def write_fit_report(report_path, outcome, line_walk_paths, master_path=None, backup_path=None):
    """
    Write the fit report: status, gates, fit summary, each walk's identification, every residual,
    the model.

    The calibration counts as APPLIED when `backup_path` is given (the master
    file was backed up and overwritten). Returns the report text; its summary
    part (status, gates, fit summary) ends at the line 'identification by walk:'.
    """
    fit = outcome.fit
    if backup_path is not None:
        status = f"APPLIED to {master_path} (previous version: {backup_path})"
    elif outcome.gates_failed:
        status = "NOT APPLIED: a gate check failed (see below)"
    else:
        status = "NOT APPLIED (report only)"
    report = [
        "Wavelength axis calibration fit (TRIAX + PIXIS); see docs/calibration.md section 3",
        f"written: {datetime.datetime.now().isoformat(timespec='seconds')}",
        f"status: {status}",
        "line walks:",
        *[f"  {path}" for path in line_walk_paths],
        "",
        *format_check_report(outcome.check_results),
        "",
    ]
    if fit is not None:
        report += [f"fitted terms: {', '.join(fit.parameter_names)}", *fit.report_lines(), ""]
    report.append("identification by walk:")
    evidence = outcome.evidence
    for label, identification in zip(evidence.walk_labels, evidence.identifications):
        report += [f"  {label}", *[f"    {line}" for line in identification.summary_lines()]]
        for frame in identification.frames:
            report += [f"      TRIAX {frame.triax_steps}: {note}" for note in frame.skipped_lines]
    if fit is not None:
        report += ["", "residuals (measured - fitted wavelength):",
                   f"  {'walk':<36} {'line':<24} {'TRIAX steps':>11} {'pixel':>8} {'+/- px':>7} "
                   f"{'residual nm':>12}"]
        groups = fit.observation_groups or [''] * len(fit.observations)
        for group, observation, residual in zip(groups, fit.observations, fit.residuals_nm):
            report.append(f"  {group:<36} {observation.line_name:<24} "
                          f"{observation.triax_steps:>11d} {observation.centre_pixel:>8.2f} "
                          f"{observation.centre_uncertainty_pixels:>7.3f} {residual:>+12.4f}")
        report += ["", "fitted model (the master file's 'wavelength_axis' group):",
                   json.dumps(fit.model.to_dict(), indent=4)]
    report_text = "\n".join(report) + "\n"
    with open(report_path, 'w') as file:
        file.write(report_text)
    return report_text


def load_master(master_path):
    with open(master_path) as file:
        return json.load(file)


def current_model_from_master(master_path):
    return WavelengthAxisModel.from_dict(load_master(master_path)[MASTER_GROUP_NAME])


def write_model_to_master(model, master_path, backup_directory):
    """Back up the master file, then replace its wavelength_axis group. Returns the backup path."""
    master = load_master(master_path)
    os.makedirs(backup_directory, exist_ok=True)
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    master_name = os.path.splitext(os.path.basename(master_path))[0]
    backup_path = os.path.join(backup_directory, f"{master_name}.bak-{timestamp}.json")
    repeat_number = 1
    while os.path.exists(backup_path):  # two writes in the same second must not overwrite a backup
        repeat_number += 1
        backup_path = os.path.join(backup_directory,
                                   f"{master_name}.bak-{timestamp}_{repeat_number}.json")
    shutil.copyfile(master_path, backup_path)

    master[MASTER_GROUP_NAME] = model.to_dict()
    with open(master_path, 'w') as file:
        json.dump(master, file, indent=4)
    return backup_path
