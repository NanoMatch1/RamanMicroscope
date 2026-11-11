# pixisspec/pixis_hardware.py

from contextlib import contextmanager

from pylablib.devices import PrincetonInstruments


class CameraHardwareBase:
    """What PIXISCamera needs from a camera backend."""
    def open_stream(self):          raise NotImplementedError
    def close_stream(self):         raise NotImplementedError
    def grab_frame(self):           raise NotImplementedError
    def acquire_frames(self, frame_count, timeout): raise NotImplementedError
    def grab_streamed_frame(self, timeout): raise NotImplementedError
    def initialise(self):           raise NotImplementedError
    def set_exposure_time(self, value): raise NotImplementedError
    def get_exposure_time(self):    raise NotImplementedError
    def set_adc_gain(self, gain_name): raise NotImplementedError
    def set_target_temperature(self, target_celsius): raise NotImplementedError
    def get_target_temperature(self): raise NotImplementedError
    def get_temperature(self):      raise NotImplementedError
    def set_roi_and_binning(self, hstart, hend, vstart, vend, hbin, vbin): raise NotImplementedError
    def get_roi_on_camera(self):    raise NotImplementedError
    def readout_settings(self):     raise NotImplementedError
    def close_camera(self):         raise NotImplementedError
    def open_camera(self):          raise NotImplementedError
    def uninit_api(self):           raise NotImplementedError


def open_pylablib_picam_camera(camera_serial, logger):
    """Connect to a Princeton Instruments camera through pylablib."""
    logger.info(f"Available PIXIS cameras: {PrincetonInstruments.list_cameras()}")
    return PrincetonInstruments.PicamCamera(camera_serial)


