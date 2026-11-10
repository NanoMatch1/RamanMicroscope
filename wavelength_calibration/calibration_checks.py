"""
Gates: is this calibration good enough to use, and if not, what is most likely wrong?

Every check is a function registered with @calibration_check. The registry is
the only list of checks: the fit report, `speccalapply` (which refuses on any
FAIL) and `speccalzero` all run whatever is registered for their kind
('fit' or 'zero'). Adding a check means writing one decorated function here.

A check returns a CheckResult (or None when it does not apply) with:
- verdict: PASS, WARN (usable, but look) or FAIL (do not apply);
- summary: one line, with the measured number and the limit;
- details: the evidence, e.g. which frames or lines;
- likely_causes and what_to_try: written for whoever is at the instrument.

Most checks read the residual decomposition (decompose_fit_residuals): the
fit residual of every line position split into
- the frame offset: the mean residual of the frame (walk, TRIAX position).
  Shared by all lines in the frame, so it belongs to the TRIAX (drive shape
  the model cannot follow, positioning error) and not to the CCD axis;
- the within-frame residual: what is left. It belongs to the CCD axis, the
  line identification, the peak fits or the table wavelengths.
On the 2026-11-10 data, correctly identified, the within-frame part is
~0.003-0.008 nm rms and the TRIAX part ~0.1 nm; a misidentified line is
~1 nm. Limits live in CheckLimits.

Pure: nothing here touches hardware or files.
"""

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from .line_identification import NO_LINES
from .wavelength_axis_model import largest_axis_difference_nm

PASS, WARN, FAIL = 'PASS', 'WARN', 'FAIL'
_SEVERITY = {PASS: 0, WARN: 1, FAIL: 2}


def _worse(first_verdict, second_verdict):
    if _SEVERITY[first_verdict] >= _SEVERITY[second_verdict]:
        return first_verdict
    return second_verdict


@dataclass
class CheckLimits:
    """Thresholds of the gates. WARN marks something to look at; FAIL blocks applying."""

    ambiguity_ratio_warn: float = 0.7        # runner-up explains this share of the winner's peaks
    ambiguity_ratio_fail: float = 0.9
    prior_offset_warn_fraction: float = 0.7  # calibration in use off by this fraction of the search
    identified_fraction_fail: float = 0.5    # of the frames that show lines
    within_frame_rms_warn_nm: float = 0.01
    within_frame_rms_fail_nm: float = 0.02
    line_bias_warn_nm: float = 0.01
    triax_shape_rms_warn_nm: float = 0.03
    triax_shape_rms_fail_nm: float = 0.15
    walk_offset_spread_warn_nm: float = 0.03
    walk_repeatability_warn_nm: float = 0.03
    minimum_sightings_per_line: int = 3
    saturated_fraction_warn: float = 0.2     # of reference-line sightings lost to saturation
    sensor_temperature_warn_c: float = -30.0
    sensor_temperature_drift_warn_c: float = 2.0
    change_from_current_warn_nm: float = 1.0
    zero_spread_warn_steps: float = 3.0
    zero_spread_fail_steps: float = 10.0
    zero_spread_fail_steps_without_table: float = 30.0  # without a TRIAX table the drive adds ~20
    large_zero_shift_warn_steps: float = 500.0


@dataclass
class CheckResult:
    name: str
    verdict: str
    summary: str
    details: list = field(default_factory=list)
    likely_causes: list = field(default_factory=list)
    what_to_try: list = field(default_factory=list)


@dataclass
class CalibrationEvidence:
    """Everything the checks look at; built by promotion (fit) or triax_zero (re-zero)."""

    kind: str                     # 'fit' or 'zero'
    walk_labels: list             # one per walk (file name), in time order
    identifications: list         # WalkIdentification per walk
    instruments: list             # each walk's 'instrument' metadata dict ({} for old files)
    frame_conditions: list        # per walk: list of per-frame conditions dicts
    format_versions: list
    current_model: object = None
    fit: object = None            # WavelengthAxisFit, None if the fit could not be made
    fit_error: str = ''
    fit_options: dict = field(default_factory=dict)
    running_in_simulate_mode: bool = False
    zero: object = None           # triax_zero.ZeroMeasurement for kind 'zero'
    number_of_pixels: int = 1024


@dataclass
class _RegisteredCheck:
    name: str
    applies_to: tuple
    function: object


CHECK_REGISTRY = []


def calibration_check(name, applies_to=('fit',)):
    """Register a check. `applies_to`: 'fit' (speccalfit/speccalapply), 'zero' (speccalzero)."""
    def register(function):
        CHECK_REGISTRY.append(_RegisteredCheck(name=name, applies_to=tuple(applies_to),
                                               function=function))
        return function
    return register


