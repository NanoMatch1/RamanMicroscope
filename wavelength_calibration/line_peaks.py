"""
Find and fit spectral line peaks in a 1D spectrum, in PIXEL units.

Working in pixels is the whole point. A line position measured against the
software's own wavelength axis can only ever agree with that axis, which is
how the previous pixel calibration became circular (docs/calibration.md,
"The circular reference"). Here the measured quantity is "which pixel the
line landed on", and wavelength only enters later, from the reference table.
"""

from dataclasses import dataclass, asdict

import numpy as np
from scipy.optimize import curve_fit
from scipy.signal import find_peaks


@dataclass
class LinePeakFit:
    """A Gaussian-plus-constant fit to one line, all positions in pixels."""

    centre_pixel: float
    centre_uncertainty_pixels: float
    amplitude: float
    sigma_pixels: float
    baseline: float
    signal_to_noise: float

    def as_dict(self):
        return asdict(self)


@dataclass
class DetectedPeak:
    """One peak found in a spectrum, before anyone says which line it is."""

    centre_pixel: float
    centre_uncertainty_pixels: float  # fit, background noise only: too small for bright lines
    height_counts: float              # fitted amplitude above the local baseline
    sigma_pixels: float
    saturated: bool                   # the peak's window reaches the saturation level


def slit_image_rows(image, half_height_rows=10):
    """(first row, last row + 1) of the band centred on the brightest row of a 2D frame."""
    image = np.asarray(image, dtype=float)
    if image.ndim == 3:
        image = image[:, :, 0]
    brightest_row = int(np.argmax(image.sum(axis=1)))
    first_row = max(0, brightest_row - half_height_rows)
    return first_row, min(image.shape[0], brightest_row + half_height_rows + 1)


def collapse_image_to_spectrum(image, half_height_rows=10, saturation_level=None, row_band=None):
    """
    Turn a 2D CCD frame (rows x columns) into a 1D spectrum (one value per column).

    The spectrum is the mean over a band of rows: `row_band` (first, last + 1)
    if given, otherwise centred on the brightest row of this frame. A line
    walk should fix the band from its first frame: if the slit image is
    tilted on the chip, a band that moves from frame to frame moves the lines.
    A 1D input is returned unchanged.

    If `saturation_level` is given, any column with a pixel at or above it
    inside the band is set to exactly `saturation_level`. Averaging would
    otherwise hide a clipped pixel, and the line walk skips lines whose
    window reaches the saturation level.
    """
    image = np.asarray(image, dtype=float)
    if image.ndim == 1:
        return image
    if image.ndim == 3:
        image = image[:, :, 0]

    if row_band is None:
        row_band = slit_image_rows(image, half_height_rows)
    first_row, last_row = row_band
    band = image[first_row:last_row, :]
    spectrum = band.mean(axis=0)
    if saturation_level is not None:
        spectrum[np.any(band >= saturation_level, axis=0)] = saturation_level
    return spectrum


def estimate_background_and_noise(spectrum):
    """Robust (median, scaled MAD) estimate; unaffected by a few bright lines."""
    spectrum = np.asarray(spectrum, dtype=float)
    background_level = float(np.median(spectrum))
    median_absolute_deviation = float(np.median(np.abs(spectrum - background_level)))
    noise_standard_deviation = 1.4826 * median_absolute_deviation
    return background_level, max(noise_standard_deviation, 1e-9)


def find_line_peaks(spectrum, minimum_signal_to_noise=10.0, minimum_separation_pixels=5):
    """
    Candidate line positions (integer pixel indices), brightest first.

    A candidate must rise at least `minimum_signal_to_noise` noise standard
    deviations above the robust background.
    """
    spectrum = np.asarray(spectrum, dtype=float)
    background_level, noise_standard_deviation = estimate_background_and_noise(spectrum)
    peak_indices, peak_properties = find_peaks(
        spectrum,
        height=background_level + minimum_signal_to_noise * noise_standard_deviation,
        distance=minimum_separation_pixels,
    )
    brightest_first = np.argsort(peak_properties['peak_heights'])[::-1]
    return [int(peak_indices[index]) for index in brightest_first]


