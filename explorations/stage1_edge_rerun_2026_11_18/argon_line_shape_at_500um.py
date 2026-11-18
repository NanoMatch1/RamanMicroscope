"""Shape of the isolated Ar 763.511 and 794.818 nm lines at 50 and 500 um (2026-11-18): width
at half maximum (nm) and the half-maximum points, in the lamp rows and the band rows. A box
FWHM of about 3 nm at 500 um means ~6 nm per mm at the slit; where the box sits relative to the
50 um line shows which jaw moves.

Run: PYTHONPATH=.:explorations/stage1_edge_rerun_2026_11_18 .venv/bin/python \
     explorations/stage1_edge_rerun_2026_11_18/argon_line_shape_at_500um.py
"""
import os

import numpy as np

import exploration_paths

DATA_DIRECTORY = os.path.join(exploration_paths.DATA_DIRECTORY, 's1ref')
FRAMES = {'500 um': ('s1ref_arhg_slit0500', 1), '50 um': ('s1ref_arhg_slit0050', 0)}
ROW_BANDS = {'lamp rows 380-460': (380, 460), 'band rows 590-610': (590, 610)}
LINES_NM = (763.511, 794.818)
HALF_WINDOW_NM = 4.0


def half_maximum_points(wavelength, spectrum, line_nm):
    window = np.abs(wavelength - (line_nm + 1.5)) <= HALF_WINDOW_NM
    window_nm, values = wavelength[window], spectrum[window]
    values = values - np.mean(np.r_[values[:5], values[-5:]])
    half = values.max() / 2
    above = np.where(values >= half)[0]
    first, last = above[0], above[-1]
    blue = np.interp(half, [values[first - 1], values[first]],
                     [window_nm[first - 1], window_nm[first]])
    red = np.interp(half, [values[last + 1], values[last]], [window_nm[last + 1], window_nm[last]])
    return blue, red


for band_label, rows in ROW_BANDS.items():
    print(band_label)
    for line_nm in LINES_NM:
        for slit_label, (name, index) in FRAMES.items():
            frame = np.load(os.path.join(DATA_DIRECTORY, name, f'{name}_{index:06d}.npz'),
                            allow_pickle=False)
            spectrum = frame['image'].astype(float)[rows[0]:rows[1]].mean(axis=0)
            blue, red = half_maximum_points(frame['wavelength'], spectrum, line_nm)
            print(f'  {line_nm:.3f} {slit_label:7s}: half-max {blue - line_nm:+.2f} to '
                  f'{red - line_nm:+.2f} nm from NIST, FWHM {red - blue:.2f} nm')
