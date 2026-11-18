"""Does the TRIAX entrance slit open symmetrically? Evidence from the 2026-11-18 Ar-Hg frames.

The Ar-Hg frames at '500 um' (s1ref_arhg_slit0500_000001, 1 s) and '50 um'
(s1ref_arhg_slit0050_000000, 15 s) at the same TRIAX position. The widths are the file names'
(the frame metadata records 500 um for every frame, and no 'ren' values came with the data).

A point of light entering the slit a distance d across it lands on the CCD d x (slit-to-CCD
dispersion) away in wavelength. The TRIAX images its slit at about 1:1, so that dispersion is the
CCD's: 0.0774 nm per 13 um pixel = NM_PER_MM_AT_SLIT. So a line's shift between the two widths
says how far apart the light entered.

Figure slit_symmetry_evidence.png:
  (a) the Ar-Hg spectrum at both widths (lamp rows), each over its own maximum, with NIST lines;
  (b) the 794.8 nm line at both widths, and what a uniformly lit 500 um slit would give (the 50 um
      line convolved with a 500 um box);
  (c) the two geometries across the slit, with where the light entered at each width;
  (d, e) the frames around the 794.8 nm line at both widths, rows 300-700.

Run: PYTHONPATH=.:explorations/stage1_edge_rerun_2026_11_18 .venv/bin/python \
     explorations/stage1_edge_rerun_2026_11_18/slit_symmetry_evidence.py
"""
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

import exploration_paths

DATA_DIRECTORY = os.path.join(exploration_paths.DATA_DIRECTORY, 's1ref')
OUTPUT_DIRECTORY = exploration_paths.OUTPUT_DIRECTORY
OUTPUT_PATH = os.path.join(OUTPUT_DIRECTORY, 'slit_symmetry_evidence.txt')
FRAMES = {'500 um': ('s1ref_arhg_slit0500', 1), '50 um': ('s1ref_arhg_slit0050', 0)}
COLOURS = {'500 um': '#1f77b4', '50 um': '#d62728'}
FILLED_SLIT_COLOUR = '#7f7f7f'
LAMP_ROWS = (380, 460)
IMAGE_ROWS = (300, 700)
PIXEL_PITCH_MM = 0.013
NIST_LINES_NM = (763.511, 772.376, 772.421, 794.818, 800.616, 801.479, 810.369, 811.531,
                 826.452)
ZOOM_LINE_NM = 794.818
WIDE_SLIT_UM, NARROW_SLIT_UM = 500, 50
MEASURED_SHIFT_NM = 2.80     # lamp rows; argon_lines_by_slit_width.txt (band rows: 3.01)

output_lines = []


def report(text=''):
    output_lines.append(text)
    print(text)


def load(name, index):
    frame = np.load(os.path.join(DATA_DIRECTORY, name, f'{name}_{index:06d}.npz'),
                    allow_pickle=False)
    return frame['image'].astype(float), frame['wavelength']


def lamp_spectrum(image):
    """Mean over the lamp rows, less the median of the row band as a flat background."""
    spectrum = image[LAMP_ROWS[0]:LAMP_ROWS[1]].mean(axis=0)
    return spectrum - np.median(spectrum)


def draw_geometry(axes, nm_per_mm):
    """Two rows, symmetric and one-jaw: the openings, and where the light entered."""
    shift_um = MEASURED_SHIFT_NM / nm_per_mm * 1000
    models = (
        ('symmetric', 1.0, (-WIDE_SLIT_UM / 2, WIDE_SLIT_UM / 2),
         (-NARROW_SLIT_UM / 2, NARROW_SLIT_UM / 2)),
        ('one jaw moves', 0.0, (0, WIDE_SLIT_UM), (0, NARROW_SLIT_UM)),
    )
    for label, height, wide, narrow in models:
        axes.broken_barh([(wide[0], wide[1] - wide[0])], (height - 0.18, 0.36),
                         facecolors=COLOURS['500 um'], alpha=0.25)
        axes.broken_barh([(narrow[0], narrow[1] - narrow[0])], (height - 0.18, 0.36),
                         facecolors=COLOURS['50 um'], alpha=0.6)
        light_um = (narrow[0] + narrow[1]) / 2 + shift_um
        inside = wide[0] <= light_um <= wide[1]
        axes.plot(light_um, height, marker='v', markersize=10, color='black')
        axes.annotate(f'500 um light: +{shift_um:.0f} um\n' +
                      ('inside the opening' if inside else 'OUTSIDE the opening'),
                      (light_um, height + 0.2), fontsize=8, ha='center', va='bottom')
        axes.text(-430, height, label, fontsize=9, va='center')
        report(f'  {label}: 500 um opening {wide[0]:+.0f}..{wide[1]:+.0f} um, light at '
               f'{light_um:+.0f} um -> {"inside" if inside else "outside"}')
    axes.set_xlim(-450, 650)
    axes.set_ylim(-0.5, 1.75)
    axes.set_yticks([])
    axes.set_xlabel('position across the slit (um); red = 50 um opening, blue = 500 um')
    axes.set_title(f'(c) where the light entered, at {nm_per_mm:.2f} nm per mm of slit',
                   fontsize=10)


