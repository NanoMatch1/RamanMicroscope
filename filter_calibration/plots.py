"""
Pictures of a stage 1 edge session, saved as PNGs next to its report.

- g1_calibration.png: the edge against the g1 count with the fitted calibration and the master's;
  the residuals of every run against the fit; how far the new calibration moves g1 at each
  centre; the edge's slope at each centre.
- edge_fits.png: every edge-walk frame's band signal with its fitted edge, one row per centre.
  The first place to look when a residual or a width is odd.
- steps_and_repeatability.png: single-step residuals and step sizes (with the way back down);
  the repeatability frames by what moved before them; the Ar-Hg axis references.
- widths_and_band.png: the edge width against wavelength, and the band's row against g1 (how
  well g2 follows).

Uses matplotlib's Figure directly (no pyplot), so nothing is drawn on screen.
"""

import os

import numpy as np
from matplotlib.figure import Figure

from .frame_names import EDGE_WALK

RUN_COLOURS = {'edge walk': '#1f77b4', 'single steps': '#ff7f0e', 'repeatability': '#2ca02c'}
MASTER_COLOUR = '#7f7f7f'
VISIT_COLOURS = {'start': '#7f7f7f', 'still': '#1f77b4', 'triax': '#d62728', 'gratings': '#2ca02c'}
GRID_STYLE = {'color': '#e5e5e5', 'linewidth': 0.6}


def _centre_colours(centres):
    """One blue per centre, light to dark in wavelength order (centres are ordered)."""
    shades = np.linspace(0.35, 0.95, max(len(centres), 1))
    from matplotlib import colormaps
    return {centre: colormaps['Blues'](shade) for centre, shade in zip(sorted(centres), shades)}


def _mark_empty(axes, text):
    axes.text(0.5, 0.5, text, ha='center', va='center', transform=axes.transAxes, fontsize=9,
              color='#666666')


def _run_points(session_analysis):
    """{run label: [(g1 count, corrected edge)]} for the frames on the calibration's axes."""
    runs = {'edge walk': [(frame.record.g1_count, frame.corrected_edge_nm)
                          for frame in session_analysis.walk_frames_with_edges()]}
    for label, kind in (('single steps', 'single_step'), ('repeatability', 'repeatability')):
        runs[label] = [(frame.record.g1_count, frame.corrected_edge_nm)
                       for frame in session_analysis.frames_of_kind(kind)
                       if frame.edge is not None and frame.record.g1_count is not None]
    return {label: points for label, points in runs.items() if points}


