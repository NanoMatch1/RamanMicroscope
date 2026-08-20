# instruments/lasers/tiger_calibration.py

import numpy as np
from scipy.interpolate import interp1d


# ------------------------------------------------------------------------------
# Verified calibration data
# ------------------------------------------------------------------------------
# Ground truth measurements taken with an accurate external spectrometer.
# Steps are absolute piezomotor positions. Wavelengths are measured values.
#
# The original 39-point dataset has been replaced with 6 verified measurements.
# The original cubic spline produced ~10 nm systematic errors due to
# oscillation between poorly verified calibration points (Runge's phenomenon).
#
# Linear interpolation is used between points — no oscillation, no overshoot,
# guaranteed accurate at every measured point.
#
# More points can be added to _RAW_STEPS / _RAW_WL as measurements are taken.
# Keep both arrays sorted by INCREASING steps (DECREASING wavelength).
#
# Measurement conditions
# ----------------------
# - Measured with external calibrated spectrometer
# - All measurements taken in the decrease-step direction (home → target)
# - Step amplitude: 600 (default)
# ------------------------------------------------------------------------------

_RAW_STEPS = np.array([
    2453,     # 840.035 nm
    3725,     # 810.772 nm
    4125,     # 801.136 nm
    4674,     # 785.780 nm
    4898,     # 779.184 nm
    5400,     # 765.546 nm  ← home
], dtype=float)

_RAW_WL = np.array([
    840.035,
    810.772,
    801.136,
    785.780,
    779.184,
    765.546,
], dtype=float)

# ------------------------------------------------------------------------------
# Boundary constants
# ------------------------------------------------------------------------------

STEP_MIN       = float(_RAW_STEPS[0])    # 2453  — top of verified range
STEP_MAX       = float(_RAW_STEPS[-1])   # 5400  — home position

WL_MAX         = float(_RAW_WL[0])       # 840.035 nm  at STEP_MIN
WL_MIN         = float(_RAW_WL[-1])      # 765.546 nm  at STEP_MAX

# Beyond STEP_MAX (> 5400 steps) the laser drops to 750.117 nm
WL_AT_OVERFLOW = 750.117


