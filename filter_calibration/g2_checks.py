"""
Gates for the g2 pinhole calibration: is the measured g2 offset good enough to apply, and if
not, what is most likely wrong?

Same pattern as the edge checks (calibration_checks.py): every check is a function registered
with @g2_pointing_check, the registry is the only list, and the report and `fit-g2 --apply`
(which refuses on any FAIL) run whatever is registered. Limits live in G2CheckLimits. There is
no bench session yet, so the limits are first estimates; comments say what each is based on.

Pure: reads a G2SessionAnalysis.
"""

from dataclasses import dataclass

from wavelength_calibration.calibration_checks import FAIL, PASS, WARN, CheckResult

from .calibration_checks import check_frames_on_disk, run_registered_checks
from .g2_analysis import CROSS_CHECK_PINHOLE, REFERENCE_PINHOLE

G2_CHECK_REGISTRY = []
CHIP_WIDTH_NM = 79.0        # 1024 columns at 0.0774 nm


@dataclass(frozen=True)
class G2CheckLimits:
    minimum_frames_per_scan: int = 11
    centre_uncertainty_warn_steps: float = 0.3      # a tenth of the ~3 steps a 1 mm pinhole spans
    window_residual_warn: float = 0.08              # of the window's height: an uneven profile
    g1_mismatch_fail_steps: float = 0.5             # g1 not where sg puts it now
    band_margin_rows: float = 15.0                  # band kept this far inside the frame
    offset_spread_warn_steps: float = 1.0           # the band row held g2 to < 1 step (RAM-F5)
    cross_check_warn_steps: float = 0.5
    mismatch_warn_steps_across_chip: float = 1.0
    slit_warn_um: float = 200.0                     # as for the edge walk
    offset_warn_steps: float = 10.0


def g2_pointing_check(name):
    """Register a check: function(g2_session_analysis, limits) -> CheckResult or None."""
    def register(function):
        G2_CHECK_REGISTRY.append((name, function))
        return function
    return register


def run_g2_checks(session_analysis, limits=G2CheckLimits()):
    """Every registered g2 check."""
    return run_registered_checks(G2_CHECK_REGISTRY, session_analysis, limits)


def _label(scan):
    return f'{scan.pinhole} {scan.centre_nm} nm'


@g2_pointing_check('frames on disk')
def check_g2_frames_on_disk(session_analysis, limits):
    return check_frames_on_disk(session_analysis, limits)


@g2_pointing_check('scans found')
def check_scans_found(session_analysis, limits):
    if not session_analysis.scans:
        return CheckResult('scans found', FAIL, 'no g2 pinhole scan frames in these logs',
                           what_to_try=['pass the stage1_g2_pinhole run logs'])
    short = [_label(scan) for scan in session_analysis.scans
             if len(scan.records) < limits.minimum_frames_per_scan]
    text = ', '.join(f'{_label(scan)} ({len(scan.records)} frames)'
                     for scan in session_analysis.scans)
    if session_analysis.reference_pinhole != REFERENCE_PINHOLE:
        return CheckResult('scans found', WARN, text,
                           ['no scans with the pinhole on stage 2\'s entrance axis: the '
                            'correction comes from the stage 1 exit scans'],
                           likely_causes=['only the cross-check file was run'],
                           what_to_try=['run stage1_g2_pinhole_stage2.txt as well'])
    if short:
        return CheckResult('scans found', WARN, text, [f'fewer than '
                                                      f'{limits.minimum_frames_per_scan} '
                                                      f'frames: {short}'],
                           likely_causes=['a scan was stopped early'])
    return CheckResult('scans found', PASS, text)


@g2_pointing_check('window inside the scan')
def check_window_inside_scan(session_analysis, limits):
    failed = []
    for scan in session_analysis.scans:
        if scan.band_track is None:
            failed.append(f'{_label(scan)}: no band in the frames')
        elif scan.total_fit is None:
            failed.append(f'{_label(scan)}: no window to fit')
        elif not scan.total_fit.peak_inside_scan:
            failed.append(f'{_label(scan)}: the light does not fall to half at both ends '
                          f'(centre {scan.total_fit.centre_count:.1f})')
    if not session_analysis.scans:
        return None
    if not failed:
        return CheckResult('window inside the scan', PASS,
                           'the light rises and falls within every scan')
    return CheckResult(
        'window inside the scan', FAIL, f'{len(failed)} scans without a whole window', failed,
        likely_causes=['g2 is further off than the scan reaches',
                       'the pinhole is not on the beam\'s axis (vertically, or the relay)',
                       'the camera ROI cuts the band as it moves along the slit'],
        what_to_try=['look at g2_pinhole.png; widen the scan (plan --g2-half-range)',
                     'with the laser, check the beam passes the pinhole'])


