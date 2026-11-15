"""
Which known line is each peak? Identification by pattern, for a whole line walk at once.

Why not "the peak nearest the predicted pixel"
----------------------------------------------
The first version of the walk predicted each line's pixel from the calibration
in use and took the nearest peak within 4 px. The calibration in use was off by
8-37 px, by an amount that changed along the walk, so a weak neighbour often
sat closer to the prediction than the line itself: in the 2026-11-10 walks 72
of 91 recorded lines were the wrong line, and no check could see it, because a
repeated walk repeats the same mistake (CHANGELOG, 2026-11-11).

What this module does instead
-----------------------------
The lamp's lines form a pattern (spacings, doublets) that only fits the
spectrum one way. So:

1. Every peak in every frame is found and fitted (line_peaks.find_and_fit_peaks).
   "Strong" peaks are those above `strong_peak_fraction` of the brightest peak
   in the walk (and above the noise threshold).
2. Each frame gets a score for every wavelength offset of the prior
   calibration over +/- `search_half_width_nm`: how many of its strong peaks
   would then sit within `match_tolerance_nm` of SOME line in the full table
   (reference_lines.ARGON_MERCURY_LAMP_LINES, which lists every line that can
   reach the chip, including ones never used as references). Listed lines too
   close to separate are merged first (merge_coincident_lines).
3. The walk is identified as a whole: the offset of the prior calibration may
   drift linearly along the walk (a slope error in the prior), and each frame
   may wander from that trend by `frame_wander_nm` (TRIAX drive error). The
   trend with the highest total score over all frames wins. Frames with few
   lines are carried by their neighbours. The runner-up trend (more than ~1 nm
   away) is reported: if it scores nearly as well, the identification is
   ambiguous and the gates say so.
4. Each frame is then refined around the trend: offset and dispersion scale,
   every peak (weak ones too) assigned to its mutually nearest line, and a
   pixel -> wavelength map fitted to the frame's reference lines. A line far
   off the others' map is dropped from the frame (with the reason recorded)
   when enough lines remain to tell which one is wrong. A second pass repeats
   steps 2-4 against the walk's own map shape (identify_walk).
5. Each frame is checked on its own: every strong peak must be explained by a
   listed line (an unexplained strong peak means the table is missing a line,
   or the frame is misidentified); there must be at least
   `minimum_lines_per_frame` lines; and the lines must agree with one smooth
   map to `frame_consistency_limit_nm`. A correctly identified frame agrees to
   ~0.005 nm; a misidentified line is off by ~1 nm, so this check has a margin
   of ~100. A frame with one line is accepted when the rest of the walk fixes
   the pattern and no other listed line is within reach.
6. Frames the trend does not reach are identified from their neighbours,
   working outward from the identified frames (_identify_frames_outward).
   The trend is straight along the walk, but the prior calibration can bend
   away from it at the ends: on 2026-11-11 it was off by 0.5-1.7 nm in the
   last frames of every walk, beyond `frame_wander_nm`, so those frames
   failed and the fit had to extrapolate there (lab notebook RAM-F2). Each
   such frame is searched within `frame_wander_nm` of the offset its two
   nearest identified frames predict, and must pass the same checks.

Only lines marked usable_as_reference, unsaturated, away from the chip edges
and not blended with a listed neighbour become LineObservations. Their centre
uncertainty is the fit uncertainty combined with
`centre_uncertainty_floor_pixels`: the Gaussian fit's own uncertainty ignores
photon noise and line shape and is 10-1000x too small for bright lines.

Pure and deterministic: nothing here touches hardware.
"""

from dataclasses import dataclass, field, replace

import numpy as np
from scipy.ndimage import maximum_filter1d

from .line_peaks import DetectedPeak, find_and_fit_peaks
from .reference_lines import ReferenceLine
from .wavelength_axis_model import LineObservation, WavelengthAxisModel

IDENTIFIED = 'IDENTIFIED'
NO_LINES = 'NO LINES'
TOO_FEW_LINES = 'TOO FEW LINES'
NOT_IDENTIFIED = 'NOT IDENTIFIED'
INCONSISTENT = 'INCONSISTENT'


@dataclass
class IdentificationSettings:
    """Tolerances of the identification. Defaults suit the 300 g/mm grating on the PIXIS."""

    search_half_width_nm: float = 12.0          # how wrong the prior calibration may be
    search_step_nm: float = 0.01
    match_tolerance_nm: float = 0.15            # ~2 px: a peak this close to a line "is explained"
    frame_wander_nm: float = 0.5                # a frame's offset may stray this far from the trend
    trend_change_limit_nm: float = 8.0          # the prior's offset may change this much per walk
    trend_change_step_nm: float = 0.05
    dispersion_scale_limit: float = 0.01        # the prior's nm/px may be wrong by up to 1 %
    strong_peak_fraction: float = 0.02          # strong = 2 % of the brightest peak in the walk
    minimum_signal_to_noise: float = 10.0
    required_explained_fraction: float = 0.8
    minimum_lines_per_frame: int = 2
    frame_consistency_limit_nm: float = 0.03
    frame_outlier_floor_nm: float = 0.03        # a line this far (or 5 sigma) off its map: dropped
    coincident_line_separation_nm: float = 0.2  # listed lines closer than this are one peak
    minimum_resolved_separation_pixels: float = 8.0
    blend_shift_limit_nm: float = 0.003         # a weaker neighbour may pull a centre by this much
    edge_margin_pixels: float = 15.0
    centre_uncertainty_floor_pixels: float = 0.05


