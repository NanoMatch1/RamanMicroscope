"""GratingService

Façade for grating-related wavelength moves leveraging calibration
service and existing motion helpers. Centralises conversion logic so
future safety / batching can be added without touching legacy class.
"""
from __future__ import annotations
from typing import Dict, Protocol

class _CalibrationLike(Protocol):
    def wl_to_steps(self, wavelength: float, group) -> Dict[str, int]: ...

class _MicroscopeLike(Protocol):
    calibration_service: _CalibrationLike
    action_groups: dict
    def check_grating_wavelength(self, wavelength) -> bool: ...
    def go_to_grating_steps(self, target_positions: Dict[str, int]): ...
    def report_grating_wavelength(self) -> float: ...  # property-like
    micro_log: object

class GratingService:
    def __init__(self, microscope: _MicroscopeLike):
        self._micro = microscope

    def move_to_wavelength(self, wavelength: float) -> bool:
        if self._micro.check_grating_wavelength(wavelength) is False:
            return False
        targets = self._micro.calibration_service.wl_to_steps(
            wavelength, self._micro.action_groups['grating_wavelength']
        )
        moved = self._micro.go_to_grating_steps(targets)
        if moved:
            self._micro.micro_log.info(f"New grating wavelength: {self._micro.report_grating_wavelength}")
        else:
            self._micro.micro_log.info("Grating motors already at target position - no motion initiated.")
        return True