def run_checks(evidence, limits=None):
    """Run every registered check for this kind of evidence. A check that raises is reported."""
    limits = limits or CheckLimits()
    results = []
    for check in CHECK_REGISTRY:
        if evidence.kind not in check.applies_to:
            continue
        try:
            result = check.function(evidence, limits)
        except Exception as error:  # a broken check must not hide the others, nor pass silently
            result = CheckResult(
                name=check.name, verdict=WARN,
                summary=f"the check itself failed ({type(error).__name__}: {error})",
                likely_causes=["a bug in the check, or data it does not expect"],
                what_to_try=["report this with the walk files"])
        if result is not None:
            results.append(result)
    return results


def any_failed(results):
    return any(result.verdict == FAIL for result in results)


def format_check_report(results):
    """Text lines: a verdict per check, then the evidence and advice for every WARN and FAIL."""
    if not results:
        return ["gate checks: none applicable"]
    counts = {verdict: sum(result.verdict == verdict for result in results)
              for verdict in (PASS, WARN, FAIL)}
    lines = [f"gate checks: {counts[FAIL]} FAIL, {counts[WARN]} WARN, {counts[PASS]} PASS"]
    for result in sorted(results, key=lambda result: -_SEVERITY[result.verdict]):
        lines.append(f"  [{result.verdict}] {result.name}: {result.summary}")
        if result.verdict == PASS:
            continue
        lines += [f"         {detail}" for detail in result.details]
        lines += [f"         likely cause: {cause}" for cause in result.likely_causes]
        lines += [f"         try: {action}" for action in result.what_to_try]
    return lines


# -- residual decomposition --------------------------------------------------------------------

@dataclass
class ResidualDecomposition:
    frame_offsets_nm: dict      # (walk, steps) -> mean fit residual of the frame
    within_frame: list          # (walk, steps, line name, pixel, within-frame residual nm)
    within_frame_rms_nm: float
    triax_shape_rms_nm: float
    position_offsets_nm: dict   # steps -> mean frame offset over the walks


def decompose_fit_residuals(fit):
    """Split the residuals into frame offsets (TRIAX) and within-frame residuals (CCD axis)."""
    groups = fit.observation_groups or ['all'] * len(fit.observations)
    by_frame = defaultdict(list)
    for group, observation, residual in zip(groups, fit.observations, fit.residuals_nm):
        by_frame[(group, observation.triax_steps)].append((observation, float(residual)))
    frame_offsets, within_frame, squared_sum, degrees_of_freedom = {}, [], 0.0, 0
    for (walk, steps), entries in by_frame.items():
        offset = float(np.mean([residual for _, residual in entries]))
        frame_offsets[(walk, steps)] = offset
        if len(entries) >= 2:
            for observation, residual in entries:
                within_frame.append((walk, steps, observation.line_name.split(' (')[0],
                                     observation.centre_pixel, residual - offset))
                squared_sum += (residual - offset) ** 2
            degrees_of_freedom += len(entries) - 1
    by_position = defaultdict(list)
    for (_, steps), offset in frame_offsets.items():
        by_position[steps].append(offset)
    within_frame_rms = np.sqrt(squared_sum / degrees_of_freedom) if degrees_of_freedom else np.nan
    triax_shape_rms = np.sqrt(np.mean(np.square(list(frame_offsets.values())))) if frame_offsets \
        else np.nan
    return ResidualDecomposition(
        frame_offsets_nm=frame_offsets, within_frame=within_frame,
        within_frame_rms_nm=float(within_frame_rms), triax_shape_rms_nm=float(triax_shape_rms),
        position_offsets_nm={steps: float(np.mean(values))
                             for steps, values in sorted(by_position.items())})


def _nm_per_step(evidence):
    model = evidence.fit.model if evidence.fit is not None else evidence.current_model
    if model is None:
        return 0.0093
    steps = [o.triax_steps for o in evidence.fit.observations] if evidence.fit is not None \
        else [100000]
    return abs(model.nm_per_triax_step(float(np.median(steps))))


def _frames_with_lines(identification):
    return [frame for frame in identification.frames if frame.status != NO_LINES]


def _camera_setting(instrument, name):
    return instrument.get('camera', {}).get(name)


# -- checks: data provenance -------------------------------------------------------------------