@dataclass
class SpectrumFrame:
    """One spectrum of a walk: where the TRIAX was and what the CCD saw."""

    label: str
    triax_steps: int
    spectrum: np.ndarray
    saturation_level: float = None


@dataclass
class LineAssignment:
    line: object          # ReferenceLine
    peak: DetectedPeak
    residual_nm: float    # line wavelength minus the frame's fitted map at the peak


@dataclass
class FrameIdentification:
    """One frame's identification, with what a person needs to see why it was accepted or not."""

    label: str
    triax_steps: int
    peaks: list
    strong_peaks: list
    status: str = NO_LINES
    reasons: list = field(default_factory=list)
    assignments: list = field(default_factory=list)
    unexplained_strong_peaks: list = field(default_factory=list)  # (peak, approximate nm)
    offset_from_prior_nm: float = float('nan')
    trend_offset_nm: float = float('nan')
    dispersion_scale: float = 1.0
    frame_map_coefficients: tuple = ()  # wavelength = c0 + c1 u + c2 u^2, u = pixel - centre
    map_parameter_count: int = 0        # how many of c0, c1, c2 were fitted to the frame's lines
    frame_residual_rms_nm: float = float('nan')
    observations: list = field(default_factory=list)
    skipped_lines: list = field(default_factory=list)        # "line: reason"
    peak_wavelengths_nm: list = field(default_factory=list)  # every peak, on the final map
    outlier_line_ids: set = field(default_factory=set)       # lines dropped as off the map
    single_line_is_unique: bool = False  # one line, no other listed line within reach of the trend

    @property
    def identified(self):
        return self.status == IDENTIFIED

    def summary(self):
        lines_text = ', '.join(assignment.line.name for assignment in self.assignments) or 'none'
        text = (f"TRIAX {self.triax_steps}: {self.status}; {len(self.strong_peaks)} strong peaks, "
                f"lines {lines_text}")
        if np.isfinite(self.frame_residual_rms_nm):
            text += f"; frame rms {self.frame_residual_rms_nm:.4f} nm"
        if self.reasons:
            text += f" -- {'; '.join(self.reasons)}"
        return text


@dataclass
class WalkIdentification:
    """Result for a whole walk."""

    frames: list
    trend_offset_nm: float     # offset of the prior calibration at the middle of the walk
    trend_change_nm: float     # change of that offset from the first to the last TRIAX position
    trend_score: float         # strong peaks explained by the winning trend, over all frames
    runner_up_score: float     # same, for the best trend more than ~1 nm from the winner
    runner_up_offset_nm: float
    strong_peak_total: int
    settings: IdentificationSettings

    @property
    def observations(self):
        return [observation for frame in self.frames if frame.identified
                for observation in frame.observations]

    @property
    def identified_frames(self):
        return [frame for frame in self.frames if frame.identified]

    @property
    def ambiguity_ratio(self):
        """Runner-up / winning score: near 1 means two identifications fit about as well."""
        return self.runner_up_score / self.trend_score if self.trend_score > 0 else 1.0

    def summary_lines(self):
        lines = [
            f"identification: {len(self.identified_frames)} of {len(self.frames)} frames "
            f"identified, {len(self.observations)} reference line positions; prior calibration "
            f"offset {self.trend_offset_nm:+.2f} nm at mid-walk, changing by "
            f"{self.trend_change_nm:+.2f} nm over the walk; {self.trend_score:.0f} of "
            f"{self.strong_peak_total} strong peaks explained; runner-up identification "
            f"({self.runner_up_offset_nm:+.2f} nm) explains {self.runner_up_score:.0f}",
        ]
        lines += [f"  {frame.summary()}" for frame in self.frames]
        return lines


def _empty_walk_identification(settings, frames=()):
    return WalkIdentification(frames=list(frames), trend_offset_nm=float('nan'),
                              trend_change_nm=float('nan'), trend_score=0.0, runner_up_score=0.0,
                              runner_up_offset_nm=float('nan'), strong_peak_total=0,
                              settings=settings)


# -- helpers ---------------------------------------------------------------------------------

def _chip_centre(number_of_pixels):
    return (number_of_pixels - 1) / 2.0


def _strong_peak_threshold(frames_peaks, settings):
    heights = [peak.height_counts for peaks in frames_peaks for peak in peaks]
    return settings.strong_peak_fraction * max(heights) if heights else np.inf


def _matched_offsets_score(peak_wavelengths, line_wavelengths, offset_grid, tolerance_nm):
    """For each offset in the grid: how many peaks would sit within the tolerance of some line."""
    score = np.zeros(offset_grid.size)
    if peak_wavelengths.size == 0:
        return score
    grid_start, grid_step = offset_grid[0], offset_grid[1] - offset_grid[0]
    needed_offsets = line_wavelengths[None, :] - peak_wavelengths[:, None]  # peaks x lines
    for peak_offsets in needed_offsets:
        covered = np.zeros(offset_grid.size + 1)
        nearby = peak_offsets[np.abs(peak_offsets) <= np.abs(offset_grid).max() + tolerance_nm]
        first = np.ceil((nearby - tolerance_nm - grid_start) / grid_step).astype(int)
        last = np.floor((nearby + tolerance_nm - grid_start) / grid_step).astype(int) + 1
        np.add.at(covered, np.clip(first, 0, offset_grid.size), 1)
        np.add.at(covered, np.clip(last, 0, offset_grid.size), -1)
        score += (np.cumsum(covered)[:-1] > 0)
    return score


