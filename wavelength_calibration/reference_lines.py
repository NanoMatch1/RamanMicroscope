"""
Reference spectral lines with wavelengths known independently of the instrument.

Wavelengths are in AIR, in nm, which is the convention for lamp line tables
and for the rest of this codebase. Values are the standard mercury lines
(NIST Atomic Spectra Database); check against the ASD before relying on the
third decimal place. At the PIXIS dispersion (~0.078 nm per pixel) a
0.002 nm table error is 1/40 of a pixel and is negligible.

Diffraction orders
------------------
A grating sends wavelength lambda in order m to the same angle as wavelength
m * lambda in first order (grating equation: m * lambda = d (sin a + sin b)).
The TRIAX position and the CCD axis are calibrated in first-order terms, so a
UV/blue mercury line seen in second order appears at twice its wavelength.
That is what makes a UV mercury lamp useful in the near infrared: the
404.656 nm and 407.783 nm lines appear at 809.313 nm and 815.566 nm.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReferenceLine:
    """One known emission line, observed in a particular diffraction order."""

    name: str
    wavelength_nm: float
    diffraction_order: int = 1
    wavelength_uncertainty_nm: float = 0.002

    @property
    def apparent_wavelength_nm(self):
        """Where the line appears on the first-order wavelength scale."""
        return self.wavelength_nm * self.diffraction_order


MERCURY_LINE_WAVELENGTHS_AIR_NM = {
    'Hg 365.015': 365.015,
    'Hg 404.656': 404.656,
    'Hg 407.783': 407.783,
    'Hg 435.833': 435.833,
    'Hg 546.074': 546.074,
    'Hg 576.960': 576.960,
    'Hg 579.066': 579.066,
}


def mercury_lines_in_window(window_start_nm, window_end_nm, diffraction_orders=(1, 2)):
    """
    Mercury lines whose apparent (first-order-equivalent) wavelength falls in a window.

    Parameters
    ----------
    window_start_nm, window_end_nm : float
        Window on the first-order wavelength scale, e.g. the TRIAX range of interest.
    diffraction_orders : iterable of int
        Orders to consider. Second order needs no order-sorting filter in the
        beam; check that nothing blocks the blue light before the TRIAX.

    Returns
    -------
    list of ReferenceLine, sorted by apparent wavelength.
    """
    lines = []
    for name, wavelength_nm in MERCURY_LINE_WAVELENGTHS_AIR_NM.items():
        for order in diffraction_orders:
            line = ReferenceLine(name=name,
                                 wavelength_nm=wavelength_nm, diffraction_order=order)
            if window_start_nm <= line.apparent_wavelength_nm <= window_end_nm:
                lines.append(line)
    return sorted(lines, key=lambda line: line.apparent_wavelength_nm)


def externally_measured_line(wavelength_nm, uncertainty_nm, name='external'):
    """
    A line whose wavelength was measured on another instrument.

    Use this for the Tiger laser read on the spare calibrated spectrometer.
    The uncertainty should be that spectrometer's real accuracy (typically
    0.1-0.5 nm for a compact CCD spectrometer), not its display resolution;
    the fit weights each point by it.
    """
    return ReferenceLine(name=name, wavelength_nm=float(wavelength_nm),
                         diffraction_order=1, wavelength_uncertainty_nm=float(uncertainty_nm))