class RealHardware(CameraHardwareBase):
    """
    Real hardware interface for Princeton Instruments PIXIS cameras
    using pylablib. Mirrors the structure of tucsenspec.RealHardware
    so that PIXISCamera can use it as a drop-in hardware backend.

    Two ways of taking frames
    -------------------------
    ACQUIRE (grab_frame, acquire_frames), the default for everything that records data:
        an acquisition is started when the frames are requested and stopped once they
        are read, so every frame is exposed after the request -- after the move that
        preceded it. The CCD is idle between acquisitions.
    RUN (open_stream, grab_streamed_frame), for live viewing during alignment only:
        the CCD free-runs into a ring buffer and the newest frame is returned at once.
        That frame may have been exposed before the request (measured on the lab PC,
        2026-11-06: 1.0-1.8 s before it at 0.5 s exposure), which is fine for watching
        but wrong for data. An acquisition stops a running stream first.

    Frame timeouts
    --------------
    A frame is waited for at least its exposure plus FRAME_TIMEOUT_MARGIN_S, whatever timeout
    the caller passes, so a long exposure (minutes, for weak Raman signals) never times out
    while it is still exposing. The caller's timeout only matters when it is longer.

    Exposure units
    --------------
    pylablib / PICAM uses milliseconds for exposure time.
    The rest of the codebase (Microscope.set_acquisition_time) passes
    values in SECONDS (matching the Tucsen convention), so this class
    converts internally:
        seconds  →  milliseconds  before writing to the camera
        milliseconds  →  seconds  before returning to the caller

    The pylablib camera object comes from `open_device(serial, logger)`: pylablib's
    PicamCamera by default, or pixisspec.simulated_picam_device.SimulatedPicamDevice in
    simulate mode, so the code here runs in tests and simulation as well.
    """

    # Serial number of the camera to connect to.
    # Change this to match your physical camera.
    CAMERA_SERIAL = '2712050005'
    # Ring buffer for both acquire and run; the same parameters mean switching between
    # them does not make pylablib reallocate the buffer.
    ACQUISITION_BUFFER_FRAMES = 100
    # Sensor set point. The PIXIS 1024F here gets to about -43 C (its vacuum is no longer
    # good enough for the -70 C of the specification), so asking for -50 C runs the cooler
    # flat out: coldest sensor, least dark current, status "Unlocked". The former -20 C was
    # the Tucsen's set point, carried over in the port; it held this sensor ~25 C warmer
    # than it can run (about ten times the dark current).
    SENSOR_TEMPERATURE_SET_POINT_C = -50.0
    # Allowance on top of the exposure when waiting for a frame: the readout (0.56 s for the
    # full sensor at 2 MHz, ~11 s at 100 kHz) plus the start of the acquisition.
    FRAME_TIMEOUT_MARGIN_S = 30.0
    ADC_GAIN_NAMES = ('Low', 'Medium', 'High')

    def __init__(self, camera, open_device=open_pylablib_picam_camera):
        self.camera         = camera
        self.interface      = camera.interface
        self.logger         = camera.logger.getChild('RealHardware')
        self.open_device    = open_device
        self._stream_open   = False
        self._cam           = None   # pylablib camera object

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialise(self):
        """
        Open the camera and apply default settings. The CCD stays idle until
        frames are acquired or the live stream is started (run).
        """
        self.open_camera()
        self.set_exposure_time(self.camera.acqtime)   # acqtime is in seconds
        self.set_target_temperature(self.SENSOR_TEMPERATURE_SET_POINT_C)
        self.logger.info("PIXIS camera initialised.")

    def open_camera(self):
        """Connect to the PIXIS camera."""
        try:
            self._cam = self.open_device(self.CAMERA_SERIAL, self.logger)
            self.logger.info(f"Connected to PIXIS camera: {self.CAMERA_SERIAL}")
        except Exception as e:
            self.logger.error(f"Failed to open PIXIS camera: {e}")
            self._cam = None

    def close_camera(self):
        """Disconnect from the PIXIS camera."""
        if self._cam is not None:
            try:
                self._cam.close()
                self.logger.info("PIXIS camera closed.")
            except Exception as e:
                self.logger.error(f"Error closing PIXIS camera: {e}")
            finally:
                self._cam = None
                self._stream_open = False

    def uninit_api(self):
        """
        No explicit API uninit needed for pylablib.
        Stub kept for interface parity with TucsenCamera.
        """
        self.logger.debug("[PIXIS] uninit_api() — no-op for pylablib.")

    # ------------------------------------------------------------------
    # Stream control
    # ------------------------------------------------------------------

    def open_stream(self):
        """Run mode: start the CCD free-running into the ring buffer (live viewing only)."""
        if self._stream_open:
            self.logger.debug("PIXIS: open_stream() called but stream already open.")
            return
        if self._cam is None:
            self.logger.error("PIXIS: Cannot open stream — camera not connected.")
            return
        try:
            self._cam.start_acquisition(mode='sequence', nframes=self.ACQUISITION_BUFFER_FRAMES)
            self._stream_open = True
            self.logger.debug("PIXIS stream opened.")
        except Exception as e:
            self.logger.error(f"PIXIS: Failed to open stream: {e}")

    def close_stream(self):
        """Stop the free-running stream."""
        if not self._stream_open:
            return
        if self._cam is None:
            return
        try:
            self._cam.stop_acquisition()
            self._stream_open = False
            self.logger.debug("PIXIS stream closed.")
        except Exception as e:
            self.logger.error(f"PIXIS: Failed to close stream: {e}")

    @contextmanager
    def _stream_paused(self):
        """Stop the stream for a settings change; restart it afterwards only if it was running."""
        was_streaming = self._stream_open
        self.close_stream()
        try:
            yield
        finally:
            if was_streaming:
                self.open_stream()

    # ------------------------------------------------------------------
    # Frame acquisition
    # ------------------------------------------------------------------

    def grab_frame(self, timeout=50000):
        """
        Acquire one frame exposed after this call (acquire mode).

        Parameters
        ----------
        timeout : int
            Timeout in milliseconds, matching the Tucsen convention.

        Returns
        -------
        np.ndarray or None
        """
        frames = self.acquire_frames(1, timeout=timeout)
        return None if frames is None else frames[0]

    def acquire_frames(self, frame_count, timeout=50000):
        """
        Acquire `frame_count` frames, all exposed after this call; None on failure.

        A sequence acquisition is started now, the first `frame_count` frames are read,
        and it is stopped while still running. pylablib's own grab() snaps instead, and
        with pylablib 1.4.5 its stop_acquisition() can raise
        PicamError_AcquisitionNotInProgress once a snap has finished by itself (seen on
        the lab PC, 2026-11-05); stopping a running sequence does not have that problem.

        `timeout` is in milliseconds per frame.
        """
        if self._cam is None:
            self.logger.error("PIXIS: acquire_frames() called but camera not connected.")
            return None
        if self._stream_open:
            self.logger.info("PIXIS: stopping the live stream to acquire.")
            self.close_stream()
        try:
            self._cam.start_acquisition(mode='sequence', nframes=self.ACQUISITION_BUFFER_FRAMES)
            self._cam.wait_for_frame(since='start', nframes=frame_count,
                                     timeout=frame_count * self.frame_timeout_s(timeout))
            frames = self._cam.read_multiple_images(rng=(0, frame_count))
            if frames is None or len(frames) < frame_count:
                frames_read = 0 if frames is None else len(frames)
                self.logger.error(f"PIXIS: acquired {frames_read} of {frame_count} frames.")
                return None
            return list(frames)
        except Exception as e:
            self.logger.error(f"PIXIS: acquire_frames({frame_count}) failed: {e}")
            return None
        finally:
            try:
                self._cam.stop_acquisition()
            except Exception as e:
                self.logger.warning(f"PIXIS: stopping the acquisition raised: {e}")

    def grab_streamed_frame(self, timeout=50000):
        """
        Run mode: the newest frame from the free-running stream, starting the stream if needed.

        Returns at once if a frame is waiting, so the frame may have been exposed before this
        call. For live viewing only; data must come from grab_frame / acquire_frames.
        `timeout` is in milliseconds.
        """
        if self._cam is None:
            self.logger.error("PIXIS: grab_streamed_frame() called but camera not connected.")
            return None
        if not self._stream_open:
            self.open_stream()
        try:
            self._cam.wait_for_frame(timeout=self.frame_timeout_s(timeout))
            frame = self._cam.read_newest_image()
            if frame is None:
                self.logger.warning("PIXIS: read_newest_image() returned None.")
            return frame
        except Exception as e:
            self.logger.error(f"PIXIS: grab_streamed_frame() failed: {e}")
            return None

    def frame_timeout_s(self, caller_timeout_ms=0):
        """How long to wait for one frame (s): its exposure plus FRAME_TIMEOUT_MARGIN_S, or the
        caller's timeout if longer."""
        exposure_s = self.get_exposure_time() or self.camera.acqtime
        return max(caller_timeout_ms / 1000.0, exposure_s + self.FRAME_TIMEOUT_MARGIN_S)

    # ------------------------------------------------------------------
    # Exposure
    # ------------------------------------------------------------------

    def set_exposure_time(self, value_s):
        """
        Set the exposure in SECONDS (Picam takes ms). Returns True if the camera took the value,
        False otherwise; a value outside the camera's range is clipped by pylablib without a
        word, so it is read back and a difference is reported.
        """
        if self._cam is None:
            self.logger.error("PIXIS: set_exposure_time() called but camera not connected.")
            return False
        requested_s = float(value_s)
        with self._stream_paused():
            self._cam.set_attribute_value("Exposure Time", requested_s * 1000.0)
        exposure_s = self.get_exposure_time()
        if exposure_s is not None and abs(exposure_s - requested_s) > 1e-3 * max(1.0, requested_s):
            self.logger.error(f"PIXIS: asked for a {requested_s:g} s exposure, the camera set "
                              f"{exposure_s:g} s (outside its range).")
            return False
        return True

    def get_exposure_time(self):
        """
        Returns the current exposure time in SECONDS.
        """
        if self._cam is None:
            return None
        try:
            ms = self._cam.get_attribute_value("Exposure Time")
            return ms / 1000.0
        except Exception as e:
            self.logger.error(f"PIXIS: get_exposure_time() failed: {e}")
            return None

    # ------------------------------------------------------------------
    # ROI and binning
    # ------------------------------------------------------------------

    def set_roi_and_binning(self, hstart, hend, vstart, vend, hbin, vbin):
        """
        Set the region read out and its on-chip binning (pylablib's set_roi, which keeps the ROI
        on the sensor and trims it to whole bins). Returns what the camera set, as get_roi()'s
        (hstart, hend, vstart, vend, hbin, vbin), or None if it failed.
        """
        if self._cam is None:
            self.logger.error("PIXIS: set_roi_and_binning() called but camera not connected.")
            return None
        try:
            with self._stream_paused():
                self._cam.set_roi(hstart, hend, vstart, vend, hbin, vbin)
            return self.get_roi_on_camera()
        except Exception as e:
            self.logger.error(f"PIXIS: set_roi_and_binning() failed: {e}")
            return None

    def get_roi_on_camera(self):
        """The camera's ROI as (hstart, hend, vstart, vend, hbin, vbin), or None if unreadable."""
        if self._cam is None:
            return None
        try:
            return tuple(int(value) for value in self._cam.get_roi())
        except Exception as e:
            self.logger.error(f"PIXIS: get_roi_on_camera() failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Temperature
    # ------------------------------------------------------------------

    def get_temperature(self):
        """Returns the current sensor temperature in degrees Celsius."""
        if self._cam is None:
            return None
        try:
            return float(self._cam.get_attribute_value("Sensor Temperature Reading"))
        except Exception as e:
            self.logger.error(f"PIXIS: get_temperature() failed: {e}")
            return None

    def get_target_temperature(self):
        """Returns the sensor temperature set point in degrees Celsius, or None if unreadable."""
        if self._cam is None:
            return None
        try:
            return float(self._cam.get_attribute_value("Sensor Temperature Set Point"))
        except Exception as e:
            self.logger.error(f"PIXIS: get_target_temperature() failed: {e}")
            return None

    def set_target_temperature(self, target_celsius):
        """
        Set the target sensor temperature.

        Parameters
        ----------
        target_celsius : float
        """
        if self._cam is None:
            self.logger.error("PIXIS: set_target_temperature() called but camera not connected.")
            return
        try:
            # Picam keeps written settings until they are committed, and pylablib commits only
            # when an acquisition is set up or started; commit now so the cooler gets it at once.
            with self._stream_paused():
                self._cam.set_attribute_value("Sensor Temperature Set Point", float(target_celsius))
                self._commit_settings_to_camera()
            set_point_c = self.get_target_temperature()
            if set_point_c is not None and abs(set_point_c - float(target_celsius)) > 0.01:
                # pylablib clips a set point outside the camera's range without saying so
                self.logger.warning(f"PIXIS: asked for a {target_celsius:.1f} °C set point, "
                                    f"the camera allows {set_point_c:.1f} °C.")
            self.logger.info(f"PIXIS target temperature set to {set_point_c} °C.")
        except Exception as e:
            self.logger.error(f"PIXIS: set_target_temperature() failed: {e}")

    def _commit_settings_to_camera(self):
        """Send written settings to the camera. pylablib commits in setup_acquisition."""
        self._cam.setup_acquisition(mode='sequence', nframes=self.ACQUISITION_BUFFER_FRAMES)

    # ------------------------------------------------------------------
    # Gain
    # ------------------------------------------------------------------

    def set_adc_gain(self, gain_name):
        """Set the ADC analogue gain: 'Low', 'Medium' or 'High' (counts per electron rise with
        it). Returns True if the camera reports the new gain."""
        if self._cam is None:
            self.logger.error("PIXIS: set_adc_gain() called but camera not connected.")
            return False
        try:
            with self._stream_paused():
                self._cam.set_attribute_value("ADC Analog Gain", gain_name)
                self._commit_settings_to_camera()
            gain_now = self._cam.get_attribute_value("ADC Analog Gain")
            self.logger.info(f"PIXIS ADC gain: {gain_now}.")
            return str(gain_now) == gain_name
        except Exception as e:
            self.logger.error(f"PIXIS: set_adc_gain({gain_name!r}) failed: {e}")
            return False

    def readout_settings(self):
        """What a saved frame needs to be interpreted: ROI and binning as set on the camera,
        exposure, gain, ADC speed, sensor temperature. Unreadable values are None."""
        def read_attribute(name):
            try:
                return self._cam.get_attribute_value(name) if self._cam is not None else None
            except Exception:
                return None
        return {
            'camera_roi_hstart_hend_vstart_vend_hbin_vbin': self.get_roi_on_camera(),
            'exposure_s': self.get_exposure_time(),
            'adc_analog_gain': read_attribute("ADC Analog Gain"),
            'adc_speed_mhz': read_attribute("ADC Speed"),
            'sensor_temperature_c': self.get_temperature(),
            'sensor_set_point_c': self.get_target_temperature(),
        }

    def get_camera_info(self):
        """Return a dict of key camera attributes for logging/debugging."""
        if self._cam is None:
            return {}
        info = {}
        attrs = [
            "Exposure Time",
            "Sensor Temperature Reading",
            "Sensor Temperature Set Point",
            "Sensor Temperature Status",
            "ADC Speed",
            "ADC Analog Gain",
            "Readout Count",
        ]
        for attr in attrs:
            try:
                info[attr] = self._cam.get_attribute_value(attr)
            except Exception:
                info[attr] = "unavailable"
        info["ROI (hstart, hend, vstart, vend, hbin, vbin)"] = self.get_roi_on_camera()
        try:  # the camera's allowed exposure range, from pylablib's attribute constraints
            exposure_attribute = self._cam.ca["Exposure Time"]
            info["Exposure Time range (ms)"] = (exposure_attribute.min, exposure_attribute.max)
        except Exception:
            info["Exposure Time range (ms)"] = "unavailable"
        return info