@calibration_check('walk data', applies_to=('fit', 'zero'))
def check_walk_data(evidence, limits):
    """Simulated walks in a real calibration, walks without metadata, mixed software versions."""
    simulated = [label for label, instrument in zip(evidence.walk_labels, evidence.instruments)
                 if instrument.get('simulate') is True]
    unknown = [label for label, version in zip(evidence.walk_labels, evidence.format_versions)
               if version < 2]
    if simulated and not evidence.running_in_simulate_mode:
        return CheckResult(
            'walk data', FAIL,
            f"{len(simulated)} walk(s) were recorded in SIMULATE mode: {', '.join(simulated)}",
            likely_causes=["a simulate-mode or test session saved its walk in the data folder"],
            what_to_try=["leave those files out ('speccalreset', then 'speccal' again, or give "
                         "'speccalfit' the real files only)"])
    commits = {instrument.get('software', {}).get('commit') for instrument in evidence.instruments
               if instrument.get('software')}
    details, verdict = [], PASS
    if unknown:
        verdict = WARN
        details.append(f"{len(unknown)} walk(s) predate walk metadata (format 1): simulate mode, "
                       "exposure, sensor temperature and software version are unknown for "
                       f"{', '.join(unknown)}")
    if len(commits) > 1:
        verdict = WARN
        details.append(f"walks were taken with different software versions: "
                       f"{sorted(map(str, commits))}")
    if verdict == PASS:
        return CheckResult('walk data', PASS, "walks recorded on the instrument, metadata complete")
    return CheckResult('walk data', verdict, "walk metadata incomplete or mixed", details=details,
                       likely_causes=["walks from before 2026-11-11, or across a software update"],
                       what_to_try=["for a calibration you will rely on, take fresh walks"])


@calibration_check('instrument conditions', applies_to=('fit', 'zero'))
def check_instrument_conditions(evidence, limits):
    """Sensor temperature (dark current, drift) and settings that changed between walks."""
    temperatures = [conditions.get('sensor_temperature_c') for walk in evidence.frame_conditions
                    for conditions in walk if conditions.get('sensor_temperature_c') is not None]
    exposures = {_camera_setting(instrument, 'exposure_s') for instrument in evidence.instruments
                 if _camera_setting(instrument, 'exposure_s') is not None}
    if not temperatures and not exposures:
        return None
    details, causes, actions = [], [], []
    if temperatures:
        warmest, spread = max(temperatures), float(np.ptp(temperatures))
        details.append(f"sensor temperature {min(temperatures):.1f} to {warmest:.1f} C")
        if warmest > limits.sensor_temperature_warn_c:
            causes.append(f"the CCD was warmer than {limits.sensor_temperature_warn_c:.0f} C: "
                          "more dark current, and the camera may still have been cooling (the chip "
                          "moves slightly as it cools)")
            actions.append("wait until the sensor is below -30 C before walking "
                           "('checkcamtemp' or the GUI)")
        if spread > limits.sensor_temperature_drift_warn_c:
            causes.append(f"the sensor temperature changed by {spread:.1f} C during the walk(s)")
            actions.append("let the camera settle before calibrating")
    if len(exposures) > 1:
        details.append(f"exposure times differ between walks: {sorted(exposures)} s")
    verdict = WARN if causes else PASS
    summary = "camera conditions stable" if verdict == PASS else "camera conditions need a look"
    return CheckResult('instrument conditions', verdict, summary, details=details,
                       likely_causes=causes, what_to_try=actions)


# -- checks: identification --------------------------------------------------------------------

@calibration_check('line identification', applies_to=('fit', 'zero'))
def check_line_identification(evidence, limits):
    """Is the pattern match unambiguous, and was the calibration in use within the search range?"""
    details, verdict, causes, actions = [], PASS, [], []
    for label, identification in zip(evidence.walk_labels, evidence.identifications):
        if not np.isfinite(identification.trend_offset_nm):
            continue  # one-line (external) walk: no pattern to match
        ratio = identification.ambiguity_ratio
        offset = identification.trend_offset_nm
        details.append(f"{label}: {identification.trend_score:.0f} of "
                       f"{identification.strong_peak_total} strong peaks explained; next-best "
                       f"identification explains {identification.runner_up_score:.0f} "
                       f"(ratio {ratio:.2f}); calibration in use off by {offset:+.2f} nm")
        if ratio >= limits.ambiguity_ratio_fail:
            verdict = FAIL
        elif ratio >= limits.ambiguity_ratio_warn:
            verdict = _worse(verdict, WARN)
        search = identification.settings.search_half_width_nm
        if abs(offset) > limits.prior_offset_warn_fraction * search:
            verdict = _worse(verdict, FAIL if abs(offset) >= search - 0.5 else WARN)
            causes.append(f"the calibration in use is off by {offset:+.1f} nm, near the "
                          f"+/-{search:g} nm search limit: the TRIAX zero may have moved a long "
                          "way, or the wrong grating is selected")
            actions.append("check the TRIAX grating, then run 'speccalzero' or widen the search")
    if verdict != PASS and not causes:
        causes = ["two different line identifications fit the spectra nearly as well: too few "
                  "lines per frame, a different lamp, or strong lines missing from the table "
                  "(see 'unexplained peaks')"]
        actions = ["check the lamp is the Ar-Hg lamp and well aligned onto the entrance slit; a "
                   "longer exposure shows more lines (keep the brightest below saturation)"]
    summary = {PASS: "each walk matches the lamp pattern one way only",
               WARN: "a second identification fits nearly as well",
               FAIL: "the identification is ambiguous or out of range"}[verdict]
    return CheckResult('line identification', verdict, summary, details=details,
                       likely_causes=causes, what_to_try=actions)