def plot_g1_calibration(session_analysis, path):
    fit = session_analysis.calibration
    if fit is None:
        return False
    figure = Figure(figsize=(12, 9))
    edge_axes, residual_axes, shift_axes, slope_axes = figure.subplots(2, 2).ravel()
    counts = np.linspace(min(fit.x_values) - 10, max(fit.x_values) + 10, 200)
    master_g1_to_wl = session_analysis.master.get('manual_g1', {}).get('g1_to_wl')
    for label, points in _run_points(session_analysis).items():
        g1_counts, edges = np.array(points, dtype=float).T
        edge_axes.plot(g1_counts, edges, 'o', markersize=4, color=RUN_COLOURS[label], label=label)
        residual_axes.plot(g1_counts, edges - fit(g1_counts), 'o', markersize=4,
                           color=RUN_COLOURS[label], label=label)
    edge_axes.plot(counts, fit(counts), color='black', linewidth=1.2,
                   label=f'fit (order {len(fit.coefficients) - 1})')
    if master_g1_to_wl is not None:
        edge_axes.plot(counts, np.polyval(master_g1_to_wl, counts), '--', color=MASTER_COLOUR,
                       linewidth=1.2, label='master g1_to_wl')
    edge_axes.set_xlabel('g1 count (allmotors)')
    edge_axes.set_ylabel('edge (nm, corrected axis)')
    edge_axes.set_title('(a) the edge against g1', fontsize=10)
    edge_axes.legend(frameon=False, fontsize=8)

    rms = fit.residual_rms
    residual_axes.axhspan(-rms, rms, color='#dddddd', zorder=0, label=f'walk rms {rms:.3f} nm')
    residual_axes.axhline(0, color='black', linewidth=0.8)
    residual_axes.set_xlabel('g1 count')
    residual_axes.set_ylabel('edge minus fit (nm)')
    residual_axes.set_title('(b) residuals: every run against the walk fit', fontsize=10)
    residual_axes.legend(frameon=False, fontsize=8)

    centres = [summary for summary in session_analysis.centres
               if summary.count_for_edge_at_centre is not None]
    if centres:
        shift_axes.plot([summary.centre_nm for summary in centres],
                        [summary.count_for_edge_at_centre - summary.master_count
                         for summary in centres], 'o-', color=RUN_COLOURS['edge walk'])
    shift_axes.axhline(0, color='black', linewidth=0.8)
    shift_axes.set_xlabel('centre (nm)')
    shift_axes.set_ylabel('new minus master g1 count (steps)')
    shift_axes.set_title('(c) where the new calibration moves g1 for sg <centre>', fontsize=10)

    with_slopes = [summary for summary in session_analysis.centres
                   if summary.slope_nm_per_step is not None]
    if with_slopes:
        slope_axes.errorbar([summary.centre_nm for summary in with_slopes],
                            [summary.slope_nm_per_step for summary in with_slopes],
                            yerr=[summary.slope_uncertainty for summary in with_slopes],
                            fmt='o', color=RUN_COLOURS['edge walk'], label='per centre (5 frames)')
        centre_range = np.linspace(min(fit.y_values), max(fit.y_values), 100)
        derivative = np.polyder(fit.coefficients)
        fit_counts = [np.interp(wavelength, sorted(fit.y_values),
                                np.array(fit.x_values)[np.argsort(fit.y_values)])
                      for wavelength in centre_range]
        slope_axes.plot(centre_range, np.polyval(derivative, fit_counts), color='black',
                        linewidth=1.0, label='fit')
        if master_g1_to_wl is not None:
            slope_axes.plot(centre_range, np.polyval(np.polyder(master_g1_to_wl), fit_counts), '--',
                            color=MASTER_COLOUR, linewidth=1.0, label='master')
        slope_axes.legend(frameon=False, fontsize=8)
    slope_axes.set_xlabel('edge (nm)')
    slope_axes.set_ylabel('d edge / d g1 (nm per step)')
    slope_axes.set_title('(d) the edge\'s slope', fontsize=10)
    for axes in (edge_axes, residual_axes, shift_axes, slope_axes):
        axes.grid(**GRID_STYLE)
    figure.tight_layout()
    figure.savefig(path, dpi=80)
    return True


