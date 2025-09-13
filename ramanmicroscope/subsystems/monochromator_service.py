"""MonochromatorService

Encapsulates monochromator wavelength validation, conversion via calibration,
 and movement helper using microscope action groups. Mirrors GratingService.
"""
from __future__ import annotations
from typing import Dict, Protocol

class _CalibrationLike(Protocol):
    def wl_to_steps(self, wavelength: float, group) -> Dict[str, int]: ...

class _MicroscopeLike(Protocol):
    calibration_service: _CalibrationLike
    action_groups: dict
    def check_monochromator_wavelength(self, wavelength) -> bool: ...
    def go_to_monochromator_steps(self, target_positions: Dict[str, int]): ...
    def report_monochromator_wavelength(self) -> float: ...
    micro_log: object

class MonochromatorService:
    def __init__(self, microscope: _MicroscopeLike):
        self._micro = microscope

    def move_to_wavelength(self, wavelength: float) -> bool:
        if self._micro.check_monochromator_wavelength(wavelength) is False:
            return False
        targets = self._micro.calibration_service.wl_to_steps(
            wavelength, self._micro.action_groups['monochromator_wavelength']
        )
        moved = self._micro.go_to_monochromator_steps(targets)
        if moved:
            self._micro.micro_log.info(
                f"New monochromator wavelength: {self._micro.report_monochromator_wavelength}"
            )
        else:
            self._micro.micro_log.info(
                "Monochromator already at target steps - no movement initiated."
            )
        return True