@calibration_check('frames identified', applies_to=('fit', 'zero'))
def check_frames_identified(evidence, limits):
    """How many frames with lines were identified, and why the others were not."""
    details, worst_fraction = [], 1.0
    for label, identification in zip(evidence.walk_labels, evidence.identifications):
        with_lines = _frames_with_lines(identification)
        if not with_lines:
            details.append(f"{label}: no frame shows lamp lines")
            worst_fraction = 0.0
            continue
        identified = [frame for frame in with_lines if frame.identified]
        worst_fraction = min(worst_fraction, len(identified) / len(with_lines))
        details.append(f"{label}: {len(identified)} of {len(with_lines)} frames with lines "
                       "identified")
        details += [f"  {frame.summary()}" for frame in with_lines if not frame.identified]
    if worst_fraction < limits.identified_fraction_fail:
        verdict = FAIL
    elif worst_fraction < 1.0:
        verdict = WARN
    else:
        verdict = PASS
    causes, actions = [], []
    if verdict != PASS:
        causes = ["INCONSISTENT: one line in the frame is far off the others' map (a blend, a weak "
                  "peak, or a misidentified line); the frame's notes name it",
                  "NOT IDENTIFIED: strong peaks no listed line explains (see 'unexplained peaks')",
                  "TOO FEW LINES: frames at the walk ends with one usable line on the chip"]
        actions = ["a few unidentified frames at the walk ends are harmless; many in the middle "
                   "are not: check the lamp and the spectra in the walk file"]
    return CheckResult('frames identified', verdict,
                       f"worst walk: {worst_fraction:.0%} of frames with lines identified "
                       f"(FAIL below {limits.identified_fraction_fail:.0%})",
                       details=details, likely_causes=causes, what_to_try=actions)


@calibration_check('unexplained peaks', applies_to=('fit', 'zero'))
def check_unexplained_peaks(evidence, limits):
    """Strong peaks no listed line explains: a line missing from the table, or something else."""
    sightings = []
    for identification in evidence.identifications:
        for frame in identification.frames:
            sightings += [(wavelength, peak.height_counts)
                          for peak, wavelength in frame.unexplained_strong_peaks]
    if not sightings:
        return CheckResult('unexplained peaks', PASS, "every strong peak is a listed line")
    clusters = []
    for wavelength, height in sorted(sightings):
        if clusters and wavelength - clusters[-1][-1][0] < 0.3:
            clusters[-1].append((wavelength, height))
        else:
            clusters.append([(wavelength, height)])
    details = [f"~{np.mean([entry[0] for entry in cluster]):.2f} nm, seen in {len(cluster)} "
               f"frame(s), up to {max(entry[1] for entry in cluster):.0f} counts"
               for cluster in clusters]
    return CheckResult(
        'unexplained peaks', WARN,
        f"{len(sightings)} strong peak sighting(s) at {len(clusters)} wavelength(s) match no "
        "listed line", details=details,
        likely_causes=["a lamp line missing from reference_lines (NIST lists every Ar I / Hg I "
                       "line; also check second order: half the wavelength)",
                       "a different or contaminated lamp, room light, or a laser at the TRIAX",
                       "if the peak moves differently from the lamp lines: a ghost or reflection"],
        what_to_try=["look the wavelength up in the NIST Atomic Spectra Database (air wavelengths) "
                     "and add the line to reference_lines.py as identification-only"])


# -- checks: the fit ---------------------------------------------------------------------------

@calibration_check('fit made', applies_to=('fit',))
def check_fit_made(evidence, limits):
    if evidence.fit is not None:
        return None
    return CheckResult('fit made', FAIL, f"no fit: {evidence.fit_error}",
                       likely_causes=["too few identified line positions ('frames identified')"],
                       what_to_try=["fix what the other checks report, then walk again"])


