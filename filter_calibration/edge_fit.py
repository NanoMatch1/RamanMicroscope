"""
The stage 1 edge in one frame: where it is, how wide, and how much light the band carries.

The filtered lamp light lands on the CCD as a thin band along the slit (6-12 rows on
2026-11-18), on top of a diffuse stray-light background with no edge in it (lamp light reaching
the wide TRIAX slit outside the filter). The background is removed in two steps:
1. subtract the closed frame (g1 at -150, the edge walk's) taken at the same centre, when there
   is one: it removes the background's shape along the wavelength axis and down the rows;
2. subtract, column by column, the median of the rows a little way either side of the band
   (EdgeFitSettings.flank_rows): it removes what is left, such as the background's drift.
On 2026-11-18 the two ways gave the same edge to 0.004 nm on average (0.05 nm rms, RAM-F5).

The band slants (about +0.25 rows/nm) and can sit anywhere along the slit, so it is found in each
frame: its brightest row, then a straight centre line through per-column centroids. The columns
then sum the rows within band_half_height_rows of that line.

Edge model, in pixels: a blue line (baseline + blue slope (x - x0)) turning into a red line
(baseline + amplitude + red slope (x - x0)) through the normal CDF Phi((x - x0) / s). x0 is the
edge midpoint (where a symmetric blur leaves it) and 2.355 s its width as a Gaussian-equivalent
FWHM. The fit window runs fit_blue_nm below to fit_red_nm above the edge's first guess.

Finding the edge. The edge is the FIRST large rise in the band signal, not the steepest one:
each column is scored by the median of step_window_nm of signal just red of it minus the median
just blue of it. Medians ignore anything narrower than half the window, so a thin dip (or a
thin spike) neither makes nor hides a step. The first rise reaching first_rise_fraction of the
biggest one is the edge; the recovery from a dip further red is never taken for it.

Fitting it. The fit is robust (soft-L1 loss), keeps the edge within one score window of its
first guess, and is repeated with the narrow dips and spikes left out (clip_sigma robust sigmas
from the fit, away from the edge itself; the left-out columns are reported). The plateau
gradient on each side of the edge is a free parameter: the flat, red-slope and two-slope models
are all fitted to the same columns and the one with the lowest BIC is kept, so a low S/N edge
is not given gradients it cannot support, and an edge whose two sides differ is not forced flat.
When no edge is fitted the reason is returned (FrameEdgeResult.edge_failure).

Pure: arrays in, results out.
"""

import warnings
from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import binary_dilation, median_filter, uniform_filter1d
from scipy.optimize import OptimizeWarning, curve_fit
from scipy.special import ndtr

GAUSSIAN_FWHM_PER_SIGMA = 2.3548


@dataclass(frozen=True)
class EdgeFitSettings:
    band_half_height_rows: float = 10.0     # rows summed either side of the band's centre line
    band_search_half_rows: int = 55         # the centre line is looked for this far from the
                                            # brightest row
    flank_rows: tuple = (15, 30)            # background rows, this far either side of the band
    minimum_band_contrast: float = 300.0    # counts above the column median, for a band column
    smoothing_columns: int = 9
    fit_blue_nm: float = 10.0
    fit_red_nm: float = 15.0
    minimum_edge_signal: float = 2000.0     # band counts per column rise needed to fit an edge
    minimum_step_snr: float = 5.0           # the rise over the noise of the two medians it is
                                            # the difference of
    step_window_nm: float = 3.0             # a rise is the median this wide red of a column minus
                                            # the median this wide blue of it: dips and spikes
                                            # narrower than half of it are ignored
    first_rise_fraction: float = 0.5        # the edge is the first rise this fraction of the
                                            # biggest rise (a trough's recovery comes later)
    clip_sigma: float = 4.0                 # columns this far (robust sigma) from the fit are left
    clip_rounds: int = 3                    # out and the fit repeated, up to this many times
    clip_dilation_columns: int = 4          # the columns beside a left-out one go too
    max_clipped_fraction: float = 0.4       # of the window; more than this is not a dip
    max_plateau_change: float = 1.0         # a plateau may change by this times the edge height
                                            # across the fit window (bounds the gradients)
    saturation_level: float = 65535.0


