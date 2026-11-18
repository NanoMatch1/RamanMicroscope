"""
One g2 pinhole scan: how much light gets through the pinhole at each g2 count, and where the
middle of that window is.

The CCD is the detector. In each frame the filtered halogen light is a thin band along the slit
(edge_fit.py finds it); its rows are summed column by column, after the background either side
of the band is removed. As g2 turns, the band also moves along the slit (the frame-flipping
periscope turns g2's pointing into a row on the CCD), so the band's centre line is found in the
frames where it is bright, fitted as a straight line in the g2 count, and every frame, dim ones
included, is summed along that predicted line. That fit also gives the rows per g2 step and the
row of the band when the beam is centred on the pinhole: the target row (issue #37).

Light against the g2 count is fitted with a window model: a top-hat (the pinhole, `width`
steps) seen through a Gaussian blur (the beam profile, `sigma` steps),
    amplitude * (Phi((x - centre + width/2) / sigma) - Phi((x - centre - width/2) / sigma))
    + baseline.
When the beam is wider than the pinhole, width and sigma trade off, but the centre does not: it
is fixed by the symmetry of the two sides, whatever their shape, so neither the beam size nor
the pinhole size nor the CCD's response moves it. Only a profile clipped unevenly on one side
(an aperture elsewhere) does, which the fit residual shows.

The scan is fitted twice: with the light of every lit column summed (one centre per scan), and
per block of columns (block_nm wide), which gives the centre against wavelength. If g1 and g2
were exactly matched, every wavelength would leave stage 1 in the same direction and the block
centres would agree; their slope measures the mismatch, in g2 steps per nm.

Pure: arrays in, results out.
"""

import warnings
from dataclasses import dataclass, field

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.optimize import OptimizeWarning, curve_fit
from scipy.special import ndtr

from .edge_fit import (EdgeFitSettings, band_centre_line, band_rows_sum, brightest_band_row,
                       remove_flank_background)


@dataclass(frozen=True)
class PinholeScanSettings:
    band: EdgeFitSettings = EdgeFitSettings()   # band finding, flanks, rows summed
    lit_column_fraction: float = 0.25           # of the brightest column, for a column to count
    block_nm: float = 10.0                      # column blocks for the centre against wavelength
    minimum_block_columns: int = 20
    minimum_band_frames: int = 3                # frames with a band, to fit the band's line


@dataclass
class WindowFit:
    centre_count: float
    centre_uncertainty: float       # 1-sigma from the fit covariance, g2 steps
    width_steps: float              # the top-hat (pinhole) part
    sigma_steps: float              # the blur (beam profile) part
    amplitude: float
    baseline: float
    residual_fraction: float        # rms fit residual over the amplitude
    peak_inside_scan: bool          # the light falls to under half its peak at both scan ends
    parameters: tuple               # window_model parameters, for plots


@dataclass
class BandTrack:
    """The band's centre row against the g2 count, from the frames where it was found."""
    row_at_middle: tuple            # (rows per g2 step, intercept): row at the middle column
    slant_rows_per_column: float
    frame_counts: list              # g2 counts of the frames the line was fitted to
    frame_rows: list                # their band rows at the middle column
    first_row: float                # the band's lowest and highest predicted row over the scan
    last_row: float

    def row(self, g2_count):
        return float(np.polyval(self.row_at_middle, g2_count))


@dataclass
class ScanLight:
    """Light through the pinhole per frame, overall and per column block."""
    g2_counts: np.ndarray
    total_light: np.ndarray                     # summed over the lit columns, per frame
    block_wavelengths_nm: list                  # middle wavelength of each block
    block_light: list                           # per block, light per frame
    lit_columns: np.ndarray = field(repr=False, default=None)


def window_model(count, amplitude, centre, width, sigma, baseline):
    half_width = width / 2
    return amplitude * (ndtr((count - centre + half_width) / sigma)
                        - ndtr((count - centre - half_width) / sigma)) + baseline