@calibration_check('CCD axis (within-frame)', applies_to=('fit',))
def check_within_frame(evidence, limits):
    """Lines in one frame must agree with the CCD axis: misidentification, blends, chip model."""
    if evidence.fit is None:
        return None
    decomposition = decompose_fit_residuals(evidence.fit)
    rms = decomposition.within_frame_rms_nm
    if not np.isfinite(rms):
        return None
    if rms > limits.within_frame_rms_fail_nm:
        verdict = FAIL
    elif rms > limits.within_frame_rms_warn_nm:
        verdict = WARN
    else:
        verdict = PASS
    summary = (f"lines in the same frame agree to {rms:.4f} nm rms "
               f"(WARN > {limits.within_frame_rms_warn_nm}, "
               f"FAIL > {limits.within_frame_rms_fail_nm} nm)")
    if verdict == PASS:
        return CheckResult('CCD axis (within-frame)', PASS, summary)
    worst = sorted(decomposition.within_frame, key=lambda entry: -abs(entry[4]))[:5]
    details = [f"{name} at TRIAX {steps}, pixel {pixel:.0f} ({walk}): {residual:+.4f} nm"
               for walk, steps, name, pixel, residual in worst]
    causes, actions = [], []
    pixel_offsets = np.array([entry[3] for entry in decomposition.within_frame]) \
        - evidence.number_of_pixels / 2
    residuals = np.array([entry[4] for entry in decomposition.within_frame])
    follows_square = abs(np.corrcoef(pixel_offsets ** 2, residuals)[0, 1]) > 0.5
    if not evidence.fit_options.get('curvature') and follows_square:
        causes.append("the residuals follow (pixel - centre)^2: the dispersion curvature across "
                      "the chip is not being fitted")
        actions.append("fit with 'curvature' (speccalfit curvature triaxorder=3)")
    causes += ["a misidentified or blended line (large residuals on one line: see 'line bias')",
               "saturated or nearly saturated peaks (flattened tops shift the fitted centre)",
               "the slit image tilted on the chip with the row band moving between frames"]
    actions.append("look at the worst lines above in the walk file's spectra")
    return CheckResult('CCD axis (within-frame)', verdict, summary, details=details,
                       likely_causes=causes, what_to_try=actions)


@calibration_check('line bias', applies_to=('fit',))
def check_line_bias(evidence, limits):
    """A line off the others in every frame: wrong table value, a blend, or another species."""
    if evidence.fit is None:
        return None
    by_line = defaultdict(list)
    for _, _, name, _, residual in decompose_fit_residuals(evidence.fit).within_frame:
        by_line[name].append(residual)
    biased = []
    for name, residuals in by_line.items():
        if len(residuals) < 3:
            continue
        mean = float(np.mean(residuals))
        standard_error = float(np.std(residuals, ddof=1) / np.sqrt(len(residuals)))
        if abs(mean) > limits.line_bias_warn_nm and abs(mean) > 3 * standard_error:
            biased.append(f"{name}: {mean:+.4f} +/- {standard_error:.4f} nm over "
                          f"{len(residuals)} frames")
    if not biased:
        return CheckResult('line bias', PASS,
                           f"no line sits more than {limits.line_bias_warn_nm} nm off the others")
    return CheckResult(
        'line bias', WARN, f"{len(biased)} line(s) sit consistently off the others",
        details=biased,
        likely_causes=["the table wavelength is wrong (compare with NIST, air wavelengths)",
                       "an unlisted line blends with it and pulls its centre",
                       "it comes from another species that lights the slit differently (mercury on "
                       "this lamp sits ~0.05 nm off the argon lines)"],
        what_to_try=["if it persists across walks, mark the line identification-only in "
                     "reference_lines.py"])


def triax_wavelengths_by_position(fit):
    """{TRIAX steps: wavelength on the reference pixel, averaged over walks}: the TRIAX measured."""
    by_position = defaultdict(list)
    for (walk, steps), offset in decompose_fit_residuals(fit).frame_offsets_nm.items():
        by_position[steps].append(float(fit.model.triax_wavelength(steps)) + offset
                                  + fit.group_offsets_nm.get(walk, 0.0))
    return {steps: float(np.mean(values)) for steps, values in sorted(by_position.items())}


def triax_rms_by_polynomial_order(fit, highest_order=5):
    """{order: rms nm of the measured TRIAX positions about a polynomial of that order in steps}."""
    by_position = triax_wavelengths_by_position(fit)
    steps = np.array(list(by_position), dtype=float)
    wavelengths = np.array(list(by_position.values()))
    scaled = (steps - steps.mean()) / (np.ptp(steps) or 1.0)
    rms_by_order = {}
    for order in range(1, min(highest_order, len(steps) - 2) + 1):
        polynomial_values = np.polyval(np.polyfit(scaled, wavelengths, order), scaled)
        rms_by_order[order] = float(np.sqrt(np.mean((wavelengths - polynomial_values) ** 2)))
    return rms_by_order


