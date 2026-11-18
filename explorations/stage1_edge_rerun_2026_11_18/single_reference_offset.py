"""What one 'referencegratings' at one wavelength does across the range, from the 2026-11-18 walk.

'referencegratings' rewrites the motor counts so the current position becomes the calibration's
position for the given wavelength: a constant shift of g1's count, the same at every wavelength.
The laser spot sits a fixed distance from the mirror edge, in the lens's focal plane, so it is a
fixed angle of g1 from the edge: also a constant count offset. This script reports:

1. The master calibration as it is: the edge above the 'sg' wavelength, in steps, nm and cm^-1.
   If manual_g1 was made with the laser pointed through the pinhole, this is the spot-to-edge
   offset built into it.
2. The master calibration referenced once, at REFERENCE_CENTRE_NM: what is left at the others.
3. A fixed spot offset (a constant count offset from the measured edge curve) chosen to put the
   cutoff CUTOFF_AT_REFERENCE_CM at REFERENCE_CENTRE_NM: the cutoff it gives at each centre.

The measured edge curve is the quadratic fit of the edge walk, as in edge_against_g1_calibration.

Run: PYTHONPATH=.:explorations/stage1_edge_rerun_2026_11_18 .venv/bin/python \
     explorations/stage1_edge_rerun_2026_11_18/single_reference_offset.py
"""
import os
import json

import numpy as np

import exploration_paths

import edge_against_g1_calibration as against_calibration

OUTPUT_PATH = os.path.join(exploration_paths.OUTPUT_DIRECTORY, 'single_reference_offset.txt')
REFERENCE_CENTRE_NM = 800
CUTOFF_AT_REFERENCE_CM = 100.0
CENTRES = against_calibration.CENTRES

output_lines = []


def report(text=''):
    output_lines.append(text)
    print(text)


def wavenumber_gap_cm(laser_nm, edge_nm):
    return 1e7 / laser_nm - 1e7 / edge_nm


def measured_edge_curve():
    """Quadratic fit of the corrected edge against g1 count over the edge walk."""
    with open(against_calibration.FIT_RESULTS_PATH) as fit_file:
        fits = json.load(fit_file)
    counts = against_calibration.g1_counts_by_filename()
    g1_values, edge_values = [], []
    for frame_name, result in fits.items():
        name = frame_name.rsplit('_', 1)[0]
        if (name.startswith('s1edge') and name in counts and result.get('summed')
                and not name.endswith('150')):
            g1_values.append(counts[name][0])
            edge_values.append(result['summed']['edge_nm']
                               + against_calibration.AXIS_CORRECTION_NM)
    return np.poly1d(np.polyfit(g1_values, edge_values, 2))


def count_where(curve, wavelength_nm, near_count):
    roots = [root.real for root in (curve - wavelength_nm).roots
             if abs(root.imag) < 1e-9 and abs(root.real - near_count) < 200]
    return roots[0]


def main():
    with open(against_calibration.CALIBRATION_PATH) as calibration_file:
        g1_section = json.load(calibration_file)['manual_g1']
    wavelength_to_steps = np.poly1d(g1_section['wl_to_g1'])
    edge_curve = measured_edge_curve()

    report('1. Master calibration as it is: where sg puts the edge')
    report('centre  sg count  edge (nm)  edge above centre: steps   nm   cm^-1')
    offsets_steps = {}
    for centre in CENTRES:
        sg_count = wavelength_to_steps(centre)
        edge_nm = edge_curve(sg_count)
        offsets_steps[centre] = count_where(edge_curve, centre, sg_count) - sg_count
        report(f'{centre}  {sg_count:8.1f}  {edge_nm:8.2f}  {offsets_steps[centre]:+14.1f}  '
               f'{edge_nm - centre:+5.2f}  {wavenumber_gap_cm(centre, edge_nm):+6.1f}')

    report(f'\n2. Master calibration referenced once at {REFERENCE_CENTRE_NM} nm '
           '(edge put on the centre there)')
    report('centre  edge left above centre: steps   nm   cm^-1')
    shift = offsets_steps[REFERENCE_CENTRE_NM]
    for centre in CENTRES:
        edge_nm = edge_curve(wavelength_to_steps(centre) + shift)
        report(f'{centre}  {offsets_steps[centre] - shift:+12.1f}  {edge_nm - centre:+6.2f}  '
               f'{wavenumber_gap_cm(centre, edge_nm):+6.1f}')

    report(f'\n3. Fixed spot offset: {CUTOFF_AT_REFERENCE_CM:.0f} cm^-1 at '
           f'{REFERENCE_CENTRE_NM} nm on the measured edge curve')
    reference_edge_nm = 1e7 / (1e7 / REFERENCE_CENTRE_NM - CUTOFF_AT_REFERENCE_CM)
    laser_count = count_where(edge_curve, REFERENCE_CENTRE_NM, wavelength_to_steps(800))
    spot_offset_steps = count_where(edge_curve, reference_edge_nm, laser_count) - laser_count
    report(f'spot offset {spot_offset_steps:+.1f} steps of g1')
    report('laser (nm)  edge (nm)  cutoff (cm^-1)  slope (nm/step)')
    for centre in CENTRES:
        laser_count = count_where(edge_curve, centre, wavelength_to_steps(centre))
        edge_nm = edge_curve(laser_count + spot_offset_steps)
        report(f'{centre}  {edge_nm:9.2f}  {wavenumber_gap_cm(centre, edge_nm):10.1f}  '
               f'{edge_curve.deriv()(laser_count):+.4f}')

    with open(OUTPUT_PATH, 'w') as output:
        output.write('\n'.join(output_lines) + '\n')


if __name__ == '__main__':
    main()
