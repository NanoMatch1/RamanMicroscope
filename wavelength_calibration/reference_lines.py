"""
Reference spectral lines with wavelengths known independently of the instrument.

Wavelengths are in AIR, in nm, which is the convention for lamp line tables
and for the rest of this codebase. At the PIXIS dispersion (~0.078 nm per
pixel) a table error of 0.005 nm is 1/16 of a pixel and is negligible.

The lab lamp is an argon-mercury (Ar-Hg) pencil lamp. Its label lists the
lines below; the values are taken from the label and agree with the NIST
Atomic Spectra Database to 0.005 nm or better.

Lines the lamp emits that are NOT on the label
----------------------------------------------
The label lists the lines the manufacturer considers useful, not every line
the lamp emits. Line identification must know about all lines that can land
on the chip, or a strong unlisted line can be mistaken for a listed one
nearby. ARGON_UNLISTED_LINES_AIR_NM holds the strong argon lines between
700 and 930 nm that the label leaves out (NIST ASD values). Some are close
to a listed line (810.369 is 15 pixels from 811.531; 801.479 is 11 pixels
from 800.616), so the walk only uses a line when nothing else is predicted
close to it.

Diffraction orders
------------------
A grating sends wavelength lambda in order m to the same angle as wavelength
m * lambda in first order (grating equation: m * lambda = d (sin a + sin b)).
The TRIAX position and the CCD axis are calibrated in first-order terms, so a
blue mercury line seen in second order appears at twice its wavelength:
404.656 nm appears at 809.313 nm, among the argon lines. Third order matters
too: the strongest mercury line, 253.652 nm, appears at 760.956 nm, and a
grating blazed at 600 nm in first order is blazed near 200 nm in third order.
With no order-sorting filter in the beam these lines are present whether we
want them or not (if UV reaches the TRIAX), so they are always part of the
catalogue. Argon's own blue lines are weak and are left out.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReferenceLine:
    """One known emission line, observed in a particular diffraction order."""

    name: str
    wavelength_nm: float
    diffraction_order: int = 1
    wavelength_uncertainty_nm: float = 0.002
    usable_as_reference: bool = True

    @property
    def apparent_wavelength_nm(self):
        """Where the line appears on the first-order wavelength scale."""
        return self.wavelength_nm * self.diffraction_order

    @property
    def label(self):
        return f"{self.name} (order {self.diffraction_order})"


MERCURY_LINE_WAVELENGTHS_AIR_NM = {
    'Hg 253.652': 253.652,
    'Hg 296.728': 296.728,
    'Hg 302.150': 302.150,
    'Hg 313.155': 313.155,
    'Hg 334.148': 334.148,
    'Hg 365.015': 365.015,
    'Hg 404.656': 404.656,
    'Hg 407.783': 407.783,
    'Hg 435.833': 435.833,
    'Hg 546.074': 546.074,
    'Hg 576.960': 576.960,
    'Hg 579.066': 579.066,
}

ARGON_LABELLED_LINES_AIR_NM = {
    'Ar 696.543': 696.543,
    'Ar 706.722': 706.722,
    'Ar 710.748': 710.748,
    'Ar 727.294': 727.294,
    'Ar 738.393': 738.393,
    'Ar 750.387': 750.387,
    'Ar 763.511': 763.511,
    'Ar 772.376': 772.376,
    'Ar 794.818': 794.818,
    'Ar 800.616': 800.616,
    'Ar 811.531': 811.531,
    'Ar 826.452': 826.452,
    'Ar 842.465': 842.465,
    'Ar 852.144': 852.144,
    'Ar 866.794': 866.794,
    'Ar 912.297': 912.297,
    'Ar 922.450': 922.450,
}

ARGON_UNLISTED_LINES_AIR_NM = {
    'Ar 714.704': 714.704,
    'Ar 751.465': 751.465,
    'Ar 772.421': 772.421,
    'Ar 801.479': 801.479,
    'Ar 810.369': 810.369,
    'Ar 840.821': 840.821,
}

# Pairs closer than the spectrometer can resolve: the fitted centre is an
# intensity-weighted blend, so neither line is used as a reference.
UNRESOLVED_BLEND_NAMES = {'Ar 772.376', 'Ar 772.421'}


def mercury_lines_in_window(window_start_nm, window_end_nm, diffraction_orders=(1, 2)):
    """
    Mercury lines whose apparent (first-order-equivalent) wavelength falls in a window.

    Returns a list of ReferenceLine, sorted by apparent wavelength.
    """
    lines = []
    for name, wavelength_nm in MERCURY_LINE_WAVELENGTHS_AIR_NM.items():
        for order in diffraction_orders:
            line = ReferenceLine(name=name, wavelength_nm=wavelength_nm, diffraction_order=order)
            if window_start_nm <= line.apparent_wavelength_nm <= window_end_nm:
                lines.append(line)
    return sorted(lines, key=lambda line: line.apparent_wavelength_nm)


def argon_mercury_lamp_lines(window_start_nm, window_end_nm):
    """
    Every line of the Ar-Hg lamp that can appear between two first-order wavelengths.

    Includes argon (first order, labelled and unlisted), mercury in first,
    second and third order, and unresolved blends. Lines that should not be used as
    references (blends) have usable_as_reference=False but are still returned,
    because line identification needs to know they are there.
    """
    lines = mercury_lines_in_window(window_start_nm, window_end_nm, diffraction_orders=(1, 2, 3))
    for line_table in (ARGON_LABELLED_LINES_AIR_NM, ARGON_UNLISTED_LINES_AIR_NM):
        for name, wavelength_nm in line_table.items():
            if window_start_nm <= wavelength_nm <= window_end_nm:
                lines.append(ReferenceLine(name=name, wavelength_nm=wavelength_nm,
                                           usable_as_reference=name not in UNRESOLVED_BLEND_NAMES))
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
