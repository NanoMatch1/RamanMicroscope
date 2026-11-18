"""Band spectra of the 2026-11-18 stage 1 edge rerun, overlaid, and the light that leaks past
the closed edge.

Figure edge_overlays.png: one panel per centre; the band signal (closed frame and flank
background removed, rows summed along the band; as in fit_edges.py) for g1 = -20 ... +20 and +150,
divided by the g1 = +20 frame's plateau. g1 is ordered, so the five walk positions share one hue,
light to dark; the open frame (+150) is grey, dashed where any pixel in the column saturates.
Figure slit_series.png: the band at 50 (both frames), 200 and 500 um, each divided by its own
plateau 815-835 nm, and the ratio to the 500 um frame.

Leakage: the closed frame's band signal (flank background only) over the +20 frame's plateau,
median over the columns where the +20 frame passes light.
Red cut-off: where the open frame's band falls to half its plateau on the long-wavelength side,
at the centres where it falls on the chip.

Run: PYTHONPATH=.:explorations/stage1_edge_rerun_2026_11_18 .venv/bin/python \
     explorations/stage1_edge_rerun_2026_11_18/edge_overlays_and_leakage.py
"""
import os

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

import exploration_paths

import fit_edges as edges

OUTPUT_DIRECTORY = exploration_paths.OUTPUT_DIRECTORY
OUTPUT_PATH = os.path.join(OUTPUT_DIRECTORY, 'edge_overlays_and_leakage.txt')
WALK_OFFSETS = (-20, -10, 0, 10, 20)
WALK_COLOURS = ('#c6dbef', '#9ecae1', '#6baed6', '#3182bd', '#08519c')
OPEN_COLOUR = '#7f7f7f'
SLIT_FRAMES = (('s1ref_slit0050', 0, '50 um, first frame', '#d62728'),
               ('s1ref_slit0050', 1, '50 um, second frame', '#ff7f0e'),
               ('s1ref_slit0200', 0, '200 um', '#2ca02c'),
               ('s1ref_slit0500', 0, '500 um', '#1f77b4'))
PLATEAU_RANGE_NM = (815.0, 835.0)

output_lines = []


def report(text=''):
    output_lines.append(text)
    print(text)


def walk_name(centre, offset):
    sign = 'm' if offset < 0 else 'p'
    return f's1edge_t{centre}_g1{sign}{abs(offset):03d}'


def band_signal(name, index=0, closed_image=None, centre_rows=None):
    """Band signal per column, with the band's centre line taken from this frame (or given)."""
    image, wavelength, _ = edges.load_frame(edges.frame_path(name, index))
    background_removed = image - closed_image if closed_image is not None else image
    if centre_rows is None:
        line = edges.band_centre_line(
            background_removed if closed_image is not None
            else edges.remove_flank_background(image, np.full(image.shape[1], 600.0)))
        if line is None:
            return wavelength, None, None, None
        centre_rows = np.polyval(line, np.arange(image.shape[1]))
    cleaned = edges.remove_flank_background(background_removed, centre_rows)
    signal = edges.band_rows_sum(cleaned, centre_rows, edges.BAND_HALF_HEIGHT_ROWS)
    saturated_columns = (image >= edges.SATURATION_LEVEL).any(axis=0)
    return wavelength, signal, saturated_columns, centre_rows


def plateau_of(signal, wavelength, edge_nm):
    passing = wavelength > edge_nm + 3
    return float(np.median(signal[passing]))


