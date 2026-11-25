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

Edge model, in pixels: (a + b (x - x0)) Phi((x - x0) / s) + c, with Phi the normal CDF. Light
passes on the long-wavelength side. x0 is the edge midpoint (where a symmetric blur leaves it)
and 2.355 s its width as a Gaussian-equivalent FWHM. The fit is ordinary least squares over a
window from fit_blue_nm below to fit_red_nm above the edge's first guess. The model and fit are
the ones the g1 calibration of 2026-11-18 was made with; keep them unless a session shows the
edge itself is misplaced (RAM-F9 compares changes on three sessions' real frames).

Finding the edge (the first guess). The edge is the FIRST large rise in the band signal, not the
steepest one: each column is scored by the median of step_window_nm of signal just red of it
minus the median just blue of it. Medians ignore anything narrower than half the window, so a
thin dip or spike neither makes nor hides a step, and the first rise reaching
first_rise_fraction of the biggest one is the edge. A narrow dip further red, such as the shadow
fixed at CCD column 953 on 2026-11-25 (RAM-F9), has a steep recovery; starting from the steepest
rise took the fit there.

When no edge is fitted the reason is returned (FrameEdgeResult.edge_failure).

Pure: arrays in, results out.
"""

import warnings
from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import median_filter, uniform_filter1d
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
    minimum_edge_signal: float = 2000.0     # band counts per column (98th percentile of the
                                            # smoothed signal) needed to fit an edge
    step_window_nm: float = 3.0             # a rise is the median this wide red of a column minus
                                            # the median this wide blue of it: dips and spikes
                                            # narrower than half of it are ignored
    first_rise_fraction: float = 0.5        # the edge is the first rise this fraction of the
                                            # biggest rise (a dip's recovery comes later)
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


def edge_model(pixel, amplitude, slope, edge_pixel, width_pixels, baseline):
    return (amplitude + slope * (pixel - edge_pixel)) * ndtr((pixel - edge_pixel) / width_pixels) \
        + baseline


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


def first_rise_pixel(signal, wavelength_nm, settings):
    """The column where the first large rise of the signal is steepest (by the median scores),
    or None if the signal never rises."""
    nm_per_pixel = float(np.median(np.abs(np.gradient(wavelength_nm))))
    half_window = max(3, int(round(settings.step_window_nm / nm_per_pixel / 2)))
    if len(signal) < 6 * half_window:
        return None
    score, _ = rise_scores(signal, half_window)
    biggest = float(score.max())
    if biggest <= 0:
        return None
    first_over = int(np.argmax(score >= settings.first_rise_fraction * biggest))
    return first_over + int(np.argmax(score[first_over:first_over + 2 * half_window + 1]))


def attempt_edge_fit(signal, wavelength_nm, settings=EdgeFitSettings()):
    """(EdgeFit or None, why not): the first large rise of the band signal, fitted."""
    signal = np.asarray(signal, dtype=float)
    pixels = np.arange(len(signal), dtype=float)
    smoothed = uniform_filter1d(signal, settings.smoothing_columns)
    brightest = float(np.percentile(smoothed, 98))
    if brightest < settings.minimum_edge_signal:
        return None, (f'too little light: the band reaches {brightest:.0f} counts per column, '
                      f'below the {settings.minimum_edge_signal:.0f} needed')
    guess_pixel = first_rise_pixel(signal, wavelength_nm, settings)
    if guess_pixel is None:
        return None, 'no rise in the band signal'
    nm_per_pixel = abs(np.gradient(wavelength_nm)[guess_pixel])
    first = max(0, int(guess_pixel - settings.fit_blue_nm / nm_per_pixel))
    last = min(len(signal), int(guess_pixel + settings.fit_red_nm / nm_per_pixel))
    window = slice(first, last)
    plateau_guess = float(np.median(signal[guess_pixel + 20:last])) if last > guess_pixel + 25 \
        else float(signal[last - 1])
    baseline_guess = float(np.median(signal[first:guess_pixel - 20])) \
        if guess_pixel - first > 25 else 0.0
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', OptimizeWarning)    # an infinite covariance is
            parameters, covariance = curve_fit(                  # caught below
                edge_model, pixels[window], signal[window],
                p0=[plateau_guess, 0.0, guess_pixel, 10.0, baseline_guess], maxfev=20000)
    except (RuntimeError, ValueError):
        return None, 'the edge fit did not converge'
    amplitude, _, edge_pixel, width_pixels, _ = parameters
    edge_uncertainty_pixels = float(np.sqrt(covariance[2, 2]))
    if not first < edge_pixel < last:
        return None, 'the fitted edge is outside the fit window'
    if amplitude <= 0:
        return None, 'the fitted step is not a rise'
    if not np.isfinite(edge_uncertainty_pixels):
        return None, 'the edge position is not constrained by the fit'
    residual = signal[window] - edge_model(pixels[window], *parameters)
    return EdgeFit(
        edge_nm=float(np.interp(edge_pixel, pixels, wavelength_nm)),
        edge_pixel=float(edge_pixel),
        edge_uncertainty_nm=edge_uncertainty_pixels * nm_per_pixel,
        width_nm=float(GAUSSIAN_FWHM_PER_SIGMA * abs(width_pixels) * nm_per_pixel),
        plateau=float(amplitude),
        residual_fraction=float(np.std(residual) / amplitude),
        window_reaches_chip_end=first == 0 or last == len(signal),
        fit_window=(first, last),
        parameters=tuple(float(value) for value in parameters)), ''


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