def plot_edge_fits(session_analysis, path):
    from .edge_fit import edge_model
    walk = [frame for frame in session_analysis.frames_of_kind(EDGE_WALK)
            if not frame.record.frame_name.is_edge_free and frame.result is not None]
    if not walk:
        return False
    centres = sorted({frame.record.frame_name.centre_nm for frame in walk})
    offsets = sorted({frame.record.frame_name.g1_offset_steps for frame in walk})
    figure = Figure(figsize=(2.6 * len(offsets), 1.9 * len(centres)))
    grid = figure.subplots(len(centres), len(offsets), squeeze=False)
    for axes in grid.ravel():
        axes.axis('off')
    for frame in walk:
        row = centres.index(frame.record.frame_name.centre_nm)
        column = offsets.index(frame.record.frame_name.g1_offset_steps)
        axes = grid[row, column]
        axes.axis('on')
        axes.set_title(f'{frame.record.frame_name.centre_nm} nm, g1 '
                       f'{frame.record.frame_name.g1_offset_steps:+d}', fontsize=8)
        axes.tick_params(labelsize=6)
        result = frame.result
        if result.signal is None:
            axes.text(0.5, 0.5, 'no band', ha='center', transform=axes.transAxes, fontsize=8)
            continue
        if frame.edge is None:
            axes.plot(result.wavelength_nm, result.signal, color='#999999', linewidth=0.6)
            axes.text(0.5, 0.5, 'no edge fitted', ha='center', transform=axes.transAxes,
                      fontsize=8)
            axes.text(0.02, 0.02, result.edge_failure, transform=axes.transAxes, fontsize=5,
                      wrap=True, va='bottom')
            continue
        first, last = frame.edge.fit_window
        pixels = np.arange(first, last, dtype=float)
        scale = frame.edge.plateau
        axes.plot(result.wavelength_nm[first:last], result.signal[first:last] / scale,
                  color=RUN_COLOURS['edge walk'], linewidth=0.8)
        axes.plot(result.wavelength_nm[first:last],
                  edge_model(pixels, *frame.edge.parameters) / scale, color='black',
                  linewidth=0.8)
        axes.axvline(frame.edge.edge_nm, color='#d62728', linewidth=0.6)
        axes.text(0.02, 0.92, f'{frame.edge.edge_nm:.2f} nm\nw {frame.edge.width_nm:.2f}',
                  transform=axes.transAxes, fontsize=6, va='top')
    figure.suptitle('Band signal / plateau (blue) and the fitted edge (black); red = edge',
                    fontsize=9)
    figure.tight_layout()
    figure.savefig(path, dpi=70)
    return True


def plot_steps_and_repeatability(session_analysis, path):
    steps = session_analysis.single_steps
    repeatability = session_analysis.repeatability
    references = session_analysis.axis_references
    if steps is None and repeatability is None and not references:
        return False
    figure = Figure(figsize=(12, 9))
    residual_axes, size_axes, visit_axes, axis_axes = figure.subplots(2, 2).ravel()
    if steps is not None:
        step_frames = sorted((frame for frame in session_analysis.frames_of_kind('single_step')
                              if frame.edge is not None),
                             key=lambda frame: frame.record.frame_name.sequence)
        offsets = np.array([frame.record.frame_name.g1_offset_steps for frame in step_frames])
        edges = np.array([frame.corrected_edge_nm for frame in step_frames])
        turn = int(np.argmax(offsets))
        line = np.polyfit(offsets[:turn + 1], edges[:turn + 1], 1)
        way_up = slice(0, turn + 1)
        residual_axes.plot(offsets[way_up], edges[way_up] - np.polyval(line, offsets[way_up]),
                           'o-', markersize=3, color=RUN_COLOURS['single steps'], label='way up')
        residual_axes.plot(offsets[turn:], edges[turn:] - np.polyval(line, offsets[turn:]), 's--',
                           markersize=4, color='#8c564b', label='way back down')
        residual_axes.axhline(0, color='black', linewidth=0.8)
        residual_axes.legend(frameon=False, fontsize=8)
        size_axes.bar(np.arange(1, len(steps.step_sizes_nm) + 1), np.abs(steps.step_sizes_nm),
                      color=RUN_COLOURS['single steps'])
        size_axes.axhline(abs(steps.slope_nm_per_step), color='black', linewidth=0.8,
                          label=f'fitted {abs(steps.slope_nm_per_step):.3f} nm/step')
        size_axes.legend(frameon=False, fontsize=8)
    if steps is None:
        _mark_empty(residual_axes, 'no single-step run in this session')
        _mark_empty(size_axes, 'no single-step run in this session')
    residual_axes.set_xlabel('g1 offset (steps)')
    residual_axes.set_ylabel('edge minus way-up line (nm)')
    residual_axes.set_title('(a) single steps', fontsize=10)
    size_axes.set_xlabel('step number (way up)')
    size_axes.set_ylabel('edge move (nm)')
    size_axes.set_title('(b) single step sizes', fontsize=10)

    if repeatability is not None:
        start = repeatability.edges_by_visit_kind.get('start', [(None, 0.0)])[0][1]
        for position, visit_kind in enumerate(('start', 'still', 'triax', 'gratings')):
            values = [edge - start for _, edge in repeatability.edges_by_visit_kind.get(visit_kind,
                                                                                          [])]
            visit_axes.plot(np.full(len(values), position) + np.linspace(-0.15, 0.15, len(values)),
                            values, 'o', color=VISIT_COLOURS[visit_kind])
        visit_axes.set_xticks(range(4))
        visit_axes.set_xticklabels(['start', 'nothing moved', 'TRIAX alone', 'gratings alone'])
        visit_axes.axhline(0, color='black', linewidth=0.8)
    else:
        _mark_empty(visit_axes, 'no repeatability run in this session')
    visit_axes.set_ylabel('edge minus the start frame (nm)')
    visit_axes.set_title('(c) repeatability: what moved before each frame', fontsize=10)

    colours = _centre_colours(references.keys())
    for centre, reference in sorted(references.items()):
        used = reference.lines_used
        axis_axes.plot([line.nist_nm for line in used],
                       [line.measured_nm - line.nist_nm for line in used], 'o-',
                       color=colours[centre], label=f'{centre} nm: correction '
                       f'{reference.correction_nm:+.3f}' if reference.correction_nm is not None
                       else f'{centre} nm')
    if references:
        axis_axes.legend(frameon=False, fontsize=7)
    else:
        _mark_empty(axis_axes, 'no axis references in this session')
    axis_axes.axhline(0, color='black', linewidth=0.8)
    axis_axes.set_xlabel('NIST wavelength (nm)')
    axis_axes.set_ylabel('measured minus NIST (nm)')
    axis_axes.set_title('(d) Ar-Hg axis references, in the band\'s rows', fontsize=10)
    for axes in (residual_axes, size_axes, visit_axes, axis_axes):
        axes.grid(**GRID_STYLE)
    figure.tight_layout()
    figure.savefig(path, dpi=80)
    return True


