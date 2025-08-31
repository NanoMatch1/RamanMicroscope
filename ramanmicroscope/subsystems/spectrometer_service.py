"""SpectrometerService

Phase 2D: Thin façade over spectrometer instrument (Triax) to provide
stable API for wavelength/step conversion, status snapshot, and simple
movement helpers. Behaviour-preserving: delegates to existing
instrument methods; no internal logic removed yet.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Callable, Optional

class _SpectrometerLike(Protocol):
    def get_spectrometer_position(self) -> int: ...
    def move_grating_relative(self, position) -> str: ...  # existing signature returns response
    def go_to_position(self, position) -> str: ...
    # Optional richer interface
    def go_to_wavelength(self, wavelength, steps_correction=200): ...  # noqa: D401
    interface: object

@dataclass
class SpectrometerStatus:
    steps: int
    wavelength_nm: Optional[float]

class SpectrometerService:
    def __init__(self, spectrometer: _SpectrometerLike, steps_to_wl: Optional[Callable[[int], float]] = None, wl_to_steps: Optional[Callable[[float], float]] = None):
        self._spec = spectrometer
        self._steps_to_wl = steps_to_wl
        self._wl_to_steps = wl_to_steps

    @classmethod
    def from_interface(cls, interface) -> "SpectrometerService":
        spec = interface.spectrometer
        cal = interface.microscope.calibration_service
        # calibration polynomials already loaded (poly1d objects)
        steps_to_wl = getattr(cal, 'triax_to_wl', None)
        wl_to_steps = getattr(cal, 'wl_to_triax', None)
        return cls(spec, steps_to_wl=steps_to_wl, wl_to_steps=wl_to_steps)

    def snapshot(self) -> SpectrometerStatus:
        steps = self._spec.get_spectrometer_position()
        wavelength = float(self._steps_to_wl(steps)) if self._steps_to_wl else None
        return SpectrometerStatus(steps=steps, wavelength_nm=wavelength)

    def move_relative(self, delta_steps: int):
        # Delegates to existing instrument command; returns new steps
        self._spec.move_grating_relative(delta_steps)
        return self._spec.get_spectrometer_position()

    def go_to_wavelength(self, wavelength_nm: float):
        # Prefer instrument native method if present
        if hasattr(self._spec, 'go_to_wavelength'):
            return self._spec.go_to_wavelength(wavelength_nm)
        if not self._wl_to_steps:
            raise RuntimeError("No wl_to_steps mapping available")
        current = self._spec.get_spectrometer_position()
        target_steps = int(round(self._wl_to_steps(float(wavelength_nm))))
        delta = target_steps - current
        if delta == 0:
            return True
        self._spec.move_grating_relative(delta)
        return True
