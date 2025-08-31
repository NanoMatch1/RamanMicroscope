"""Protocol (interface) definitions for core hardware drivers.

These structural contracts intentionally capture only the *minimum*
set of members consumed outside the concrete driver modules, keeping
refactors low-risk while enabling:

* Type checking / editor assistance
* Easier mocking in future unit tests
* Clear separation between Application layer (Interface / Microscope)
  and physical driver implementations

NOTE: We avoid prescribing rich behaviour (threading, watchdogs, etc.)
in the Protocols to keep simulation + real hardware alignment easy.
Additional optional attributes are annotated with ``@typing_extensions.runtime_checkable``
to allow lightweight isinstance checks in tests.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable, Iterable, Sequence, Tuple, Any


@runtime_checkable
class ControllerProtocol(Protocol):
    """Arduino / motion controller contract."""

    def initialise(self) -> None: ...
    def send_command(self, command: str): ...  # returns list[str] historically
    def get_motor_positions(self, motor_list: Iterable[str]): ...
    def write_motor_positions(self, motor_id_dict: dict): ...


@runtime_checkable
class LaserProtocol(Protocol):
    """Millennia (or other) laser contract used by higher layers."""

    status: str
    current_power: float

    def initialise(self) -> Any: ...
    def set_power(self, power_watts: float): ...
    def get_power(self) -> float: ...
    def get_power_setpoint(self) -> float: ...
    def enable_laser(self) -> bool | None: ...
    def get_warmup_status(self) -> float: ...
    def open_shutter(self) -> bool | Any: ...
    def close_shutter(self) -> bool | Any: ...


@runtime_checkable
class SpectrometerProtocol(Protocol):
    """TRIAX (or other) spectrometer contract."""

    spectrometer_position: int

    def initialise(self) -> Any: ...
    def get_spectrometer_position(self) -> int: ...
    def go_to_position(self, position: int | str): ...
    def read_enterance_slit(self) -> int: ...
    def move_enterance_slit(self, position: int | str): ...
    def move_grating_relative(self, position: int | str): ...


@runtime_checkable
class CameraProtocol(Protocol):
    """Camera contract consumed by acquisition + microscope layers."""

    roi: tuple[int, int, int, int]
    acqtime: float

    def initialise(self) -> None: ...
    def grab_frame(self, timeout: int = 100_000): ...
    def start_continuous_acquisition(self, report: bool = False): ...
    def stop_continuous_acquisition(self) -> None: ...
    def set_exposure_time(self, value: float | int): ...
    def set_roi(self, roi_tuple): ...
    def close_camera(self) -> None: ...


__all__ = [
    'ControllerProtocol',
    'LaserProtocol',
    'SpectrometerProtocol',
    'CameraProtocol',
]
