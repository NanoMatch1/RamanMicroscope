"""LaserService

Phase 2C: thin service abstraction over laser instrument providing
higher-level helpers (status bundle & validated set_power) without
changing existing instrument behaviour. Future: scheduling, ramping,
safety interlocks.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Optional

class _LaserLike(Protocol):
    # Minimal subset we depend on (structural typing)
    status: str
    current_power: float
    shutter_status: str
    def get_power(self) -> float: ...
    def get_power_setpoint(self) -> float: ...
    def get_warmup_status(self) -> float: ...
    def get_shutter_status(self) -> str: ...
    def set_power(self, power_watts): ...

@dataclass
class LaserStatus:
    status: str
    power: float
    setpoint: float
    warmup_pct: float
    shutter: str

class LaserService:
    def __init__(self, laser: _LaserLike):
        self._laser = laser

    def snapshot(self) -> LaserStatus:
        # Query live values (do not rely on cached attributes so tests catch drift)
        setpoint = self._laser.get_power_setpoint()
        power = self._laser.get_power()
        warm = self._laser.get_warmup_status()
        shutter_raw = self._laser.get_shutter_status()
        shutter = 'OPEN' if shutter_raw == '1' else 'CLOSED'
        return LaserStatus(
            status=getattr(self._laser, 'status', 'UNKNOWN'),
            power=power,
            setpoint=setpoint,
            warmup_pct=warm,
            shutter=shutter,
        )

    def set_power_safe(self, watts: float, allow_zero: bool = True) -> Optional[float]:
        """Validated power set: returns new setpoint or None if rejected.

        Rejects values outside physical 0–6 range & optionally zero.
        Delegates to underlying instrument for actual command.
        """
        try:
            watts_f = float(watts)
        except (TypeError, ValueError):
            return None
        if watts_f < 0 or watts_f > 6:
            return None
        if not allow_zero and watts_f == 0:
            return None
        self._laser.set_power(watts_f)
        return watts_f
