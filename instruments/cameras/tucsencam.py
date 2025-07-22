from contextlib import contextmanager
# import ctypes
# from ctypes import byref
import os
import threading
import time
import numpy as np
from PyQt5.QtCore import QObject, pyqtSignal
# import matplotlib.pyplot as plt
# from PIL import Image
# from ctypes import pointer, cast, POINTER
from functools import wraps

from instruments.cameras.base_camera import Camera
from instruments.cameras.camera_hardware import RealHardware, SimulatedHardware

def synchronized(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        with self.camera_lock:
            return func(self, *args, **kwargs)
    return wrapper


class CameraHardwareBase:
    def open_stream(self): raise NotImplementedError
    def close_stream(self): raise NotImplementedError
    def grab_frame(self): raise NotImplementedError
    def initialise(self): raise NotImplementedError



class TucsenCamera(QObject):
    _instance_lock = threading.Lock()
    _instance_active = False

    temp_signal = pyqtSignal(float)

    def __init__(self, interface, **kwargs):
        super().__init__()
        with TucsenCamera._instance_lock:
            if TucsenCamera._instance_active:
                raise RuntimeError("Only one instance of TucsenCamera can be active.")
            TucsenCamera._instance_active = True

        self.interface = interface
        self.simulate = kwargs.get('simulate', False)
        self.logger = interface.logger.getChild('TucsenCamera')
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.acqtime = 0.5
        self.full_roi = (0, 0, 2048, 2048)
        self.roi = (0, 1220, 2048, 148)
        self.timeout = kwargs.get('timeout', 100000)
        self.camera_parameters = {}
        self.camera_capabilities = {}
        self.camera_lock = threading.RLock()
        self.stop_flag = threading.Event()
        self.is_running = False
        self.acquisition_thread = None
        self.command_functions = {}
        self.cam_temp = None

        if self.simulate:
            self.hardware = SimulatedHardware(self)
            self.logger.info('Using simulated camera hardware.')
        else:
            self.hardware = RealHardware(self)
            self.logger.info('Using real camera hardware.')
        self.logger.info('Finished TucsenCamera init')

    @synchronized
    def get_temperature(self):
        """Returns the current camera temperature and emits a signal for the GUI."""
        self.cam_temp = float(round(self.hardware.get_temperature(), 2))
        self.temp_signal.emit(self.cam_temp)
        return self.cam_temp

    @contextmanager
    def camera_session(self):
        '''Intended to be used with future debugging. Not to be used in production code.
        Wraps the camera operations in a context manager to ensure that the stream is opened and closed properly.
        Note: will break if the camera is already running because open_stream() is managed strictly by the camera class.'''

        with self.camera_lock:
            try:
                self.hardware.open_stream()
                yield
            finally:
                self.hardware.close_stream()

    def list_threads(self):
        self.logger.info("=== Active Threads ===")
        for thread in threading.enumerate():
            self.logger.info(f"{thread.name} (ID={thread.ident}, daemon={thread.daemon})")

    @synchronized
    def grab_frame(self, timeout=100000):
        return self.hardware.grab_frame(timeout=timeout)

    @synchronized
    def open_stream(self):
        if self.is_running:
            self.logger.info("Camera is already running. Please stop acquisition before starting a new one!")
            return
        
        self.is_running = True
        self.hardware.open_stream()

    @synchronized
    def close_stream(self):
        self.hardware.close_stream()
        self.is_running = False

    def start_continuous_acquisition(self, report=False):
        """Starts continuous acquisition on the camera."""
        # self.open_stream()
        n_frames = self.interface.acq_ctrl.general_parameters['n_frames']

        def continuous_task():
            try:
                self.stop_flag.clear()
                while not self.stop_flag.is_set():
                    for index in range(n_frames):
                        if self.stop_flag.is_set():
                            self.logger.info("Stop flag set. Stopping acquisition.")
                            return
                        new_frame = self.grab_frame(timeout=100000)
                        self.get_temperature()
                        
                        if new_frame is None:
                            self.logger.info("New frame is None. Stopping acquisition.")
                            break
                        if index == 0:
                            data = new_frame.astype(np.float32)
                        else:
                            data = (data + new_frame.astype(np.float32)) / 2
                        wavelengths = self.interface.microscope.wavelength_axis
                        self.save_transient_spectrum_cb(data, wavelengths)
                        time.sleep(0.01)

            except Exception as e:
                self.logger.error(f"Acquisition thread crashed: {e}")
                self.stop_flag.set()

        if self.acquisition_thread and self.acquisition_thread.is_alive():
            self.logger.warning("Acquisition thread already running.")
            return

        self.acquisition_thread = threading.Thread(target=continuous_task, daemon=True)
        self.acquisition_thread.start()
        self.logger.info("Started continuous acquisition.")

    @synchronized
    def stop_continuous_acquisition(self):
        self.stop_flag.set()
        if self.acquisition_thread and self.acquisition_thread.is_alive():
            self.acquisition_thread.join(timeout=2)
            self.acquisition_thread = None
        # self.close_stream()
        self.logger.info("Continuous acquisition stopped.")

    @synchronized
    def initialise(self):
        self.save_transient_spectrum_cb = self.interface.acq_ctrl.save_spectrum_transient
        self.hardware.initialise()

    def refresh(self):
        self.hardware.close_camera()
        self.hardware.uninit_api()
        self.hardware.initialise()

    @synchronized
    def _open_camera(self):
        self.hardware.open_camera()

    @synchronized
    def _close_camera(self):
        self.hardware.close_camera()
        self.logger.info("Close the camera success")

    @synchronized
    def _uninit_api(self):
        self.hardware.uninit_api()

    def close_camera(self):
        self._close_camera()
        self._uninit_api()
        self.logger.info("Camera connection closed and API uninitialized.")

    def grab_frame_safe(self, target_temp=-15, timeout=100000):
        while True:
            temp = self.hardware.get_temperature()
            if temp < target_temp:
                image_data = self.grab_frame(timeout=timeout)
                temp = self.get_temperature()
                if temp > target_temp:
                    self.logger.info(f"Frame acquired at {temp}°C. Discarding and retrying")
                    continue
                return image_data
            else:
                self.logger.info(f"Camera too hot ({temp}°C). Waiting...")
                time.sleep(5)

    @synchronized
    def check_camera_temperature(self):
        self.get_temperature()
        self.logger.info(f"Current camera temperature: {self.cam_temp}°C")
        return self.cam_temp

    @synchronized
    def set_roi(self, roi_tuple=(0, 0, 2048, 2048)):
        # x1, y1, x2, y2 = roi_tuple
        # if x1 < 0 or y1 < 0 or x2 > 2048 or y2 > 2048 or x2 <= x1 or y2 <= y1:
        #     raise ValueError(f"Invalid ROI: {roi_tuple}")
        
        if roi_tuple == 'full':
            roi_tuple = self.full_roi
        elif isinstance(roi_tuple, list):
            roi_tuple = tuple(int(x) for x in roi_tuple[0].split(','))
        elif isinstance(roi_tuple, str):
            roi_tuple = tuple(int(x) for x in roi_tuple.split(','))

        if len(roi_tuple) != 4:
            self.logger.info("ROI must be a 4-element tuple: (HOffset, VOffset, Width, Height)")
            return

        self.hardware.set_roi(roi_tuple)
        self.roi = roi_tuple

    @synchronized
    def get_fan_speed(self, report=True):
        speed = self.hardware.get_fan_speed()
        if report:
            speed_name = {0: "Off", 1: "Low", 2: "Medium", 3: "High"}.get(speed, "Unknown")
            self.logger.info(f"Current fan speed: {speed} ({speed_name})")
        return speed

    # @synchronized
    # def enable_auto_temperature_control(self, enable: bool, report: bool = True):
    #     self.hardware.enable_auto_temperature_control(enable)
    #     if report:
    #         state = "enabled" if enable else "disabled"
    #         self.logger.info(f"Automatic temperature control {state}.")

    @synchronized
    def set_target_temperature(self, target_celsius: float, report: bool = True):
        self.hardware.set_target_temperature(target_celsius)
        if report:
            self.logger.info(f"Target temperature set to {target_celsius}°C.")

    @synchronized
    def set_exposure_time(self, value):
        self.hardware.set_exposure_time(value)
        self.logger.info(f"Set exposure to {value} seconds.")

    @synchronized
    def _set_image_and_gain(self, img_mode=1, gain_level=0):
        self.hardware.set_image_and_gain(img_mode, gain_level)

    @synchronized
    def _set_image_processing(self, value=0):
        self.hardware.set_image_processing(value)

    @synchronized
    def _set_denoise(self, value=0):
        self.hardware.set_denoise(value)

    @synchronized
    def _set_resolution(self, resolution=1):
        self.hardware.set_resolution(resolution)

    @synchronized
    def set_fan_speed(self, speed=3, report=True):
        self.hardware.set_fan_speed(speed)
        if report:
            self.logger.info(f"Fan speed set to {speed}.")

    @synchronized
    def _set_hardware_binning(self, binning_level=1):
        self.hardware.set_hardware_binning(binning_level)