@dataclass
class EdgeFit:
    edge_nm: float
    edge_pixel: float
    edge_uncertainty_nm: float      # 1-sigma from the fit covariance
    width_nm: float                 # Gaussian-equivalent FWHM
    plateau: float                  # band counts per column just above the edge
    residual_fraction: float        # rms fit residual over the plateau
    window_reaches_chip_end: bool
    fit_window: tuple               # (first, last) pixel of the fit
    parameters: tuple               # edge_model parameters, for plots
    model: str = ''                 # 'flat', 'red slope' or 'two slopes' (lowest BIC)
    clipped_columns: int = 0        # window columns left out as narrow dips or spikes


@dataclass
class FrameEdgeResult:
    """Everything one frame gives. edge is None when there is no band or no edge to fit
    (edge_failure says why)."""
    band_found: bool
    edge: EdgeFit = None
    edge_failure: str = ''
    band_row_at_centre: float = None        # band centre row at the middle column
    band_rows_per_nm: float = None          # the band's slant
    saturated_pixels_in_band: int = 0
    background: str = ''                    # 'closed frame and flanks' or 'flanks only'
    signal: np.ndarray = field(default=None, repr=False)        # band sum per column
    wavelength_nm: np.ndarray = field(default=None, repr=False)


def edge_model(pixel, amplitude, slope, edge_pixel, width_pixels, baseline, baseline_slope=0.0):
    """A blue line (baseline, baseline_slope) turning into a red line (baseline + amplitude, slope)
    through the normal CDF. slope and baseline_slope are the gradients far from the edge."""
    offset = pixel - edge_pixel
    return baseline + baseline_slope * offset + \
        (amplitude + (slope - baseline_slope) * offset) * ndtr(offset / width_pixels)


# the edge_model parameters each model varies (the rest are 0): amplitude, slope, edge_pixel,
# width_pixels, baseline, baseline_slope
EDGE_MODELS = {'flat': (0, 2, 3, 4), 'red slope': (0, 1, 2, 3, 4),
               'two slopes': (0, 1, 2, 3, 4, 5)}
CLIP_MODEL = 'two slopes'        # the model whose residuals say which columns are dips


def robust_sigma(values):
    """Standard deviation from the median absolute deviation."""
    return 1.4826 * float(np.median(np.abs(values - np.median(values))))


def brightest_band_row(image):
    """The row with the most light after each column's median is removed (the band's row)."""
    above_median = image - np.median(image, axis=0)[None, :]
    row_profile = uniform_filter1d(np.median(above_median, axis=1), 5)
    return int(np.argmax(row_profile))


def band_centre_line(image, search_rows, settings):
    """Centre row of the band against column, as (slope rows/column, intercept): a straight line
    through per-column centroids where the band is bright. None if there is no band."""
    first_row, last_row = max(search_rows[0], 0), min(search_rows[1], image.shape[0])
    rows = np.arange(first_row, last_row)
    region = image[first_row:last_row]
    columns, centres, weights = [], [], []
    for column in range(5, image.shape[1] - 5, 10):
        profile = region[:, column - 5:column + 5].mean(axis=1)
        profile = profile - np.median(profile)
        peak = int(np.argmax(profile))
        if profile[peak] < settings.minimum_band_contrast:
            continue
        window = slice(max(peak - 6, 0), peak + 7)
        positive = np.clip(profile[window], 0, None)
        columns.append(column)
        centres.append(np.sum(rows[window] * positive) / positive.sum())
        weights.append(profile[peak])
    if len(columns) < 5:
        return None
    return np.polyfit(columns, centres, 1, w=np.sqrt(weights))


def remove_flank_background(image, centre_rows, settings):
    """Subtract, per column, the median of the rows flank_rows either side of the band."""
    row_index = np.arange(image.shape[0])[:, None]
    distance = np.abs(row_index - centre_rows[None, :])
    flank = (distance >= settings.flank_rows[0]) & (distance <= settings.flank_rows[1])
    flank_median = np.nanmedian(np.where(flank, image, np.nan), axis=0)
    return image - np.nan_to_num(flank_median)[None, :]


def band_rows_sum(image, centre_rows, half_height_rows):
    """Per column, the sum of the rows within half_height_rows of the band's centre line."""
    distance = np.arange(image.shape[0])[:, None] - centre_rows[None, :]
    return np.where(np.abs(distance) <= half_height_rows, image, 0.0).sum(axis=0)