def _prior_wavelengths(prior_model, pixels, triax_steps, dispersion_scale, centre_pixel):
    pixels = np.asarray(pixels, dtype=float)
    prior = np.asarray(prior_model.wavelength_at(pixels, triax_steps), dtype=float)
    centre = float(prior_model.wavelength_at(centre_pixel, triax_steps))
    return prior + dispersion_scale * (prior - centre)


def _assign_mutually_nearest(peak_wavelengths, line_wavelengths, tolerance_nm):
    """[(peak index, line index)] where each is the other's nearest within the tolerance."""
    if peak_wavelengths.size == 0 or line_wavelengths.size == 0:
        return []
    distances = np.abs(peak_wavelengths[:, None] - line_wavelengths[None, :])
    pairs = []
    for peak_index in range(peak_wavelengths.size):
        line_index = int(np.argmin(distances[peak_index]))
        nearest_peak_of_line = int(np.argmin(distances[:, line_index]))
        if distances[peak_index, line_index] <= tolerance_nm and nearest_peak_of_line == peak_index:
            pairs.append((peak_index, line_index))
    return pairs


def _reference_observation(line, peak, triax_steps, settings):
    return LineObservation(
        line_name=line.label, apparent_wavelength_nm=line.apparent_wavelength_nm,
        wavelength_uncertainty_nm=line.wavelength_uncertainty_nm, triax_steps=int(triax_steps),
        centre_pixel=peak.centre_pixel,
        centre_uncertainty_pixels=float(np.hypot(peak.centre_uncertainty_pixels,
                                                 settings.centre_uncertainty_floor_pixels)))


def merge_coincident_lines(catalogue_lines, separation_nm, blend_shift_limit_nm):
    """
    Listed lines closer than `separation_nm` land on one peak on this CCD: one entry per group.

    If the group's strongest line is so much stronger than the others (same
    element, so the NIST intensities compare) that they cannot move its centre
    by more than `blend_shift_limit_nm`, the group is that line, usable as
    before (Ar 706.722 with the 100x weaker Ar 706.874). Otherwise it is a
    blend: one identification-only entry at the intensity-weighted wavelength
    (Ar 772.376 + Ar 772.421).
    """
    groups = []
    for line in sorted(catalogue_lines, key=lambda line: line.apparent_wavelength_nm):
        previous = groups[-1][-1].apparent_wavelength_nm if groups else -np.inf
        if line.apparent_wavelength_nm - previous < separation_nm:
            groups[-1].append(line)
        else:
            groups.append([line])
    merged = []
    for group in groups:
        if len(group) == 1:
            merged.append(group[0])
            continue
        strongest = max(group, key=lambda line: line.relative_intensity)
        same_element = all(line.element == strongest.element for line in group) \
            and strongest.relative_intensity > 0
        weights = np.array([line.relative_intensity if same_element else 1.0 for line in group])
        wavelengths = np.array([line.apparent_wavelength_nm for line in group])
        blend_wavelength = float(np.average(wavelengths, weights=weights))
        if same_element and abs(blend_wavelength - strongest.apparent_wavelength_nm) \
                <= blend_shift_limit_nm:
            merged.append(strongest)
            continue
        merged.append(ReferenceLine(
            name=' + '.join(line.label for line in group), wavelength_nm=blend_wavelength,
            usable_as_reference=False,
            relative_intensity=float(weights.sum()) if same_element else 0.0))
    return merged


# -- the identification ----------------------------------------------------------------------

def identify_walk(frames, catalogue_lines, prior_model, number_of_pixels=1024, settings=None):
    """
    Identify the lines in every frame of a walk; see the module docstring.

    `frames` is a list of SpectrumFrame; `prior_model` is the calibration in use
    (only needs to be within `search_half_width_nm`).

    Two passes. The first searches widely around the prior. Its well-identified
    frames then define the walk's own map shape (wavelength at the chip centre and
    nm/px against TRIAX position, curvature), and the second pass re-identifies
    every frame against that shape within a narrow window, so a frame with only two
    lines gets its dispersion from its neighbours instead of from the prior. The
    result keeps the first pass's search figures (how far off the prior was, and how
    well the runner-up identification did), since those describe the search.
    """
    settings = settings or IdentificationSettings()
    if not frames:
        return _empty_walk_identification(settings)
    catalogue_lines = merge_coincident_lines(catalogue_lines,
                                             settings.coincident_line_separation_nm,
                                             settings.blend_shift_limit_nm)
    frames_peaks = [find_and_fit_peaks(frame.spectrum,
                                       minimum_signal_to_noise=settings.minimum_signal_to_noise,
                                       saturation_level=frame.saturation_level)
                    for frame in frames]
    first_pass = _identify_walk_once(frames, frames_peaks, catalogue_lines, prior_model,
                                     number_of_pixels, settings)
    walk_shape = _walk_map_shape(first_pass.frames, number_of_pixels)
    if walk_shape is None:
        _identify_frames_outward(first_pass.frames, frames, frames_peaks, catalogue_lines,
                                 prior_model, number_of_pixels, settings)
        return first_pass
    narrow_settings = replace(settings, search_half_width_nm=2.0, trend_change_limit_nm=1.0,
                              dispersion_scale_limit=0.001)
    second_pass = _identify_walk_once(frames, frames_peaks, catalogue_lines, walk_shape,
                                      number_of_pixels, narrow_settings)
    _identify_frames_outward(second_pass.frames, frames, frames_peaks, catalogue_lines, walk_shape,
                             number_of_pixels, narrow_settings)
    return replace(second_pass, trend_offset_nm=first_pass.trend_offset_nm,
                   trend_change_nm=first_pass.trend_change_nm, trend_score=first_pass.trend_score,
                   runner_up_score=first_pass.runner_up_score,
                   runner_up_offset_nm=first_pass.runner_up_offset_nm, settings=settings)


