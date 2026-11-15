"""
Which CCD rows make the spectrum, and how they are binned.

The spectrograph images the entrance slit as a band of rows across the PIXIS (1024 x 1024);
the spectrum runs along the columns. Reading only the rows of that band (the region of
interest, ROI) cuts the readout time and the file size, and leaves out rows that hold only
dark current and read noise.

Two ways to combine the ROI rows into one spectrum:

- software binning (`rows_binned_on_chip = 1`): every ROI row is read out and saved, and the
  rows are combined afterwards. Each row adds its own read noise, but the frame still shows
  where the slit image sits, how it is tilted, and which rows a cosmic ray hit.
- on-chip binning (`rows_binned_on_chip = row count`): the CCD sums the rows' charge before
  the single read of each column, so read noise enters once per column. Best for weak signals;
  the frame is one row, so the slit image can no longer be checked from the data. The summed
  charge is clipped at the ADC full scale (65535 counts), so bright lines saturate sooner.

A value between the two bins that many rows per output row.

Setting the ROI: `find_slit_image` locates the slit image on a full-sensor frame (the lamp
or laser on), which is what an automatic ROI uses; it follows the slit image while the
camera is being aligned and moves it. Before collecting data the rows should be chosen by
hand in the live viewer, around the slit image and no wider, so no rows of pure noise are
binned in (docs/user_guide.md).

Pure: no camera or GUI here.
"""

from dataclasses import asdict, dataclass, replace
import datetime

import numpy as np

SENSOR_ROWS = 1024
SENSOR_COLUMNS = 1024

MANUAL = 'manual'        # rows chosen by a person (live viewer or 'roi <first> <last>')
AUTOMATIC = 'automatic'  # rows found by find_slit_image
FULL_SENSOR = 'full sensor'


@dataclass(frozen=True)
class SpectralRoi:
    """Rows [first_row, last_row) of the full sensor, all columns, and how they are binned."""

    first_row: int
    last_row: int                 # exclusive
    rows_binned_on_chip: int = 1  # 1: software binning; row_count: on-chip binning
    source: str = MANUAL          # MANUAL, AUTOMATIC or FULL_SENSOR
    set_on: str = ''              # ISO time it was chosen

    def __post_init__(self):
        if not 0 <= self.first_row < self.last_row <= SENSOR_ROWS:
            raise ValueError(f"rows {self.first_row}..{self.last_row} are not inside the "
                             f"sensor's 0..{SENSOR_ROWS} (first row included, last excluded)")
        if not 1 <= self.rows_binned_on_chip <= self.row_count:
            raise ValueError(f"cannot bin {self.rows_binned_on_chip} rows on the chip in an ROI "
                             f"of {self.row_count} rows")

    @classmethod
    def full_sensor(cls):
        return cls(0, SENSOR_ROWS, 1, FULL_SENSOR, _now())

    @classmethod
    def from_dict(cls, stored):
        return cls(**{name: stored[name] for name in
                      ('first_row', 'last_row', 'rows_binned_on_chip', 'source', 'set_on')
                      if name in stored})

    def as_dict(self):
        return asdict(self)

    @property
    def row_count(self):
        return self.last_row - self.first_row

    @property
    def binned_on_chip(self):
        return self.rows_binned_on_chip == self.row_count and self.row_count > 1

    @property
    def binning_description(self):
        if self.rows_binned_on_chip == 1:
            return 'software binning (every row read out)'
        if self.binned_on_chip:
            return 'on-chip binning (all rows summed on the CCD)'
        return f'on-chip binning in groups of {self.rows_binned_on_chip} rows'

    def camera_roi(self):
        """(hstart, hend, vstart, vend, hbin, vbin) as pylablib's set_roi takes it; columns never
        binned."""
        return (0, SENSOR_COLUMNS, self.first_row, self.last_row, 1, self.rows_binned_on_chip)

    def with_rows(self, first_row, last_row, source=MANUAL):
        """The same binning mode on other rows (on-chip stays on-chip, software stays software)."""
        rows_binned = (last_row - first_row) if self.binned_on_chip else 1
        return SpectralRoi(int(first_row), int(last_row), rows_binned, source, _now())

    def with_rows_binned_on_chip(self, rows_binned_on_chip):
        """Bin this many rows on the chip; 'all' for every ROI row, 1 for software binning."""
        if rows_binned_on_chip == 'all':
            rows_binned_on_chip = self.row_count
        return replace(self, rows_binned_on_chip=int(rows_binned_on_chip), set_on=_now())

    def contains_rows(self, first_row, last_row):
        return self.first_row <= first_row and last_row <= self.last_row

    def describe(self):
        return (f"rows {self.first_row}..{self.last_row - 1} ({self.row_count} rows, "
                f"{self.source}), {self.binning_description}")