def main():
    figure, axes_grid = plt.subplots(4, 2, figsize=(12, 13))
    report('Leakage past the closed edge, and the red cut-off of the open frame')
    for axes, centre in zip(np.ravel(axes_grid), edges.CENTRES):
        closed_image, _, _ = edges.load_frame(edges.frame_path(walk_name(centre, -150)))
        reference = band_signal(walk_name(centre, 20), closed_image=closed_image)
        if reference[3] is None:
            # No band at g1 +20 (960 nm): take the band's line from the open frame.
            _, _, _, centre_rows = band_signal(walk_name(centre, 150), closed_image=closed_image)
            reference = band_signal(walk_name(centre, 20), closed_image=closed_image,
                                    centre_rows=centre_rows)
        wavelength, reference_signal, _, centre_rows = reference
        fit = edges.fit_edge(reference_signal, wavelength)
        plateau = plateau_of(reference_signal, wavelength, fit['edge_nm']) if fit else \
            float(np.percentile(reference_signal, 95))
        for offset, colour in zip(WALK_OFFSETS, WALK_COLOURS):
            _, signal, _, _ = band_signal(walk_name(centre, offset), closed_image=closed_image,
                                          centre_rows=centre_rows)
            axes.plot(wavelength, signal / plateau, color=colour, linewidth=1.2,
                      label=f'g1 {offset:+d}')
        _, open_signal, saturated, _ = band_signal(walk_name(centre, 150),
                                                   closed_image=closed_image,
                                                   centre_rows=centre_rows)
        axes.plot(wavelength, np.where(saturated, np.nan, open_signal / plateau),
                  color=OPEN_COLOUR, linewidth=1.2, label='g1 +150 (open)')
        axes.plot(wavelength, np.where(saturated, open_signal / plateau, np.nan),
                  color=OPEN_COLOUR, linewidth=1.2, linestyle='--')
        _, closed_signal, _, _ = band_signal(walk_name(centre, -150), centre_rows=centre_rows)
        passing = wavelength > (fit['edge_nm'] + 3 if fit else wavelength[0])
        leak = float(np.median(closed_signal[passing])) / plateau
        open_relative = open_signal / plateau
        red_text = ''
        unsaturated_open = np.where(saturated, np.nan, open_relative)
        open_plateau = np.nanpercentile(unsaturated_open, 90)
        above_half = np.where(unsaturated_open > open_plateau / 2)[0]
        if len(above_half) and above_half[-1] < len(wavelength) - 20:
            red_text = f', open frame falls to half at {wavelength[above_half[-1]]:.1f} nm'
        report(f'  {centre} nm: closed / plateau = {leak:+.4f} (plateau {plateau:.0f} counts per '
               f'column){red_text}')
        axes.set_title(f'centre {centre} nm', fontsize=10)
        axes.set_ylim(-0.1, 2.0)
        axes.grid(color='#e5e5e5', linewidth=0.6)
        axes.set_xlabel('wavelength on the frame axis (nm)', fontsize=9)
        axes.set_ylabel('band signal / g1 +20 plateau', fontsize=9)
    np.ravel(axes_grid)[0].legend(fontsize=8, frameon=False)
    np.ravel(axes_grid)[-1].axis('off')
    figure.tight_layout()
    figure.savefig(os.path.join(OUTPUT_DIRECTORY, 'edge_overlays.png'), dpi=70)

    report('\nSlit series (no closed frame at these widths: flank background only)')
    figure, (spectrum_axes, ratio_axes) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
    _, _, _, centre_rows = band_signal('s1edge_t800_g1p000', closed_image=edges.load_frame(
        edges.frame_path('s1edge_t800_g1m150'))[0])
    normalised = {}
    for name, index, label, colour in SLIT_FRAMES:
        wavelength, signal, _, _ = band_signal(name, index, centre_rows=centre_rows)
        in_range = (wavelength > PLATEAU_RANGE_NM[0]) & (wavelength < PLATEAU_RANGE_NM[1])
        plateau = float(np.median(signal[in_range]))
        normalised[label] = signal / plateau
        spectrum_axes.plot(wavelength, signal / plateau, color=colour, linewidth=1.1, label=label)
        report(f'  {label:20s} plateau {plateau:8.0f} counts per column (815-835 nm)')
    for name, index, label, colour in SLIT_FRAMES[:-1]:
        smoothed_ratio = np.convolve(normalised[label] / normalised['500 um'], np.ones(15) / 15,
                                     mode='same')
        ratio_axes.plot(wavelength, smoothed_ratio, color=colour, linewidth=1.1, label=label)
        passing = wavelength > 806
        report(f'  {label:20s} / 500 um, 806-839 nm: slope '
               f'{np.polyfit(wavelength[passing], smoothed_ratio[passing], 1)[0] * 30:+.3f} '
               f'per 30 nm, rms {np.std(smoothed_ratio[passing]):.3f}')
    spectrum_axes.set_ylabel('band signal / own plateau 815-835 nm')
    spectrum_axes.legend(frameon=False, fontsize=9)
    spectrum_axes.set_ylim(-0.1, 1.4)
    ratio_axes.set_ylabel('ratio to 500 um (15-column mean)')
    ratio_axes.set_ylim(0.8, 1.2)
    ratio_axes.set_xlim(800, 839.5)
    ratio_axes.set_xlabel('wavelength on the frame axis (nm)')
    for axes in (spectrum_axes, ratio_axes):
        axes.grid(color='#e5e5e5', linewidth=0.6)
    figure.tight_layout()
    figure.savefig(os.path.join(OUTPUT_DIRECTORY, 'slit_series.png'), dpi=70)

    with open(OUTPUT_PATH, 'w') as output:
        output.write('\n'.join(output_lines) + '\n')


if __name__ == '__main__':
    main()
