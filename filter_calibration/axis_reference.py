"""
How far a frame's wavelength axis is off, from the argon lines in an Ar-Hg frame taken at the
same TRIAX position: the correction the edges at that position need.

The TRIAX's wavelength axis is off by a different amount at each position (a fixed pattern of
about +/-0.13 nm, RAM-F3) and its zero can move between sessions (RAM-F1). The edges are read on
the axis saved with each frame, so each centre's edges are corrected by its own Ar-Hg frame:
correction = -(median over lines of measured minus NIST wavelength).

The lines are measured in the band's rows: lines curve along the slit, so the correction for
the band's light must come from the rows the band occupies (on 2026-11-18 it was +0.30 nm in the
band's rows and +0.8 nm in the rows the lamp lit most). The frame should be taken at about 50 um:
at 500 um the lamp lights a different part of the slit from the filtered light (RAM-F6).

Only lines confirmed unblended on this instrument are used
(wavelength_calibration.reference_lines.CONFIRMED_ARGON_REFERENCE_WAVELENGTHS_NM). A line is
looked for within search_nm of where the axis puts it, fitted with a Gaussian
(wavelength_calibration.line_peaks.fit_line_peak), and left out if it is saturated, faint, or
too near the chip end.

Pure: arrays in, results out.
"""

from dataclasses import dataclass, field

import numpy as np

from wavelength_calibration.line_peaks import fit_line_peak
from wavelength_calibration.reference_lines import (ARGON_LINES_NIST,
                                                    CONFIRMED_ARGON_REFERENCE_WAVELENGTHS_NM)

ISOLATION_MINIMUM_INTENSITY = 1000     # NIST relative intensity of a neighbour that could be
                                       # mistaken for the line


@dataclass(frozen=True)
class AxisReferenceSettings:
    band_half_height_rows: int = 10
    search_nm: float = 1.5              # the axis can be this far off
    refine_nm: float = 0.3              # second pass: this far from the coarse offset
    fit_half_window_pixels: int = 5
    minimum_signal_to_noise: float = 20.0
    saturation_level: float = 65535.0
    chip_end_margin_pixels: int = 15


@dataclass
class ArgonLineReading:
    nist_nm: float
    measured_nm: float = None
    signal_to_noise: float = None
    used: bool = False
    reason: str = ''                    # why it was left out


@dataclass
class AxisReference:
    """The correction for one TRIAX position, and the lines it rests on."""
    correction_nm: float = None         # add to an edge read on this position's axis
    spread_nm: float = None             # rms of (measured - NIST) about their median
    lines: list = field(default_factory=list)
    band_rows: tuple = None
    triax_steps: int = None             # from the run log, to match frames at the same position
    slit_width_um: float = None         # from the run log ('ren')

    @property
    def lines_used(self):
        return [line for line in self.lines if line.used]


def band_rows_spectrum(image, band_row, half_height_rows):
    """Mean over the band's rows, less its median (a flat background)."""
    first, last = max(int(round(band_row - half_height_rows)), 0), \
        min(int(round(band_row + half_height_rows)) + 1, image.shape[0])
    spectrum = image[first:last].mean(axis=0)
    return spectrum - np.median(spectrum), (first, last), image[first:last].max(axis=0)


def _pixel_of(wavelength_nm, axis_nm):
    pixels = np.arange(len(axis_nm), dtype=float)
    if axis_nm[-1] > axis_nm[0]:
        return float(np.interp(wavelength_nm, axis_nm, pixels))
    return float(np.interp(wavelength_nm, axis_nm[::-1], pixels[::-1]))


def _brightest_pixel_near(spectrum, centre_pixel, half_width_pixels):
    pixels = np.arange(len(spectrum))
    near = np.abs(pixels - centre_pixel) <= half_width_pixels
    return int(pixels[near][np.argmax(spectrum[near])])


def _isolated(nist_nm, distance_nm):
    """No other bright argon line (NIST intensity >= ISOLATION_MINIMUM_INTENSITY) this close."""
    return all(abs(other_nm - nist_nm) > distance_nm or other_nm == nist_nm
               for other_nm, intensity in ARGON_LINES_NIST
               if intensity >= ISOLATION_MINIMUM_INTENSITY)


def measure_axis_reference(image, wavelength_nm, band_row, settings=AxisReferenceSettings(),
                           line_wavelengths_nm=CONFIRMED_ARGON_REFERENCE_WAVELENGTHS_NM):
    """AxisReference from an Ar-Hg frame, measured in the rows around band_row.

    Two passes, so that a brighter neighbour is never taken for a line: first the coarse offset
    from lines with no bright neighbour within twice search_nm (each the brightest pixel within
    search_nm), then every line within refine_nm of where that offset puts it."""
    spectrum, band_rows, column_maximum = band_rows_spectrum(image, band_row,
                                                             settings.band_half_height_rows)
    nm_per_pixel = abs(np.mean(np.diff(wavelength_nm)))
    search_pixels = settings.search_nm / nm_per_pixel
    margin = settings.chip_end_margin_pixels + search_pixels
    on_chip = [nist_nm for nist_nm in line_wavelengths_nm
               if margin <= _pixel_of(nist_nm, wavelength_nm) <= len(spectrum) - 1 - margin]
    coarse_offsets = []
    for nist_nm in on_chip:
        if _isolated(nist_nm, 2 * settings.search_nm):
            peak_pixel = _brightest_pixel_near(spectrum, _pixel_of(nist_nm, wavelength_nm),
                                               search_pixels)
            coarse_offsets.append(np.interp(peak_pixel, np.arange(len(wavelength_nm)),
                                            wavelength_nm) - nist_nm)
    coarse_offset_nm = float(np.median(coarse_offsets)) if coarse_offsets else 0.0

    readings = []
    for nist_nm in line_wavelengths_nm:
        reading = ArgonLineReading(nist_nm=float(nist_nm))
        readings.append(reading)
        if nist_nm not in on_chip:
            reading.reason = 'off the chip'
            continue
        peak_pixel = _brightest_pixel_near(
            spectrum, _pixel_of(nist_nm + coarse_offset_nm, wavelength_nm),
            settings.refine_nm / nm_per_pixel)
        window = slice(peak_pixel - settings.fit_half_window_pixels,
                       peak_pixel + settings.fit_half_window_pixels + 1)
        if np.max(column_maximum[window]) >= settings.saturation_level:
            reading.reason = 'saturated'
            continue
        fit = fit_line_peak(spectrum, peak_pixel,
                            half_window_pixels=settings.fit_half_window_pixels)
        if fit is None:
            reading.reason = 'fit failed'
            continue
        reading.measured_nm = float(np.interp(fit.centre_pixel, np.arange(len(wavelength_nm)),
                                              wavelength_nm))
        reading.signal_to_noise = float(fit.signal_to_noise)
        if fit.signal_to_noise < settings.minimum_signal_to_noise:
            reading.reason = f'faint (S/N {fit.signal_to_noise:.0f})'
            continue
        if abs(reading.measured_nm - nist_nm - coarse_offset_nm) > settings.refine_nm:
            reading.reason = 'fit left the line'
            continue
        reading.used = True
    offsets = np.array([reading.measured_nm - reading.nist_nm for reading in readings
                        if reading.used])
    if len(offsets) == 0:
        return AxisReference(lines=readings, band_rows=band_rows)
    median_offset = float(np.median(offsets))
    return AxisReference(correction_nm=-median_offset,
                         spread_nm=float(np.sqrt(np.mean((offsets - median_offset) ** 2))),
                         lines=readings, band_rows=band_rows)