def fit_window(g2_counts, light):
    """WindowFit of light against g2 count, or None if there is no window to fit."""
    counts = np.asarray(g2_counts, dtype=float)
    light = np.asarray(light, dtype=float)
    if len(counts) < 6:
        return None
    baseline_guess = float(np.percentile(light, 10))
    above = np.clip(light - baseline_guess, 0, None)
    peak = float(above.max())
    if peak <= 0:
        return None
    centre_guess = float(np.sum(counts * above) / above.sum())
    full_width_half_maximum = float(np.ptp(counts[above >= peak / 2])) or 1.0
    initial = [peak, centre_guess, full_width_half_maximum / 2,
               max(full_width_half_maximum / 4, 0.5), baseline_guess]
    lower = [0.0, counts.min(), 0.0, 0.1, -np.inf]
    upper = [np.inf, counts.max(), np.ptp(counts), np.ptp(counts), np.inf]
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', OptimizeWarning)
            parameters, covariance = curve_fit(window_model, counts, light, p0=initial,
                                               bounds=(lower, upper), maxfev=20000)
    except (RuntimeError, ValueError):
        return None
    amplitude, centre, width, sigma, baseline = parameters
    centre_uncertainty = float(np.sqrt(covariance[1, 1]))
    if amplitude <= 0 or not np.isfinite(centre_uncertainty):
        return None
    residual = light - window_model(counts, *parameters)
    order = np.argsort(counts)
    ends = light[order][[0, -1]] - baseline
    return WindowFit(
        centre_count=float(centre), centre_uncertainty=centre_uncertainty,
        width_steps=float(width), sigma_steps=float(sigma), amplitude=float(amplitude),
        baseline=float(baseline), residual_fraction=float(np.std(residual) / amplitude),
        peak_inside_scan=bool(np.all(ends < 0.5 * amplitude)),
        parameters=tuple(float(value) for value in parameters))


def track_band(images, g2_counts, settings=PinholeScanSettings()):
    """BandTrack from the frames whose band is found, or None if too few are."""
    counts, rows, slants, weights = [], [], [], []
    middle_column = images[0].shape[1] // 2
    for image, g2_count in zip(images, g2_counts):
        estimate = brightest_band_row(image)
        provisional = remove_flank_background(
            image, np.full(image.shape[1], estimate, dtype=float), settings.band)
        line = band_centre_line(provisional, (estimate - settings.band.band_search_half_rows,
                                              estimate + settings.band.band_search_half_rows),
                                settings.band)
        if line is None:
            continue
        counts.append(float(g2_count))
        rows.append(float(np.polyval(line, middle_column)))
        slants.append(float(line[0]))
        weights.append(float(np.percentile(image, 99.9) - np.median(image)))
    if len(counts) < settings.minimum_band_frames:
        return None
    if len(set(counts)) > 1:
        row_line = np.polyfit(counts, rows, 1, w=np.sqrt(np.clip(weights, 1e-9, None)))
    else:
        row_line = np.array([0.0, rows[0]])
    predicted = np.polyval(row_line, [min(g2_counts), max(g2_counts)])
    return BandTrack(row_at_middle=tuple(float(value) for value in row_line),
                     slant_rows_per_column=float(np.median(slants)),
                     frame_counts=counts, frame_rows=rows,
                     first_row=float(predicted.min()), last_row=float(predicted.max()))


def scan_light(images, wavelength_nm, g2_counts, band_track, settings=PinholeScanSettings()):
    """ScanLight: each frame's band summed along the tracked line, over the lit columns."""
    columns = np.arange(images[0].shape[1])
    middle_column = len(columns) // 2
    signals = []
    for image, g2_count in zip(images, g2_counts):
        centre_rows = band_track.row(g2_count) + band_track.slant_rows_per_column * \
            (columns - middle_column)
        cleaned = remove_flank_background(image, centre_rows, settings.band)
        signals.append(band_rows_sum(cleaned, centre_rows, settings.band.band_half_height_rows))
    signals = np.array(signals)
    brightest = uniform_filter1d(signals.max(axis=0), settings.band.smoothing_columns)
    lit_columns = brightest >= settings.lit_column_fraction * brightest.max()
    total_light = signals[:, lit_columns].sum(axis=1)

    block_wavelengths, block_light = [], []
    lit_wavelengths = np.asarray(wavelength_nm)[lit_columns]
    if len(lit_wavelengths):
        edges = np.arange(lit_wavelengths.min(), lit_wavelengths.max() + settings.block_nm,
                          settings.block_nm)
        for low, high in zip(edges[:-1], edges[1:]):
            in_block = lit_columns & (wavelength_nm >= low) & (wavelength_nm < high)
            if in_block.sum() < settings.minimum_block_columns:
                continue
            block_wavelengths.append(float(np.mean(np.asarray(wavelength_nm)[in_block])))
            block_light.append(signals[:, in_block].sum(axis=1))
    return ScanLight(g2_counts=np.asarray(g2_counts, dtype=float), total_light=total_light,
                     block_wavelengths_nm=block_wavelengths, block_light=block_light,
                     lit_columns=lit_columns)
