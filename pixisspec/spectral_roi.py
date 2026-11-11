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


def find_slit_image(frame, first_sensor_row=0, minimum_signal_to_noise=10.0):
    """
    Locate the slit image on a frame (rows x columns) of the lit slit: lamp lines, laser, or
    any spectrum. `first_sensor_row` is the sensor row of the frame's first row (0 for a
    full-sensor frame). Raises SlitImageNotFound if nothing stands out of the noise.

    Each column's own background (its median over the rows) is subtracted, the result summed
    over the columns gives the row profile, and the slit image is the band around its peak down
    to half the peak. The tilt comes from the centroid row of the brightest columns.
    """
    frame = np.asarray(frame, dtype=float)
    if frame.ndim != 2 or frame.shape[0] < 5:
        raise SlitImageNotFound(f"need a frame with rows and columns, got shape {frame.shape}")
    above_background = frame - np.median(frame, axis=0)[None, :]
    row_profile = np.convolve(above_background.sum(axis=1), np.ones(3) / 3, mode='same')
    profile_noise = 1.4826 * np.median(np.abs(row_profile - np.median(row_profile)))
    peak_row = int(np.argmax(row_profile))
    peak = row_profile[peak_row]
    signal_to_noise = float(peak / max(profile_noise, 1e-9))
    if signal_to_noise < minimum_signal_to_noise:
        raise SlitImageNotFound(
            f"no slit image: the brightest rows stand only {signal_to_noise:.1f} x the noise "
            f"above the rest (need {minimum_signal_to_noise:.0f}); is the light on and reaching "
            "the spectrograph?")
    first_row = peak_row
    while first_row > 0 and row_profile[first_row - 1] >= peak / 2:
        first_row -= 1
    last_row = peak_row + 1
    while last_row < len(row_profile) and row_profile[last_row] >= peak / 2:
        last_row += 1

    tilt = _slit_image_tilt(above_background, first_row, last_row)
    return SlitImage(peak_row=peak_row + first_sensor_row,
                     first_row=first_row + first_sensor_row,
                     last_row=last_row + first_sensor_row,
                     tilt_rows_per_1000_columns=tilt, signal_to_noise=signal_to_noise)


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