def _offset_at_chip_centre(frame_result, prior_model, centre_pixel):
    """How far the frame's own map sits from the prior calibration, at the chip centre (nm)."""
    prior_at_centre = float(_prior_wavelengths(prior_model, [centre_pixel],
                                               frame_result.triax_steps, 0.0, centre_pixel)[0])
    return frame_result.frame_map_coefficients[0] - prior_at_centre


def _predicted_offset(triax_steps, identified_offsets):
    """
    The prior's offset at `triax_steps` from the two identified frames nearest to it: a straight
    line through them (interpolating or extrapolating), or the one frame's offset if only one.
    """
    nearest = sorted(identified_offsets, key=lambda steps: abs(steps - triax_steps))[:2]
    if len(nearest) == 1 or nearest[0] == nearest[1]:
        return identified_offsets[nearest[0]]
    slope = ((identified_offsets[nearest[1]] - identified_offsets[nearest[0]])
             / (nearest[1] - nearest[0]))
    return identified_offsets[nearest[0]] + slope * (triax_steps - nearest[0])


def _identify_frames_outward(frame_results, frames, frames_peaks, catalogue_lines, prior_model,
                             number_of_pixels, settings):
    """
    Step 6 of the module docstring: re-try the frames the walk trend did not reach, nearest to an
    identified frame first, each from the offset its two nearest identified frames predict.
    A frame identified this way joins the neighbours of the next. `frame_results` is updated in
    place.
    """
    centre_pixel = _chip_centre(number_of_pixels)
    line_wavelengths = np.array([line.apparent_wavelength_nm for line in catalogue_lines])
    retry_statuses = (NOT_IDENTIFIED, TOO_FEW_LINES, INCONSISTENT)
    tried = set()
    while True:
        identified_offsets = {result.triax_steps: _offset_at_chip_centre(result, prior_model,
                                                                         centre_pixel)
                              for result in frame_results
                              if result.identified and result.frame_map_coefficients}
        if len(identified_offsets) < 2:
            return
        candidates = [index for index, result in enumerate(frame_results)
                      if result.status in retry_statuses and index not in tried]
        if not candidates:
            return
        index = min(candidates, key=lambda index: min(
            abs(frame_results[index].triax_steps - steps) for steps in identified_offsets))
        tried.add(index)
        old_result = frame_results[index]
        predicted_offset = _predicted_offset(old_result.triax_steps, identified_offsets)
        retried = _identify_frame(frames[index], old_result.peaks, old_result.strong_peaks,
                                  predicted_offset, catalogue_lines, line_wavelengths, prior_model,
                                  centre_pixel, number_of_pixels, settings)
        if retried.status == TOO_FEW_LINES and retried.single_line_is_unique \
                and not retried.unexplained_strong_peaks:
            retried.status = IDENTIFIED
            _make_observations(retried, catalogue_lines, number_of_pixels, settings)
        if not retried.identified:
            continue
        retried.reasons = [f"identified from its neighbouring frames: "
                           f"{predicted_offset - old_result.trend_offset_nm:+.2f} nm off the "
                           f"walk trend (was: {old_result.status})"]
        frame_results[index] = retried
        tried = set()  # a new neighbour: frames that failed before may now be reached


def _walk_map_shape(frame_results, number_of_pixels):
    """
    A WavelengthAxisModel (reference pixel = chip centre) through the maps of the frames whose
    dispersion was fitted (4 or more lines): wavelength at the centre quadratic in steps, nm/px
    linear in steps, curvature the median of the frames that fitted it. None if under 3 frames.
    """
    fitted = [frame for frame in frame_results
              if frame.identified and frame.map_parameter_count >= 2]
    if len(fitted) < 3:
        return None
    steps = np.array([frame.triax_steps for frame in fitted], dtype=float)
    centre_wavelengths = np.array([frame.frame_map_coefficients[0] for frame in fitted])
    dispersions = np.array([frame.frame_map_coefficients[1] for frame in fitted])
    curvatures = [frame.frame_map_coefficients[2] for frame in fitted
                  if frame.map_parameter_count == 3]
    distinct_positions = len(set(steps))
    if distinct_positions >= 2:
        dispersion_slope, dispersion_at_mean = np.polyfit(steps - steps.mean(), dispersions, 1)
    else:
        dispersion_slope, dispersion_at_mean = 0.0, float(dispersions.mean())
    centre_polynomial = np.polyfit(steps, centre_wavelengths, min(2, distinct_positions - 1))
    return WavelengthAxisModel(
        reference_pixel=_chip_centre(number_of_pixels),
        triax_to_wavelength_coefficients=list(centre_polynomial),
        nm_per_pixel=float(dispersion_at_mean),
        nm_per_pixel_squared=float(np.median(curvatures)) if curvatures else 0.0,
        nm_per_pixel_change_per_triax_step=float(dispersion_slope),
        dispersion_reference_triax_steps=float(steps.mean()))


