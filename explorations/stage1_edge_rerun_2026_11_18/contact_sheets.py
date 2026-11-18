"""Contact sheets of the 2026-11-18 stage 1 edge rerun (log colour), to see where the light is
and what the stray-light background looks like.

Sheet 1: reference frames (slit series, dark, Ar-Hg, check pair) and the 800 nm walk.
Sheet 2: the g1 = 0, +150 and -150 frames at every centre.
Colour: log10 of counts above the dark frame (raw counts for the dark itself).

Run: PYTHONPATH=.:explorations/stage1_edge_rerun_2026_11_18 .venv/bin/python \
     explorations/stage1_edge_rerun_2026_11_18/contact_sheets.py
"""
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

import exploration_paths

DATA_DIRECTORY = exploration_paths.DATA_DIRECTORY
OUTPUT_DIRECTORY = exploration_paths.OUTPUT_DIRECTORY
CENTRES = (720, 760, 800, 840, 880, 920, 960)
SATURATION_LEVEL = 65535


def load_frame(name, index=0):
    group = name.split('_')[0]
    path = os.path.join(DATA_DIRECTORY, group, name, f'{name}_{index:06d}.npz')
    frame = np.load(path, allow_pickle=False)
    return frame['image'].astype(float), frame['wavelength']


DARK, _ = load_frame('s1ref_dark')


def draw_sheet(panels, output_name, columns=4):
    rows = int(np.ceil(len(panels) / columns))
    figure, axes_grid = plt.subplots(rows, columns, figsize=(4 * columns, 3.6 * rows))
    for axes, (title, (image, wavelength)) in zip(np.ravel(axes_grid), panels):
        shown = image if title.startswith('s1ref_dark') else image - DARK
        axes.imshow(np.log10(np.clip(shown, 1, None)), origin='lower', aspect='auto',
                    cmap='magma', vmin=1.5, vmax=4.8,
                    extent=(wavelength[0], wavelength[-1], 0, image.shape[0]))
        saturated = int((image >= SATURATION_LEVEL).sum())
        axes.set_title(f'{title}  sat {saturated}', fontsize=9)
    for axes in np.ravel(axes_grid)[len(panels):]:
        axes.axis('off')
    figure.tight_layout()
    path = os.path.join(OUTPUT_DIRECTORY, output_name)
    figure.savefig(path, dpi=60)
    print(path)


def main():
    reference_frames = [('s1ref_slit0050', 0), ('s1ref_slit0050', 1), ('s1ref_slit0200', 0),
                        ('s1ref_slit0500', 0), ('s1ref_dark', 0), ('s1ref_arhg_slit0500', 1),
                        ('s1ref_arhg_slit0050', 0), ('s1ref_g1p000', 0), ('s1ref_g1p000', 2),
                        ('s1ref_g1p010', 0)]
    walk_800 = [f's1edge_t800_g1{label}' for label in ('m150', 'm020', 'm010', 'p000', 'p010',
                                                       'p020', 'p150')]
    draw_sheet([(f'{name}_{index}', load_frame(name, index)) for name, index in reference_frames]
               + [(name, load_frame(name)) for name in walk_800], 'sheet_references_and_800.png')
    centre_panels = []
    for centre in CENTRES:
        for label in ('m150', 'p000', 'p150'):
            name = f's1edge_t{centre}_g1{label}'
            centre_panels.append((name, load_frame(name)))
    draw_sheet(centre_panels, 'sheet_centres.png', columns=3)


if __name__ == '__main__':
    main()
