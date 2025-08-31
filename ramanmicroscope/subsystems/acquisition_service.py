"""AcquisitionService

Phase 2E: façade over camera + AcquisitionControl for simple scripted
operations (set exposure, grab averaged frame) without reaching into
nested attributes from higher layers.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Protocol, Optional
import numpy as np

class _CameraLike(Protocol):
    acqtime: float
    def grab_frame(self, timeout: int = 100000): ...
    def set_exposure_time(self, value): ...

class _AcqCtrlLike(Protocol):
    general_parameters: dict

@dataclass
class AcquisitionSnapshot:
    exposure_s: float
    n_frames: int

class AcquisitionService:
    def __init__(self, camera: _CameraLike, acq_ctrl: _AcqCtrlLike):
        self._camera = camera
        self._acq = acq_ctrl

    @classmethod
    def from_interface(cls, interface):
        return cls(interface.camera, interface.acq_ctrl)

    def snapshot(self) -> AcquisitionSnapshot:
        return AcquisitionSnapshot(
            exposure_s=self._camera.acqtime,
            n_frames=int(self._acq.general_parameters.get('n_frames', 1))
        )

    def set_exposure(self, seconds: float):
        self._camera.set_exposure_time(seconds)
        self._acq.general_parameters['acquisition_time'] = seconds
        return self._camera.acqtime

    def grab_average(self, n: Optional[int] = None):
        n_frames = n or int(self._acq.general_parameters.get('n_frames', 1))
        acc = None
        for i in range(n_frames):
            frame = self._camera.grab_frame()
            if frame is None:
                continue
            arr = frame.astype('float32')
            acc = arr if acc is None else (acc + arr)/2.0
        return acc