def _identify_walk_once(frames, frames_peaks, catalogue_lines, prior_model, number_of_pixels,
                        settings):
    """One identification pass over the walk (steps 2-5 of the module docstring)."""
    centre_pixel = _chip_centre(number_of_pixels)
    line_wavelengths = np.array([line.apparent_wavelength_nm for line in catalogue_lines])
    strong_threshold = _strong_peak_threshold(frames_peaks, settings)
    strong_peaks_per_frame = [[peak for peak in peaks if peak.height_counts >= strong_threshold]
                              for peaks in frames_peaks]

    # 2. Score every offset of the prior calibration, frame by frame (best dispersion scale).
    offset_grid = np.arange(-settings.search_half_width_nm,
                            settings.search_half_width_nm + settings.search_step_nm / 2,
                            settings.search_step_nm)
    scale_limit = settings.dispersion_scale_limit
    coarse_scales = np.linspace(-scale_limit, scale_limit, 5)
    frame_scores = []
    for frame, strong_peaks in zip(frames, strong_peaks_per_frame):
        pixels = [peak.centre_pixel for peak in strong_peaks]
        frame_scores.append(np.max([
            _matched_offsets_score(_prior_wavelengths(prior_model, pixels, frame.triax_steps, scale,
                                                      centre_pixel),
                                   line_wavelengths, offset_grid, settings.match_tolerance_nm)
            for scale in coarse_scales], axis=0))

    # 3. The walk trend: offset = a + b * x, x from -0.5 (first position) to +0.5 (last).
    steps = np.array([frame.triax_steps for frame in frames], dtype=float)
    span = float(np.ptp(steps)) or 1.0
    walk_positions = (steps - steps.mean()) / span if len(frames) > 1 else np.zeros(1)
    wander_cells = int(round(settings.frame_wander_nm / settings.search_step_nm))
    wandering_scores = np.array([maximum_filter1d(score, size=2 * wander_cells + 1)
                                 for score in frame_scores])
    if len(frames) > 1:
        change_limit = settings.trend_change_limit_nm
        change_grid = np.arange(-change_limit, change_limit + 1e-9, settings.trend_change_step_nm)
    else:
        change_grid = np.zeros(1)
    frame_index = np.repeat(np.arange(len(frames))[:, None], offset_grid.size, axis=1)
    totals_by_change = np.empty((change_grid.size, offset_grid.size))
    for change_index, change in enumerate(change_grid):
        shifted = np.rint((offset_grid[None, :] + change * walk_positions[:, None] - offset_grid[0])
                          / settings.search_step_nm).astype(int)
        inside = (shifted >= 0) & (shifted < offset_grid.size)
        clipped = np.clip(shifted, 0, offset_grid.size - 1)
        frame_scores_at_trend = wandering_scores[frame_index, clipped]
        totals_by_change[change_index] = np.where(inside, frame_scores_at_trend, 0).sum(axis=0)
    best_totals = totals_by_change.max(axis=0)
    # Every trend within the wander of all frames scores the same: take the middle of that
    # plateau, not its edge, or frames near the edge fall outside their window and the
    # dispersion bends to reach them.
    best_change_indices, best_offset_indices = np.nonzero(totals_by_change
                                                          == totals_by_change.max())
    trend_offset = float(np.median(offset_grid[best_offset_indices]))
    near_winner = np.abs(offset_grid[best_offset_indices] - trend_offset) \
        <= 2 * settings.frame_wander_nm
    trend_change = float(np.median(change_grid[best_change_indices[near_winner]]))
    best_index = int(np.argmin(np.abs(offset_grid - trend_offset)))
    exclusion_nm = 2 * settings.frame_wander_nm + 2 * settings.match_tolerance_nm
    far_from_winner = np.abs(offset_grid - trend_offset) > exclusion_nm
    runner_up_index = int(np.argmax(np.where(far_from_winner, best_totals, -1)))

    # 4-5. Refine, assign and check each frame around the trend.
    frame_results = [
        _identify_frame(frame, peaks, strong_peaks, trend_offset + trend_change * walk_position,
                        catalogue_lines, line_wavelengths, prior_model, centre_pixel,
                        number_of_pixels, settings)
        for frame, peaks, strong_peaks, walk_position
        in zip(frames, frames_peaks, strong_peaks_per_frame, walk_positions)]
    _accept_unique_single_line_frames(frame_results, catalogue_lines, number_of_pixels, settings)

    return WalkIdentification(
        frames=frame_results, trend_offset_nm=trend_offset, trend_change_nm=trend_change,
        trend_score=float(best_totals[best_index]),
        runner_up_score=float(max(best_totals[runner_up_index], 0)),
        runner_up_offset_nm=float(offset_grid[runner_up_index]),
        strong_peak_total=int(sum(len(strong) for strong in strong_peaks_per_frame)),
        settings=settings)


