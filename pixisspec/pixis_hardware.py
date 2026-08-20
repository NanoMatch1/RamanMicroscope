# pixisspec/pixis_hardware.py

import time
import numpy as np
from pylablib.devices import PrincetonInstruments


class CameraHardwareBase:
    """Mirror of tucsenspec.camera_hardware.CameraHardwareBase for PIXIS cameras."""
    def open_stream(self):          raise NotImplementedError
    def close_stream(self):         raise NotImplementedError
    def grab_frame(self):           raise NotImplementedError
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
    def get_temperature(self):      raise NotImplementedError
    def set_roi(self, roi_tuple):   raise NotImplementedError
    def close_camera(self):         raise NotImplementedError
    def open_camera(self):          raise NotImplementedError
    def uninit_api(self):           raise NotImplementedError


class RealHardware(CameraHardwareBase):
    """
    Real hardware interface for Princeton Instruments PIXIS cameras
    using pylablib. Mirrors the structure of tucsenspec.RealHardware
    so that PIXISCamera can use it as a drop-in hardware backend.

    Exposure units
    --------------
    pylablib / PICAM uses milliseconds for exposure time.
    The rest of the codebase (Microscope.set_acquisition_time) passes
    values in SECONDS (matching the Tucsen convention), so this class
    converts internally:
        seconds  →  milliseconds  before writing to the camera
        milliseconds  →  seconds  before returning to the caller
    """

    # Serial number of the camera to connect to.
    # Change this to match your physical camera.
    CAMERA_SERIAL = '2712050005'

    def __init__(self, camera):
        self.camera         = camera
        self.interface      = camera.interface
        self.logger         = camera.logger.getChild('RealHardware')
        self._stream_open   = False
        self._cam           = None   # pylablib camera object

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialise(self):
        """
        Open the camera, apply default settings, and open the stream.
        Mirrors RealHardware.initialise() in camera_hardware.py.
        """
        self.open_camera()
        self.set_exposure_time(self.camera.acqtime)   # acqtime is in seconds
        self.set_target_temperature(-20)
        self.open_stream()
        self.logger.info("PIXIS camera initialised.")

    def open_camera(self):
        """Connect to the PIXIS camera via pylablib."""
        try:
            available = PrincetonInstruments.list_cameras()
            self.logger.info(f"Available PIXIS cameras: {available}")

            self._cam = PrincetonInstruments.PicamCamera(self.CAMERA_SERIAL)
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
        """Start acquisition on the PIXIS camera."""
        if self._stream_open:
            self.logger.debug("PIXIS: open_stream() called but stream already open.")
            return
        if self._cam is None:
            self.logger.error("PIXIS: Cannot open stream — camera not connected.")
            return
        try:
            self._cam.start_acquisition()
            self._stream_open = True
            self.logger.debug("PIXIS stream opened.")
        except Exception as e:
            self.logger.error(f"PIXIS: Failed to open stream: {e}")

    def close_stream(self):
        """Stop acquisition on the PIXIS camera."""
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

    # ------------------------------------------------------------------
    # Frame acquisition
    # ------------------------------------------------------------------

    def grab_frame(self, timeout=50000):
        """
        Wait for a frame and return it as a numpy array.

        Parameters
        ----------
        timeout : int
            Timeout in milliseconds, matching the Tucsen convention.

        Returns
        -------
        np.ndarray or None
        """
        if self._cam is None:
            self.logger.error("PIXIS: grab_frame() called but camera not connected.")
            return None
        try:
            timeout_s = timeout / 1000.0
            self._cam.wait_for_frame(timeout=timeout_s)
            frame = self._cam.read_newest_image()
            if frame is None:
                self.logger.warning("PIXIS: read_newest_image() returned None.")
            return frame
        except Exception as e:
            self.logger.error(f"PIXIS: grab_frame() failed: {e}")
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
        self.close_stream()
        ms = float(value_s) * 1000.0   # ← correct, keep this
        self._cam.set_attribute_value("Exposure Time", ms)
        self.open_stream()
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
            self.close_stream()

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
            self.open_stream()
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
            self.close_stream()

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
            self.open_stream()
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


# ---------------------------------------------------------------------------
# Simulated hardware
# ---------------------------------------------------------------------------