def roi_from_camera_readback(camera_roi, previous):
    """
    The SpectralRoi the camera actually set, from pylablib's get_roi() tuple (hstart, hend,
    vstart, vend, hbin, vbin); `previous` supplies the source and time. The camera may have
    trimmed the rows to a whole number of bins.
    """
    _hstart, _hend, vstart, vend, _hbin, vbin = (int(value) for value in camera_roi)
    return SpectralRoi(vstart, vend, vbin, previous.source, previous.set_on)


def frame_rows_to_bin(selected_rows, frame_row_count):
    """
    The frame rows [first, last) a viewer bins into its spectrum: the selected rows, kept inside
    the frame, or all of the frame's rows when no selected row is in it. A viewer's selection
    is in rows of the frame, so when the camera ROI changes (another number of rows, or one row
    binned on the chip) an old selection can lie outside the new frame; binning no rows gave an
    empty spectrum (2026-11-12, after 'roi auto').
    """
    if selected_rows is None:
        return 0, frame_row_count
    first_row = max(0, int(selected_rows[0]))
    last_row = min(frame_row_count, int(selected_rows[1]))
    if last_row <= first_row:
        return 0, frame_row_count
    return first_row, last_row


@dataclass(frozen=True)
class SlitImage:
    """Where the slit image lies on a full-sensor frame."""

    peak_row: int
    first_row: int                   # half-maximum edges of the summed row profile
    last_row: int                    # exclusive
    tilt_rows_per_1000_columns: float  # how far the slit image's centre moves across the chip
    signal_to_noise: float           # peak of the row profile over its noise

    @property
    def width_rows(self):
        return self.last_row - self.first_row

    def roi(self, margin_rows=3):
        """An automatic ROI: the half-maximum band, widened by the tilt and `margin_rows`."""
        tilt_spread_rows = int(np.ceil(abs(self.tilt_rows_per_1000_columns)
                                       * SENSOR_COLUMNS / 1000 / 2))
        first_row = max(0, self.first_row - margin_rows - tilt_spread_rows)
        last_row = min(SENSOR_ROWS, self.last_row + margin_rows + tilt_spread_rows)
        return SpectralRoi(first_row, last_row, 1, AUTOMATIC, _now())

    def describe(self):
        return (f"slit image centred on row {self.peak_row}, half-maximum rows "
                f"{self.first_row}..{self.last_row - 1} ({self.width_rows} rows), tilted "
                f"{self.tilt_rows_per_1000_columns:+.1f} rows per 1000 columns, "
                f"signal-to-noise {self.signal_to_noise:.0f}")


class SlitImageNotFound(ValueError):
    """The frame shows no slit image (light off or blocked, or the image is off the chip)."""


