"""
Export line walks as a CSV of observed vs expected wavelength (a scatter plot's data).

For every line observation, "expected" is the reference wavelength of the lamp
line and "observed" is the wavelength the given axis model assigns to the pixel
where the line landed at the TRIAX position it was measured at. Run after a
TRIAX repeatability trial, a repeated walk gives several rows per line, so the
spread of `observed_nm` for one `line_name` is the repeatability.
"""

import csv
import datetime
import os

from .line_walk import load_line_walk_observations

CSV_COLUMNS = ['source_file', 'line_name', 'triax_steps', 'centre_pixel', 'expected_nm',
               'observed_nm', 'error_nm', 'expected_uncertainty_nm', 'pixel_uncertainty_nm']


def build_scatter_rows(line_walk_paths, model):
    """One dict per observation, in file order. `model` converts (pixel, TRIAX steps) to nm."""
    rows = []
    for path in line_walk_paths:
        observations, _planning_model, _contents = load_line_walk_observations(path)
        for observation in observations:
            observed_nm = float(model.wavelength_at(observation.centre_pixel, observation.triax_steps))
            pixel_uncertainty_nm = (observation.centre_uncertainty_pixels
                                    * abs(float(model.nm_per_pixel_at(observation.triax_steps))))
            rows.append({
                'source_file': os.path.basename(str(path)),
                'line_name': observation.line_name,
                'triax_steps': observation.triax_steps,
                'centre_pixel': f'{observation.centre_pixel:.3f}',
                'expected_nm': f'{observation.apparent_wavelength_nm:.4f}',
                'observed_nm': f'{observed_nm:.4f}',
                'error_nm': f'{observed_nm - observation.apparent_wavelength_nm:+.4f}',
                'expected_uncertainty_nm': f'{observation.wavelength_uncertainty_nm:.4f}',
                'pixel_uncertainty_nm': f'{pixel_uncertainty_nm:.4f}',
            })
    return rows


def new_export_path(export_directory):
    """A timestamped, non-clashing CSV path (the directory is created)."""
    os.makedirs(export_directory, exist_ok=True)
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    path = os.path.join(export_directory, f'spectral_calibration_scatter_{timestamp}.csv')
    repeat_number = 1
    while os.path.exists(path):
        repeat_number += 1
        path = os.path.join(export_directory, f'spectral_calibration_scatter_{timestamp}_{repeat_number}.csv')
    return path


def export_scatter_csv(line_walk_paths, model, export_path):
    """Write the scatter CSV and return the rows. Raises ValueError if there are no observations."""
    rows = build_scatter_rows(line_walk_paths, model)
    if not rows:
        raise ValueError("the line walk files contain no observations")
    rows.sort(key=lambda row: (float(row['expected_nm']), row['source_file'], row['triax_steps']))
    with open(export_path, 'w', newline='') as file:
        writer = csv.DictWriter(file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return rows