class SimulatedHardware(CameraHardwareBase):
    """
    Simulated PIXIS hardware for use when no camera is connected.
    Mirrors tucsenspec.SimulatedHardware so PIXISCamera behaves
    identically in simulation mode.
    """

    def __init__(self, camera):
        self.camera     = camera
        self.interface  = camera.interface
        self.logger     = camera.logger.getChild('SimulatedHardware')
        self.acqtime    = 0.5          # seconds
        self.roi        = (0, 0, 1024, 1024)
        self._temperature = -20.0

    def initialise(self):
        self.logger.info("[SIM] PIXIS simulated camera initialised.")
        self.camera.save_transient_spectrum_cb = (
            self.interface.acq_ctrl.save_spectrum_transient
        )

    def open_stream(self):
        self.logger.debug("[SIM] open_stream() called.")

    def close_stream(self):
        self.logger.debug("[SIM] close_stream() called.")

    def grab_frame(self, timeout=100000):
        """Return a simulated CCD frame after a short delay."""
        self.logger.debug("[SIM] grab_frame() called.")
        time.sleep(min(self.acqtime, 0.1))   # cap sim delay at 100 ms
        return self._generate_simulated_image()

    def open_camera(self):
        self.logger.debug("[SIM] open_camera() stub.")

    def close_camera(self):
        self.logger.debug("[SIM] close_camera() stub.")

    def uninit_api(self):
        self.logger.debug("[SIM] uninit_api() stub.")

    def set_exposure_time(self, value_s):
        try:
            self.acqtime = float(value_s)
            return True
        except ValueError:
            self.logger.error("[SIM] Invalid exposure time value.")
            return False

    def get_exposure_time(self):
        return self.acqtime

    def set_roi(self, roi_tuple):
        self.logger.info(f"[SIM] ROI set to {roi_tuple}.")
        self.roi = roi_tuple

    def set_hardware_binning(self, binning_level=1):
        self.logger.debug(f"[SIM] set_hardware_binning({binning_level}) stub.")

    def get_temperature(self):
        return self._temperature + np.random.uniform(-0.5, 0.5)

    def set_target_temperature(self, target_celsius):
        self.logger.info(f"[SIM] Target temperature set to {target_celsius} °C.")
        self._temperature = float(target_celsius)

    def enable_auto_temperature_control(self, enable):
        state = "enabled" if enable else "disabled"
        self.logger.debug(f"[SIM] Auto temperature control {state}.")

    def get_fan_speed(self):
        return 3

    def set_fan_speed(self, speed):
        self.logger.debug(f"[SIM] set_fan_speed({speed}) stub.")

    def set_image_and_gain(self, img_mode, gain_level):
        self.logger.debug(f"[SIM] set_image_and_gain({img_mode}, {gain_level}) stub.")

    def set_image_processing(self, value):
        self.logger.debug(f"[SIM] set_image_processing({value}) stub.")

    def set_denoise(self, value):
        self.logger.debug(f"[SIM] set_denoise({value}) stub.")

    def set_resolution(self, resolution):
        self.logger.debug(f"[SIM] set_resolution({resolution}) stub.")

    def get_camera_info(self):
        return {
            "Exposure Time"               : self.acqtime * 1000,
            "Sensor Temperature Reading"  : self.get_temperature(),
            "Sensor Temperature Set Point": self._temperature,
            "Sensor Temperature Status"   : "Locked",
            "ADC Speed"                   : 1.0,
            "ADC Analog Gain"             : "Low",
            "Readout Count"               : 1,
        }

    # ------------------------------------------------------------------
    # Simulated image generation
    # ------------------------------------------------------------------

    def _generate_simulated_image(self, width=1024, height=100):
        """
        Generate a realistic-looking simulated CCD spectrum image.
        Mirrors SimulatedHardware._generate_simulated_image() in
        camera_hardware.py so downstream code sees the same data shape.
        """
        background   = 400
        noise        = np.random.randint(-30, 30, (height, width))

        laser_signal = self._generate_simulated_laser_signal(
            width=width, height=height
        )

        image = background + laser_signal + noise
        image = np.clip(image, 0, 65535).astype(np.uint16)
        return image

    def _generate_simulated_laser_signal(
        self, width=1024, height=100,
        laser_width=3, y_spread=15,
        peak_height=20000, peak_sigma=0.1
    ):
        """Generate a Gaussian laser line on the simulated CCD."""
        try:
            laser_on = (
                self.interface.laser.status == 'ON'
                and self.interface.laser.current_power >= 3
            )
        except Exception:
            laser_on = False

        if not laser_on:
            return np.zeros((height, width), dtype=np.float32)

        try:
            wavelength_axis = self.interface.microscope.wavelength_axis
            laser_wavelength = (
                self.interface.microscope.laser_wavelength_calibrated
                or next(iter(
                    self.interface.microscope.laser_wavelengths.values()
                ), 785)
            )
            laser_px = int(np.argmin(np.abs(wavelength_axis - laser_wavelength)))
        except Exception:
            laser_px = width // 2

        Y, X = np.meshgrid(np.arange(height), np.arange(width), indexing='ij')
        signal = (
            np.exp(-0.5 * ((X - laser_px)   / laser_width) ** 2) *
            np.exp(-0.5 * ((Y - height / 2) / y_spread)   ** 2)
        )
        scale  = abs(np.random.normal(peak_height, peak_height * peak_sigma))
        return (signal * scale).astype(np.float32)