def plot_widths_and_band(session_analysis, path):
    walk = session_analysis.walk_frames_with_edges()
    if not walk:
        return False
    figure = Figure(figsize=(12, 4.5))
    width_axes, row_axes = figure.subplots(1, 2)
    centres = sorted({frame.record.frame_name.centre_nm for frame in walk})
    colours = _centre_colours(centres)
    for centre in centres:
        frames = [frame for frame in walk if frame.record.frame_name.centre_nm == centre]
        width_axes.plot([frame.corrected_edge_nm for frame in frames],
                        [frame.edge.width_nm for frame in frames], 'o', color=colours[centre],
                        label=f'{centre} nm')
        row_axes.plot([frame.record.frame_name.g1_offset_steps for frame in frames],
                      [frame.result.band_row_at_centre for frame in frames], 'o-',
                      color=colours[centre], label=f'{centre} nm')
    width_axes.set_xlabel('edge (nm)')
    width_axes.set_ylabel('edge width, FWHM-equivalent (nm)')
    width_axes.set_title('(a) edge width', fontsize=10)
    row_axes.set_xlabel('g1 offset (steps), g2 following')
    row_axes.set_ylabel('band centre row')
    row_axes.set_title('(b) band row: flat means g2 follows g1 at the right ratio', fontsize=10)
    for axes in (width_axes, row_axes):
        axes.grid(**GRID_STYLE)
        axes.legend(frameon=False, fontsize=7)
    figure.tight_layout()
    figure.savefig(path, dpi=80)
    return True


PLOTS = {
    'g1_calibration.png': plot_g1_calibration,
    'edge_fits.png': plot_edge_fits,
    'steps_and_repeatability.png': plot_steps_and_repeatability,
    'widths_and_band.png': plot_widths_and_band,
}


def save_all_plots(session_analysis, directory):
    """Draw every plot that has data; returns the paths written."""
    written = []
    for file_name, plot in PLOTS.items():
        path = os.path.join(directory, file_name)
        if plot(session_analysis, path):
            written.append(path)
    return written
