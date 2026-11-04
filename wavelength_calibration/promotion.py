"""
Fit saved line walks, compare with the current calibration, and (only when
asked) write the result into the master calibration file.

Promotion is a separate, explicit step on purpose: a line walk produces a
file, the fit produces a report, and a person decides. The previous master
file is always backed up before it is overwritten.

Every fit writes a report file (write_fit_report), applied or not, so the
quality of each calibration and whether it was put into use is on record.
An applied model names its report in its metadata ('fit_report').
"""

import datetime
import json
import os
import shutil

import numpy as np

from .line_walk import load_line_walk_observations
from .wavelength_axis_model import WavelengthAxisModel, fit_wavelength_axis, largest_axis_difference_nm

MASTER_GROUP_NAME = 'wavelength_axis'


def fit_line_walk_files(line_walk_paths, reference_pixel=50.0, fit_dispersion_curvature=False,
                        fit_dispersion_change_with_triax=True, triax_polynomial_order=1):
    """Combine the observations of one or more saved line walks and fit them."""
    all_observations = []
    for path in line_walk_paths:
        observations, _planning_model, _contents = load_line_walk_observations(path)
        all_observations.extend(observations)
    source_files = [os.path.basename(str(path)) for path in line_walk_paths]
    return fit_wavelength_axis(
        all_observations, reference_pixel=reference_pixel, triax_polynomial_order=triax_polynomial_order,
        fit_dispersion_curvature=fit_dispersion_curvature,
        fit_dispersion_change_with_triax=fit_dispersion_change_with_triax,
        metadata={'source_line_walks': source_files, 'verified_against_external_reference': True},
    )


def comparison_report_lines(fit, current_model, number_of_pixels=1024):
    """The fit report plus how far the new axis is from the one in use, over the measured TRIAX range."""
    measured_triax_steps = sorted({observation.triax_steps for observation in fit.observations})
    report = fit.report_lines()
    report.append(
        f"largest change from current calibration over measured TRIAX range "
        f"({measured_triax_steps[0]}..{measured_triax_steps[-1]} steps): "
        f"{largest_axis_difference_nm(fit.model, current_model, measured_triax_steps, number_of_pixels):.3f} nm")

    robust_residual_scale_nm = 1.4826 * float(np.median(np.abs(fit.residuals_nm)))
    outlier_limit_nm = max(0.5, 6 * robust_residual_scale_nm)
    for observation, residual in zip(fit.observations, fit.residuals_nm):
        if abs(residual) > outlier_limit_nm:
            report.append(f"  CHECK: {observation.line_name} at TRIAX {observation.triax_steps}, pixel "
                          f"{observation.centre_pixel:.1f} has residual {residual:+.3f} nm (misidentified line?)")
    return report


def new_fit_report_path(report_directory):
    """A timestamped path for the next fit report (the directory is created)."""
    os.makedirs(report_directory, exist_ok=True)
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    report_path = os.path.join(report_directory, f'wavelength_axis_fit_{timestamp}.txt')
    repeat_number = 1
    while os.path.exists(report_path):  # two fits in the same second must not overwrite
        repeat_number += 1
        report_path = os.path.join(report_directory, f'wavelength_axis_fit_{timestamp}_{repeat_number}.txt')
    return report_path


def write_fit_report(report_path, fit, current_model, line_walk_paths, master_path=None, backup_path=None,
                     number_of_pixels=1024):
    """
    Write the fit report to `report_path`: what was fitted, whether it was applied, every residual.

    The calibration counts as APPLIED when `backup_path` is given (the master
    file was backed up and overwritten). Returns the report text.
    """
    if backup_path is not None:
        status = f"APPLIED to {master_path} (previous version: {backup_path})"
    else:
        status = "NOT APPLIED (report only)"
    report = [
        "Wavelength axis calibration fit (TRIAX + PIXIS); see docs/calibration.md section 3",
        f"written: {datetime.datetime.now().isoformat(timespec='seconds')}",
        f"status: {status}",
        "line walks:",
        *[f"  {path}" for path in line_walk_paths],
        f"fitted terms: {', '.join(fit.parameter_names)}",
        "",
        *comparison_report_lines(fit, current_model, number_of_pixels=number_of_pixels),
        "",
        "residuals (measured - fitted wavelength):",
        f"  {'line':<24} {'TRIAX steps':>11} {'pixel':>8} {'+/- px':>7} {'residual nm':>12}",
    ]
    for observation, residual in zip(fit.observations, fit.residuals_nm):
        report.append(f"  {observation.line_name:<24} {observation.triax_steps:>11d} "
                      f"{observation.centre_pixel:>8.2f} {observation.centre_uncertainty_pixels:>7.3f} "
                      f"{residual:>+12.4f}")
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
    backup_path = os.path.join(backup_directory,
                               f"{os.path.splitext(os.path.basename(master_path))[0]}.bak-{timestamp}.json")
    shutil.copyfile(master_path, backup_path)

    master[MASTER_GROUP_NAME] = model.to_dict()
    with open(master_path, 'w') as file:
        json.dump(master, file, indent=4)
    return backup_path
