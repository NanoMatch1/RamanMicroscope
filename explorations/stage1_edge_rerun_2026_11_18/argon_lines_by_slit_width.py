"""Ar-Hg lines at the two TRIAX slit widths, 2026-11-18 rerun (sg 800, 760-839 nm on the chip).

What a 500 um slit does to the wavelength reading: compare each argon line's centre at 500 um
(s1ref_arhg_slit0500_000001, 1 s; frame _000000 at 15 s saturates) and at 50 um
(s1ref_arhg_slit0050_000000, 15 s). At 500 um a line is a ~3 nm flat-topped box, so a Gaussian
fit does not apply: every line is measured the same way at both widths, as the centroid above a
straight baseline drawn between the ends of a window CENTROID_HALF_WINDOW_NM either side of
the line. Close pairs (800.616 + 801.479, 810.369 + 811.531, 772.376 + 772.421) merge at 500 um,
so they are measured as one group each; a group's reference wavelength is its intensity-weighted
NIST mean, which cancels in the 500-minus-50 difference anyway.

Lines are measured in two row bands, because the lines curve along the slit image: where the
lamp is brightest (rows 380-460) and the filtered band's rows (590-610).

Run: PYTHONPATH=.:explorations/stage1_edge_rerun_2026_11_18 .venv/bin/python \
     explorations/stage1_edge_rerun_2026_11_18/argon_lines_by_slit_width.py
"""
import os

import numpy as np

import exploration_paths

DATA_DIRECTORY = os.path.join(exploration_paths.DATA_DIRECTORY, 's1ref')
OUTPUT_PATH = os.path.join(exploration_paths.OUTPUT_DIRECTORY, 'argon_lines_by_slit_width.txt')
FRAMES = {'500 um': ('s1ref_arhg_slit0500', 1), '50 um': ('s1ref_arhg_slit0050', 0)}
ROW_BANDS = {'lamp rows 380-460': (380, 460), 'band rows 590-610': (590, 610)}
# (NIST air wavelength, relative intensity) per group; groups are > 6 nm apart.
LINE_GROUPS = (
    ((763.511, 25000),),
    ((772.376, 15000), (772.421, 10000)),
    ((794.818, 20000),),
    ((800.616, 20000), (801.479, 25000)),
    ((810.369, 20000), (811.531, 35000)),
    ((826.452, 10000),),
)
CENTROID_HALF_WINDOW_NM = 3.0
SATURATION_LEVEL = 65535

output_lines = []


def report(text=''):
    output_lines.append(text)
    print(text)


def load(name, index):
    frame = np.load(os.path.join(DATA_DIRECTORY, name, f'{name}_{index:06d}.npz'),
                    allow_pickle=False)
    return frame['image'].astype(float), frame['wavelength']


def group_reference_nm(group):
    wavelengths, intensities = np.array(group).T
    return float(np.sum(wavelengths * intensities) / intensities.sum())


def centroid_nm(spectrum, wavelength, approximate_nm):
    """Centroid above a straight baseline between the window's ends, with the window centred
    on the brightest pixel within 1.5 nm of approximate_nm."""
    near = np.abs(wavelength - approximate_nm) <= 1.5
    peak_nm = wavelength[near][np.argmax(spectrum[near])]
    window = np.abs(wavelength - peak_nm) <= CENTROID_HALF_WINDOW_NM
    window_nm, window_values = wavelength[window], spectrum[window]
    baseline = np.interp(window_nm, [window_nm[0], window_nm[-1]],
                         [np.mean(window_values[:3]), np.mean(window_values[-3:])])
    above = np.clip(window_values - baseline, 0, None)
    return float(np.sum(window_nm * above) / above.sum())


def main():
    measured = {}
    for slit_label, (name, index) in FRAMES.items():
        image, wavelength = load(name, index)
        report(f'{slit_label}: {name}_{index:06d}, axis {wavelength[0]:.2f}-{wavelength[-1]:.2f} '
               f'nm, {abs(np.mean(np.diff(wavelength))):.4f} nm/pixel, saturated pixels '
               f'{int((image >= SATURATION_LEVEL).sum())}')
        for band_label, rows in ROW_BANDS.items():
            spectrum = image[rows[0]:rows[1]].mean(axis=0)
            saturated_columns = (image[rows[0]:rows[1]] >= SATURATION_LEVEL).any(axis=0)
            for group in LINE_GROUPS:
                reference = group_reference_nm(group)
                # The 50 um frames read ~0.3-0.8 nm high; search around reference + 0.5 nm.
                centre = centroid_nm(spectrum, wavelength, reference + 0.5)
                column = int(np.argmin(np.abs(wavelength - centre)))
                measured[(slit_label, band_label, reference)] = (
                    centre, bool(saturated_columns[column - 40:column + 40].any()))

    for band_label in ROW_BANDS:
        report(f'\n{band_label}: centroid minus NIST group mean (nm)')
        report('NIST group'.ljust(22) + ''.join(f'{slit:>12s}' for slit in FRAMES)
               + '   500 minus 50 (nm)')
        differences = []
        for group in LINE_GROUPS:
            reference = group_reference_nm(group)
            values = [measured[(slit, band_label, reference)] for slit in FRAMES]
            cells = ''.join(f'{centre - reference:+9.3f}{" s" if saturated else "  "} '
                            for centre, saturated in values)
            difference = values[0][0] - values[1][0]
            differences.append(difference)
            names = '+'.join(f'{wavelength:.1f}' for wavelength, _ in group)
            report(f'{names:22s}{cells}  {difference:+.3f}')
        report(f'mean 500 minus 50 um: {np.mean(differences):+.3f} +/- {np.std(differences):.3f} '
               f'nm over {len(differences)} groups')

    with open(OUTPUT_PATH, 'w') as output:
        output.write('\n'.join(output_lines) + '\n')


if __name__ == '__main__':
    main()
