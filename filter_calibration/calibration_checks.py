"""
Gates: is this g1 calibration good enough to apply, and if not, what is most likely wrong?

Every check is a function registered with @edge_calibration_check; the registry is the only list
of checks, and the report and `--apply` (which refuses on any FAIL) run whatever is registered.
Adding a check means writing one decorated function here.

The results use the wavelength axis calibration's CheckResult and verdicts (PASS, WARN, FAIL),
so both calibrations report alike: a one-line summary with the number and the limit, then for a
WARN or FAIL the evidence, the likely causes and what to try, written for whoever is at the
instrument. Limits live in EdgeCheckLimits; the values come from the 2026-11-18 session
(lab-notebook RAM-F5) unless a comment says otherwise.

Pure: reads a SessionAnalysis.
"""

from dataclasses import dataclass

import numpy as np

from wavelength_calibration.calibration_checks import FAIL, PASS, WARN, CheckResult

from .frame_names import EDGE_WALK

EDGE_CHECK_REGISTRY = []


@dataclass(frozen=True)
class EdgeCheckLimits:
    slope_range_nm_per_step: tuple = (-0.70, -0.25)   # measured -0.47 to -0.40 (720-920 nm)
    minimum_edges_per_centre: int = 3
    fit_rms_pass_nm: float = 0.15                      # 0.14 nm on 2026-11-18
    fit_rms_warn_nm: float = 0.30
    width_range_nm: tuple = (0.3, 1.5)                 # 0.70-0.94 nm
    axis_spread_warn_nm: float = 0.05                  # 0.022 nm in the 50 um frame
    minimum_axis_lines: int = 3
    axis_slit_warn_um: float = 100.0                   # axis references at about 50 um
    walk_slit_warn_um: float = 200.0                   # a narrower slit clips the band
    repeatability_warn_nm: float = 0.2                 # the 0.7 nm found between runs
    between_runs_warn_nm: float = 0.2
    step_size_fraction_range: tuple = (0.3, 2.0)       # of the mean single step
    backlash_warn_steps: float = 1.0
    count_shift_warn_steps: float = 25.0               # 1.6-8.7 steps on 2026-11-18


def edge_calibration_check(name):
    """Register a check: function(session_analysis, limits) -> CheckResult or None."""
    def register(function):
        EDGE_CHECK_REGISTRY.append((name, function))
        return function
    return register


def run_registered_checks(registry, analysis, limits):
    """Every check in a registry ([(name, function)]); one that raises is reported as a WARN,
    not hidden. Shared by the edge and the g2 pinhole checks (g2_checks.py)."""
    results = []
    for name, function in registry:
        try:
            result = function(analysis, limits)
        except Exception as error:
            result = CheckResult(name=name, verdict=WARN,
                                 summary=f'the check itself failed ({type(error).__name__}: '
                                         f'{error})')
        if result is not None:
            results.append(result)
    return results


def run_edge_checks(session_analysis, limits=EdgeCheckLimits()):
    """Every registered edge check."""
    return run_registered_checks(EDGE_CHECK_REGISTRY, session_analysis, limits)


@edge_calibration_check('frames on disk')
def check_frames_on_disk(session_analysis, limits):
    found = session_analysis.frames_found
    details = []
    if found.missing_frames:
        details.append(f'acquired but not found: {", ".join(found.missing_frames)}')
    if found.older_frames_present:
        details.append('more frames on disk than these logs acquired (the newest were taken): '
                       + ', '.join(found.older_frames_present))
    if found.unrecognised_names:
        details.append(f'not stage 1 frame names: {", ".join(found.unrecognised_names)}')
    if not details:
        return CheckResult('frames on disk', PASS,
                           f'all {len(found.records)} acquired frames found')
    return CheckResult(
        'frames on disk', FAIL if found.missing_frames else WARN,
        f'{len(found.missing_frames)} missing, {len(found.older_frames_present)} names with older '
        'frames', details,
        likely_causes=['the data directory is not the one the frames were saved to',
                       'an earlier session\'s frames were left in data/ under the same names'],
        what_to_try=['pass --data-directory pointing at the session\'s frames',
                     'move earlier sessions\' frames into their own folder'])


