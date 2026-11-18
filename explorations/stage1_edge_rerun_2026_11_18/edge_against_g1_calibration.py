"""The measured stage 1 edge against the master calibration's g1_to_wl, 2026-11-18 rerun.

Each frame's g1 count comes from the run logs (the 'allmotors' line before its 'filename');
the edge comes from fit_edges.json. The edge is read on the frame's own wavelength axis, which
the 50 um Ar-Hg frame shows reading AXIS_CORRECTION_NM high in the band's rows at 763-826 nm
(argon_lines_by_slit_width.txt); that correction is applied everywhere, though it is measured
at the 800 nm TRIAX position only.

Reports, per frame: g1 count, calibrated wavelength g1_to_wl(count), measured edge, difference.
Then a quadratic fit of edge against g1 count over the edge walk (the single-step run sits
~0.7 nm off the walk at the same counts, so it is fitted separately), against the calibration's
own polynomial: offset and slope, and the g1 count that puts the edge at each centre.

Run: PYTHONPATH=.:explorations/stage1_edge_rerun_2026_11_18 .venv/bin/python \
     explorations/stage1_edge_rerun_2026_11_18/edge_against_g1_calibration.py
"""
import ast
import glob
import json
import os

import numpy as np

import exploration_paths

DATA_DIRECTORY = exploration_paths.DATA_DIRECTORY
FIT_RESULTS_PATH = os.path.join(exploration_paths.OUTPUT_DIRECTORY, 'fit_edges.json')
CALIBRATION_PATH = 'calibration/master_calibration_microsteps_32.json'
OUTPUT_PATH = os.path.join(exploration_paths.OUTPUT_DIRECTORY, 'edge_against_g1_calibration.txt')
AXIS_CORRECTION_NM = -0.31
CENTRES = (720, 760, 800, 840, 880, 920)

output_lines = []


def report(text=''):
    output_lines.append(text)
    print(text)


def g1_counts_by_filename():
    counts = {}
    for log_path in sorted(glob.glob(os.path.join(DATA_DIRECTORY, 'stage1_*.txt'))):
        last_motors = None
        with open(log_path) as log_file:
            for line in log_file:
                fields = line.rstrip('\n').split('\t')
                if len(fields) < 3:
                    continue
                if fields[1] == 'allmotors':
                    last_motors = ast.literal_eval(fields[2])
                elif fields[1].startswith('filename ') and last_motors is not None:
                    counts[fields[1].split()[1]] = (last_motors['g1'], last_motors['g2'])
    return counts


def main():
    with open(CALIBRATION_PATH) as calibration_file:
        g1_section = json.load(calibration_file)['manual_g1']
    steps_to_wavelength = np.poly1d(g1_section['g1_to_wl'])
    wavelength_to_steps = np.poly1d(g1_section['wl_to_g1'])
    with open(FIT_RESULTS_PATH) as fit_file:
        fits = json.load(fit_file)
    counts = g1_counts_by_filename()

    report(f'Axis correction applied to every edge: {AXIS_CORRECTION_NM:+.2f} nm')
    report('frame'.ljust(30) + '  g1    g2   g1_to_wl   edge     edge - g1_to_wl')
    walk_points, step_points = [], []
    for frame_name, result in fits.items():
        name = frame_name.rsplit('_', 1)[0]
        if name not in counts or not result.get('summed') or name.endswith('150'):
            continue
        g1_count, g2_count = counts[name]
        edge_nm = result['summed']['edge_nm'] + AXIS_CORRECTION_NM
        calibrated_nm = steps_to_wavelength(g1_count)
        (step_points if name.startswith('s1step') else walk_points).append((g1_count, edge_nm))
        report(f'{name:30s}{g1_count:5d} {g2_count:5d}  {calibrated_nm:8.2f}  {edge_nm:8.2f}  '
               f'{edge_nm - calibrated_nm:+7.2f}')

    for label, points in (('edge walk', walk_points), ('single steps', step_points)):
        g1_values, edge_values = (np.array(values, dtype=float) for values in zip(*points))
        degree = 2 if label == 'edge walk' else 1
        fitted = np.poly1d(np.polyfit(g1_values, edge_values, degree))
        residual = edge_values - fitted(g1_values)
        report(f'\n{label}: edge = {fitted} ; residual rms {np.std(residual):.3f} nm over '
               f'{len(points)} frames')
        if label == 'edge walk':
            report('  calibration g1_to_wl = ' + str(steps_to_wavelength))
            report('  centre  calibrated count  edge there  slope measured / calibrated  '
                   'count for edge at centre (shift)')
            for centre in CENTRES:
                calibrated_count = wavelength_to_steps(centre)
                roots = (fitted - centre).roots
                real_roots = [root.real for root in roots if abs(root.imag) < 1e-9
                              and abs(root.real - calibrated_count) < 200]
                needed_count = real_roots[0] if real_roots else np.nan
                report(f'  {centre}  {calibrated_count:9.1f}  {fitted(calibrated_count):10.2f}  '
                       f'{fitted.deriv()(calibrated_count):+.4f} / '
                       f'{steps_to_wavelength.deriv()(calibrated_count):+.4f}  '
                       f'{needed_count:9.1f} ({needed_count - calibrated_count:+.1f})')

    with open(OUTPUT_PATH, 'w') as output:
        output.write('\n'.join(output_lines) + '\n')


if __name__ == '__main__':
    main()