def rise_scores(signal, half_window):
    """(score, medians): score[i] is the median of the half_window * 2 + 1 columns centred
    half_window red of column i minus the median of those centred half_window blue of it."""
    medians = median_filter(signal, size=2 * half_window + 1, mode='nearest')
    score = np.zeros(len(signal))
    score[half_window:-half_window] = medians[2 * half_window:] - medians[:-2 * half_window]
    return score, medians


def _fit_model(name, pixels, signal, keep, start, lower, upper, f_scale):
    """(full parameters, edge variance) of one model on the kept columns, or None."""
    free = list(EDGE_MODELS[name])

    def restricted(pixel, *values):
        full = np.zeros(6)
        full[free] = values
        return edge_model(pixel, *full)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', OptimizeWarning)    # an infinite covariance is
            values, covariance = curve_fit(                      # caught below
                restricted, pixels[keep], signal[keep], p0=start[free],
                bounds=(lower[free], upper[free]), method='trf', loss='soft_l1',
                f_scale=f_scale, max_nfev=2000)
    except (RuntimeError, ValueError):
        return None
    edge_variance = covariance[free.index(2), free.index(2)]
    if not np.isfinite(edge_variance):
        return None
    full = np.zeros(6)
    full[free] = values
    return full, float(edge_variance)


def attempt_edge_fit(signal, wavelength_nm, settings=EdgeFitSettings()):
    """(EdgeFit or None, why not): the first large rise of the band signal, fitted."""
    signal = np.asarray(signal, dtype=float)
    pixels = np.arange(len(signal), dtype=float)
    nm_per_pixel_axis = float(np.median(np.abs(np.gradient(wavelength_nm))))
    half_window = max(3, int(round(settings.step_window_nm / nm_per_pixel_axis / 2)))
    if len(signal) < 6 * half_window:
        return None, 'the signal is too short for the step window'
    score, medians = rise_scores(signal, half_window)
    noise = robust_sigma(np.diff(signal)) / np.sqrt(2) * 1.2533 * \
        np.sqrt(2 / (2 * half_window + 1))             # of one rise score
    biggest = float(score.max())
    if biggest < settings.minimum_edge_signal:
        return None, (f'no rise: the biggest is {biggest:.0f} counts, below the '
                      f'{settings.minimum_edge_signal:.0f} needed')
    if biggest < settings.minimum_step_snr * noise:
        return None, (f'no rise: the biggest, {biggest:.0f} counts, is only {biggest / noise:.1f} '
                      f'times the noise (needs {settings.minimum_step_snr:.1f})')
    first_over = int(np.argmax(score >= settings.first_rise_fraction * biggest))
    guess_pixel = first_over + int(np.argmax(score[first_over:first_over + 2 * half_window + 1]))
    blue_level = float(medians[guess_pixel - half_window])
    height = float(medians[guess_pixel + half_window]) - blue_level
    nm_per_pixel = abs(np.gradient(wavelength_nm)[guess_pixel])
    first = max(0, int(guess_pixel - settings.fit_blue_nm / nm_per_pixel))
    last = min(len(signal), int(guess_pixel + settings.fit_red_nm / nm_per_pixel))
    red_slope_limit = settings.max_plateau_change * height / max(last - guess_pixel, 1)
    blue_slope_limit = settings.max_plateau_change * height / max(guess_pixel - first, 1)
    width_limits = (0.5, max(2.0, settings.fit_blue_nm / nm_per_pixel / 3.0))
    start = np.array([height, 0.0, guess_pixel,
                      np.clip(0.8 / GAUSSIAN_FWHM_PER_SIGMA / nm_per_pixel, *width_limits),
                      blue_level, 0.0])
    lower = np.array([0.1 * height, -red_slope_limit, guess_pixel - half_window, width_limits[0],
                      blue_level - height, -blue_slope_limit])
    upper = np.array([3.0 * height, red_slope_limit, guess_pixel + half_window, width_limits[1],
                      blue_level + height, blue_slope_limit])
    start[3] = np.clip(start[3], lower[3] + 1e-3, upper[3] - 1e-3)
    f_scale = max(3.0 * noise, 0.02 * height)
    x, y = pixels[first:last], signal[first:last]
    keep = np.ones(len(x), dtype=bool)
    clip_fit = _fit_model(CLIP_MODEL, x, y, keep, start, lower, upper, f_scale)
    for _ in range(settings.clip_rounds):       # leave out the narrow dips and spikes
        if clip_fit is None:
            break
        parameters = clip_fit[0]
        residual = y - edge_model(x, *parameters)
        sigma = max(robust_sigma(residual[keep]), 1e-9 * height)
        near_edge = np.abs(x - parameters[2]) <= 3.0 * parameters[3]
        outlier = (np.abs(residual) > settings.clip_sigma * sigma) & ~near_edge
        new_keep = ~binary_dilation(outlier, iterations=settings.clip_dilation_columns)
        if np.array_equal(new_keep, keep) or \
                (~new_keep).mean() > settings.max_clipped_fraction:
            break
        refit = _fit_model(CLIP_MODEL, x, y, new_keep, parameters, lower, upper, f_scale)
        if refit is None:
            break
        keep, clip_fit = new_keep, refit
    count = int(keep.sum())
    floor = (1e-9 * height) ** 2
    best = None
    for name, free in EDGE_MODELS.items():     # the same columns, so the BICs compare
        fitted = _fit_model(name, x, y, keep, clip_fit[0] if clip_fit is not None else start,
                            lower, upper, f_scale)
        if fitted is None:
            continue
        residual = y[keep] - edge_model(x[keep], *fitted[0])
        bic = count * np.log(float(np.mean(residual ** 2)) + floor) + len(free) * np.log(count)
        if best is None or bic < best[0]:
            best = (bic, name, fitted, residual)
    if best is None:
        return None, 'the edge fit did not converge'
    _, name, (parameters, edge_variance), residual = best
    edge_pixel = parameters[2]
    if not first < edge_pixel < last:
        return None, 'the fitted edge is outside the fit window'
    return EdgeFit(
        edge_nm=float(np.interp(edge_pixel, pixels, wavelength_nm)),
        edge_pixel=float(edge_pixel),
        edge_uncertainty_nm=float(np.sqrt(edge_variance)) * nm_per_pixel,
        width_nm=float(GAUSSIAN_FWHM_PER_SIGMA * abs(parameters[3]) * nm_per_pixel),
        plateau=float(parameters[0]),
        residual_fraction=float(np.std(residual) / parameters[0]),
        window_reaches_chip_end=first == 0 or last == len(signal),
        fit_window=(first, last),
        parameters=tuple(float(value) for value in parameters),
        model=name, clipped_columns=int((~keep).sum())), ''