def find_slit_image(frame, first_sensor_row=0, minimum_signal_to_noise=10.0,
                    maximum_smear_step_fraction=0.5):
    """
    Locate the slit image on a frame (rows x columns) of the lit slit: lamp lines or a laser
    line (light in some columns, not a continuum filling all of them). `first_sensor_row` is
    the sensor row of the frame's first row (0 for a full-sensor frame). Raises
    SlitImageNotFound if nothing stands out of the noise, or if the readout smear is too strong
    against the slit image to place its edges.

    Steps:
    1. Background: each column's median over the rows, then the slope down the rows that all
       columns share (bias and dark current change from the first row read to the last; on
       the PIXIS by ~130 counts per pixel at 1 s, 2026-11-12), taken from the darker half of
       the columns.
    2. Row profile: the sum of the lit columns only (the dark ones add noise and no signal).
    3. Noise: from row-to-row differences of the profile, so slow structure (what is left of
       the slope, readout smear) does not count as noise.
    4. The slit image is the band around the profile's peak down to half its height, each edge
       measured from the background on its own side. Readout smear (the PIXIS has no shutter:
       light keeps landing on the rows while they are shifted out) puts a step in the lit
       columns' background between the two sides; if the step is more than
       `maximum_smear_step_fraction` of the slit image's height, the edges cannot be placed
       and a longer exposure is needed.
    The tilt comes from the centroid row of the brightest columns.
    """
    frame = np.asarray(frame, dtype=float)
    if frame.ndim != 2 or frame.shape[0] < 5:
        raise SlitImageNotFound(f"need a frame with rows and columns, got shape {frame.shape}")
    light = _light_above_background(frame)
    raw_profile = light[:, _lit_columns(light)].sum(axis=1)
    row_profile = np.convolve(raw_profile, np.ones(3) / 3, mode='same')
    # Differences of independent rows have sqrt(2) x their noise; averaging 3 rows divides it
    # by sqrt(3).
    profile_noise = 1.4826 * np.median(np.abs(np.diff(raw_profile))) / np.sqrt(6)
    peak_row = int(np.argmax(row_profile))
    # First guess of the band from the background either side of the peak, then again with the
    # background from the rows outside that band only (the first guess counts its wings in). A
    # side needs 50 rows of its own to count: on a frame of little more than the slit image
    # (an ROI), the few rows left are its wings, not background.
    background = _background_either_side(row_profile, peak_row, peak_row + 1)
    first_row, last_row = _half_height_band(row_profile, peak_row, background)
    background = _background_either_side(row_profile, first_row, last_row, guard_rows=10,
                                        minimum_rows=50)
    first_row, last_row = _half_height_band(row_profile, peak_row, background)

    height = row_profile[peak_row] - max(background)
    signal_to_noise = float(height / max(profile_noise, 1e-9))
    if signal_to_noise < minimum_signal_to_noise:
        raise SlitImageNotFound(
            f"no slit image: the brightest rows stand only {signal_to_noise:.1f} x the noise "
            f"above the rest (need {minimum_signal_to_noise:.0f}); is the light on and reaching "
            "the spectrograph?")
    smear_step = abs(background.after - background.before)
    if background.both_sides_measured and smear_step > maximum_smear_step_fraction * height:
        raise SlitImageNotFound(
            f"the slit image is too faint against the readout smear to find its edges (the "
            f"background differs by {smear_step / height:.0%} of the slit image's height between "
            "its two sides: the PIXIS has no shutter, so light lands on the rows while they are "
            "read out); lengthen the exposure")

    tilt = _slit_image_tilt(light, first_row, last_row)
    return SlitImage(peak_row=peak_row + first_sensor_row,
                     first_row=first_row + first_sensor_row,
                     last_row=last_row + first_sensor_row,
                     tilt_rows_per_1000_columns=tilt, signal_to_noise=signal_to_noise)