def main():
    frames = {label: load(*source) for label, source in FRAMES.items()}
    wavelength = frames['50 um'][1]
    nm_per_mm = abs(np.mean(np.diff(wavelength))) / PIXEL_PITCH_MM
    report(f'Dispersion at the slit (1:1 imaging assumed): {nm_per_mm:.2f} nm/mm')
    report(f'Measured shift 500 minus 50 um: {MEASURED_SHIFT_NM:.2f} nm -> '
           f'{MEASURED_SHIFT_NM / nm_per_mm * 1000:.0f} um across the slit')
    report(f'Most a symmetric slit allows: (500 + 50) / 2 um = '
           f'{(WIDE_SLIT_UM + NARROW_SLIT_UM) / 2:.0f} um -> '
           f'{(WIDE_SLIT_UM + NARROW_SLIT_UM) / 2 / 1000 * nm_per_mm:.2f} nm')

    figure = plt.figure(figsize=(12, 11))
    grid = figure.add_gridspec(3, 2, height_ratios=(1, 0.8, 1.1))
    spectrum_axes = figure.add_subplot(grid[0, :])
    zoom_axes = figure.add_subplot(grid[1, 0])
    geometry_axes = figure.add_subplot(grid[1, 1])
    image_axes = {'50 um': figure.add_subplot(grid[2, 0]),
                  '500 um': figure.add_subplot(grid[2, 1])}

    spectra = {}
    for label, (image, frame_wavelength) in frames.items():
        spectra[label] = lamp_spectrum(image)
        spectrum_axes.plot(frame_wavelength, spectra[label] / spectra[label].max(),
                           color=COLOURS[label], linewidth=1.1, label=label)
    for line_nm in NIST_LINES_NM:
        spectrum_axes.axvline(line_nm, color='#bbbbbb', linewidth=0.8, zorder=0)
    spectrum_axes.set_xlim(760, 832)
    spectrum_axes.set_xlabel('wavelength on the frame axis (nm); grey = NIST Ar lines')
    spectrum_axes.set_ylabel('lamp rows, / own max')
    spectrum_axes.set_title('(a) Ar-Hg, lamp rows 380-460: every line moves ~2.8 nm at 500 um '
                            'and stays narrow', fontsize=10)
    spectrum_axes.legend(frameon=False)

    zoom = np.abs(wavelength - (ZOOM_LINE_NM + 2)) < 5
    box_pixels = int(round(WIDE_SLIT_UM / 1000 * nm_per_mm / abs(np.mean(np.diff(wavelength)))))
    filled_slit = np.convolve(spectra['50 um'], np.ones(box_pixels) / box_pixels, mode='same')
    for label in FRAMES:
        zoom_axes.plot(wavelength[zoom], spectra[label][zoom] / spectra[label][zoom].max(),
                       color=COLOURS[label], linewidth=1.3, label=label)
    zoom_axes.plot(wavelength[zoom], filled_slit[zoom] / filled_slit[zoom].max(),
                   color=FILLED_SLIT_COLOUR, linewidth=1.3, linestyle='--',
                   label='500 um, uniformly lit (predicted)')
    zoom_axes.axvline(ZOOM_LINE_NM, color='#bbbbbb', linewidth=0.8, zorder=0)
    zoom_axes.set_xlabel('wavelength on the frame axis (nm)')
    zoom_axes.set_ylabel('/ own max')
    zoom_axes.set_title(f'(b) the {ZOOM_LINE_NM} nm line', fontsize=10)
    zoom_axes.legend(frameon=False, fontsize=8)
    report(f'Filled 500 um slit: a {box_pixels}-pixel box '
           f'({box_pixels * abs(np.mean(np.diff(wavelength))):.2f} nm)')

    draw_geometry(geometry_axes, nm_per_mm)

    columns = np.where(np.abs(wavelength - (ZOOM_LINE_NM + 1.8)) < 4)[0]
    for label, axes in image_axes.items():
        image, frame_wavelength = frames[label]
        crop = image[IMAGE_ROWS[0]:IMAGE_ROWS[1], columns[0]:columns[-1] + 1]
        crop = crop - np.median(crop)
        axes.imshow(crop, aspect='auto', cmap='gray_r', origin='lower',
                    vmin=0, vmax=np.percentile(crop, 99.8),
                    extent=(frame_wavelength[columns[0]], frame_wavelength[columns[-1]],
                            IMAGE_ROWS[0], IMAGE_ROWS[1]))
        axes.axvline(ZOOM_LINE_NM, color=COLOURS[label], linewidth=0.8, linestyle=':')
        for row in (LAMP_ROWS[0], LAMP_ROWS[1], 590, 610):
            axes.axhline(row, color='#999999', linewidth=0.5)
        axes.set_xlabel('wavelength on the frame axis (nm)')
        axes.set_ylabel('CCD row (along the slit)')
        axes.set_title(f'({"d" if label == "50 um" else "e"}) {label}: the {ZOOM_LINE_NM} nm '
                       'line on the chip; dotted = NIST', fontsize=10)

    figure.tight_layout()
    figure.savefig(os.path.join(OUTPUT_DIRECTORY, 'slit_symmetry_evidence.png'), dpi=80)
    with open(OUTPUT_PATH, 'w') as output:
        output.write('\n'.join(output_lines) + '\n')


if __name__ == '__main__':
    main()