@g2_pointing_check('window fit')
def check_window_fit(session_analysis, limits):
    details, verdict = [], PASS
    for scan in session_analysis.scans:
        fit = scan.total_fit
        if fit is None or scan.centre_count is None:
            continue
        details.append(f'{_label(scan)}: centre {scan.centre_count:.2f} +/- '
                       f'{scan.centre_uncertainty:.2f} steps, residual '
                       f'{fit.residual_fraction:.3f} of the height')
        if scan.centre_uncertainty > limits.centre_uncertainty_warn_steps or \
                fit.residual_fraction > limits.window_residual_warn:
            verdict = WARN
    if not details:
        return None
    if verdict == PASS:
        return CheckResult('window fit', PASS, 'every centre found to within '
                                               f'{limits.centre_uncertainty_warn_steps} steps',
                           details)
    return CheckResult(
        'window fit', WARN, 'a centre is uncertain or a profile is uneven', details,
        likely_causes=['the profile is clipped on one side by another aperture (relay mirror '
                       'edge, stage 2 port): that moves the centre',
                       'too little light (exposure) or the lamp drifted during the scan'],
        what_to_try=['look at the profile in g2_pinhole.png: it should be symmetric',
                     'repeat the scan without the pinhole: a flat top means nothing else clips'])


@g2_pointing_check('g1 where the calibration puts it')
def check_g1_position(session_analysis, limits):
    mismatched = []
    for scan in session_analysis.scans:
        if scan.master_g1_count is None:
            continue
        for g1_count in scan.g1_counts:
            if abs(g1_count - round(scan.master_g1_count)) > limits.g1_mismatch_fail_steps:
                mismatched.append(f'{_label(scan)}: g1 {g1_count}, the calibration in use puts '
                                  f'{round(scan.master_g1_count)}')
    if not session_analysis.scans:
        return None
    if not mismatched:
        return CheckResult('g1 where the calibration puts it', PASS,
                           'every scan was taken with g1 at sg <centre> of the calibration in '
                           'use')
    return CheckResult(
        'g1 where the calibration puts it', FAIL,
        'a scan was taken with another g1 calibration', mismatched,
        likely_causes=['the g1 calibration was applied (or changed) after the scan',
                       'g1 was moved by hand during the scan'],
        what_to_try=['apply the g1 calibration first, then scan g2'])


@g2_pointing_check('band on the sensor')
def check_band_on_sensor(session_analysis, limits):
    outside = []
    for scan in session_analysis.scans:
        track = scan.band_track
        if track is None:
            continue
        margin = limits.band_margin_rows
        if track.first_row < margin or track.last_row > scan.frame_height - margin:
            outside.append(f'{_label(scan)}: band rows {track.first_row:.0f}-'
                           f'{track.last_row:.0f} of {scan.frame_height}')
    if not session_analysis.scans:
        return None
    if not outside:
        return CheckResult('band on the sensor', PASS,
                           'the band stays inside the frame over every scan')
    return CheckResult('band on the sensor', WARN, 'the band leaves the frame', outside,
                       likely_causes=['a camera ROI is set', 'the scan is wider than needed'],
                       what_to_try=['read the whole sensor for the scan'])


@g2_pointing_check('offsets agree between centres')
def check_offsets_agree(session_analysis, limits):
    proposed = session_analysis.proposed
    if proposed is None:
        return CheckResult('offsets agree between centres', FAIL, 'no g2 offset could be '
                                                                  'measured')
    scans = [scan for scan in session_analysis.scans_at(proposed.pinhole)
             if scan.offset_steps is not None]
    text = ', '.join(f'{scan.centre_nm}: {scan.offset_steps:+.2f}' for scan in scans)
    summary = (f'offsets {text} steps; spread {proposed.spread_steps:.2f} (warn > '
               f'{limits.offset_spread_warn_steps})')
    if len(scans) < 2:
        return CheckResult('offsets agree between centres', WARN, summary,
                           ['one centre only: the offset cannot be checked across wavelength'],
                           what_to_try=['scan at three centres (the default)'])
    if proposed.spread_steps <= limits.offset_spread_warn_steps:
        return CheckResult('offsets agree between centres', PASS, summary)
    return CheckResult(
        'offsets agree between centres', WARN, summary,
        likely_causes=['the g1:g2 pairing changes with wavelength, so one constant is not '
                       'enough', 'a scan whose profile is clipped (window fit)'],
        what_to_try=['compare with the band row across the edge walk',
                     'apply only if the spread is understood'])


