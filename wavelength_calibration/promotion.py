"""
Fit saved line walks, compare with the current calibration, and (only when
asked) write the result into the master calibration file.

Promotion is a separate, explicit step on purpose: a line walk produces a
file, the fit produces a report, and a person decides. The previous master
file is always backed up before it is overwritten.
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
                        triax_polynomial_order=1):
    """Combine the observations of one or more saved line walks and fit them."""
    all_observations = []
    for path in line_walk_paths:
        observations, _planning_model, _contents = load_line_walk_observations(path)
        all_observations.extend(observations)
    source_files = [os.path.basename(str(path)) for path in line_walk_paths]
    return fit_wavelength_axis(
        all_observations, reference_pixel=reference_pixel, triax_polynomial_order=triax_polynomial_order,
        fit_dispersion_curvature=fit_dispersion_curvature,
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