@calibration_check('TRIAX shape', applies_to=('fit',))
def check_triax_shape(evidence, limits):
    """Frame offsets: what the TRIAX polynomial does not follow (drive shape, positioning)."""
    if evidence.fit is None:
        return None
    decomposition = decompose_fit_residuals(evidence.fit)
    rms = decomposition.triax_shape_rms_nm
    if rms > limits.triax_shape_rms_fail_nm:
        verdict = FAIL
    elif rms > limits.triax_shape_rms_warn_nm:
        verdict = WARN
    else:
        verdict = PASS
    summary = (f"frame offsets about the TRIAX polynomial {rms:.3f} nm rms "
               f"(WARN > {limits.triax_shape_rms_warn_nm}, "
               f"FAIL > {limits.triax_shape_rms_fail_nm} nm)")
    if verdict == PASS:
        return CheckResult('TRIAX shape', PASS, summary)
    largest = sorted(decomposition.position_offsets_nm.items(), key=lambda item: -abs(item[1]))[:4]
    details = [f"TRIAX {steps}: {offset:+.3f} nm (~{offset / _nm_per_step(evidence):+.1f} steps)"
               for steps, offset in largest]
    order_rms = triax_rms_by_polynomial_order(evidence.fit)
    details.append("measured TRIAX positions about a polynomial of order "
                   + ", ".join(f"{order}: {value:.3f} nm" for order, value in order_rms.items()))
    current_order = evidence.fit_options.get('triax_polynomial_order', 1)
    best = min(order_rms.values()) if order_rms else rms
    suggested = min((order for order, value in order_rms.items() if value <= 1.25 * best + 0.005),
                    default=None)
    causes, actions = [], []
    if suggested is not None and suggested > current_order:
        steps = sorted(decomposition.position_offsets_nm)
        causes.append(f"the TRIAX polynomial (order {current_order}) is too stiff for this range: "
                      f"order {suggested} leaves {order_rms[suggested]:.3f} nm")
        actions.append(f"speccalfit curvature triaxorder={suggested} (orders above 3 swing outside "
                       f"the walked range, TRIAX {steps[0]}..{steps[-1]}: do not use the axis "
                       "beyond it)")
    causes.append("what no polynomial follows is the TRIAX drive itself (2026-11-10: ~0.1 nm from "
                  "one calibration position to the next, the same in every walk); between "
                  "calibration positions the axis is off by about this much")
    if len(evidence.walk_labels) > 1:
        causes.append("if the offsets differ from walk to walk instead (see 'walk agreement'), "
                      "the TRIAX is not returning to the same place: backlash or lost steps")
    return CheckResult('TRIAX shape', verdict, summary, details=details, likely_causes=causes,
                       what_to_try=actions)


def _walk_departures(by_position, walk):
    """[(steps, this walk's frame offset minus the other walks' mean)] where others measured too."""
    departures = []
    for steps, walks in sorted(by_position.items()):
        if walk in walks and len(walks) > 1:
            others = [value for other, value in walks.items() if other != walk]
            departures.append((steps, walks[walk] - float(np.mean(others))))
    return departures


@calibration_check('walk agreement', applies_to=('fit',))
def check_walk_agreement(evidence, limits):
    """Several walks: did the TRIAX zero move between them, and does it return to the same place?"""
    if evidence.fit is None or len(set(evidence.fit.observation_groups)) < 2:
        return None
    nm_per_step = _nm_per_step(evidence)
    reference = evidence.fit.reference_group
    offsets = evidence.fit.group_offsets_nm
    spread = float(np.ptp(list(offsets.values())))
    details = [f"{walk}: zero {offset:+.3f} nm ({offset / nm_per_step:+.1f} steps) from {reference}"
               for walk, offset in offsets.items()]
    by_position = defaultdict(dict)
    for (walk, steps), offset in decompose_fit_residuals(evidence.fit).frame_offsets_nm.items():
        by_position[steps][walk] = offset
    differences = [offset - np.mean(list(walks.values())) for walks in by_position.values()
                   if len(walks) > 1 for offset in walks.values()]
    repeatability = float(np.sqrt(np.mean(np.square(differences)))) if differences else np.nan
    drifting_walks = []
    if np.isfinite(repeatability):
        details.append(f"at the same TRIAX positions, after each walk's zero, the walks agree to "
                       f"{repeatability:.3f} nm rms (~{repeatability / nm_per_step:.1f} steps)")
        for walk in sorted(offsets):
            departures = _walk_departures(by_position, walk)
            if not departures:
                continue
            walk_rms = float(np.sqrt(np.mean([value ** 2 for _, value in departures])))
            if walk_rms <= limits.walk_repeatability_warn_nm:
                continue
            (first_steps, first), (last_steps, last) = departures[0], departures[-1]
            details.append(f"{walk} departs from the others by {walk_rms:.3f} nm rms: {first:+.3f} "
                           f"nm at TRIAX {first_steps}, {last:+.3f} nm at TRIAX {last_steps}")
            if abs(first - last) > 2 * limits.walk_repeatability_warn_nm:
                drifting_walks.append(walk)
    causes, actions, verdict = [], [], PASS
    if drifting_walks:
        verdict = WARN
        causes.append(f"{', '.join(drifting_walks)} drift(s) along the walk relative to the "
                      "others: the instrument was still warming up, or the TRIAX settling after a "
                      "long move; its fitted zero is a compromise")
        actions.append("leave a drifting walk out (typically the first of a session) and let the "
                       "instrument run for a while before calibrating")
    if spread > limits.walk_offset_spread_warn_nm and not drifting_walks:
        verdict = WARN
        causes.append(f"the TRIAX zero moved by up to {spread:.3f} nm ({spread / nm_per_step:.0f} "
                      "steps) between walks: a restart or re-initialisation of the TRIAX, a "
                      "re-reference, or lost steps. The shape fit uses all walks; the zero comes "
                      f"from the latest walk ({reference})")
        actions.append("if nothing was restarted between these walks, the TRIAX is losing steps: "
                       "check the drive")
    if np.isfinite(repeatability) and repeatability > limits.walk_repeatability_warn_nm:
        verdict = WARN
        causes.append("the TRIAX does not return to the same place at the same step count: "
                      "backlash, lost steps, or drift while the instrument warms up (compare the "
                      "first walk of a session with the rest)")
        actions.append("repeat the walk after the instrument has run for 30 min; leave a drifting "
                       "first walk out")
    return CheckResult('walk agreement', verdict,
                       f"walk zeros spread over {spread:.3f} nm "
                       f"(WARN > {limits.walk_offset_spread_warn_nm} nm)",
                       details=details, likely_causes=causes, what_to_try=actions)


