# pixisspec/pixiscam.py

import os
import threading
import time
import numpy as np

from contextlib import contextmanager
from PyQt5.QtCore import QObject, pyqtSignal
from functools import wraps

from pixisspec.pixis_hardware import RealHardware, SimulatedHardware


def synchronized(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        with self.camera_lock:
            return func(self, *args, **kwargs)
    return wrapper


class PIXISCamera(QObject):
    """
    Wrapper class for Princeton Instruments PIXIS cameras using pylablib.

    Designed as a drop-in replacement for TucsenCamera so that Interface,
    Microscope, and AcquisitionControl require minimal changes.

    Design contract
    ---------------
    - Public API mirrors TucsenCamera exactly (same method names,
      same argument conventions, same attribute names).
    - Exposure times are always in SECONDS at this level, matching
      the Tucsen convention. RealHardware converts to ms internally.
    - ROI is always (HOffset, VOffset, Width, Height).
    - simulate=True uses SimulatedHardware and never touches pylablib.
    """

    # Singleton guard — only one camera instance may be active at a time,
    # matching the TucsenCamera pattern.
    _instance_lock   = threading.Lock()
    _instance_active = False

    temp_signal = pyqtSignal(float)

    def __init__(self, interface, **kwargs):
        super().__init__()

        with PIXISCamera._instance_lock:
            if PIXISCamera._instance_active:
                raise RuntimeError(
                    "Only one instance of PIXISCamera can be active."
                )
            PIXISCamera._instance_active = True

        self.interface  = interface
        self.simulate   = kwargs.get('simulate', False)
        self.logger     = interface.logger.getChild('Camera')
        self.script_dir = os.path.dirname(os.path.abspath(__file__))

        # ── Default acquisition parameters ────────────────────────────
        self.acqtime  = 0.5                    # seconds — matches Tucsen default
        self.full_roi = (0, 0, 1024, 1024)     # (HOffset, VOffset, Width, Height)
        self.roi      = (0, 0, 1024, 100)      # default spectral ROI

        self.timeout             = kwargs.get('timeout', 100000)  # ms
        self.camera_parameters   = {}
        self.camera_capabilities = {}
        self.camera_lock         = threading.RLock()
        self.stop_flag           = threading.Event()
        self.stop_flag.set()       # set = not running, mirrors Tucsen convention
        self.is_running          = False
        self.acquisition_thread  = None
        self.command_functions   = {}          # intentionally empty — see note below
        self.cam_temp            = None
        self.acquire_mode        = 'spectrum'  # 'spectrum' | 'image'

        # ── Hardware backend ───────────────────────────────────────────
        if self.simulate:
            self.hardware = SimulatedHardware(self)
            self.logger.info('PIXISCamera: using simulated hardware.')
        else:
            self.hardware = RealHardware(self)
            self.logger.info('PIXISCamera: using real hardware.')

        self.logger.info('PIXISCamera __init__ complete.')

    # ------------------------------------------------------------------
    # NOTE on command_functions
    # ------------------------------------------------------------------
    # command_functions is intentionally left empty here, exactly as in
    # TucsenCamera. All camera CLI commands are registered on Microscope
    # (e.g. 'acquire', 'roi', 'temp', 'settemp', 'run', 'stop', etc.).
    # PIXISCamera is therefore not picked up by Interface._generate_command_map
    # because it does not inherit from Instrument or InstrumentBase.
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    @synchronized
    def initialise(self):
        """
        Initialise the camera hardware and bind the transient spectrum
        callback from AcquisitionControl.
        Mirrors TucsenCamera.initialise().
        """
        self.save_transient_spectrum_cb = (
            self.interface.acq_ctrl.save_spectrum_transient
        )
        self.hardware.initialise()
        self.logger.info('PIXISCamera initialised.')

    @synchronized
    def second_initialise(self):
        """Apply secondary settings after first initialise. Stub — no PIXIS equivalent."""
        self.logger.debug('PIXISCamera.second_initialise() — no-op for PIXIS.')

    @synchronized
    def minimal_initialise(self):
        """Minimal initialise without full settings. Stub — no PIXIS equivalent."""
        self.logger.debug('PIXISCamera.minimal_initialise() — no-op for PIXIS.')

    # ------------------------------------------------------------------
    # Stream control
    # ------------------------------------------------------------------

    @synchronized
    def open_stream(self):
        """Open the acquisition stream."""
        if self.is_running:
            self.logger.info(
                "PIXISCamera: already running — stop before starting a new stream."
            )
            return
        self.is_running = True
        self.hardware.open_stream()

    @synchronized
    def close_stream(self):
        """Close the acquisition stream."""
        self.hardware.close_stream()
        self.is_running = False

    # ------------------------------------------------------------------
    # Frame acquisition
    # ------------------------------------------------------------------

    @synchronized
    def grab_frame(self, timeout=50000):
        """
        Grab a single frame from the camera.

        Parameters
        ----------
        timeout : int
            Timeout in milliseconds, matching the Tucsen convention.

        Returns
        -------
        np.ndarray or None
        """
        return self.hardware.grab_frame(timeout=timeout)

    def grab_frame_safe(self, target_temp=-15, timeout=10000):
        """
        Grab a frame only when the sensor is at or below target_temp.
        Mirrors TucsenCamera.grab_frame_safe().
        """
        while True:
            temp = self.check_camera_temperature()
            if temp is not None and temp <= target_temp:
                image_data = self.grab_frame(timeout=timeout)
                temp_after = self.check_camera_temperature()
                if temp_after is not None and temp_after > target_temp:
                    self.logger.info(
                        f"Frame acquired at {temp_after}°C — discarding and retrying."
                    )
                    continue
                return image_data
            else:
                self.logger.info(
                    f"Camera too warm ({temp}°C) — waiting for {target_temp}°C."
                )
                time.sleep(5)

    # ------------------------------------------------------------------
    # Continuous acquisition
    # ------------------------------------------------------------------

    def start_continuous_acquisition(self, report=False):
        """
        Start continuous frame acquisition on a background thread.
        Mirrors TucsenCamera.start_continuous_acquisition().
        """
        n_frames = self.interface.acq_ctrl.general_parameters['n_frames']

        def continuous_task():
            try:
                self.stop_flag.clear()
                while not self.stop_flag.is_set():
                    for index in range(n_frames):
                        if self.stop_flag.is_set():
                            self.logger.info(
                                "PIXISCamera: stop flag set — ending acquisition."
                            )
                            return

                        new_frame = self.grab_frame(timeout=100000)
                        self.get_temperature()

                        if new_frame is None:
                            self.logger.info(
                                "PIXISCamera: grab_frame returned None — stopping."
                            )
                            break

                        # Average frames as they arrive
                        if index == 0:
                            data = new_frame.astype(np.float32)
                        else:
                            data = (data + new_frame.astype(np.float32)) / 2

                        wavelengths = self.interface.microscope.wavelength_axis
                        self.save_transient_spectrum_cb(data, wavelengths)
                        time.sleep(0.01)

            except Exception as e:
                self.logger.error(f"PIXISCamera: acquisition thread crashed: {e}")
                self.stop_flag.set()

        if self.acquisition_thread and self.acquisition_thread.is_alive():
            self.logger.warning(
                "PIXISCamera: acquisition thread already running."
            )
            return

        self.acquisition_thread = threading.Thread(
            target=continuous_task, daemon=True
        )
        self.acquisition_thread.start()
        self.logger.info("PIXISCamera: continuous acquisition started.")

    @synchronized
    def stop_continuous_acquisition(self):
        """
        Stop the continuous acquisition thread.
        Mirrors TucsenCamera.stop_continuous_acquisition().
        """
        self.stop_flag.set()
        if self.acquisition_thread and self.acquisition_thread.is_alive():
            self.acquisition_thread.join(timeout=2)
            self.acquisition_thread = None
        self.logger.info("PIXISCamera: continuous acquisition stopped.")

    # ------------------------------------------------------------------
    # Exposure
    # ------------------------------------------------------------------

    @synchronized
    def set_exposure_time(self, value):
        """
        Set the exposure time.

        Parameters
        ----------
        value : float or str
            Exposure time in SECONDS, matching the Tucsen convention.
        """
        if not self.stop_flag.is_set():
            self.stop_continuous_acquisition()

        ret = self.hardware.set_exposure_time(value)
        if ret is True:
            self.acqtime = float(value)
            self.logger.info(
                f"PIXISCamera: exposure time set to {float(value) * 1000:.1f} ms."
            )

    @synchronized
    def get_exposure_time(self, report=True):
        """
        Returns the current exposure time in seconds.
        """
        exp = self.hardware.get_exposure_time()
        if report and exp is not None:
            self.logger.info(f"PIXISCamera: current exposure time: {exp:.4f} s.")
        return exp

    # ------------------------------------------------------------------
    # ROI and binning
    # ------------------------------------------------------------------

    @synchronized
    def set_roi(self, roi_tuple=(0, 0, 1024, 1024)):
        """
        Set the region of interest.

        Parameters
        ----------
        roi_tuple : tuple or str or list
            (HOffset, VOffset, Width, Height).
            Accepts the same flexible input types as TucsenCamera.set_roi().
        """
        if roi_tuple == 'full':
            roi_tuple = self.full_roi
        elif isinstance(roi_tuple, list):
            roi_tuple = tuple(int(x) for x in roi_tuple[0].split(','))
        elif isinstance(roi_tuple, str):
            roi_tuple = tuple(int(x) for x in roi_tuple.split(','))

        if len(roi_tuple) != 4:
            self.logger.error(
                "PIXISCamera: ROI must be a 4-element tuple: "
                "(HOffset, VOffset, Width, Height)."
            )
            return

        self.hardware.set_roi(roi_tuple)
        self.roi = roi_tuple

    @synchronized
    def set_hardware_binning(self, binning_level=1):
        """
        Set hardware binning on both axes.

        Parameters
        ----------
        binning_level : int
        """
        self.hardware.set_hardware_binning(binning_level)

    # ------------------------------------------------------------------
    # Temperature
    # ------------------------------------------------------------------

    @synchronized
    def get_temperature(self):
        """
        Returns the current sensor temperature and emits temp_signal.
        Mirrors TucsenCamera.get_temperature().
        """
        temp = self.hardware.get_temperature()
        if temp is not None:
            self.cam_temp = float(round(temp, 2))
            self.temp_signal.emit(self.cam_temp)
        return self.cam_temp

    @synchronized
    def check_camera_temperature(self):
        """
        Log and return the current camera temperature.
        Mirrors TucsenCamera.check_camera_temperature().
        """
        self.get_temperature()
        self.logger.info(
            f"PIXISCamera: current temperature: {self.cam_temp}°C."
        )
        return self.cam_temp

    @synchronized
    def set_target_temperature(self, target_celsius, report=True):
        """
        Set the target sensor temperature.

        Parameters
        ----------
        target_celsius : float
        """
        self.hardware.set_target_temperature(target_celsius)
        if report:
            self.logger.info(
                f"PIXISCamera: target temperature set to {target_celsius}°C."
            )

    # ------------------------------------------------------------------
    # Fan speed
    # ------------------------------------------------------------------

    @synchronized
    def get_fan_speed(self, report=True):
        """
        Returns the fan speed.
        PIXIS has no software fan control — always returns 3 (high).
        """
        speed = self.hardware.get_fan_speed()
        if report:
            speed_name = {0: "Off", 1: "Low", 2: "Medium", 3: "High"}.get(
                speed, "Unknown"
            )
            self.logger.info(
                f"PIXISCamera: fan speed: {speed} ({speed_name})."
            )
        return speed

    @synchronized
    def set_fan_speed(self, speed=3, report=True):
        """Stub — PIXIS fan speed is not software-controllable."""
        self.hardware.set_fan_speed(speed)
        if report:
            self.logger.info(
                f"PIXISCamera: set_fan_speed({speed}) — no-op on PIXIS."
            )

    # ------------------------------------------------------------------
    # Gain and image mode
    # ------------------------------------------------------------------

    @synchronized
    def set_global_gain(self, gain):
        """
        Set the ADC analogue gain.
        gain mapping: 0=Low, 1=Medium, 2=High.
        """
        self.hardware.set_image_and_gain(img_mode=0, gain_level=gain)

    @synchronized
    def _set_image_and_gain(self, img_mode=1, gain_level=0):
        self.hardware.set_image_and_gain(img_mode, gain_level)

    # ------------------------------------------------------------------
    # Stubs for Tucsen-specific features
    # ------------------------------------------------------------------

    @synchronized
    def _set_image_processing(self, value=0):
        self.hardware.set_image_processing(value)

    @synchronized
    def _set_denoise(self, value=0):
        self.hardware.set_denoise(value)

    @synchronized
    def _set_resolution(self, resolution=1):
        self.hardware.set_resolution(resolution)

    def enable_auto_temperature_control(self, enable, report=True):
        """
        PIXIS manages its own TEC — stub for interface parity.
        """
        self.hardware.enable_auto_temperature_control(enable)
        if report:
            state = "enabled" if enable else "disabled"
            self.logger.info(
                f"PIXISCamera: auto temperature control {state} "
                f"(managed by camera firmware)."
            )

    # ------------------------------------------------------------------
    # Camera info / debug
    # ------------------------------------------------------------------

    def get_camera_info(self, dump=False, log_name="pixis_camera_info.txt"):
        """
        Return a dict of camera attributes.
        Optionally dump to a text file, mirroring TucsenCamera.get_camera_info().
        """
        info = self.hardware.get_camera_info()
        if dump:
            log_path = os.path.join(self.script_dir, log_name)
            with open(log_path, 'w') as f:
                for key, value in info.items():
                    f.write(f"{key}: {value}\n")
            self.logger.info(f"PIXISCamera: camera info dumped to {log_path}.")
        return info

    def dbg_dump(self):
        """Log all key camera attributes for debugging."""
        info = self.hardware.get_camera_info()
        for key, value in info.items():
            self.logger.info(f"  {key}: {value}")

    def list_threads(self):
        """Log all active threads. Mirrors TucsenCamera.list_threads()."""
        self.logger.info("=== Active Threads ===")
        for thread in threading.enumerate():
            self.logger.info(
                f"{thread.name} "
                f"(ID={thread.ident}, daemon={thread.daemon})"
            )

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    @contextmanager
    def camera_session(self):
        """
        Context manager that opens and closes the stream around a block.
        Mirrors TucsenCamera.camera_session().
        Intended for debugging — do not use in production acquisition loops.
        """
        with self.camera_lock:
            try:
                self.hardware.open_stream()
                yield
            finally:
                self.hardware.close_stream()

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def refresh(self):
        """
        Close and re-initialise the camera.
        Mirrors TucsenCamera.refresh().
        """
        self.hardware.close_camera()
        self.hardware.uninit_api()
        self.hardware.initialise()

    @synchronized
    def close_camera(self):
        """
        Close the stream and disconnect from the camera.
        Mirrors TucsenCamera.close_camera().
        Called by Interface.cli() on 'exit' and Microscope.close_camera().

        Releases the singleton guard directly rather than relying on
        __del__, since other references to this instance (e.g.
        Microscope.camera) commonly outlive the call to close_camera()
        and would otherwise delay garbage collection.
        """
        self.hardware.close_stream()
        self.hardware.close_camera()
        with PIXISCamera._instance_lock:
            PIXISCamera._instance_active = False
        self.logger.info("PIXISCamera: camera closed.")

    @synchronized
    def shutdown_api(self):
        """
        Uninitialise the camera API.
        Mirrors TucsenCamera.shutdown_api().
        """
        self.logger.info("PIXISCamera: uninitialising API...")
        self.hardware.uninit_api()

    # ------------------------------------------------------------------
    # Destructor guard
    # ------------------------------------------------------------------

    def __del__(self):
        with PIXISCamera._instance_lock:
            PIXISCamera._instance_active = False
