# pixisspec/pixiscam.py

import os
import threading
import time
import numpy as np

from PyQt5.QtCore import QObject, pyqtSignal
from functools import wraps

from pixisspec.pixis_hardware import RealHardware
from pixisspec.simulated_microscope_scene import SimulatedMicroscopeScene
from pixisspec.simulated_picam_device import SimulatedPicamDevice
from pixisspec.spectral_roi import (SENSOR_COLUMNS, SENSOR_ROWS, SpectralRoi,
                                    roi_from_camera_readback)

# Simulate mode: exposures and readouts run at this fraction of real time.
SIMULATED_TIME_SCALE = 0.1
SIMULATED_READOUT_S = 0.1
# grab_frame_safe takes a frame once the sensor is at or below this. The cooler runs flat
# out (RealHardware.SENSOR_TEMPERATURE_SET_POINT_C is below what it reaches, ~-43 C), so
# the sensor is not regulated to the set point; this only catches a camera still cooling
# down after power-on or one whose cooling has failed.
SENSOR_TEMPERATURE_LIMIT_C = -30.0
TEMPERATURE_POLL_INTERVAL_S = 5.0


def synchronized(func):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        with self.camera_lock:
            return func(self, *args, **kwargs)
    return wrapper


class PIXISCamera(QObject):
    """
    Wrapper class for Princeton Instruments PIXIS cameras using pylablib.

    It replaced TucsenCamera and kept its method names where Interface, Microscope and
    AcquisitionControl call them; the Tucsen-only settings (fan, image processing, column
    binning) were removed in November 2026.

    Design contract
    ---------------
    - Exposure times are always in SECONDS at this level. RealHardware converts to ms.
    - The rows read out and their binning are a SpectralRoi (`spectral_roi`, set with
      set_spectral_roi); `roi` is the same region as (HOffset, VOffset, Width, Height) for the
      callers that size the wavelength axis from it. Both hold what the camera reports after
      setting, not what was asked for.
    - simulate=True runs the same RealHardware on a SimulatedPicamDevice imaging
      `self.simulated_scene`, and never touches a camera.

    Acquire and run
    ---------------
    grab_frame / grab_frame_safe ACQUIRE: every frame is exposed after the call, so
    after any move that preceded it. Everything that records data uses them.
    start_continuous_acquisition (the `run` command) RUNS the camera free for live
    viewing during alignment; its frames can predate a move. Acquiring stops a run.
    See RealHardware.
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
        self.acqtime  = 0.5                    # seconds
        # The camera reads the full sensor until an ROI is set (Microscope applies the stored one).
        self.spectral_roi = SpectralRoi.full_sensor()
        self.roi      = (0, 0, SENSOR_COLUMNS, SENSOR_ROWS)   # (HOffset, VOffset, Width, Height)

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

        # ── Hardware backend ───────────────────────────────────────────
        if self.simulate:
            self.simulated_scene = SimulatedMicroscopeScene(interface)
            self.hardware = RealHardware(self, open_device=self._open_simulated_device)
            self.logger.info('PIXISCamera: using a simulated camera device.')
        else:
            self.hardware = RealHardware(self)
            self.logger.info('PIXISCamera: using real hardware.')

        self.logger.info('PIXISCamera __init__ complete.')

    def _open_simulated_device(self, camera_serial, logger):
        """Simulate mode: the Picam device RealHardware opens instead of the real camera."""
        return SimulatedPicamDevice(self.simulated_scene, exposure_s=self.acqtime,
                                    readout_s=SIMULATED_READOUT_S, time_scale=SIMULATED_TIME_SCALE)

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

    def grab_frame(self, timeout=50000):
        """
        Acquire a single frame exposed after this call. Stops a run (live view) first.

        Parameters
        ----------
        timeout : int
            Timeout in milliseconds, matching the Tucsen convention.

        Returns
        -------
        np.ndarray or None
        """
        if self.acquisition_thread is not None and self.acquisition_thread.is_alive():
            self.logger.info("PIXISCamera: stopping the live view (run) to acquire.")
            self.stop_continuous_acquisition()
        with self.camera_lock:
            return self.hardware.grab_frame(timeout=timeout)

    def grab_streamed_frame(self, timeout=50000):
        """Run mode: the newest frame of the live stream (may predate a move); None once stopped."""
        with self.camera_lock:
            if self.stop_flag.is_set():
                return None
            return self.hardware.grab_streamed_frame(timeout=timeout)

    def grab_frame_safe(self, timeout=10000, temperature_wait_timeout_s=600.0,
                        temperature_limit_c=SENSOR_TEMPERATURE_LIMIT_C):
        """
        Acquire a frame once the sensor is cold enough; None if it does not get there in time.

        Cold enough means at or below `temperature_limit_c` (SENSOR_TEMPERATURE_LIMIT_C).
        While waiting, the temperature is checked every TEMPERATURE_POLL_INTERVAL_S; after
        `temperature_wait_timeout_s` an error is logged and None returned, so the caller's
        retry and failure handling takes over instead of the scan hanging. An unreadable
        temperature counts as not cold enough.
        """
        allowed_temperature_c = temperature_limit_c
        give_up_at = time.monotonic() + temperature_wait_timeout_s
        while True:
            sensor_temperature_c = self.hardware.get_temperature()
            if sensor_temperature_c is not None:
                self._publish_temperature(sensor_temperature_c)
            if sensor_temperature_c is not None and sensor_temperature_c <= allowed_temperature_c:
                return self.grab_frame(timeout=timeout)
            seconds_left = give_up_at - time.monotonic()
            if seconds_left <= 0:
                self.logger.error(
                    f"PIXISCamera: sensor at {sensor_temperature_c} °C, "
                    f"allowed {allowed_temperature_c} °C; "
                    f"gave up after {temperature_wait_timeout_s:.0f} s — no frame taken."
                )
                return None
            self.logger.info(
                f"PIXISCamera: sensor at {sensor_temperature_c} °C, "
                f"waiting for {allowed_temperature_c} °C "
                f"({seconds_left:.0f} s left)."
            )
            time.sleep(min(TEMPERATURE_POLL_INTERVAL_S, seconds_left))

    # ------------------------------------------------------------------
    # Continuous acquisition
    # ------------------------------------------------------------------

    def start_continuous_acquisition(self, report=False):
        """
        Run mode (`run`): live frames from the free-running stream on a background thread,
        for alignment and live optimisation. Frames can predate a move; not for data.
        Each cycle of n_frames is averaged with equal weights as the frames arrive.
        Mirrors TucsenCamera.start_continuous_acquisition().
        """
        n_frames = self.interface.acq_ctrl.general_parameters['n_frames']

        def continuous_task():
            try:
                while not self.stop_flag.is_set():
                    frames_this_cycle = []
                    for index in range(n_frames):
                        new_frame = self.grab_streamed_frame(timeout=100000)
                        if self.stop_flag.is_set():
                            self.logger.info(
                                "PIXISCamera: stop flag set — ending acquisition."
                            )
                            return
                        self.get_temperature()

                        if new_frame is None:
                            self.logger.info(
                                "PIXISCamera: no frame from the stream — stopping."
                            )
                            self.stop_flag.set()
                            return

                        frames_this_cycle.append(new_frame.astype(np.float32))
                        data = np.mean(frames_this_cycle, axis=0)

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

        self.stop_flag.clear()
        self.open_stream()
        self.acquisition_thread = threading.Thread(
            target=continuous_task, daemon=True
        )
        self.acquisition_thread.start()
        self.logger.info("PIXISCamera: continuous acquisition started.")

    def stop_continuous_acquisition(self):
        """
        Stop the live view: end the thread, then stop the stream.

        Not synchronized while joining: the thread may be waiting for the camera lock,
        and holding the lock here would keep it from finishing.
        Mirrors TucsenCamera.stop_continuous_acquisition().
        """
        self.stop_flag.set()
        if self.acquisition_thread and self.acquisition_thread.is_alive():
            self.acquisition_thread.join(timeout=self.acqtime + 10)
            if self.acquisition_thread.is_alive():
                self.logger.warning("PIXISCamera: live view thread did not finish in time.")
        self.acquisition_thread = None
        self.close_stream()
        self.logger.info("PIXISCamera: continuous acquisition stopped.")

    # ------------------------------------------------------------------
    # Exposure
    # ------------------------------------------------------------------

    def set_exposure_time(self, value):
        """
        Set the exposure time. Stops a run (live view) first.

        Parameters
        ----------
        value : float or str
            Exposure time in SECONDS, matching the Tucsen convention.
        """
        if not self.stop_flag.is_set():
            self.stop_continuous_acquisition()

        with self.camera_lock:
            ret = self.hardware.set_exposure_time(value)
        if ret is True:
            self.acqtime = float(value)
            self.logger.info(
                f"PIXISCamera: exposure time set to {float(value) * 1000:.1f} ms."
            )
        return ret

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
    def set_spectral_roi(self, spectral_roi):
        """
        Read out these rows (all columns) with this on-chip binning (a SpectralRoi). Returns the
        SpectralRoi the camera reports afterwards (it may trim the rows to whole bins), or None
        if the camera refused, in which case the previous ROI stands.
        """
        camera_roi = self.hardware.set_roi_and_binning(*spectral_roi.camera_roi())
        if camera_roi is None:
            return None
        self.spectral_roi = roi_from_camera_readback(camera_roi, spectral_roi)
        hstart, hend, vstart, vend, _hbin, _vbin = camera_roi
        self.roi = (hstart, vstart, hend - hstart, vend - vstart)
        if self.spectral_roi != spectral_roi:
            self.logger.warning(f"PIXISCamera: asked for {spectral_roi.describe()}; the camera "
                                f"set {self.spectral_roi.describe()}.")
        self.logger.info(f"PIXISCamera: reading {self.spectral_roi.describe()}.")
        return self.spectral_roi

    def set_rows_binned_on_chip(self, rows_binned_on_chip):
        """Bin this many ROI rows on the chip (1: none; 'all': every ROI row). Rows only:
        columns are never binned, so the spectrum keeps one value per pixel."""
        binned_roi = self.spectral_roi.with_rows_binned_on_chip(rows_binned_on_chip)
        return self.set_spectral_roi(binned_roi)

    def describe_readout(self):
        """For the metadata of saved data: the ROI as chosen and as read back, exposure, gain,
        ADC speed, sensor temperature."""
        with self.camera_lock:
            settings = self.hardware.readout_settings()
        return {'spectral_roi': self.spectral_roi.as_dict(),
                'binning': self.spectral_roi.binning_description, **settings}

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
            self._publish_temperature(temp)
        return self.cam_temp

    def _publish_temperature(self, sensor_temperature_c):
        """Record a sensor reading and send it to the GUI (temp_signal)."""
        self.cam_temp = float(round(sensor_temperature_c, 2))
        self.temp_signal.emit(self.cam_temp)

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
    # Gain
    # ------------------------------------------------------------------

    @synchronized
    def set_adc_gain(self, gain_name):
        """Set the ADC analogue gain, 'Low', 'Medium' or 'High' (case ignored). Returns True if
        the camera took it."""
        gain_name = str(gain_name).capitalize()
        if gain_name not in RealHardware.ADC_GAIN_NAMES:
            self.logger.error(f"PIXISCamera: gain must be one of {RealHardware.ADC_GAIN_NAMES}.")
            return False
        return self.hardware.set_adc_gain(gain_name)

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