@edge_calibration_check('edges found in the walk')
def check_edges_found(session_analysis, limits):
    walk = [frame for frame in session_analysis.frames_of_kind(EDGE_WALK)
            if not frame.record.frame_name.is_edge_free]
    if not walk:
        return CheckResult('edges found in the walk', FAIL, 'no edge walk frames in these logs',
                           what_to_try=['include the stage1_edge_walk run log'])
    missing = [frame.record.name for frame in walk if frame.edge is None]
    counts = {}
    for frame in walk:
        if frame.edge is not None:
            counts[frame.record.frame_name.centre_nm] = \
                counts.get(frame.record.frame_name.centre_nm, 0) + 1
    thin = sorted(centre for centre in {frame.record.frame_name.centre_nm for frame in walk}
                  if counts.get(centre, 0) < limits.minimum_edges_per_centre)
    summary = f'{len(walk) - len(missing)} of {len(walk)} walk frames have an edge'
    if not missing:
        return CheckResult('edges found in the walk', PASS, summary)
    return CheckResult(
        'edges found in the walk', WARN, summary + (f'; centres with fewer than '
                                                    f'{limits.minimum_edges_per_centre}: {thin}'
                                                    if thin else ''),
        [f'no edge: {", ".join(missing)}'],
        likely_causes=['no light at that centre (lamp or camera range; 960 nm had none on '
                       '2026-11-18)', 'the edge is off the chip at that g1 offset'],
        what_to_try=['look at the frame; if the lamp does not reach there, drop that centre '
                     '(--centres when writing the run files)'])


@edge_calibration_check('edge moves with g1')
def check_edge_moves_with_g1(session_analysis, limits):
    low, high = limits.slope_range_nm_per_step
    out_of_range = [summary for summary in session_analysis.centres
                    if summary.slope_nm_per_step is None or
                    not low <= summary.slope_nm_per_step <= high]
    text = ', '.join(f'{summary.centre_nm}: {summary.slope_nm_per_step:+.3f}'
                     for summary in session_analysis.centres
                     if summary.slope_nm_per_step is not None)
    if not session_analysis.centres:
        return None
    if not out_of_range:
        return CheckResult('edge moves with g1', PASS,
                           f'slopes {low} to {high} nm/step at every centre ({text})')
    return CheckResult(
        'edge moves with g1', FAIL, f'{len(out_of_range)} centres outside {low} to {high} '
                                     'nm/step', [text],
        likely_causes=['stage 2\'s intermediate slit is in: its edge hides stage 1\'s, and the '
                       'edge hardly moves with g1 (2026-11-17)',
                       'the frames at that centre are not an edge walk'],
        what_to_try=['take the intermediate slit out and repeat the walk'])


@edge_calibration_check('calibration fit residual')
def check_fit_residual(session_analysis, limits):
    fit = session_analysis.calibration
    if fit is None:
        return CheckResult('calibration fit residual', FAIL, 'too few walk edges to fit')
    rms = fit.residual_rms
    worst = int(np.argmax(np.abs(fit.residuals)))
    summary = (f'{rms:.3f} nm rms over {len(fit.residuals)} frames (pass <= '
               f'{limits.fit_rms_pass_nm}, fail > {limits.fit_rms_warn_nm}); worst '
               f'{fit.labels[worst]} {fit.residuals[worst]:+.3f} nm')
    if rms <= limits.fit_rms_pass_nm:
        return CheckResult('calibration fit residual', PASS, summary)
    return CheckResult(
        'calibration fit residual', WARN if rms <= limits.fit_rms_warn_nm else FAIL, summary,
        likely_causes=['a centre without an axis reference (each TRIAX position is off by its '
                       'own amount)', 'a frame whose edge fit failed quietly',
                       'the lamp or the cards moved during the walk'],
        what_to_try=['take the axis references', 'look at that frame in edge_fits.png'])


