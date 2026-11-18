"""
Pictures of a g2 pinhole session, saved as g2_pinhole.png next to its report.

g2 is plotted as steps from the calibration in use (g2 count minus wl_to_g2 at the scan's
reference wavelength), so every scan sits on one axis and a centre's position IS its offset.
Four panels:
- the light through the pinhole, each scan scaled to its fitted window's peak, with the fitted
  window and its centre (vertical line); 0 is where the calibration in use puts g2. The profile
  should be symmetric;
- the block centres against wavelength, with their straight line and the centre at the sg
  wavelength (star): the g1:g2 mismatch is the slope;
- the band's row against g2, with the target row at the fitted centre (star, issue #37);
- each centre's offset with its uncertainty, and the proposed constant (grey).

Uses matplotlib's Figure directly (no pyplot), so nothing is drawn on screen.
"""

import os

import numpy as np
from matplotlib.figure import Figure

from .pinhole_scan import window_model
from .plots import GRID_STYLE, MASTER_COLOUR, _centre_colours, _mark_empty

PINHOLE_MARKERS = {'stage2': 'o', 'stage1': 's'}


def plot_g2_pinhole(session_analysis, path):
    if not session_analysis.scans:
        return False
    figure = Figure(figsize=(12, 9))
    light_axes, block_axes, row_axes, offset_axes = figure.subplots(2, 2).ravel()
    colours = _centre_colours({scan.centre_nm for scan in session_analysis.scans})

    for scan in session_analysis.scans:
        colour = colours[scan.centre_nm]
        marker = PINHOLE_MARKERS.get(scan.pinhole, 'o')
        label = f'{scan.pinhole} {scan.centre_nm} nm'
        zero = scan.master_count or 0.0     # g2 axis: steps from the calibration in use
        fit = scan.total_fit
        if scan.light is not None and fit is not None:
            counts = scan.light.g2_counts
            fine_counts = np.linspace(counts.min(), counts.max(), 300)
            fine_light = window_model(fine_counts, *fit.parameters) - fit.baseline
            peak = fine_light.max()
            light_axes.plot(counts - zero, (scan.light.total_light - fit.baseline) / peak, marker,
                            color=colour, markersize=4, linestyle='none', label=label)
            light_axes.plot(fine_counts - zero, fine_light / peak, color=colour, linewidth=1.5)
            if scan.centre_count is not None:
                light_axes.axvline(scan.centre_count - zero, color=colour, linewidth=1)
        if scan.light is not None:
            points = [(wavelength, block.centre_count - zero, block.centre_uncertainty)
                      for wavelength, block in zip(scan.light.block_wavelengths_nm,
                                                   scan.block_fits) if block is not None]
            if points:
                wavelengths, centres, uncertainties = zip(*points)
                block_axes.errorbar(wavelengths, centres, yerr=uncertainties, fmt=marker,
                                    color=colour, markersize=4, label=label)
            if scan.centre_count is not None:
                reference_nm = scan.reference_wavelength_nm
                block_axes.plot(reference_nm, scan.centre_count - zero, '*', color=colour,
                                markersize=12)
                if scan.mismatch_steps_per_nm is not None and points:
                    span = np.array([reference_nm, max(wavelengths)])
                    block_axes.plot(span, scan.centre_count - zero + scan.mismatch_steps_per_nm
                                    * (span - reference_nm), color=colour, linewidth=1)
        track = scan.band_track
        if track is not None:
            row_axes.plot(np.array(track.frame_counts) - zero, track.frame_rows, marker,
                          color=colour, markersize=4, linestyle='none', label=label)
            span = np.array([min(track.frame_counts), max(track.frame_counts)])
            row_axes.plot(span - zero, np.polyval(track.row_at_middle, span), color=colour,
                          linewidth=1)
            if scan.target_band_row is not None:
                row_axes.plot(scan.centre_count - zero, scan.target_band_row, '*', color=colour,
                              markersize=12)
        if scan.offset_steps is not None:
            offset_axes.errorbar(scan.centre_nm, scan.offset_steps,
                                 yerr=scan.centre_uncertainty or 0, fmt=marker, color=colour,
                                 markersize=6, label=label)

    proposed = session_analysis.proposed
    if proposed is not None:
        offset_axes.axhline(proposed.offset_steps, color=MASTER_COLOUR, linewidth=1)
        offset_axes.axhspan(proposed.offset_steps - proposed.offset_uncertainty,
                            proposed.offset_steps + proposed.offset_uncertainty,
                            color=MASTER_COLOUR, alpha=0.15, linewidth=0)
    else:
        _mark_empty(offset_axes, 'no offset measured')
    if not block_axes.lines and not block_axes.collections:
        _mark_empty(block_axes, 'no block centres')
    if not row_axes.lines:
        _mark_empty(row_axes, 'no band found')

    for axes in (light_axes, row_axes):
        axes.axvline(0, color=MASTER_COLOUR, linewidth=1, linestyle='--')
    block_axes.axhline(0, color=MASTER_COLOUR, linewidth=1, linestyle='--')
    steps_label = 'g2 steps from the calibration in use'
    titles = (('light through the pinhole; line = centre, dashed = calibration in use',
               steps_label, 'light / window peak'),
              ('g2 centre per wavelength block; star = at the sg wavelength', 'wavelength (nm)',
               steps_label),
              ('band row (middle column); star = target row', steps_label, 'CCD row'),
              ('offset from the calibration in use; grey = proposed', 'centre (nm)',
               'g2 steps'))
    for axes, (title, x_label, y_label) in zip((light_axes, block_axes, row_axes, offset_axes),
                                               titles):
        axes.set_title(title, fontsize=9)
        axes.set_xlabel(x_label)
        axes.set_ylabel(y_label)
        axes.grid(**GRID_STYLE)
        if axes.get_legend_handles_labels()[0]:
            axes.legend(frameon=False, fontsize=7)
    figure.tight_layout()
    figure.savefig(path, dpi=80)
    return True


G2_PLOTS = {'g2_pinhole.png': plot_g2_pinhole}


def save_g2_plots(session_analysis, directory):
    """Draw every g2 plot that has data; returns the paths written."""
    written = []
    for file_name, plot in G2_PLOTS.items():
        path = os.path.join(directory, file_name)
        if plot(session_analysis, path):
            written.append(path)
    return written