def _light_above_background(frame, row_background_smoothing_rows=25):
    """
    The frame less its background: each column's median, then the slope down the rows that all
    columns share, from the darker half of the columns (smoothed along the rows; it is slow,
    and every column has it subtracted, so its noise must stay well below a pixel's).
    """
    above_column_median = frame - np.median(frame, axis=0)[None, :]
    column_brightness = _column_brightness(above_column_median)
    dark_columns = column_brightness <= np.median(column_brightness)
    row_background = np.median(above_column_median[:, dark_columns], axis=1)
    if frame.shape[0] > row_background_smoothing_rows:
        padded = np.pad(row_background, row_background_smoothing_rows // 2, mode='edge')
        row_background = np.convolve(padded, np.ones(row_background_smoothing_rows)
                                     / row_background_smoothing_rows, mode='valid')
    return above_column_median - row_background[:, None]


def _column_brightness(above_background, smoothing_rows=15):
    """How far each column's brightest band of `smoothing_rows` rows stands above the column's
    median: high in columns crossed by a line, low in dark ones. Averaging the rows first keeps
    single hot pixels and noise from looking like light."""
    smoothing_rows = min(smoothing_rows, above_background.shape[0])
    kernel = np.ones(smoothing_rows) / smoothing_rows
    smoothed = np.apply_along_axis(lambda column: np.convolve(column, kernel, mode='valid'),
                                   0, above_background)
    return smoothed.max(axis=0) - np.median(smoothed, axis=0)


def _lit_columns(light, column_signal_fraction=0.3):
    """Columns at least `column_signal_fraction` as bright as the brightest one."""
    column_brightness = _column_brightness(light)
    return column_brightness >= column_signal_fraction * column_brightness.max()


@dataclass(frozen=True)
class _BackgroundEitherSide:
    """The row profile's background before and after the slit image."""

    before: float
    after: float
    both_sides_measured: bool  # False: one side had too few rows, and has the other's value

    def __iter__(self):
        return iter((self.before, self.after))


def _background_either_side(row_profile, first_row, last_row, guard_rows=0, minimum_rows=1):
    """
    The profile's median over the rows before `first_row` and after `last_row`, leaving
    `guard_rows` next to each. A side with fewer than `minimum_rows` rows (the band reaches the
    frame's edge) takes the other side's value; with neither, the profile's lowest value.
    """
    before = row_profile[:max(0, first_row - guard_rows)]
    after = row_profile[last_row + guard_rows:]
    before_measured, after_measured = before.size >= minimum_rows, after.size >= minimum_rows
    if not (before_measured or after_measured):
        lowest = float(row_profile.min())
        return _BackgroundEitherSide(lowest, lowest, False)
    background_before = float(np.median(before)) if before_measured else None
    background_after = float(np.median(after)) if after_measured else background_before
    if background_before is None:
        background_before = background_after
    return _BackgroundEitherSide(background_before, background_after,
                                 before_measured and after_measured)


def _half_height_band(row_profile, peak_row, background, bridged_gap_rows=15):
    """
    [first_row, last_row) around the peak, out to the last rows at half the peak's height
    above the background on each side. Dust on the slit jaws casts dark rows across the slit
    image (2026-11-12: a dip to a third of the peak, ~10 rows wide); gaps of up to
    `bridged_gap_rows` rows below half height are part of the band.
    """
    peak = row_profile[peak_row]

    def outermost_row(half_height, step):
        row = peak_row
        while True:
            rows_ahead = [row + step * distance for distance in range(1, bridged_gap_rows + 2)]
            rows_above = [ahead for ahead in rows_ahead if 0 <= ahead < len(row_profile)
                          and row_profile[ahead] >= half_height]
            if not rows_above:
                return row
            row = rows_above[0]

    first_row = outermost_row(background.before + (peak - background.before) / 2, -1)
    last_row = outermost_row(background.after + (peak - background.after) / 2, +1) + 1
    return first_row, last_row


def _slit_image_tilt(above_background, first_row, last_row, column_signal_fraction=0.3):
    """
    Slope of the slit image's centroid row against column, from the columns where the light is
    (at least `column_signal_fraction` of the brightest column's signal; dark columns would only
    add centroids of noise at the band's middle and flatten the slope).
    """
    width = last_row - first_row
    band_first = max(0, first_row - width)
    band_last = min(above_background.shape[0], last_row + width)
    band = np.clip(above_background[band_first:band_last], 0, None)
    column_signal = band.sum(axis=0)
    lit_columns = np.flatnonzero(column_signal >= column_signal_fraction * column_signal.max())
    if lit_columns.size < 3 or np.ptp(lit_columns) < 50:  # one line: no lever arm for a slope
        return 0.0
    rows = np.arange(band_first, band_last, dtype=float)
    # Centroid of each column's top half only, for the same reason.
    column_profiles = band[:, lit_columns]
    top_half = np.where(column_profiles >= 0.5 * column_profiles.max(axis=0), column_profiles, 0.0)
    centroids = (top_half * rows[:, None]).sum(axis=0) / top_half.sum(axis=0)
    slope_rows_per_column = np.polyfit(lit_columns.astype(float), centroids, 1)[0]
    return float(slope_rows_per_column * 1000)


def _now():
    return datetime.datetime.now().isoformat(timespec='seconds')
