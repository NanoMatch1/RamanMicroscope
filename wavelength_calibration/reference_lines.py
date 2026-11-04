"""
Reference spectral lines with wavelengths known independently of the instrument.

Wavelengths are in AIR, in nm, which is the convention for lamp line tables
and for the rest of this codebase. At the PIXIS dispersion (~0.078 nm per
pixel) a table error of 0.005 nm is 1/16 of a pixel and is negligible.

The lab lamp is an argon-mercury (Ar-Hg) pencil lamp. Wavelengths are from
its label, or from the NIST Atomic Spectra Database for lines the label
leaves out; the two agree to 0.005 nm or better.

The lamp catalogue is what THIS lamp shows on THIS instrument
--------------------------------------------------------------
Line identification must know every line that can land on the chip, or a
real line can be mistaken for a known one nearby. The reverse matters as
much: a catalogue line the lamp does not actually show is a target that an
unrelated weak peak can be matched to. So ARGON_MERCURY_LAMP_LINES lists the
lines seen in a real walk (Riley, 2026-11-04, 690-910 nm), not every line in
the atomic tables:

- argon, first order: the label lines plus strong unlisted ones (714.704,
  751.465, 801.479, 810.369, 840.821) that sit close to label lines;
- Ar 710.748 is on the label but was not seen, so it is left out;
- mercury: none of the mercury lines expected in second or third order
  (730.0, 760.96, 809.31, 815.57, 890.2, 906.5 nm) were seen (presumably
  the lamp envelope or the optics absorb the UV and most of the blue). One weak line at
  ~871.6 nm matches Hg 435.833 in second order and is kept for
  identification only;
- 912.297 and 922.450 were beyond the recorded frames: expected, not yet
  confirmed.

When a walk shows a line that is not in the table (or misses one that is),
edit the table: it is the only place the lamp's lines are defined.

Diffraction orders
------------------
A grating sends wavelength lambda in order m to the same angle as wavelength
m * lambda in first order (grating equation: m * lambda = d (sin a + sin b)).
The TRIAX position and the CCD axis are calibrated in first-order terms, so a
blue mercury line seen in second order appears at twice its wavelength:
435.833 nm appears at 871.666 nm, among the argon lines. With no
order-sorting filter in the beam such lines are present whenever the light
reaches the TRIAX, so check for them whenever the lamp or optics change.
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

def _argon(wavelength_nm, usable_as_reference=True):
    return ReferenceLine(name=f'Ar {wavelength_nm:.3f}', wavelength_nm=wavelength_nm,
                         usable_as_reference=usable_as_reference)


# Every line the lab Ar-Hg lamp shows between 690 and 930 nm (first-order
# scale); see the module docstring. usable_as_reference=False lines are
# known to be there but never fitted.
ARGON_MERCURY_LAMP_LINES = (
    _argon(696.543),
    _argon(706.722),
    _argon(714.704),                               # weak, not on the label
    _argon(727.294),
    _argon(738.393),
    _argon(750.387),
    _argon(751.465),                               # not on the label; 14 px from 750.387
    _argon(763.511),                               # brightest line
    _argon(772.376, usable_as_reference=False),    # unresolved blend with 772.421:
    _argon(772.421, usable_as_reference=False),    # the fitted centre is a mix of both
    _argon(794.818),
    _argon(800.616),
    _argon(801.479),                               # not on the label; 11 px from 800.616
    _argon(810.369),                               # not on the label; 15 px from 811.531
    _argon(811.531),
    _argon(826.452),
    _argon(840.821),                               # not on the label; 21 px from 842.465
    _argon(842.465),
    _argon(852.144),
    _argon(866.794),
    ReferenceLine(name='Hg 435.833', wavelength_nm=435.833, diffraction_order=2,
                  usable_as_reference=False),      # weak; identity not yet confirmed
    _argon(912.297),                               # not yet confirmed (beyond recorded frames)
    _argon(922.450),                               # not yet confirmed (beyond recorded frames)
)


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
    The lab Ar-Hg lamp's lines (ARGON_MERCURY_LAMP_LINES) between two first-order wavelengths.

    Lines that should not be used as references (blends, unconfirmed lines)
    have usable_as_reference=False but are still returned, because line
    identification needs to know they are there.
    """
    lines = [line for line in ARGON_MERCURY_LAMP_LINES
             if window_start_nm <= line.apparent_wavelength_nm <= window_end_nm]
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