def _best_offset_and_scale(strong_peaks, triax_steps, trend_offset, line_wavelengths, prior_model,
                           centre_pixel, settings):
    """The offset (within the wander) and dispersion scale that explain the most strong peaks."""
    strong_pixels = [peak.centre_pixel for peak in strong_peaks]
    wander = settings.frame_wander_nm
    local_offsets = trend_offset + np.arange(-wander, wander + 1e-9, settings.search_step_nm)
    best = None
    for scale in np.arange(-settings.dispersion_scale_limit, settings.dispersion_scale_limit + 1e-9,
                           0.0005):
        strong_wavelengths = _prior_wavelengths(prior_model, strong_pixels, triax_steps, scale,
                                                centre_pixel)
        distances = np.abs(line_wavelengths[None, None, :] - strong_wavelengths[None, :, None]
                           - local_offsets[:, None, None]).min(axis=2)  # offsets x peaks
        matched = (distances <= settings.match_tolerance_nm).sum(axis=1)
        closeness = np.minimum(distances, settings.match_tolerance_nm).sum(axis=1)
        order = np.lexsort((closeness, -matched))[0]
        candidate = (int(matched[order]), -float(closeness[order]), float(local_offsets[order]),
                     float(scale))
        if best is None or candidate[:2] > best[:2]:
            best = candidate
    return best[2], best[3]


def _identify_frame(frame, peaks, strong_peaks, trend_offset, catalogue_lines, line_wavelengths,
                    prior_model, centre_pixel, number_of_pixels, settings):
    result = FrameIdentification(label=frame.label, triax_steps=int(frame.triax_steps), peaks=peaks,
                                 strong_peaks=strong_peaks, trend_offset_nm=trend_offset)
    if not strong_peaks:
        result.status = NO_LINES
        result.reasons.append("no strong peaks (lamp off or blocked, or no lamp lines at this "
                              "TRIAX position)")
        return result
    offset, scale = _best_offset_and_scale(strong_peaks, frame.triax_steps, trend_offset,
                                           line_wavelengths, prior_model, centre_pixel, settings)
    result.offset_from_prior_nm, result.dispersion_scale = offset, 1.0 + scale

    # Assign every peak (weak ones too), then fit the frame's own map and re-assign with it.
    pixels = np.array([peak.centre_pixel for peak in peaks])
    chip_offsets = np.arange(number_of_pixels) - centre_pixel
    scaled_prior = _prior_wavelengths(prior_model, chip_offsets + centre_pixel, frame.triax_steps,
                                      scale, centre_pixel) + offset
    map_coefficients = np.polyfit(chip_offsets, scaled_prior, 2)[::-1]
    for _pass in range(2):
        peak_wavelengths = np.polyval(map_coefficients[::-1], pixels - centre_pixel)
        pairs = _assign_mutually_nearest(peak_wavelengths, line_wavelengths,
                                         settings.match_tolerance_nm)
        map_coefficients, fitted_parameter_count, defining_pairs, outlier_pairs = \
            _fit_frame_map_rejecting_outliers(pixels, peaks, pairs, catalogue_lines,
                                              line_wavelengths, centre_pixel, map_coefficients,
                                              settings)
    peak_wavelengths = np.polyval(map_coefficients[::-1], pixels - centre_pixel)
    result.frame_map_coefficients = tuple(float(value) for value in map_coefficients)
    result.map_parameter_count = fitted_parameter_count
    result.peak_wavelengths_nm = [float(value) for value in peak_wavelengths]

    def residual(peak_index, line_index):
        return float(line_wavelengths[line_index] - peak_wavelengths[peak_index])

    assigned_peaks = {peak_index for peak_index, _ in pairs}
    result.assignments = [LineAssignment(line=catalogue_lines[line_index], peak=peaks[peak_index],
                                         residual_nm=residual(peak_index, line_index))
                          for peak_index, line_index in pairs]
    strong_ids = {id(peak) for peak in strong_peaks}
    result.unexplained_strong_peaks = [(peak, float(peak_wavelengths[index]))
                                       for index, peak in enumerate(peaks)
                                       if id(peak) in strong_ids and index not in assigned_peaks]
    defining_residuals = np.array([residual(peak_index, line_index)
                                   for peak_index, line_index in defining_pairs])
    if defining_residuals.size > fitted_parameter_count:
        result.frame_residual_rms_nm = float(np.sqrt(
            np.sum(defining_residuals ** 2) / (defining_residuals.size - fitted_parameter_count)))
    result.outlier_line_ids = {id(catalogue_lines[line_index]) for _, line_index in outlier_pairs}
    for peak_index, line_index in outlier_pairs:
        result.skipped_lines.append(
            f"{catalogue_lines[line_index].name}: {residual(peak_index, line_index):+.3f} nm off "
            "the map of the other lines in this frame (weak, blended or misidentified peak); "
            "not used")
    if len(defining_pairs) == 1:
        trend_wavelength = float(_prior_wavelengths(prior_model, [pixels[defining_pairs[0][0]]],
                                                    frame.triax_steps, 0.0, centre_pixel)[0])
        trend_wavelength += trend_offset
        reach_nm = settings.frame_wander_nm + settings.match_tolerance_nm
        lines_within_reach = int(np.sum(np.abs(line_wavelengths - trend_wavelength) <= reach_nm))
        result.single_line_is_unique = lines_within_reach == 1

    _check_frame(result, settings, defining_pairs)
    if result.identified:
        _make_observations(result, catalogue_lines, number_of_pixels, settings)
    return result