def _gaussian_on_constant(pixel, amplitude, centre_pixel, sigma_pixels, baseline):
    return baseline + amplitude * np.exp(-0.5 * ((pixel - centre_pixel) / sigma_pixels) ** 2)


def fit_line_peak(spectrum, approximate_pixel, half_window_pixels=12):
    """
    Fit one line near `approximate_pixel`.

    Returns a LinePeakFit, or None if the fit fails or the window would be
    cut by the edge of the chip (an edge-clipped line has a biased centre).
    The centre uncertainty comes from the fit covariance with each point
    weighted by the robust noise estimate, so it is a real 1-sigma value.
    """
    spectrum = np.asarray(spectrum, dtype=float)
    approximate_pixel = int(round(approximate_pixel))
    first_pixel = approximate_pixel - half_window_pixels
    last_pixel = approximate_pixel + half_window_pixels + 1
    if first_pixel < 0 or last_pixel > len(spectrum):
        return None

    window_pixels = np.arange(first_pixel, last_pixel, dtype=float)
    window_values = spectrum[first_pixel:last_pixel]
    _, noise_standard_deviation = estimate_background_and_noise(spectrum)

    baseline_guess = float(np.min(window_values))
    amplitude_guess = float(np.max(window_values) - baseline_guess)
    centre_guess = float(window_pixels[np.argmax(window_values)])
    try:
        fitted_parameters, covariance = curve_fit(
            _gaussian_on_constant, window_pixels, window_values,
            p0=[amplitude_guess, centre_guess, 2.0, baseline_guess],
            sigma=np.full_like(window_values, noise_standard_deviation),
            absolute_sigma=True,
            bounds=([0, first_pixel, 0.3, -np.inf], [np.inf, last_pixel - 1, half_window_pixels, np.inf]),
            maxfev=5000,
        )
    except (RuntimeError, ValueError):
        return None

    amplitude, centre_pixel, sigma_pixels, baseline = fitted_parameters
    centre_uncertainty_pixels = float(np.sqrt(covariance[1, 1]))
    if not np.isfinite(centre_uncertainty_pixels):
        return None

    return LinePeakFit(
        centre_pixel=float(centre_pixel),
        centre_uncertainty_pixels=centre_uncertainty_pixels,
        amplitude=float(amplitude),
        sigma_pixels=float(sigma_pixels),
        baseline=float(baseline),
        signal_to_noise=float(amplitude / noise_standard_deviation),
    )


def find_and_fit_peaks(spectrum, minimum_signal_to_noise=10.0, saturation_level=None,
                       half_window_pixels=5):
    """
    Every peak in a spectrum, fitted, brightest first.

    The fit window is narrowed to half the distance to the nearest other peak
    (at least 3 px), so a neighbour's tail stays out of it. A peak whose
    window reaches `saturation_level` is kept, marked saturated: it still
    helps identify the frame, but its centre is biased and is never used as a
    measurement. Peaks too close to the chip edge to fit are left out.
    """
    spectrum = np.asarray(spectrum, dtype=float)
    candidate_pixels = find_line_peaks(spectrum, minimum_signal_to_noise=minimum_signal_to_noise)
    peaks = []
    for pixel in candidate_pixels:
        other_pixels = [other for other in candidate_pixels if other != pixel]
        nearest_other = min((abs(other - pixel) for other in other_pixels), default=np.inf)
        window = int(max(3, min(half_window_pixels, nearest_other // 2)))
        fit = fit_line_peak(spectrum, pixel, half_window_pixels=window)
        if fit is None:
            continue
        window_values = spectrum[max(0, pixel - window):pixel + window + 1]
        saturated = saturation_level is not None and \
            float(np.max(window_values)) >= saturation_level
        peaks.append(DetectedPeak(centre_pixel=fit.centre_pixel,
                                  centre_uncertainty_pixels=fit.centre_uncertainty_pixels,
                                  height_counts=fit.amplitude, sigma_pixels=fit.sigma_pixels,
                                  saturated=bool(saturated)))
    return sorted(peaks, key=lambda peak: -peak.height_counts)