@g2_pointing_check('g1 and g2 matched across the chip')
def check_mismatch_across_chip(session_analysis, limits):
    slopes = [(scan, scan.mismatch_steps_per_nm) for scan in session_analysis.scans
              if scan.mismatch_steps_per_nm is not None]
    if not slopes:
        return None
    text = ', '.join(f'{_label(scan)}: {slope:+.3f}' for scan, slope in slopes)
    worst = max(abs(slope) for _, slope in slopes) * CHIP_WIDTH_NM / 2
    summary = (f'block centres change by up to {worst:.2f} steps over half the chip ({text} '
               'steps/nm)')
    if worst <= limits.mismatch_warn_steps_across_chip:
        return CheckResult('g1 and g2 matched across the chip', PASS, summary)
    return CheckResult(
        'g1 and g2 matched across the chip', WARN, summary,
        likely_causes=['g2 does not exactly undo g1\'s dispersion: wavelengths leave stage 1 '
                       'in slightly different directions'],
        what_to_try=['the g2 offset is still right at the sg wavelength; note the slope for '
                     'the pairing'])


@g2_pointing_check('stage 1 exit cross-check')
def check_cross_check(session_analysis, limits):
    reference = {scan.centre_nm: scan for scan in session_analysis.scans_at(REFERENCE_PINHOLE)}
    pairs = [(reference[scan.centre_nm], scan)
             for scan in session_analysis.scans_at(CROSS_CHECK_PINHOLE)
             if scan.centre_nm in reference and scan.offset_steps is not None
             and reference[scan.centre_nm].offset_steps is not None]
    if not pairs:
        return None
    differences = [(stage2.centre_nm, stage1.offset_steps - stage2.offset_steps)
                   for stage2, stage1 in pairs]
    text = ', '.join(f'{centre}: {difference:+.2f}' for centre, difference in differences)
    largest = max(abs(difference) for _, difference in differences)
    summary = f'stage 1 exit minus stage 2 entrance: {text} steps'
    if largest <= limits.cross_check_warn_steps:
        return CheckResult('stage 1 exit cross-check', PASS, summary)
    return CheckResult(
        'stage 1 exit cross-check', WARN, summary,
        likely_causes=['the relay mirrors do not carry stage 1\'s exit axis onto stage 2\'s '
                       'entrance axis', 'a pinhole was not centred on its port'],
        what_to_try=['realign the relay with the laser through both pinholes, then scan again'])


@g2_pointing_check('slit width')
def check_g2_slit_width(session_analysis, limits):
    widths = sorted({scan.slit_width_um for scan in session_analysis.scans
                     if scan.slit_width_um is not None})
    if not session_analysis.scans:
        return None
    if not widths:
        return CheckResult('slit width', WARN, "no 'ren' in the run logs: width unknown")
    if min(widths) < limits.slit_warn_um:
        return CheckResult('slit width', WARN, f'slit {widths} um, below {limits.slit_warn_um} um',
                           likely_causes=['a narrow slit clips the band'],
                           what_to_try=['open the slit to about 500 um, as for the edge walk'])
    return CheckResult('slit width', PASS, f'slit {widths} um')


@g2_pointing_check('size of the correction')
def check_offset_size(session_analysis, limits):
    proposed = session_analysis.proposed
    if proposed is None:
        return None
    summary = (f'g2 offset {proposed.offset_steps:+.2f} +/- {proposed.offset_uncertainty:.2f} '
               f'steps (warn beyond +/-{limits.offset_warn_steps})')
    if abs(proposed.offset_steps) <= limits.offset_warn_steps:
        return CheckResult('size of the correction', PASS, summary)
    return CheckResult(
        'size of the correction', WARN, summary,
        likely_causes=['g2 was re-homed or referenced since the calibration',
                       'the pinhole is not where the relay sends the beam'],
        what_to_try=['check with the laser that the beam passes the pinhole at sg'])

