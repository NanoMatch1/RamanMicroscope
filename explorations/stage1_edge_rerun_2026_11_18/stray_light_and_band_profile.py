"""Stray light and the filtered band's shape, 2026-11-18 stage 1 edge rerun.

The frames carry a diffuse background over the whole chip that is not in the dark frame: lamp
light reaching the wide TRIAX slit without passing the filter's edge (it has no edge in it).
This script checks whether the closed frame at each centre (g1 at -150, nothing passes the
edge) is a good background for the other frames at that centre:
- background level per frame, above the dark frame, in rows away from the band;
- the same after subtracting the closed frame (should be ~0 if the stray light is steady);
- in the band's rows but blue of every edge (first 100 columns), where only stray light and any
  leakage through the edge can be.
Then the band itself, from the open-side light of the 800 nm g1 = 0 frame: centre row and
height (FWHM in rows) against wavelength.

Run: PYTHONPATH=.:explorations/stage1_edge_rerun_2026_11_18 .venv/bin/python \
     explorations/stage1_edge_rerun_2026_11_18/stray_light_and_band_profile.py
"""
import os

import numpy as np

import exploration_paths

DATA_DIRECTORY = exploration_paths.DATA_DIRECTORY
OUTPUT_PATH = os.path.join(exploration_paths.OUTPUT_DIRECTORY, 'stray_light_and_band_profile.txt')
CENTRES = (720, 760, 800, 840, 880, 920, 960)
WALK_LABELS = ('m020', 'm010', 'p000', 'p010', 'p020', 'p150')
OFF_BAND_ROWS = np.r_[100:400, 700:950]
BAND_ROWS = slice(540, 660)
BLUE_COLUMNS = slice(0, 100)
PROFILE_ROWS = (540, 660)

output_lines = []


def report(text=''):
    output_lines.append(text)
    print(text)


def load_frame(name, index=0):
    group = name.split('_')[0]
    path = os.path.join(DATA_DIRECTORY, group, name, f'{name}_{index:06d}.npz')
    frame = np.load(path, allow_pickle=False)
    return frame['image'].astype(float), frame['wavelength']


def full_width_half_maximum(profile):
    peak_index = int(np.argmax(profile))
    half = profile[peak_index] / 2
    above = np.where(profile >= half)[0]
    return float(above[-1] - above[0] + 1)


def main():
    dark, _ = load_frame('s1ref_dark')
    report('Background above dark (median counts in 15 s), off-band rows 100-400 and 700-950;')
    report('"minus closed" = same after subtracting the g1 -150 frame at that centre;')
    report('"band, blue side" = band rows 540-660, first 100 columns, minus closed.')
    report('frame'.ljust(26) + 'above dark  minus closed  band blue side minus closed')
    for centre in CENTRES:
        closed, _ = load_frame(f's1edge_t{centre}_g1m150')
        report(f's1edge_t{centre}_g1m150'.ljust(26)
               + f'{np.median((closed - dark)[OFF_BAND_ROWS]):10.0f}')
        for label in WALK_LABELS:
            image, _ = load_frame(f's1edge_t{centre}_g1{label}')
            difference = image - closed
            report(f'  g1{label}'.ljust(26)
                   + f'{np.median((image - dark)[OFF_BAND_ROWS]):10.0f}'
                   + f'{np.median(difference[OFF_BAND_ROWS]):14.1f}'
                   + f'{np.median(difference[BAND_ROWS, BLUE_COLUMNS]):16.1f}')

    report('\nReference frames: background above dark, off-band rows')
    for name, index in (('s1ref_slit0050', 0), ('s1ref_slit0050', 1), ('s1ref_slit0200', 0),
                        ('s1ref_slit0500', 0), ('s1ref_g1p000', 0), ('s1ref_g1p000', 2),
                        ('s1ref_g1p010', 0)):
        image, _ = load_frame(name, index)
        report(f'  {name}_{index}'.ljust(26) + f'{np.median((image - dark)[OFF_BAND_ROWS]):10.0f}')

    report('\nBand shape, s1edge_t800_g1p000 minus the closed frame, columns red of the edge')
    image, wavelength = load_frame('s1edge_t800_g1p000')
    closed, _ = load_frame('s1edge_t800_g1m150')
    band = (image - closed)[PROFILE_ROWS[0]:PROFILE_ROWS[1]]
    rows = np.arange(*PROFILE_ROWS)
    centre_rows, widths, column_wavelengths = [], [], []
    for column in range(560, 1020, 40):
        profile = band[:, column - 5:column + 5].mean(axis=1)
        profile = profile - np.median(profile)
        positive = np.clip(profile, 0, None)
        peak = int(np.argmax(positive))
        window = slice(max(peak - 8, 0), peak + 9)
        centre_row = np.sum(rows[window] * positive[window]) / positive[window].sum()
        centre_rows.append(centre_row)
        widths.append(full_width_half_maximum(positive))
        column_wavelengths.append(wavelength[column])
        report(f'  {wavelength[column]:7.2f} nm: centre row {centre_row:7.2f}, FWHM '
               f'{widths[-1]:4.0f} rows, peak {profile.max():7.0f} counts per pixel')
    slope, _ = np.polyfit(column_wavelengths, centre_rows, 1)
    report(f'  centre row moves {slope:+.3f} rows/nm')
    with open(OUTPUT_PATH, 'w') as output:
        output.write('\n'.join(output_lines) + '\n')


if __name__ == '__main__':
    main()
