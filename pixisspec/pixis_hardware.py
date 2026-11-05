# pixisspec/pixis_hardware.py

from contextlib import contextmanager

from pylablib.devices import PrincetonInstruments


class CameraHardwareBase:
    """Mirror of tucsenspec.camera_hardware.CameraHardwareBase for PIXIS cameras."""
    def open_stream(self):          raise NotImplementedError
    def close_stream(self):         raise NotImplementedError
    def grab_frame(self):           raise NotImplementedError
    def acquire_frames(self, frame_count, timeout): raise NotImplementedError
    def grab_streamed_frame(self, timeout): raise NotImplementedError
    def initialise(self):           raise NotImplementedError
    def set_exposure_time(self, value): raise NotImplementedError
    def set_image_and_gain(self, img_mode, gain_level): raise NotImplementedError
    def set_image_processing(self, value): raise NotImplementedError
    def set_resolution(self, resolution): raise NotImplementedError
    def set_denoise(self, value):   raise NotImplementedError
    def set_fan_speed(self, speed): raise NotImplementedError
    def get_fan_speed(self):        raise NotImplementedError
    def enable_auto_temperature_control(self, enable): raise NotImplementedError
    def set_target_temperature(self, target_celsius): raise NotImplementedError
    def get_target_temperature(self): raise NotImplementedError
    def get_temperature(self):      raise NotImplementedError
    def set_roi(self, roi_tuple):   raise NotImplementedError
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
        self.set_target_temperature(-20)
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
                                     timeout=frame_count * timeout / 1000.0)
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
            self._cam.wait_for_frame(timeout=timeout / 1000.0)
            frame = self._cam.read_newest_image()
            if frame is None:
                self.logger.warning("PIXIS: read_newest_image() returned None.")
            return frame
        except Exception as e:
            self.logger.error(f"PIXIS: grab_streamed_frame() failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Exposure
    # ------------------------------------------------------------------

    def set_exposure_time(self, value_s):
        """
        Parameters
        ----------
        value_s : float
            Exposure time in SECONDS — converted to ms for PICAM internally.
        """
        if self._cam is None:
            self.logger.error("PIXIS: set_exposure_time() called but camera not connected.")
            return False
        with self._stream_paused():
            ms = float(value_s) * 1000.0   # ← correct, keep this
            self._cam.set_attribute_value("Exposure Time", ms)
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
    # ROI
    # ------------------------------------------------------------------

    def set_roi(self, roi_tuple):
        """
        Set the camera ROI.

        Parameters
        ----------
        roi_tuple : tuple
            (HOffset, VOffset, Width, Height) — same convention as Tucsen.
            Converted to the pylablib ROI named-tuple format internally.
        """
        if self._cam is None:
            self.logger.error("PIXIS: set_roi() called but camera not connected.")
            return
        try:
            with self._stream_paused():
                h_offset, v_offset, width, height = roi_tuple

                current_rois = self._cam.get_attribute_value("ROIs")
                roi          = current_rois[0]

                # pylablib ROI namedtuple fields:
                # (x, width, x_binning, y, height, y_binning)
                try:
                    new_roi = roi._replace(
                        x       = h_offset,
                        width   = width,
                        y       = v_offset,
                        height  = height,
                    )
                except AttributeError:
                    # Fallback: build as plain tuple if _replace unavailable
                    new_roi = (h_offset, width, 1, v_offset, height, 1)

                self._cam.set_attribute_value("ROIs", [new_roi])
                self.logger.info(f"PIXIS ROI set to {roi_tuple}.")
        except Exception as e:
            self.logger.error(f"PIXIS: set_roi() failed: {e}")

    # ------------------------------------------------------------------
    # Binning
    # ------------------------------------------------------------------

    def set_hardware_binning(self, binning_level=1):
        """
        Set hardware binning on both axes.

        Parameters
        ----------
        binning_level : int
            Binning factor applied to both X and Y axes.
        """
        if self._cam is None:
            self.logger.error("PIXIS: set_hardware_binning() called but camera not connected.")
            return
        try:
            with self._stream_paused():
                current_rois = self._cam.get_attribute_value("ROIs")
                roi          = current_rois[0]

                try:
                    new_roi = roi._replace(
                        x_binning = binning_level,
                        y_binning = binning_level,
                    )
                except AttributeError:
                    new_roi = (0, 1024, binning_level, 0, 1024, binning_level)

                self._cam.set_attribute_value("ROIs", [new_roi])
                self.logger.info(f"PIXIS binning set to {binning_level}x{binning_level}.")
        except Exception as e:
            self.logger.error(f"PIXIS: set_hardware_binning() failed: {e}")

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
            self._cam.set_attribute_value("Sensor Temperature Set Point", float(target_celsius))
            self.logger.info(f"PIXIS target temperature set to {target_celsius:.1f} °C.")
        except Exception as e:
            self.logger.error(f"PIXIS: set_target_temperature() failed: {e}")

    def enable_auto_temperature_control(self, enable):
        """
        The PIXIS manages its own TEC automatically.
        This is a stub for interface parity — logs the call but takes no action.
        """
        state = "enabled" if enable else "disabled"
        self.logger.info(f"[PIXIS] Auto temperature control {state} (managed by camera firmware).")

    # ------------------------------------------------------------------
    # Fan speed — no direct PICAM equivalent
    # ------------------------------------------------------------------

    def get_fan_speed(self):
        """
        The PIXIS has no software-controllable fan speed.
        Returns a fixed sentinel value (3 = high) for interface parity.
        """
        self.logger.debug("[PIXIS] get_fan_speed() — no fan control on PIXIS, returning 3.")
        return 3

    def set_fan_speed(self, speed):
        """Stub — PIXIS fan speed is not software-controllable."""
        self.logger.debug(f"[PIXIS] set_fan_speed({speed}) — no fan control on PIXIS, ignoring.")

    # ------------------------------------------------------------------
    # Stubs for Tucsen-specific features with no PIXIS equivalent
    # ------------------------------------------------------------------

    def set_image_and_gain(self, img_mode, gain_level):
        """
        PIXIS gain is set via ADC Analog Gain attribute.
        img_mode is ignored — no direct equivalent on PIXIS.
        gain_level mapping: 0=Low, 1=Medium, 2=High.
        """
        gain_map = {0: "Low", 1: "Medium", 2: "High"}
        gain_str = gain_map.get(int(gain_level), "Low")
        if self._cam is not None:
            try:
                self._cam.set_attribute_value("ADC Analog Gain", gain_str)
                self.logger.info(f"PIXIS ADC gain set to {gain_str}.")
            except Exception as e:
                self.logger.error(f"PIXIS: set_image_and_gain() failed: {e}")

    def set_image_processing(self, value):
        """No image processing pipeline on PIXIS — stub for parity."""
        self.logger.debug(f"[PIXIS] set_image_processing({value}) — no-op.")

    def set_denoise(self, value):
        """No denoise capability on PIXIS — stub for parity."""
        self.logger.debug(f"[PIXIS] set_denoise({value}) — no-op.")

    def set_resolution(self, resolution):
        """
        No resolution switching on PIXIS in the Tucsen sense.
        Stub for parity.
        """
        self.logger.debug(f"[PIXIS] set_resolution({resolution}) — no-op.")

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
        return info


