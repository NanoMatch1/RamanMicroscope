"""Driver abstraction layer.

This package defines thin Protocol-based interfaces (PEP 544) for the
hardware driver layer (controller, laser, spectrometer, camera). They
allow future refactors to depend on stable contracts instead of the
concrete implementation classes embedded in `instruments_old` or
individual hardware modules.

Phase 2 goal: introduce these Protocols without changing runtime
behaviour. Existing classes already satisfy these contracts
structurally; tests assert conformance in simulate mode.
"""

from .protocols import (
    ControllerProtocol,
    LaserProtocol,
    SpectrometerProtocol,
    CameraProtocol,
)

__all__ = [
    'ControllerProtocol',
    'LaserProtocol',
    'SpectrometerProtocol',
    'CameraProtocol',
]