@calibration_check('coverage', applies_to=('fit',))
def check_coverage(evidence, limits):
    """Is every usable line seen often enough, and is the TRIAX range covered without gaps?"""
    if evidence.fit is None:
        return None
    sightings = defaultdict(int)
    for observation in evidence.fit.observations:
        sightings[observation.line_name.split(' (')[0]] += 1
    rare = [f"{name} ({count})" for name, count in sorted(sightings.items())
            if count < limits.minimum_sightings_per_line]
    steps = sorted({observation.triax_steps for observation in evidence.fit.observations})
    pixels = [observation.centre_pixel for observation in evidence.fit.observations]
    details = [f"TRIAX {steps[0]}..{steps[-1]}, {len(steps)} positions; pixels "
               f"{min(pixels):.0f}..{max(pixels):.0f}; {len(sightings)} lines"]
    gaps = []
    for identification in evidence.identifications:
        run = []
        for frame in identification.frames:
            if frame.identified:
                if len(run) >= 2:
                    gaps.append(f"TRIAX {run[0]}..{run[-1]}")
                run = []
            elif frame.status != NO_LINES:
                run.append(frame.triax_steps)
    if rare:
        details.append(f"seen fewer than {limits.minimum_sightings_per_line} times: "
                       f"{', '.join(rare)}")
    if gaps:
        details.append(f"runs of 2+ unidentified frames: {', '.join(sorted(set(gaps)))}")
    if not gaps:
        return CheckResult('coverage', PASS, "the walk range is covered", details=details)
    return CheckResult('coverage', WARN, "part of the TRIAX range has no identified frames",
                       details=details,
                       likely_causes=["the axis is interpolated across the gap; see 'frames "
                                      "identified' for why those frames failed"],
                       what_to_try=["fix the cause and walk again"])


@calibration_check('saturation', applies_to=('fit', 'zero'))
def check_saturation(evidence, limits):
    """Reference lines lost because they saturated the CCD."""
    lost = used = 0
    for identification in evidence.identifications:
        for frame in identification.identified_frames:
            lost += sum('saturated' in note for note in frame.skipped_lines)
            used += len(frame.observations)
    if lost + used == 0:
        return None
    summary = (f"{lost} of {lost + used} reference line sightings lost to saturation "
               f"(WARN above {limits.saturated_fraction_warn:.0%})")
    if lost / (lost + used) <= limits.saturated_fraction_warn:
        return CheckResult('saturation', PASS, summary)
    exposures = sorted({_camera_setting(instrument, 'exposure_s')
                        for instrument in evidence.instruments
                        if _camera_setting(instrument, 'exposure_s') is not None})
    return CheckResult(
        'saturation', WARN, summary,
        likely_causes=["exposure too long for the brightest argon lines"],
        what_to_try=[f"shorten the exposure (walk exposure {exposures} s); about half usually "
                     "keeps the brightest lines (763.5, 811.5, 912.3 nm) below 65000 counts while "
                     "the weak ones stay detectable"])