def _fit_frame_map_rejecting_outliers(pixels, peaks, pairs, catalogue_lines, line_wavelengths,
                                      centre_pixel, current_coefficients, settings):
    """
    Fit the frame map to its defining lines, dropping the worst line while it is off the map by
    more than max(`frame_outlier_floor_nm`, 5 sigma) and enough lines remain to tell which one is
    wrong (at least `minimum_lines_per_frame` + 1 before dropping). Returns (coefficients, fitted
    parameter count, defining pairs kept, pairs dropped).
    """
    defining = list(_map_defining_pairs(pairs, peaks, catalogue_lines))
    dropped = []
    while True:
        coefficients, fitted_parameter_count = _fit_frame_map(pixels, defining, line_wavelengths,
                                                              centre_pixel, current_coefficients)
        if len(defining) <= max(settings.minimum_lines_per_frame, fitted_parameter_count + 1):
            return coefficients, fitted_parameter_count, defining, dropped
        nm_per_pixel = abs(coefficients[1])
        residuals = np.array([line_wavelengths[line_index]
                              - np.polyval(coefficients[::-1], pixels[peak_index] - centre_pixel)
                              for peak_index, line_index in defining])
        limits = np.array([
            max(settings.frame_outlier_floor_nm,
                5 * nm_per_pixel * np.hypot(peaks[peak_index].centre_uncertainty_pixels,
                                            settings.centre_uncertainty_floor_pixels))
            for peak_index, _ in defining])
        worst = int(np.argmax(np.abs(residuals) / limits))
        if abs(residuals[worst]) <= limits[worst]:
            return coefficients, fitted_parameter_count, defining, dropped
        dropped.append(defining.pop(worst))


def _map_defining_pairs(pairs, peaks, catalogue_lines):
    """
    The (peak, line) pairs the frame map is fitted to: unsaturated reference lines when there are
    at least two of them, otherwise every unsaturated assigned line. Identification-only lines
    (mercury, weak argon) still have to agree with the map, but they do not define it: mercury
    sits ~0.05 nm off the argon lines on this instrument (reference_lines module docstring).
    """
    unsaturated = [(peak_index, line_index) for peak_index, line_index in pairs
                   if not peaks[peak_index].saturated]
    references = [(peak_index, line_index) for peak_index, line_index in unsaturated
                  if catalogue_lines[line_index].usable_as_reference]
    return references if len(references) >= 2 else unsaturated


def _fit_frame_map(pixels, fit_pairs, line_wavelengths, centre_pixel, current_coefficients):
    """
    Refit the frame's map (c0, c1, c2 in u = pixel - centre) to its assigned, unsaturated lines.

    1-3 lines: offset only (dispersion and curvature kept); 4-5: offset and dispersion; 6 or
    more: all three. Returns (coefficients, number of fitted parameters); with no lines the map
    is returned unchanged.
    """
    current_coefficients = np.array(current_coefficients, dtype=float)
    if not fit_pairs:
        return current_coefficients, 0
    peak_indices = np.array([peak_index for peak_index, _ in fit_pairs])
    targets = line_wavelengths[[line_index for _, line_index in fit_pairs]]
    offsets = pixels[peak_indices] - centre_pixel
    if len(fit_pairs) < 4:
        shift = float(np.mean(targets - np.polyval(current_coefficients[::-1], offsets)))
        return current_coefficients + np.array([shift, 0.0, 0.0]), 1
    if len(fit_pairs) < 6:
        linear = np.polyfit(offsets, targets - current_coefficients[2] * offsets ** 2, 1)[::-1]
        return np.array([linear[0], linear[1], current_coefficients[2]]), 2
    return np.polyfit(offsets, targets, 2)[::-1], 3


def _check_frame(result, settings, defining_pairs):
    strong_count = len(result.strong_peaks)
    explained = strong_count - len(result.unexplained_strong_peaks)
    for peak, wavelength in result.unexplained_strong_peaks:
        result.reasons.append(f"strong peak at pixel {peak.centre_pixel:.1f} "
                              f"(~{wavelength:.2f} nm, {peak.height_counts:.0f} counts) matches "
                              "no listed line")
    assigned_lines = len(defining_pairs)
    if explained < settings.required_explained_fraction * strong_count:
        result.status = NOT_IDENTIFIED
        result.reasons.insert(0, f"only {explained} of {strong_count} strong peaks match listed "
                                 "lines")
    elif assigned_lines < settings.minimum_lines_per_frame:
        result.status = TOO_FEW_LINES
        result.reasons.insert(0, f"{assigned_lines} usable unsaturated line(s) agree with each "
                                 f"other; at least {settings.minimum_lines_per_frame} are needed "
                                 "to check the frame")
    elif np.isfinite(result.frame_residual_rms_nm) and \
            result.frame_residual_rms_nm > settings.frame_consistency_limit_nm:
        defining_peaks = {id(result.peaks[peak_index]) for peak_index, _ in defining_pairs}
        worst = max((assignment for assignment in result.assignments
                     if id(assignment.peak) in defining_peaks),
                    key=lambda assignment: abs(assignment.residual_nm))
        result.status = INCONSISTENT
        result.reasons.insert(0, f"lines disagree with one pixel->wavelength map by "
                                 f"{result.frame_residual_rms_nm:.3f} nm rms (limit "
                                 f"{settings.frame_consistency_limit_nm} nm); worst "
                                 f"{worst.line.name} at pixel {worst.peak.centre_pixel:.1f}, "
                                 f"{worst.residual_nm:+.3f} nm")
    else:
        result.status = IDENTIFIED