def fit_edge(signal, wavelength_nm, settings=EdgeFitSettings()):
    """The EdgeFit of a band signal, or None if there is no edge to fit."""
    return attempt_edge_fit(signal, wavelength_nm, settings)[0]


def analyse_edge_frame(image, wavelength_nm, closed_image=None, settings=EdgeFitSettings()):
    """FrameEdgeResult for one frame; closed_image (same centre, same exposure) if there is one."""
    background_removed = image - closed_image if closed_image is not None else image
    centre_estimate = brightest_band_row(background_removed)
    search_rows = (centre_estimate - settings.band_search_half_rows,
                   centre_estimate + settings.band_search_half_rows)
    if closed_image is None:
        provisional = remove_flank_background(image, np.full(image.shape[1], centre_estimate,
                                                             dtype=float), settings)
        line = band_centre_line(provisional, search_rows, settings)
    else:
        line = band_centre_line(background_removed, search_rows, settings)
    if line is None:
        return FrameEdgeResult(band_found=False,
                               background='closed frame and flanks' if closed_image is not None
                               else 'flanks only')
    centre_rows = np.polyval(line, np.arange(image.shape[1]))
    cleaned = remove_flank_background(background_removed, centre_rows, settings)
    signal = band_rows_sum(cleaned, centre_rows, settings.band_half_height_rows)
    in_band = np.abs(np.arange(image.shape[0])[:, None] - centre_rows[None, :]) <= \
        settings.band_half_height_rows
    middle_column = image.shape[1] // 2
    edge, edge_failure = attempt_edge_fit(signal, wavelength_nm, settings)
    return FrameEdgeResult(
        band_found=True, edge=edge, edge_failure=edge_failure,
        band_row_at_centre=float(centre_rows[middle_column]),
        band_rows_per_nm=float(line[0] / abs(np.gradient(wavelength_nm)[middle_column])),
        saturated_pixels_in_band=int(((image >= settings.saturation_level) & in_band).sum()),
        background='closed frame and flanks' if closed_image is not None else 'flanks only',
        signal=signal, wavelength_nm=wavelength_nm)