@calibration_check('fit statistics', applies_to=('fit',))
def check_fit_statistics(evidence, limits):
    """Reduced chi^2 against the decomposition, and any option that changes what chi^2 means."""
    fit = evidence.fit
    if fit is None:
        return None
    details = [f"residual rms {fit.residual_rms_nm:.4f} nm, max {fit.residual_max_nm:.4f} nm, "
               f"reduced chi^2 {fit.reduced_chi_squared:.1f}"]
    if evidence.fit_options.get('triax_step_uncertainty', 0) > 0:
        return CheckResult(
            'fit statistics', WARN,
            "triaxsigma inflates every point's uncertainty, so chi^2 no longer tests the fit",
            details=details,
            likely_causes=["a TRIAX positioning error is shared by every line in a frame; adding "
                           "it to each line as if independent hides misidentified lines and model "
                           "errors alike"],
            what_to_try=["fit without triaxsigma and read 'CCD axis (within-frame)' and "
                         "'TRIAX shape' instead"])
    decomposition = decompose_fit_residuals(fit)
    if np.isfinite(decomposition.within_frame_rms_nm) and \
            decomposition.triax_shape_rms_nm > 3 * decomposition.within_frame_rms_nm:
        details.append(f"most of the residual is shared within frames (TRIAX: "
                       f"{decomposition.triax_shape_rms_nm:.3f} nm) rather than within them (CCD "
                       f"axis: {decomposition.within_frame_rms_nm:.4f} nm), so chi^2 mainly "
                       "measures the TRIAX shape; see 'TRIAX shape'")
    return CheckResult('fit statistics', PASS,
                       f"reduced chi^2 {fit.reduced_chi_squared:.1f} (informational)",
                       details=details)


@calibration_check('change from calibration in use', applies_to=('fit',))
def check_change_from_current(evidence, limits):
    if evidence.fit is None or evidence.current_model is None:
        return None
    steps = sorted({observation.triax_steps for observation in evidence.fit.observations})
    change = largest_axis_difference_nm(evidence.fit.model, evidence.current_model, steps,
                                        evidence.number_of_pixels)
    summary = f"largest change over the measured range {change:.3f} nm"
    if change <= limits.change_from_current_warn_nm:
        return CheckResult('change from calibration in use', PASS, summary)
    return CheckResult(
        'change from calibration in use', WARN, summary,
        likely_causes=["the calibration in use was off by this much (expected the first time, or "
                       "after the TRIAX zero moved)"],
        what_to_try=["after applying, check the grating calibrations: they were made against the "
                     "old axis"])


# -- checks: the quick re-zero -----------------------------------------------------------------

@calibration_check('zero consistency', applies_to=('zero',))
def check_zero_consistency(evidence, limits):
    """The re-zero frames must agree on one step offset; if not, more than the zero changed."""
    zero = evidence.zero
    if zero is None or not zero.frame_offsets_steps:
        return CheckResult(
            'zero consistency', FAIL, "no identified frame to measure the zero from",
            likely_causes=["lamp off or not reaching the TRIAX, or the zero is beyond the search"],
            what_to_try=["check the lamp, then run the full 'speccal'"])
    spread = zero.spread_steps
    fail_limit = limits.zero_spread_fail_steps if zero.used_position_table \
        else limits.zero_spread_fail_steps_without_table
    if spread > fail_limit or len(zero.frame_offsets_steps) < 2:
        verdict = FAIL
    elif spread > limits.zero_spread_warn_steps:
        verdict = WARN
    else:
        verdict = PASS
    details = [f"TRIAX {steps}: {offset:+.1f} steps"
               for steps, offset in zero.frame_offsets_steps.items()]
    if not zero.used_position_table:
        details.append("the calibration in use has no TRIAX position table (fitted before "
                       "2026-11-11), so the TRIAX shape adds up to ~20 steps of scatter")
    causes, actions = [], []
    if verdict != PASS:
        causes = ["the frames disagree: the axis SHAPE changed (optics, grating), not only the "
                  "TRIAX zero",
                  "or a frame is misidentified (see 'frames identified')"]
        actions = ["run the full calibration: 'speccal', 'speccalfit curvature triaxorder=3', "
                   "then 'speccalapply'"]
    if len(zero.frame_offsets_steps) < 2:
        causes.insert(0, "only one frame was identified, so the result cannot be cross-checked")
    return CheckResult('zero consistency', verdict,
                       f"frames agree on the offset to {spread:.1f} steps "
                       f"(WARN > {limits.zero_spread_warn_steps:g}, FAIL > {fail_limit:g})",
                       details=details, likely_causes=causes, what_to_try=actions)


@calibration_check('zero size', applies_to=('zero',))
def check_zero_size(evidence, limits):
    zero = evidence.zero
    if zero is None or not zero.frame_offsets_steps:
        return None
    summary = (f"TRIAX zero moved by {zero.step_offset:+.1f} steps "
               f"({zero.step_offset * zero.nm_per_step:+.3f} nm)")
    if abs(zero.step_offset) <= limits.large_zero_shift_warn_steps:
        return CheckResult('zero size', PASS, summary)
    return CheckResult(
        'zero size', WARN, summary,
        likely_causes=["a large jump: the TRIAX was re-initialised, the grating turret moved, or "
                       "many steps were lost"],
        what_to_try=["confirm the right grating is in use; if the jump recurs without a restart, "
                     "check the drive"])