class TigerCalibration:
    """
    Converts between piezomotor step position and laser wavelength for the
    Tiger Ti:Sapphire laser, using verified ground truth measurements.

    Design notes
    ------------
    - Linear interpolation is used between calibration points.
      This guarantees no oscillation or overshoot between points,
      at the cost of slight discontinuities in the derivative at each
      calibration point. For a piezomotor tuning system this is acceptable.
    - The relationship is monotonically decreasing (more steps → shorter
      wavelength).
    - Steps below STEP_MIN are clamped to WL_MAX.
    - Steps above STEP_MAX return WL_AT_OVERFLOW (750.117 nm).
    - The inverse (wavelength → steps) is constructed by flipping the
      arrays. Because the forward curve is monotonic this is unambiguous.
    - Add new verified measurements to _RAW_STEPS and _RAW_WL as they
      are taken. Keep both arrays sorted by increasing steps.
    """

    def __init__(self):
        # ── Forward interpolant: steps → wavelength ───────────────────────────
        self._steps_to_wl = interp1d(
            _RAW_STEPS,
            _RAW_WL,
            kind         = 'linear',
            bounds_error = False,
            fill_value   = (WL_MAX, WL_AT_OVERFLOW),
        )

        # ── Inverse interpolant: wavelength → steps ───────────────────────────
        # _RAW_WL is decreasing so flip both arrays for interp1d which
        # requires x to be monotonically increasing.
        self._wl_to_steps = interp1d(
            _RAW_WL[::-1],
            _RAW_STEPS[::-1],
            kind         = 'linear',
            bounds_error = False,
            fill_value   = (STEP_MIN, STEP_MAX),
        )

    # --------------------------------------------------------------------------
    # Public API
    # --------------------------------------------------------------------------

    def steps_to_wavelength(self, steps: float) -> float:
        """
        Convert an absolute step position to wavelength in nm.

        Parameters
        ----------
        steps : float
            Absolute piezomotor step position.

        Returns
        -------
        float
            Wavelength in nm.
            - steps < STEP_MIN  → WL_MAX (840.035 nm, clamped)
            - steps > STEP_MAX  → WL_AT_OVERFLOW (750.117 nm)
        """
        wl = float(self._steps_to_wl(steps))
        return round(wl, 3)

    def wavelength_to_steps(self, wavelength_nm: float) -> int:
        """
        Convert a target wavelength to the nearest absolute step position.

        Parameters
        ----------
        wavelength_nm : float
            Target wavelength in nm.

        Returns
        -------
        int
            Absolute step position, clamped to [STEP_MIN, STEP_MAX].
        """
        if wavelength_nm > WL_MAX:
            return int(STEP_MIN)
        if wavelength_nm < WL_MIN:
            return int(STEP_MAX)

        steps = float(self._wl_to_steps(wavelength_nm))
        return int(round(steps))

    def steps_to_wavelength_array(self, steps_array) -> np.ndarray:
        """
        Vectorised version of steps_to_wavelength.

        Parameters
        ----------
        steps_array : array-like

        Returns
        -------
        np.ndarray
        """
        return np.round(
            self._steps_to_wl(np.asarray(steps_array, dtype=float)), 3
        )

    def is_in_range(self, wavelength_nm: float) -> bool:
        """
        Return True if the wavelength is within the verified calibrated range.

        Parameters
        ----------
        wavelength_nm : float

        Returns
        -------
        bool
        """
        return WL_MIN <= wavelength_nm <= WL_MAX

    def get_range(self) -> tuple:
        """
        Return the calibrated wavelength range as (min_nm, max_nm).
        """
        return (WL_MIN, WL_MAX)

    def get_step_range(self) -> tuple:
        """
        Return the calibrated step range as (min_steps, max_steps).
        """
        return (int(STEP_MIN), int(STEP_MAX))

    def plot_calibration(self):
        """
        Plot the calibration curve for visual inspection.
        Requires matplotlib — intended for debugging only.
        """
        try:
            import matplotlib.pyplot as plt
        except ImportError:
            print("matplotlib not available — cannot plot calibration.")
            return

        steps_fine     = np.linspace(STEP_MIN, STEP_MAX, 500)
        wl_fine        = self.steps_to_wavelength_array(steps_fine)

        # Extend beyond STEP_MAX to show the overflow value
        steps_extended = np.linspace(STEP_MIN, STEP_MAX + 500, 600)
        wl_extended    = self.steps_to_wavelength_array(steps_extended)

        fig, axes = plt.subplots(1, 2, figsize=(12, 4))

        # Forward: steps → wavelength
        axes[0].plot(
            steps_extended, wl_extended,
            'b-', label='Linear interpolation (+ overflow)', lw=2
        )
        axes[0].plot(
            _RAW_STEPS, _RAW_WL,
            'ro', label='Verified calibration points', ms=6
        )
        axes[0].axhline(
            WL_AT_OVERFLOW, color='orange', linestyle='--',
            alpha=0.7, label=f'Overflow: {WL_AT_OVERFLOW} nm'
        )
        axes[0].axvline(
            STEP_MAX, color='grey', linestyle=':',
            alpha=0.7, label=f'Home: {int(STEP_MAX)} steps'
        )
        axes[0].set_xlabel("Step position")
        axes[0].set_ylabel("Wavelength (nm)")
        axes[0].set_title("Steps → Wavelength  (linear)")
        axes[0].legend(fontsize=7)
        axes[0].grid(True, alpha=0.3)

        # Inverse: wavelength → steps
        wl_range  = np.linspace(WL_MIN, WL_MAX, 500)
        steps_inv = np.array([self.wavelength_to_steps(w) for w in wl_range])
        axes[1].plot(
            wl_range, steps_inv,
            'g-', label='Linear interpolation', lw=2
        )
        axes[1].plot(
            _RAW_WL, _RAW_STEPS,
            'ro', label='Verified calibration points', ms=6
        )
        axes[1].set_xlabel("Wavelength (nm)")
        axes[1].set_ylabel("Step position")
        axes[1].set_title("Wavelength → Steps  (linear)")
        axes[1].legend(fontsize=7)
        axes[1].grid(True, alpha=0.3)

        fig.suptitle(
            f"Tiger Ti:Sapph calibration  |  "
            f"verified range: {WL_MIN:.3f}–{WL_MAX:.3f} nm  |  "
            f"steps: {int(STEP_MIN)}–{int(STEP_MAX)}  |  "
            f"interpolation: linear  |  "
            f"points: {len(_RAW_STEPS)}",
            fontsize=9
        )
        fig.tight_layout()
        plt.show()
