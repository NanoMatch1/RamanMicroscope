"""
Reference spectral lines with wavelengths known independently of the instrument.

Wavelengths are in AIR, in nm, which is the convention for lamp line tables
and for the rest of this codebase. At the PIXIS dispersion (~0.077 nm per
pixel) a table error of 0.005 nm is 1/16 of a pixel.

The lab lamp is an argon-mercury (Ar-Hg) pencil lamp. Every wavelength below
is from the NIST Atomic Spectra Database (observed air wavelengths, Ar I and
Hg I, retrieved 2026-11-10), rounded to 0.001 nm.

Two jobs, two kinds of line
---------------------------
1. IDENTIFICATION must know every line that can land on the chip. A line
   missing from the table is invisible to the identification, so a peak from
   it can be taken for a listed line nearby. That is how the 2026-11-10 walks
   went wrong: Hg 404.656 in second order (809.31) was recorded as Ar 811.531,
   Ar 737.212 as Ar 738.398, Ar 919.464 as Ar 922.450, and so on (CHANGELOG,
   "Known issues"). So ARGON_MERCURY_LAMP_LINES holds every NIST line that can
   reach the chip during an Ar-Hg walk (chip edges about 615-1015 nm): argon
   with NIST relative intensity 50 or more, mercury in first order, and
   mercury from 300-515 nm in second order.
2. FITTING uses only lines confirmed on this instrument (`usable_as_reference`):
   argon lines that were seen, are not blends, and whose table wavelength
   agrees with the other lines in the same frames to better than 0.01 nm
   (scratch/check_candidate_line_wavelengths.py, 2026-11-10 data).

Mercury lines are identification-only. On 2026-11-10 every mercury line,
first order (690.746, 708.190) as well as second order (809.313, 815.567,
871.667), sat 0.03-0.06 nm away from where the argon lines in the same frames
put it, while the argon lines agreed to 0.007 nm. The table values are right
(NIST), so the offset is instrumental, probably mercury and argon lighting
the entrance slit differently.

`relative_intensity` is the NIST relative intensity. It compares lines of the
same element only (NIST scales differ between spectra) and is used to judge
whether a weak neighbour can pull a line's fitted centre.

When a walk shows a strong peak that no line here explains, the gate report
says so with its wavelength: look it up in NIST and add it.

Diffraction orders
------------------
A grating sends wavelength lambda in order m to the same angle as wavelength
m * lambda in first order (grating equation: m * lambda = d (sin a + sin b)).
The TRIAX position and the CCD axis are calibrated in first-order terms, so a
blue mercury line seen in second order appears at twice its wavelength:
435.833 nm appears at 871.667 nm, among the argon lines. With no
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
    relative_intensity: float = 0.0  # NIST relative intensity, within one element only; 0 = unknown

    @property
    def apparent_wavelength_nm(self):
        """Where the line appears on the first-order wavelength scale."""
        return self.wavelength_nm * self.diffraction_order

    @property
    def element(self):
        return self.name.split()[0]

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

# Argon lines fitted as references: seen on this instrument, not blended, and consistent with
# the other lines in the same frame to < 0.01 nm (2026-11-04 and 2026-11-10 walks).
CONFIRMED_ARGON_REFERENCE_WAVELENGTHS_NM = (
    696.543, 703.025, 706.722, 714.704, 727.294, 737.212, 738.398, 750.387, 751.465, 763.511,
    794.818, 800.616, 801.479, 810.369, 811.531, 826.452, 840.821, 842.465, 852.144, 866.794,
    912.297, 919.464, 922.450, 935.422,
)

# NIST ASD Ar I, 600-1030 nm, relative intensity >= 50: (wavelength in air, relative intensity).
ARGON_LINES_NIST = (
    (603.213, 70), (641.631, 70), (667.728, 100), (675.283, 150), (687.129, 150),
    (693.766, 50), (696.543, 10000), (703.025, 150), (706.722, 10000), (706.874, 100),
    (714.704, 1000), (720.698, 70), (727.294, 2000), (735.329, 70), (737.212, 200),
    (738.398, 10000), (750.387, 20000), (751.465, 15000), (763.511, 25000), (772.376, 15000),
    (772.421, 10000), (794.818, 20000), (800.616, 20000), (801.479, 25000), (810.369, 20000),
    (811.531, 35000), (826.452, 10000), (840.821, 15000), (842.465, 20000), (852.144, 15000),
    (866.794, 4500), (884.991, 180), (912.297, 35000), (919.464, 550), (922.450, 15000),
    (929.153, 400), (935.422, 1600), (965.779, 25000), (978.450, 4500), (1005.206, 180),
)

# NIST ASD Hg I lines that land on the chip: first order 600-1030 nm, and 300-515 nm lines
# (relative intensity >= 200) in second order.
MERCURY_FIRST_ORDER_LINES_NIST = (
    (671.634, 600), (690.746, 1000), (708.190, 1000), (709.186, 800), (1013.975, 1600),
)
MERCURY_SECOND_ORDER_PARENT_LINES_NIST = (
    (302.150, 1200), (302.347, 300), (312.567, 4000), (313.156, 3000), (313.184, 4000),
    (334.148, 700), (365.016, 9000), (365.484, 3000), (366.289, 500), (366.328, 2000),
    (404.657, 12000), (407.784, 1000), (435.834, 12000),
)


def _build_argon_mercury_lamp_lines():
    confirmed = set(CONFIRMED_ARGON_REFERENCE_WAVELENGTHS_NM)
    lines = [ReferenceLine(name=f'Ar {wavelength_nm:.3f}', wavelength_nm=wavelength_nm,
                           usable_as_reference=wavelength_nm in confirmed,
                           relative_intensity=float(intensity))
             for wavelength_nm, intensity in ARGON_LINES_NIST]
    lines += [ReferenceLine(name=f'Hg {wavelength_nm:.3f}', wavelength_nm=wavelength_nm,
                            usable_as_reference=False, relative_intensity=float(intensity))
              for wavelength_nm, intensity in MERCURY_FIRST_ORDER_LINES_NIST]
    lines += [ReferenceLine(name=f'Hg {wavelength_nm:.3f}', wavelength_nm=wavelength_nm,
                            diffraction_order=2, usable_as_reference=False,
                            relative_intensity=float(intensity))
              for wavelength_nm, intensity in MERCURY_SECOND_ORDER_PARENT_LINES_NIST]
    return tuple(sorted(lines, key=lambda line: line.apparent_wavelength_nm))


# Every line that can land on the chip during an Ar-Hg walk; see the module docstring.
ARGON_MERCURY_LAMP_LINES = _build_argon_mercury_lamp_lines()


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


def argon_mercury_lamp_lines(window_start_nm=None, window_end_nm=None):
    """
    The lab Ar-Hg lamp's lines (ARGON_MERCURY_LAMP_LINES), optionally between two first-order
    wavelengths.

    Identification-only lines (usable_as_reference=False) are always included:
    line identification needs to know they are there.
    """
    window_start_nm = -float('inf') if window_start_nm is None else window_start_nm
    window_end_nm = float('inf') if window_end_nm is None else window_end_nm
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