@edge_calibration_check('axis references')
def check_axis_references(session_analysis, limits):
    centres = sorted({summary.centre_nm for summary in session_analysis.centres})
    references = session_analysis.axis_references
    missing = [centre for centre in centres if centre not in references or
               references[centre].correction_nm is None]
    details, verdict = [], PASS
    for centre, reference in sorted(references.items()):
        if reference.correction_nm is None:
            details.append(f'{centre} nm: no usable line')
            continue
        line_count = len(reference.lines_used)
        details.append(f'{centre} nm: correction {reference.correction_nm:+.3f} nm, spread '
                       f'{reference.spread_nm:.3f} nm over {line_count} lines, slit '
                       f'{reference.slit_width_um} um')
        if reference.spread_nm > limits.axis_spread_warn_nm or \
                line_count < limits.minimum_axis_lines or \
                (reference.slit_width_um or 0) > limits.axis_slit_warn_um:
            verdict = WARN
    if missing:
        verdict = WARN
    summary = (f'{len(centres) - len(missing)} of {len(centres)} centres corrected'
               + (f'; uncorrected: {missing}' if missing else ''))
    if verdict == PASS:
        return CheckResult('axis references', PASS, summary, details)
    return CheckResult(
        'axis references', verdict, summary, details,
        likely_causes=['no stage1_axis_references run log given, or it was not run',
                       'the slit was not closed to about 50 um for the Ar-Hg frames'],
        what_to_try=['run stage1_axis_references.txt with the Ar-Hg lamp and the slit at about '
                     '50 um, and pass its log too',
                     'uncorrected, each centre can be off by about 0.1-0.2 nm, more if the '
                     'TRIAX zero moved'])


@edge_calibration_check('slit width')
def check_slit_width(session_analysis, limits):
    widths = sorted({frame.record.slit_width_um
                     for frame in session_analysis.walk_frames_with_edges()
                     if frame.record.slit_width_um is not None})
    if not widths:
        return CheckResult('slit width', WARN, "no 'ren' in the walk's run log: width unknown",
                           what_to_try=['write the run files again (they now start with ren)'])
    if min(widths) < limits.walk_slit_warn_um:
        return CheckResult('slit width', WARN, f'walk slit {widths} um, below '
                                               f'{limits.walk_slit_warn_um} um',
                           likely_causes=['a narrow slit clips the band, by an amount that '
                                          'changes with wavelength (RAM-F5)'],
                           what_to_try=['open the slit to about 500 um for the walk'])
    return CheckResult('slit width', PASS, f'walk slit {widths} um')


@edge_calibration_check('edge width')
def check_edge_width(session_analysis, limits):
    low, high = limits.width_range_nm
    walk = session_analysis.walk_frames_with_edges()
    if not walk:
        return None
    widths = np.array([frame.edge.width_nm for frame in walk])
    outside = [frame.record.name for frame in walk if not low <= frame.edge.width_nm <= high]
    summary = f'{widths.min():.2f}-{widths.max():.2f} nm (expected {low}-{high})'
    if not outside:
        return CheckResult('edge width', PASS, summary)
    return CheckResult('edge width', WARN, summary, [f'outside: {", ".join(outside)}'],
                       likely_causes=['the aperture cards were opened up or removed',
                                      'a poor fit (look at edge_fits.png)'])