def _accept_unique_single_line_frames(frame_results, catalogue_lines, number_of_pixels, settings,
                                      minimum_cross_checked_frames=2):
    """
    A frame with one line cannot check itself. Once the walk's pattern is fixed by frames that can
    (at least `minimum_cross_checked_frames` identified with two or more lines), its line is
    identified if no other listed line is within reach of the walk trend there. Such frames carry
    the walk at its ends and for sparse lamps.
    """
    if sum(frame.identified for frame in frame_results) < minimum_cross_checked_frames:
        return
    for frame in frame_results:
        if frame.status == TOO_FEW_LINES and frame.single_line_is_unique \
                and not frame.unexplained_strong_peaks:
            frame.status = IDENTIFIED
            frame.reasons = ["one line: identified from the walk's pattern, not cross-checked "
                             "within the frame"]
            _make_observations(frame, catalogue_lines, number_of_pixels, settings)


def _make_observations(result, catalogue_lines, number_of_pixels, settings):
    nm_per_pixel = abs(result.frame_map_coefficients[1]) if len(result.frame_map_coefficients) > 1 \
        else 0.077
    separation_nm = settings.minimum_resolved_separation_pixels * nm_per_pixel
    detected_wavelengths = np.array(result.peak_wavelengths_nm)
    edge = settings.edge_margin_pixels
    for assignment in result.assignments:
        line, peak = assignment.line, assignment.peak
        if not line.usable_as_reference or id(line) in result.outlier_line_ids:
            continue
        if peak.saturated:
            result.skipped_lines.append(f"{line.name}: saturated (shorten the exposure)")
            continue
        if not edge <= peak.centre_pixel < number_of_pixels - edge:
            result.skipped_lines.append(f"{line.name}: within {edge:.0f} px of the chip edge")
            continue
        blend = _blending_neighbour(line, catalogue_lines, detected_wavelengths, separation_nm,
                                    settings)
        if blend:
            result.skipped_lines.append(f"{line.name}: {blend}")
            continue
        result.observations.append(_reference_observation(line, peak, result.triax_steps, settings))


def _blending_neighbour(line, catalogue_lines, detected_wavelengths, separation_nm, settings):
    """A reason the line's centre may be pulled by an unresolved listed neighbour, or None."""
    for other in catalogue_lines:
        if other is line:
            continue
        distance_nm = abs(other.apparent_wavelength_nm - line.apparent_wavelength_nm)
        if distance_nm == 0 or distance_nm >= separation_nm:
            continue
        if np.any(np.abs(detected_wavelengths - other.apparent_wavelength_nm) < distance_nm / 3):
            continue  # the neighbour is a peak of its own: resolved
        if other.element == line.element and line.relative_intensity > 0:
            pull_nm = distance_nm * other.relative_intensity / line.relative_intensity
            if pull_nm <= settings.blend_shift_limit_nm:
                continue
        return f"blended with {other.label} ({distance_nm:.3f} nm away)"
    return None


def identify_single_line_walk(frames, line, number_of_pixels=1024, settings=None,
                              dominance_ratio=5.0):
    """
    Walks of ONE external line (the Tiger laser): in each frame the line must be the dominant
    peak, at least `dominance_ratio` times the next one, or the frame is not used. There is no
    pattern to match.
    """
    settings = settings or IdentificationSettings()
    edge = settings.edge_margin_pixels
    results = []
    for frame in frames:
        peaks = find_and_fit_peaks(frame.spectrum,
                                   minimum_signal_to_noise=settings.minimum_signal_to_noise,
                                   saturation_level=frame.saturation_level)
        result = FrameIdentification(label=frame.label, triax_steps=int(frame.triax_steps),
                                     peaks=peaks, strong_peaks=peaks[:1])
        if not peaks:
            result.reasons.append("no peak")
        elif len(peaks) > 1 and peaks[0].height_counts < dominance_ratio * peaks[1].height_counts:
            result.status = NOT_IDENTIFIED
            result.reasons.append(f"brightest peak ({peaks[0].height_counts:.0f}) is not "
                                  f"{dominance_ratio:g}x the next ({peaks[1].height_counts:.0f}): "
                                  f"cannot tell which is {line.name}")
        elif peaks[0].saturated:
            result.status = NOT_IDENTIFIED
            result.reasons.append(f"{line.name} is saturated (shorten the exposure)")
        elif not edge <= peaks[0].centre_pixel < number_of_pixels - edge:
            result.status = TOO_FEW_LINES
            result.reasons.append(f"{line.name} is within {edge:.0f} px of the chip edge")
        else:
            result.status = IDENTIFIED
            result.assignments = [LineAssignment(line=line, peak=peaks[0], residual_nm=0.0)]
            result.observations = [_reference_observation(line, peaks[0], frame.triax_steps,
                                                           settings)]
        results.append(result)
    identification = _empty_walk_identification(settings, results)
    identification.trend_score = float(sum(frame.identified for frame in results))
    identification.strong_peak_total = len(results)
    return identification
