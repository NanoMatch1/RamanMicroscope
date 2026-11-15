"""
A picture of a wavelength axis fit and its residuals, saved as a PNG next to the fit report.

Four panels, which follow the split the gate checks use (calibration_checks,
decompose_fit_residuals):

- TRIAX map: the wavelength each frame puts on the reference pixel against
  TRIAX steps, with the fitted TRIAX polynomial. Each walk's own zero is
  removed, so all walks sit on the one curve.
- TRIAX residual: each frame's offset from that curve (the mean residual of
  its lines). Structure here belongs to the TRIAX drive or to a walk
  drifting; one walk off the others means its zero or its warm-up.
- CCD axis: each line's residual within its frame (the frame offset
  removed), against pixel. A trend across the chip means a missing CCD term
  (curvature); scatter well above ~0.01 nm means misidentification or
  saturation.
- Residual by line: each reference line's within-frame residuals, with
  their mean. One line sitting off the others means a wrong table
  wavelength or a blend (the line-bias gate).

Uses matplotlib's Figure directly (no pyplot), so it draws nothing on screen
and is safe to call from the application's command thread.
"""

from collections import defaultdict

import numpy as np
from matplotlib.figure import Figure

from .calibration_checks import decompose_fit_residuals


def _short_walk_label(walk_label):
    return walk_label.replace('linewalk_', '').replace('.json', '')


def _gate_summary(check_results):
    counts = defaultdict(int)
    for result in check_results:
        counts[result.verdict] += 1
    return ', '.join(f"{counts[verdict]} {verdict}" for verdict in ('FAIL', 'WARN', 'PASS'))


def _plot_triax_map(axes, fit, decomposition, colour_of_walk):
    model = fit.model
    all_steps = [steps for _, steps in decomposition.frame_offsets_nm]
    curve_steps = np.linspace(min(all_steps), max(all_steps), 400)
    triax_order = len(model.triax_to_wavelength_coefficients) - 1
    axes.plot(curve_steps, model.triax_wavelength(curve_steps), color='0.3', linewidth=1,
              label=f"fitted TRIAX polynomial (order {triax_order})")
    for walk, colour in colour_of_walk.items():
        frames = sorted((steps, offset) for (frame_walk, steps), offset
                        in decomposition.frame_offsets_nm.items() if frame_walk == walk)
        steps = np.array([steps for steps, _ in frames], dtype=float)
        measured = model.triax_wavelength(steps) + np.array([offset for _, offset in frames])
        axes.plot(steps, measured, 'o', markersize=3, color=colour, label=_short_walk_label(walk))
    axes.set_xlabel('TRIAX steps')
    axes.set_ylabel(f'wavelength on pixel {model.reference_pixel:g} (nm)')
    axes.set_title('TRIAX map (each walk\'s zero removed)')
    axes.legend(fontsize=7, loc='best')


def _plot_triax_residual(axes, decomposition, colour_of_walk):
    for walk, colour in colour_of_walk.items():
        frames = sorted((steps, offset) for (frame_walk, steps), offset
                        in decomposition.frame_offsets_nm.items() if frame_walk == walk)
        axes.plot([steps for steps, _ in frames], [offset for _, offset in frames], 'o-',
                  markersize=3, linewidth=0.8, color=colour, label=_short_walk_label(walk))
    axes.axhline(0.0, color='0.5', linewidth=0.8)
    axes.set_xlabel('TRIAX steps')
    axes.set_ylabel('frame offset from the fit (nm)')
    axes.set_title(f'TRIAX residual: rms {decomposition.triax_shape_rms_nm:.4f} nm')


def _plot_ccd_residual(axes, decomposition, colour_of_walk):
    if not decomposition.within_frame:
        axes.text(0.5, 0.5, 'no frame with two or more lines', ha='center', va='center',
                  transform=axes.transAxes)
    for walk, colour in colour_of_walk.items():
        entries = [entry for entry in decomposition.within_frame if entry[0] == walk]
        axes.plot([entry[3] for entry in entries], [entry[4] for entry in entries], 'o',
                  markersize=2.5, alpha=0.7, color=colour)
    axes.axhline(0.0, color='0.5', linewidth=0.8)
    axes.set_xlabel('pixel')
    axes.set_ylabel('residual within the frame (nm)')
    axes.set_title(f'CCD axis: rms {decomposition.within_frame_rms_nm:.4f} nm within frames')


def _plot_residual_by_line(axes, fit, decomposition):
    wavelength_of_line = {observation.line_name.split(' (')[0]: observation.apparent_wavelength_nm
                          for observation in fit.observations}
    residuals_by_line = defaultdict(list)
    for _, _, line_name, _, residual in decomposition.within_frame:
        residuals_by_line[wavelength_of_line[line_name]].append(residual)
    if not residuals_by_line:
        axes.text(0.5, 0.5, 'no frame with two or more lines', ha='center', va='center',
                  transform=axes.transAxes)
    for wavelength_nm, residuals in sorted(residuals_by_line.items()):
        axes.plot([wavelength_nm] * len(residuals), residuals, '.', color='0.6', markersize=3)
        axes.plot(wavelength_nm, np.mean(residuals), 'D', color='C3', markersize=4)
    axes.axhline(0.0, color='0.5', linewidth=0.8)
    axes.set_xlabel('reference line (nm, first-order scale)')
    axes.set_ylabel('residual within the frame (nm)')
    axes.set_title('Residual by line, within frames (diamond: mean)')


def plot_wavelength_axis_fit(outcome, plot_path, title=''):
    """
    Draw the fit of a promotion.WalkFitOutcome to `plot_path` (PNG). Returns the path, or None
    if there is no fit to draw.
    """
    fit = outcome.fit
    if fit is None:
        return None
    decomposition = decompose_fit_residuals(fit)
    walks = list(dict.fromkeys(fit.observation_groups or ['all'] * len(fit.observations)))
    colour_of_walk = {walk: f'C{index % 10}' for index, walk in enumerate(walks)}

    figure = Figure(figsize=(13, 8.5), layout='constrained')
    (map_axes, ccd_axes), (triax_axes, line_axes) = figure.subplots(2, 2)
    triax_axes.sharex(map_axes)
    _plot_triax_map(map_axes, fit, decomposition, colour_of_walk)
    _plot_triax_residual(triax_axes, decomposition, colour_of_walk)
    _plot_ccd_residual(ccd_axes, decomposition, colour_of_walk)
    _plot_residual_by_line(line_axes, fit, decomposition)
    figure.suptitle(
        f"{title + ': ' if title else ''}{len(fit.observations)} points, "
        f"residual rms {fit.residual_rms_nm:.4f} nm; gates: {_gate_summary(outcome.check_results)}",
        fontsize=11)
    figure.savefig(plot_path, dpi=110)
    return plot_path