@edge_calibration_check('single steps')
def check_single_steps(session_analysis, limits):
    steps = session_analysis.single_steps
    if steps is None:
        return None
    sizes = np.abs(steps.step_sizes_nm)
    mean_size = float(np.mean(sizes))
    low, high = (fraction * mean_size for fraction in limits.step_size_fraction_range)
    odd = [index for index, size in enumerate(sizes) if not low <= size <= high]
    backlash = steps.backlash_steps
    summary = (f'{steps.slope_nm_per_step:+.4f} nm/step, residual {steps.residual_rms_nm:.3f} '
               f'nm rms; steps {sizes.min():.2f}-{sizes.max():.2f} nm (mean {mean_size:.2f})'
               + (f'; backlash {backlash:.2f} steps' if backlash is not None else ''))
    if not odd and (backlash is None or backlash <= limits.backlash_warn_steps):
        return CheckResult('single steps', PASS, summary)
    return CheckResult(
        'single steps', WARN, summary,
        [f'steps outside {low:.2f}-{high:.2f} nm: numbers {odd}'] if odd else [],
        likely_causes=['a step that did not move (lost) or moved twice',
                       'backlash above one step: a loose belt or coupling'],
        what_to_try=['repeat the single-step run; check the belt tension'])


@edge_calibration_check('repeatability')
def check_repeatability(session_analysis, limits):
    repeatability = session_analysis.repeatability
    if repeatability is None:
        return None
    details, worst = [], 0.0
    for visit_kind in ('still', 'triax', 'gratings'):
        spread = repeatability.spread_nm(visit_kind)
        if spread is None:
            continue
        details.append(f'{visit_kind}: spread {spread:.3f} nm over '
                       f'{len(repeatability.edges_by_visit_kind[visit_kind])} frames')
        worst = max(worst, spread)
    summary = f'largest spread {worst:.3f} nm (warn > {limits.repeatability_warn_nm})'
    if worst <= limits.repeatability_warn_nm:
        return CheckResult('repeatability', PASS, summary, details)
    return CheckResult(
        'repeatability', WARN, summary, details,
        likely_causes=['spread in the still frames: the lamp, the cards or temperature drifted',
                       'spread after the TRIAX alone moved: the TRIAX does not return to the '
                       'same angle (the frame\'s axis moves)',
                       'spread after the gratings alone moved: g1 does not return'],
        what_to_try=['the visit kind with the spread is the part to look at'])


@edge_calibration_check('between runs')
def check_between_runs(session_analysis, limits):
    offsets = []
    if session_analysis.single_steps is not None and \
            session_analysis.single_steps.offset_from_walk_nm is not None:
        offsets.append(('single steps', session_analysis.single_steps.offset_from_walk_nm))
    if session_analysis.repeatability is not None and \
            session_analysis.repeatability.offset_from_walk_nm is not None:
        offsets.append(('repeatability', session_analysis.repeatability.offset_from_walk_nm))
    if not offsets:
        return None
    text = ', '.join(f'{label} {offset:+.3f} nm' for label, offset in offsets)
    if all(abs(offset) <= limits.between_runs_warn_nm for _, offset in offsets):
        return CheckResult('between runs', PASS, f'other runs against the walk fit: {text}')
    return CheckResult(
        'between runs', WARN, f'other runs against the walk fit: {text} (warn > '
                              f'{limits.between_runs_warn_nm})',
        likely_causes=['the TRIAX or g1 did not return to the same place between runs (the '
                       'repeatability run says which)', 'drift between the runs'],
        what_to_try=['compare with the repeatability frames before applying'])


@edge_calibration_check('change from the master calibration')
def check_count_shift(session_analysis, limits):
    shifts = [(summary.centre_nm, summary.count_for_edge_at_centre - summary.master_count)
              for summary in session_analysis.centres
              if summary.count_for_edge_at_centre is not None and summary.master_count is not None]
    if not shifts:
        return None
    text = ', '.join(f'{centre}: {shift:+.1f}' for centre, shift in shifts)
    largest = max(abs(shift) for _, shift in shifts)
    if largest <= limits.count_shift_warn_steps:
        return CheckResult('change from the master calibration', PASS,
                           f'g1 count shifts {text} steps')
    return CheckResult(
        'change from the master calibration', WARN,
        f'largest g1 shift {largest:.1f} steps (warn > {limits.count_shift_warn_steps})', [text],
        likely_causes=['the g1 motor was re-homed or referenced since the master calibration',
                       'the frames are not where the logs say'],
        what_to_try=['check allmotors in the run log against the frames'])
