"""
laser_tracking_system.py

Coordinates:
  - Tiger Ti:Sapph laser  (Codebase 1 serial protocol)
  - PIXIS 1024 CCD camera (Codebase 2 pylablib interface)
  - Triax spectrometer    (Codebase 3 Triax class protocol)

Workflow:
  1. Connect all instruments with fixed default acquisition parameters.
  2. Run a two-part gradient calibration:
       a. Laser gradient  — step laser +100, measure pixel shift → px/laser_step
       b. Triax gradient  — step Triax +100, measure pixel shift → px/triax_step
  3. Compute the combined correction gradient:
       triax_steps_per_laser_step = laser_gradient / triax_gradient
  4. Enter the tracking loop:
       - Step laser by LASER_STEPS_PER_MOVE
       - Acquire frame, fit Voigt centre
       - Apply Triax correction to hold laser at pixel 50
"""

import time
import serial
import numpy as np
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit
from scipy.special import voigt_profile
from pylablib.devices import PrincetonInstruments

# ============================================================
# CONFIGURATION
# ============================================================

# --- Laser (Tiger Ti:Sapph) — Codebase 1 protocol ---
LASER_COM_PORT  = 'COM17'
LASER_BAUD_RATE = 9600

# --- Triax Spectrometer — Codebase 3 protocol ---
TRIAX_COM_PORT  = 'COM16'
TRIAX_BAUD_RATE = 4800

# --- PIXIS Camera — Codebase 2 protocol ---
CAMERA_SERIAL = '2712050005'

# --- Fixed default acquisition parameters (set automatically) ---
EXPOSURE_MS  = 100.0   # ms
AVG_FRAMES   = 3       # frames averaged per measurement

# --- Laser stepping ---
LASER_STEPS_PER_MOVE = 100

# --- Gradient calibration ---
LASER_CAL_STEPS = 100   # laser steps used for gradient measurement
TRIAX_CAL_STEPS = 100   # Triax steps used for gradient measurement

# --- Tracking ---
TARGET_PIXEL      = 50.0
MAX_TRIAX_CORRECTION = 5000   # safety clamp (steps)

# --- CCD ROI for spectrum extraction ---
ROI_Y_START = 550
ROI_Y_END   = 650
ROI_X_START = 10
ROI_X_END   = 1024


# ============================================================
# SECTION 1 — LASER COMMUNICATION  (Codebase 1)
# ============================================================

def laser_connect(port: str, baud: int) -> serial.Serial:
    """
    Open a serial connection to the Tiger Ti:Sapph laser controller.
    Uses the exact serial configuration from Codebase 1.
    """
    ser = serial.Serial(
        port     = port,
        baudrate = baud,
        bytesize = 8,
        parity   = 'N',
        stopbits = 1,
        timeout  = 2,
    )
    print(f"[LASER] Connected on {port} at {baud} baud.")
    return ser


def laser_send_command(ser: serial.Serial, command: str) -> bool:
    """
    Send a raw ASCII command to the laser and interpret the response.
    Mirrors send_command() from Codebase 1 exactly.

    Returns True on ACK (0x06), False on NAK (0x15) or no response.
    """
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    ser.write(command.encode('ascii'))
    time.sleep(0.5)
    response = ser.read(ser.in_waiting)

    if response == b'\x06':
        return True
    elif response == b'\x15':
        print(f"[LASER] NAK received for command: {command}")
        return False
    else:
        print(f"[LASER] Unexpected response: {response!r}")
        return False


def laser_format_steps(value: int) -> str:
    """Zero-pad an integer to 6 digits — matches format_value() in Codebase 1."""
    return str(int(value)).zfill(6)


def laser_step_increase(ser: serial.Serial, n_steps: int) -> bool:
    """
    Command the birefringent filter to increase wavelength by n_steps.
    Command format from Codebase 1: *M1!SInnnnnn#
    """
    command = f'*M1!SI{laser_format_steps(n_steps)}#'
    success = laser_send_command(ser, command)
    if success:
        print(f"[LASER] Stepped +{n_steps} (increase).")
    return success


def laser_step_decrease(ser: serial.Serial, n_steps: int) -> bool:
    """
    Command the birefringent filter to decrease wavelength by n_steps.
    Command format from Codebase 1: *M1!SDnnnnnn#
    """
    command = f'*M1!SD{laser_format_steps(n_steps)}#'
    success = laser_send_command(ser, command)
    if success:
        print(f"[LASER] Stepped -{n_steps} (decrease).")
    return success


# ============================================================
# SECTION 2 — PIXIS CAMERA COMMUNICATION  (Codebase 2)
# ============================================================

def camera_connect(serial_number: str) -> PrincetonInstruments.PicamCamera:
    """
    Connect to the PIXIS 1024 camera using pylablib.
    Mirrors the connection approach from Codebase 2.
    """
    print("[CAMERA] Searching for connected PIXIS cameras...")
    cameras = PrincetonInstruments.list_cameras()
    print(f"[CAMERA] Found: {cameras}")
    if not cameras:
        raise RuntimeError("[CAMERA] No Princeton Instruments cameras detected.")
    cam = PrincetonInstruments.PicamCamera(serial_number)
    print(f"[CAMERA] Connected to camera: {serial_number}")
    return cam


def camera_configure(
    cam:         PrincetonInstruments.PicamCamera,
    exposure_ms: float,
    avg_frames:  int,
) -> None:
    """
    Set exposure time and readout count on the PIXIS camera.
    Uses attribute names from Codebase 2.
    Called once at startup with fixed defaults — no user prompt.
    """
    cam.set_attribute_value("Exposure Time", exposure_ms)
    cam.set_attribute_value("Readout Count", avg_frames)
    print(
        f"[CAMERA] Parameters set automatically:\n"
        f"         Exposure time : {exposure_ms:.1f} ms\n"
        f"         Avg frames    : {avg_frames}"
    )


def camera_acquire_averaged_frame(
    cam:         PrincetonInstruments.PicamCamera,
    avg_frames:  int,
    exposure_ms: float,
) -> np.ndarray | None:
    """
    Acquire avg_frames frames, average them, and return the 2-D array.
    Mirrors acquire_calibration_frame() from Codebase 2.

    Returns the averaged 2-D image array, or None on failure.
    """
    try:
        cam.stop_acquisition()
    except Exception:
        pass

    cam.set_attribute_value("Readout Count", avg_frames)
    cam.start_acquisition()

    accumulated      = None
    frames_collected = 0
    timeout          = (exposure_ms / 1000.0) + 5.0

    try:
        for _ in range(avg_frames):
            cam.wait_for_frame(timeout=timeout)
            frame = cam.read_newest_image()
            if frame is not None:
                if accumulated is None:
                    accumulated = frame.astype(np.float64)
                else:
                    accumulated += frame.astype(np.float64)
                frames_collected += 1
    except Exception as exc:
        print(f"[CAMERA] Frame acquisition error: {exc}")

    try:
        cam.stop_acquisition()
    except Exception:
        pass

    if frames_collected == 0 or accumulated is None:
        print("[CAMERA] No frames collected.")
        return None

    return accumulated / frames_collected


def camera_extract_spectrum(
    full_frame: np.ndarray,
    y_start:    int = ROI_Y_START,
    y_end:      int = ROI_Y_END,
    x_start:    int = ROI_X_START,
    x_end:      int = ROI_X_END,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Extract the mean x-spectrum from the ROI rows y_start:y_end.
    Mirrors the ROI extraction in acquire_calibration_frame() from Codebase 2.

    Returns
    -------
    x_pixels   : 1-D array of pixel indices
    x_spectrum : 1-D array of mean intensity values
    """
    region     = full_frame[y_start:y_end, x_start:x_end].astype(np.float64)
    x_spectrum = region.mean(axis=0)
    x_pixels   = np.arange(x_start, x_end)
    return x_pixels, x_spectrum


# ============================================================
# SECTION 3 — VOIGT FIT  (Codebase 2 fit functions)
# ============================================================

def _voigt_model(x, amplitude, center, sigma, gamma, offset):
    """
    Voigt profile with background offset.
    Taken directly from Codebase 2 — voigt().
    """
    peak_norm = voigt_profile(0, sigma, gamma)
    if peak_norm == 0:
        return np.full_like(x, offset, dtype=np.float64)
    return offset + (amplitude / peak_norm) * voigt_profile(
        x - center, sigma, gamma
    )


def _gaussian_model(x, amplitude, center, sigma, offset):
    """
    Gaussian profile with background offset.
    Taken directly from Codebase 2 — gaussian().
    """
    return offset + amplitude * np.exp(
        -0.5 * ((x - center) / sigma) ** 2
    )


def fit_voigt_center(
    x_pixels:   np.ndarray,
    x_spectrum: np.ndarray,
) -> dict | None:
    """
    Fit a Voigt profile to the x-pixel vs intensity data.
    Falls back to a Gaussian if the Voigt fit fails.
    Mirrors fit_center_pixel() from Codebase 2.

    Returns a dict with keys:
        center, center_err, fwhm, r_squared, model, popt
    or None if both fits fail.
    """
    if len(x_pixels) < 5:
        print("[FIT] Too few data points.")
        return None

    # --- Initial parameter estimates (Codebase 2 approach) ---
    offset_guess    = float(np.percentile(x_spectrum, 10))
    amplitude_guess = float(x_spectrum.max() - offset_guess)
    center_guess    = float(x_pixels[np.argmax(x_spectrum)])

    half_max   = offset_guess + amplitude_guess / 2.0
    above_half = x_pixels[x_spectrum > half_max]
    width_guess = (
        float(above_half[-1] - above_half[0])
        if len(above_half) > 1
        else 5.0
    )
    width_guess = max(1.0, min(width_guess, 50.0))

    px_lo = float(x_pixels[0])
    px_hi = float(x_pixels[-1])

    # --- Attempt Voigt fit ---
    try:
        p0    = [amplitude_guess, center_guess,
                 width_guess, width_guess, offset_guess]
        lower = [0.0,    px_lo, 1e-6, 1e-6, 0.0   ]
        upper = [np.inf, px_hi, np.inf, np.inf, np.inf]

        popt, pcov = curve_fit(
            _voigt_model, x_pixels, x_spectrum,
            p0=p0, bounds=(lower, upper), maxfev=50000,
        )
        amplitude, center, sigma, gamma, offset = popt
        perr       = np.sqrt(np.diag(pcov))
        center_err = perr[1]
        y_fit      = _voigt_model(x_pixels, *popt)

        fg   = 2.355 * sigma
        fl   = 2.0   * gamma
        fwhm = 0.5346 * fl + np.sqrt(0.2166 * fl ** 2 + fg ** 2)

        ss_res = np.sum((x_spectrum - y_fit) ** 2)
        ss_tot = np.sum((x_spectrum - x_spectrum.mean()) ** 2)
        r2     = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

        print(
            f"[FIT] Voigt  — centre: {center:.4f} ± {center_err:.4f} px  "
            f"FWHM: {fwhm:.4f} px  R²: {r2:.6f}"
        )
        return {
            "center"     : center,
            "center_err" : center_err,
            "fwhm"       : fwhm,
            "r_squared"  : r2,
            "model"      : "Voigt",
            "popt"       : popt,
        }

    except Exception as voigt_exc:
        print(f"[FIT] Voigt failed: {voigt_exc} — trying Gaussian fallback.")

    # --- Gaussian fallback ---
    try:
        p0    = [amplitude_guess, center_guess, width_guess, offset_guess]
        lower = [0.0,    px_lo, 1e-6, 0.0   ]
        upper = [np.inf, px_hi, np.inf, np.inf]

        popt, pcov = curve_fit(
            _gaussian_model, x_pixels, x_spectrum,
            p0=p0, bounds=(lower, upper), maxfev=50000,
        )
        amplitude, center, sigma, offset = popt
        perr       = np.sqrt(np.diag(pcov))
        center_err = perr[1]
        y_fit      = _gaussian_model(x_pixels, *popt)
        fwhm       = 2.355 * abs(sigma)

        ss_res = np.sum((x_spectrum - y_fit) ** 2)
        ss_tot = np.sum((x_spectrum - x_spectrum.mean()) ** 2)
        r2     = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

        print(
            f"[FIT] Gaussian — centre: {center:.4f} ± {center_err:.4f} px  "
            f"FWHM: {fwhm:.4f} px  R²: {r2:.6f}"
        )
        return {
            "center"     : center,
            "center_err" : center_err,
            "fwhm"       : fwhm,
            "r_squared"  : r2,
            "model"      : "Gaussian",
            "popt"       : popt,
        }

    except Exception as gauss_exc:
        print(f"[FIT] Gaussian also failed: {gauss_exc}")
        return None


# ============================================================
# SECTION 4 — TRIAX SPECTROMETER COMMUNICATION  (Codebase 3)
# ============================================================

class TriaxController:
    """
    Minimal standalone Triax controller extracted from Codebase 3.

    Uses only the serial communication methods from Codebase 3,
    without the Instrument base class or interface dependencies.
    """

    # Message map taken directly from Codebase 3
    MESSAGE_MAP = {
        'get_grating_steps' : 'H0',
        'read_grating'      : 'H0',
        'move_grating'      : 'F0,',
        'mg'                : 'F0,',
        'initialise'        : 'A',
        'specgrat1'         : 'a0',
        'specgrat2'         : 'b0',
        'read_enter'        : 'j0,0',
        'read_exit'         : 'j0,3',
        'move_enter'        : 'k0,0,',
        'move_exit'         : 'k0,3,',
        'ccd_mode'          : 'f0',
        'apd_mode'          : 'e0',
    }

    def __init__(self, port: str):
        self.port = port
        # Serial config taken directly from Codebase 3
        self.serial_config = {
            'baudrate' : 4800,
            'bytesize' : serial.EIGHTBITS,
            'parity'   : serial.PARITY_NONE,
            'stopbits' : serial.STOPBITS_ONE,
            'timeout'  : 2,
        }
        self.spectrometer          = None
        self.spectrometer_position = None

    # ------------------------------------------------------------------
    # Connection — mirrors connect() and _enter_intelligent_mode()
    # from Codebase 3
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """
        Open the serial port and enter intelligent communications mode.
        Mirrors connect() from Codebase 3.
        """
        print(f"[TRIAX] Connecting on {self.port}...")
        self.spectrometer = serial.Serial(
            port=self.port,
            **self.serial_config,
        )
        self._enter_intelligent_mode()
        print(f"[TRIAX] Connected on {self.port}.")

    def _enter_intelligent_mode(self) -> None:
        """
        Send byte 248 to switch to intelligent communications mode.
        Mirrors _enter_intelligent_mode() from Codebase 3.
        """
        print("[TRIAX] Entering intelligent mode...")
        self.spectrometer.write(bytes([248]))
        time.sleep(0.2)

        if not self._is_initialised():
            print("[TRIAX] Not initialised — running initialisation.")
            self._run_initialisation()
        else:
            print("[TRIAX] Already initialised — skipping init.")

    def _is_initialised(self) -> bool:
        """
        Send H0 and check whether the spectrometer is already initialised.
        Mirrors _is_initialised() from Codebase 3.
        """
        self.spectrometer.reset_input_buffer()
        self.spectrometer.write(b'H0\r')
        response   = self._read_response(wait=0.5)
        has_digits = any(char.isdigit() for char in response)
        result     = ('o' in response and has_digits)
        print(f"[TRIAX] Initialisation check: {result!r}  (response: {response!r})")
        return result

    def _run_initialisation(self) -> None:
        """
        Trigger autobaud and full spectrometer initialisation.
        Mirrors _run_initialisation() from Codebase 3.
        """
        print("[TRIAX] Sending space to trigger initialisation...")
        self.spectrometer.write(b' ')

        last_data_time = time.time()
        while True:
            if self.spectrometer.in_waiting > 0:
                data = self.spectrometer.read(self.spectrometer.in_waiting)
                print(f"[TRIAX] Init: {data.decode('ascii', errors='replace')!r}")
                last_data_time = time.time()
            if time.time() - last_data_time > 5:
                print("[TRIAX] Initialisation complete.")
                break
            time.sleep(0.1)

        # Re-enter intelligent mode after init — mirrors Codebase 3
        self.spectrometer.write(bytes([248]))
        time.sleep(0.2)
        self.spectrometer.write(b' ')
        response = self._read_response(wait=0.5)
        if 'F' in response:
            print("[TRIAX] Intelligent mode confirmed after init.")
        else:
            print(f"[TRIAX] Unexpected post-init response: {response!r}")

    def disconnect(self) -> None:
        """Close the serial connection."""
        if self.spectrometer and self.spectrometer.is_open:
            self.spectrometer.close()
            print("[TRIAX] Connection closed.")

    # ------------------------------------------------------------------
    # Low-level I/O — mirrors _send_command_to_spectrometer() and
    # _read_response() from Codebase 3
    # ------------------------------------------------------------------

    def _read_response(self, wait: float = 0.3) -> str:
        """
        Read all available bytes from the serial port.
        Mirrors _read_response() from Codebase 3.
        """
        time.sleep(wait)
        response = b''
        while self.spectrometer.in_waiting > 0:
            response += self.spectrometer.read(self.spectrometer.in_waiting)
            time.sleep(0.05)
        return response.decode('ascii', errors='replace')

    def _send_command_to_spectrometer(self, command: str) -> str:
        """
        Send a CR-terminated ASCII command and return the response string.
        Mirrors _send_command_to_spectrometer() from Codebase 3.
        """
        full_command = (command + '\r').encode('ascii')
        self.spectrometer.reset_input_buffer()
        self.spectrometer.write(full_command)

        # Initialise command takes up to 2 minutes — mirrors Codebase 3
        if command == 'A':
            print("[TRIAX] Initialising — waiting up to 120 s...")
            time.sleep(120)

        return self._read_response(wait=0.5)

    # ------------------------------------------------------------------
    # Position query — mirrors get_triax_steps() from Codebase 3
    # ------------------------------------------------------------------

    def get_position(self) -> int:
        """
        Query the current grating position in motor steps.
        Mirrors get_triax_steps() from Codebase 3.
        """
        response = self._send_command_to_spectrometer(
            self.MESSAGE_MAP['get_grating_steps']
        )
        try:
            position = int(response.strip()[1:])
            self.spectrometer_position = position
            return position
        except (ValueError, IndexError):
            print(f"[TRIAX] Could not parse position from: {response!r}")
            return self.spectrometer_position

    # ------------------------------------------------------------------
    # Relative move — mirrors move_grating_relative() from Codebase 3
    # ------------------------------------------------------------------

    def move_relative(self, steps: int) -> str:
        """
        Move the grating by a relative number of steps.
        Uses the F0,<steps> command from Codebase 3 MESSAGE_MAP.
        Positive steps increase position; negative steps decrease.
        """
        command  = self.MESSAGE_MAP['move_grating'] + str(steps)
        print(f"[TRIAX] Sending: {command}")
        response = self._send_command_to_spectrometer(command)
        print(f"[TRIAX] Response: {response.strip()!r}")
        return response

    def wait_for_move(self, target_steps: int, timeout: float = 10.0) -> bool:
        """
        Poll the spectrometer position until target_steps is reached.
        Mirrors wait_for_triax() from Codebase 3.

        Returns True on success, False on timeout.
        """
        start = time.time()
        while True:
            current = self.get_position()
            if current == target_steps:
                return True
            if time.time() - start > timeout:
                print(
                    f"[TRIAX] Timeout waiting for position {target_steps}. "
                    f"Current: {current}"
                )
                return False
            time.sleep(0.1)


# ============================================================
# SECTION 5 — GRADIENT CALIBRATION
# ============================================================

def _acquire_and_fit(
    cam:         PrincetonInstruments.PicamCamera,
    avg_frames:  int,
    exposure_ms: float,
    label:       str,
) -> float | None:
    """
    Acquire one averaged frame, extract the ROI spectrum, fit a Voigt
    (or Gaussian) profile, and return the fitted centre pixel.

    Returns the centre pixel as a float, or None if acquisition or
    fitting fails.
    """
    print(f"[CAL] Acquiring frame — {label}...")
    full_frame = camera_acquire_averaged_frame(cam, avg_frames, exposure_ms)
    if full_frame is None:
        print(f"[CAL] Acquisition failed at: {label}")
        return None

    x_pixels, x_spectrum = camera_extract_spectrum(full_frame)
    fit = fit_voigt_center(x_pixels, x_spectrum)
    if fit is None:
        print(f"[CAL] Fit failed at: {label}")
        return None

    print(f"[CAL] {label} — centre pixel: {fit['center']:.4f} px")
    return fit['center']


def run_gradient_calibration(
    laser_ser:   serial.Serial,
    cam:         PrincetonInstruments.PicamCamera,
    triax:       TriaxController,
    avg_frames:  int,
    exposure_ms: float,
) -> tuple[float, float, float]:
    """
    Measure both gradients from hardware and compute the combined
    correction gradient needed to hold the laser at TARGET_PIXEL.

    Two-stage procedure
    -------------------
    Stage A — Laser gradient
      1. Acquire baseline frame → fit centre pixel C0.
      2. Step laser forward by LASER_CAL_STEPS.
      3. Acquire frame → fit centre pixel C1.
      4. laser_gradient = (C1 - C0) / LASER_CAL_STEPS   [px / laser_step]
      5. Return laser to baseline (step backward LASER_CAL_STEPS).

    Stage B — Triax gradient
      1. Acquire baseline frame → fit centre pixel T0.
      2. Move Triax forward by TRIAX_CAL_STEPS.
      3. Acquire frame → fit centre pixel T1.
      4. triax_gradient = (T1 - T0) / TRIAX_CAL_STEPS   [px / triax_step]
      5. Return Triax to baseline (move backward TRIAX_CAL_STEPS).

    Combined gradient
    -----------------
    Each laser step shifts the spot by laser_gradient pixels.
    Each Triax step shifts the spot by triax_gradient pixels.

    To cancel the laser shift after each laser step:
      triax_steps_needed = laser_gradient / triax_gradient

    This is the number of Triax steps to apply per laser step so that
    the net pixel displacement is zero and the spot stays at pixel 50.

    Returns
    -------
    laser_gradient          : float  [px / laser_step]
    triax_gradient          : float  [px / triax_step]
    triax_steps_per_laser_step : float  [triax_steps / laser_step]
    """

    print("\n" + "=" * 60)
    print("  GRADIENT CALIBRATION")
    print("=" * 60)

    # ── Stage A: Laser gradient ────────────────────────────────────────
    print("\n[CAL] Stage A — measuring laser gradient...")
    print(f"[CAL] Laser calibration steps: {LASER_CAL_STEPS}")

    baseline_laser = _acquire_and_fit(
        cam, avg_frames, exposure_ms, "laser baseline"
    )
    if baseline_laser is None:
        raise RuntimeError(
            "[CAL] Could not acquire laser baseline — aborting calibration."
        )

    print(f"[CAL] Stepping laser forward {LASER_CAL_STEPS} steps...")
    success = laser_step_increase(laser_ser, LASER_CAL_STEPS)
    if not success:
        raise RuntimeError(
            "[CAL] Laser did not acknowledge calibration step — aborting."
        )
    time.sleep(0.5)   # settle after laser step

    after_laser = _acquire_and_fit(
        cam, avg_frames, exposure_ms, "after laser step"
    )
    if after_laser is None:
        raise RuntimeError(
            "[CAL] Could not acquire post-laser-step frame — aborting calibration."
        )

    laser_gradient = (after_laser - baseline_laser) / LASER_CAL_STEPS
    print(
        f"\n[CAL] Laser gradient result:\n"
        f"      Baseline pixel : {baseline_laser:.4f} px\n"
        f"      Post-step pixel: {after_laser:.4f} px\n"
        f"      Pixel shift    : {after_laser - baseline_laser:+.4f} px\n"
        f"      Laser gradient : {laser_gradient:+.8f} px / laser_step"
    )

    # Return laser to baseline position
    print(f"[CAL] Returning laser by {LASER_CAL_STEPS} steps (decrease)...")
    laser_step_decrease(laser_ser, LASER_CAL_STEPS)
    time.sleep(0.5)

    # Confirm return
    return_laser = _acquire_and_fit(
        cam, avg_frames, exposure_ms, "laser return check"
    )
    if return_laser is not None:
        print(
            f"[CAL] Laser return pixel : {return_laser:.4f} px  "
            f"(residual: {return_laser - baseline_laser:+.4f} px)"
        )

    # ── Stage B: Triax gradient ────────────────────────────────────────
    print("\n[CAL] Stage B — measuring Triax gradient...")
    print(f"[CAL] Triax calibration steps: {TRIAX_CAL_STEPS}")

    baseline_triax = _acquire_and_fit(
        cam, avg_frames, exposure_ms, "Triax baseline"
    )
    if baseline_triax is None:
        raise RuntimeError(
            "[CAL] Could not acquire Triax baseline — aborting calibration."
        )

    position_before = triax.get_position()
    target_position = position_before + TRIAX_CAL_STEPS

    print(f"[CAL] Moving Triax forward {TRIAX_CAL_STEPS} steps...")
    triax.move_relative(TRIAX_CAL_STEPS)
    triax.wait_for_move(target_position, timeout=10.0)
    time.sleep(0.5)   # settle after Triax move

    after_triax = _acquire_and_fit(
        cam, avg_frames, exposure_ms, "after Triax step"
    )
    if after_triax is None:
        raise RuntimeError(
            "[CAL] Could not acquire post-Triax-step frame — aborting calibration."
        )

    triax_gradient = (after_triax - baseline_triax) / TRIAX_CAL_STEPS
    print(
        f"\n[CAL] Triax gradient result:\n"
        f"      Baseline pixel : {baseline_triax:.4f} px\n"
        f"      Post-step pixel: {after_triax:.4f} px\n"
        f"      Pixel shift    : {after_triax - baseline_triax:+.4f} px\n"
        f"      Triax gradient : {triax_gradient:+.8f} px / triax_step"
    )

    # Return Triax to baseline position
    print(f"[CAL] Returning Triax by {TRIAX_CAL_STEPS} steps...")
    return_position = position_before
    triax.move_relative(-TRIAX_CAL_STEPS)
    triax.wait_for_move(return_position, timeout=10.0)
    time.sleep(0.5)

    # Confirm return
    return_triax = _acquire_and_fit(
        cam, avg_frames, exposure_ms, "Triax return check"
    )
    if return_triax is not None:
        print(
            f"[CAL] Triax return pixel : {return_triax:.4f} px  "
            f"(residual: {return_triax - baseline_triax:+.4f} px)"
        )

    # ── Combined gradient ──────────────────────────────────────────────
    #
    # After one laser step the spot moves by laser_gradient pixels.
    # Each Triax step moves the spot by triax_gradient pixels.
    # We need to find how many Triax steps cancel the laser shift:
    #
    #   laser_gradient + N * triax_gradient = 0
    #   N = -laser_gradient / triax_gradient
    #
    # N is the number of Triax steps to apply per laser step.
    # The sign is handled automatically: if the laser shifts the spot
    # right (+) and the Triax shifts it left (-), N will be positive,
    # meaning we move the Triax forward to compensate.
    #
    if abs(triax_gradient) < 1e-12:
        raise RuntimeError(
            "[CAL] Triax gradient is effectively zero — "
            "check that the Triax moved and the laser spot is visible."
        )

    triax_steps_per_laser_step = -laser_gradient / triax_gradient

    print(
        f"\n[CAL] Combined gradient summary:\n"
        f"      Laser gradient             : {laser_gradient:+.8f} px / laser_step\n"
        f"      Triax gradient             : {triax_gradient:+.8f} px / triax_step\n"
        f"      Triax steps per laser step : {triax_steps_per_laser_step:+.6f}\n"
        f"      (Apply this many Triax steps after each laser step\n"
        f"       to keep the laser spot at pixel {TARGET_PIXEL:.0f})"
    )
    print("=" * 60)

    return laser_gradient, triax_gradient, triax_steps_per_laser_step


# ============================================================
# SECTION 6 — TRIAX CORRECTION LOGIC
# ============================================================

def apply_triax_correction(
    triax:                     TriaxController,
    fitted_center:             float,
    target_pixel:              float,
    triax_gradient:            float,
) -> bool:
    """
    Compute and apply a residual Triax correction based on the
    current fitted pixel position vs the target.

    This is a secondary fine correction applied after the pre-computed
    feed-forward move (triax_steps_per_laser_step) to mop up any
    residual error from imperfect gradient estimates or hysteresis.

    pixel_error      = fitted_center - target_pixel
    correction_steps = pixel_error / triax_gradient

    Returns True if the correction was applied (or was zero).
    """
    if abs(triax_gradient) < 1e-12:
        print("[CORRECTION] Triax gradient is zero — skipping correction.")
        return False

    pixel_error      = fitted_center - target_pixel
    correction_steps = int(round(pixel_error / triax_gradient))

    # Safety clamp
    correction_steps = max(
        -MAX_TRIAX_CORRECTION,
        min(MAX_TRIAX_CORRECTION, correction_steps),
    )

    print(
        f"[CORRECTION] Fitted centre : {fitted_center:.4f} px\n"
        f"[CORRECTION] Target pixel  : {target_pixel:.1f} px\n"
        f"[CORRECTION] Pixel error   : {pixel_error:+.4f} px\n"
        f"[CORRECTION] Triax gradient: {triax_gradient:+.8f} px/step\n"
        f"[CORRECTION] Steps needed  : {correction_steps:+d}"
    )

    if correction_steps == 0:
        print("[CORRECTION] No residual correction needed.")
        return True

    position_before = triax.get_position()
    target_position = position_before + correction_steps

    triax.move_relative(correction_steps)
    success = triax.wait_for_move(target_position, timeout=10.0)

    if success:
        print(f"[CORRECTION] Move complete. Position: {target_position} steps")
    else:
        print("[CORRECTION] Move did not complete within timeout.")

    return success


# ============================================================
# SECTION 7 — LIVE DISPLAY
# ============================================================

def setup_display() -> dict:
    """
    Create a two-panel matplotlib figure for live monitoring.
    Left panel : CCD image with ROI markers and target pixel line.
    Right panel: x-spectrum with Voigt/Gaussian fit overlay.
    """
    plt.ion()
    fig, (ax_img, ax_fit) = plt.subplots(1, 2, figsize=(13, 4))
    fig.suptitle("Laser Tracking — Live View", fontsize=10)

    dummy_img = np.zeros((1024, 1024))
    im        = ax_img.imshow(dummy_img, cmap='gray', aspect='auto')
    fig.colorbar(im, ax=ax_img, label='Intensity (Counts)')
    ax_img.axhline(y=ROI_Y_START, color='cyan', linewidth=1,
                   linestyle='--', alpha=0.8, label='ROI top')
    ax_img.axhline(y=ROI_Y_END,   color='cyan', linewidth=1,
                   linestyle='--', alpha=0.8, label='ROI bottom')
    ax_img.axvline(x=TARGET_PIXEL, color='lime', linewidth=1,
                   linestyle=':',  alpha=0.9,
                   label=f'Target px {TARGET_PIXEL:.0f}')
    ax_img.set_title("CCD Image")
    ax_img.set_xlabel("X pixel")
    ax_img.set_ylabel("Y pixel")
    ax_img.legend(fontsize=7, loc='upper right')

    line_spectrum, = ax_fit.plot([], [], color='steelblue',
                                 linewidth=1,                                 label='X spectrum')
    line_fit,      = ax_fit.plot([], [], color='gold', linewidth=1.5,
                                 linestyle='--', label='Voigt/Gaussian fit')
    vline_center   = ax_fit.axvline(x=0, color='gold', linewidth=1,
                                    linestyle=':', alpha=0.0)
    vline_target   = ax_fit.axvline(x=TARGET_PIXEL, color='lime',
                                    linewidth=1, linestyle=':',
                                    alpha=0.9,
                                    label=f'Target px {TARGET_PIXEL:.0f}')
    ax_fit.set_xlabel("X pixel")
    ax_fit.set_ylabel("Mean intensity (counts)")
    ax_fit.set_title("X spectrum fit")
    ax_fit.grid(True, alpha=0.3)
    ax_fit.legend(fontsize=7)

    fig.tight_layout(rect=[0, 0, 1, 0.93])

    return {
        "fig"           : fig,
        "ax_img"        : ax_img,
        "ax_fit"        : ax_fit,
        "im"            : im,
        "line_spectrum" : line_spectrum,
        "line_fit"      : line_fit,
        "vline_center"  : vline_center,
        "vline_target"  : vline_target,
    }


def update_display(
    display:           dict,
    full_frame:        np.ndarray,
    x_pixels:          np.ndarray,
    x_spectrum:        np.ndarray,
    fit_result:        dict | None,
    step_number:       int,
    total_laser_steps: int,
    laser_gradient:    float,
    triax_gradient:    float,
    triax_steps_per_laser_step: float,
) -> None:
    """
    Refresh both panels of the live display with the latest data.
    Gradient values are shown in the figure title for reference.
    """
    # --- Left panel: CCD image ---
    display["im"].set_data(full_frame)
    display["im"].set_clim(vmin=full_frame.min(), vmax=full_frame.max())
    display["ax_img"].set_title(
        f"CCD Image  |  step {step_number}  |  "
        f"cumulative laser steps: {total_laser_steps}"
    )

    # --- Right panel: spectrum ---
    display["line_spectrum"].set_xdata(x_pixels)
    display["line_spectrum"].set_ydata(x_spectrum)
    display["ax_fit"].set_xlim(x_pixels[0], x_pixels[-1])
    y_margin = (x_spectrum.max() - x_spectrum.min()) * 0.05
    display["ax_fit"].set_ylim(
        x_spectrum.min() - y_margin,
        x_spectrum.max() + y_margin,
    )

    if fit_result is not None:
        center = fit_result["center"]
        model  = fit_result["model"]
        popt   = fit_result["popt"]

        x_fine = np.linspace(x_pixels[0], x_pixels[-1], 500)
        y_fine = (
            _voigt_model(x_fine, *popt)
            if model == "Voigt"
            else _gaussian_model(x_fine, *popt)
        )

        display["line_fit"].set_xdata(x_fine)
        display["line_fit"].set_ydata(y_fine)
        display["vline_center"].set_xdata([center, center])
        display["vline_center"].set_alpha(0.8)
        display["ax_fit"].set_title(
            f"{model}  |  "
            f"Centre: {center:.4f} ± {fit_result['center_err']:.4f} px  |  "
            f"FWHM: {fit_result['fwhm']:.4f} px  |  "
            f"R²: {fit_result['r_squared']:.6f}\n"
            f"∂px/∂laser: {laser_gradient:+.6f}  |  "
            f"∂px/∂triax: {triax_gradient:+.6f}  |  "
            f"triax/laser: {triax_steps_per_laser_step:+.4f}",
            fontsize=7,
        )
    else:
        display["line_fit"].set_xdata([])
        display["line_fit"].set_ydata([])
        display["vline_center"].set_alpha(0.0)
        display["ax_fit"].set_title(
            "X spectrum fit  |  fit failed", fontsize=8
        )

    display["fig"].tight_layout(rect=[0, 0, 1, 0.93])
    display["fig"].canvas.draw()
    display["fig"].canvas.flush_events()
    plt.pause(0.05)


# ============================================================
# SECTION 8 — MAIN TRACKING LOOP
# ============================================================

def run_tracking_loop(
    laser_ser:                 serial.Serial,
    cam:                       PrincetonInstruments.PicamCamera,
    triax:                     TriaxController,
    laser_gradient:            float,
    triax_gradient:            float,
    triax_steps_per_laser_step: float,
    step_direction:            str   = 'i',
    laser_steps_per_move:      int   = LASER_STEPS_PER_MOVE,
    target_pixel:              float = TARGET_PIXEL,
    exposure_ms:               float = EXPOSURE_MS,
    avg_frames:                int   = AVG_FRAMES,
) -> None:
    """
    Main tracking loop.

    Each iteration:
      1. Prompt user to step (1) or stop (2).
      2. Send laser step command via Codebase 1 serial protocol.
      3. Apply feed-forward Triax move using triax_steps_per_laser_step
         to pre-emptively cancel the expected pixel shift.
      4. Acquire and average frames via Codebase 2 camera interface.
      5. Extract ROI spectrum and fit Voigt profile (Codebase 2 fit).
      6. Apply a residual fine correction based on the actual fitted
         pixel position vs target_pixel.
      7. Update live display.

    Parameters
    ----------
    laser_gradient             : px / laser_step  (from calibration)
    triax_gradient             : px / triax_step  (from calibration)
    triax_steps_per_laser_step : triax steps to apply per laser step
                                 = -laser_gradient / triax_gradient
    step_direction             : 'i' increase wavelength, 'd' decrease
    """
    display = setup_display()

    step_number       = 0
    total_laser_steps = 0

    print("\n" + "=" * 60)
    print("  Laser Tracking Loop")
    print(f"  Direction                  : "
          f"{'increase' if step_direction == 'i' else 'decrease'}")
    print(f"  Laser steps per move       : {laser_steps_per_move}")
    print(f"  Target pixel               : {target_pixel}")
    print(f"  Laser gradient             : {laser_gradient:+.8f} px/laser_step")
    print(f"  Triax gradient             : {triax_gradient:+.8f} px/triax_step")
    print(f"  Triax steps per laser step : {triax_steps_per_laser_step:+.6f}")
    print(f"  Exposure                   : {exposure_ms:.1f} ms")
    print(f"  Avg frames                 : {avg_frames}")
    print("=" * 60)
    print("  Enter '1' to step and correct, '2' to stop.\n")

    while True:
        user_input = input(
            f"  [Step {step_number:>4d}  |  "
            f"Laser steps: {total_laser_steps:>7d}]  "
            f"Enter 1 (step) or 2 (stop): "
        ).strip()

        # ── Stop ──────────────────────────────────────────────────────────
        if user_input == '2':
            print("\n  Tracking stopped by user.")
            break

        # ── Step ──────────────────────────────────────────────────────────
        elif user_input == '1':
            step_number       += 1
            total_laser_steps += laser_steps_per_move

            # 1. Step the laser wavelength
            print(f"\n[STEP {step_number}] Stepping laser "
                  f"({'increase' if step_direction == 'i' else 'decrease'}) "
                  f"by {laser_steps_per_move} steps...")
            if step_direction == 'i':
                success = laser_step_increase(laser_ser, laser_steps_per_move)
            else:
                success = laser_step_decrease(laser_ser, laser_steps_per_move)

            if not success:
                print(f"[STEP {step_number}] Laser NAK — skipping this step.")
                continue

            time.sleep(0.5)

            # 2. Feed-forward Triax move
            #    Scale triax_steps_per_laser_step by the number of laser
            #    steps actually taken this move.
            ff_triax_steps = int(round(
                triax_steps_per_laser_step * laser_steps_per_move
            ))
            print(
                f"[STEP {step_number}] Feed-forward Triax move: "
                f"{ff_triax_steps:+d} steps  "
                f"(= {triax_steps_per_laser_step:+.6f} × {laser_steps_per_move})"
            )

            if ff_triax_steps != 0:
                position_before = triax.get_position()
                target_position = position_before + ff_triax_steps
                triax.move_relative(ff_triax_steps)
                triax.wait_for_move(target_position, timeout=10.0)
                time.sleep(0.3)

            # 3. Acquire averaged CCD frame
            print(f"[STEP {step_number}] Acquiring {avg_frames} frame(s) "
                  f"at {exposure_ms:.1f} ms...")
            full_frame = camera_acquire_averaged_frame(
                cam, avg_frames, exposure_ms
            )

            if full_frame is None:
                print(f"[STEP {step_number}] Acquisition failed — skipping.")
                continue

            # 4. Extract ROI spectrum
            x_pixels, x_spectrum = camera_extract_spectrum(full_frame)

            # 5. Fit Voigt profile to find actual laser centre pixel
            print(f"[STEP {step_number}] Fitting Voigt profile...")
            fit_result = fit_voigt_center(x_pixels, x_spectrum)

            if fit_result is None:
                print(
                    f"[STEP {step_number}] Fit failed — "
                    f"skipping residual correction."
                )
                update_display(
                    display, full_frame, x_pixels, x_spectrum,
                    None, step_number, total_laser_steps,
                    laser_gradient, triax_gradient,
                    triax_steps_per_laser_step,
                )
                continue

            # 6. Residual fine correction
            #    The feed-forward move should have brought the spot close
            #    to pixel 50. This step corrects any remaining error.
            print(f"[STEP {step_number}] Applying residual Triax correction...")
            apply_triax_correction(
                triax,
                fit_result["center"],
                target_pixel,
                triax_gradient,
            )

            # 7. Update live display
            update_display(
                display, full_frame, x_pixels, x_spectrum,
                fit_result, step_number, total_laser_steps,
                laser_gradient, triax_gradient,
                triax_steps_per_laser_step,
            )

        # ── Invalid input ──────────────────────────────────────────────────
        else:
            print("  Invalid input — enter '1' to step or '2' to stop.")

    # ── End of loop ────────────────────────────────────────────────────────
    plt.ioff()
    plt.close(display["fig"])
    print("\n  Tracking loop complete.")


# ============================================================
# SECTION 9 — ENTRY POINT
# ============================================================

def main():
    """
    Entry point.

    1. Connect to all three instruments.
    2. Set acquisition parameters automatically to fixed defaults
       (no user prompt for exposure or frames).
    3. Ask only for step direction.
    4. Run gradient calibration (laser + Triax).
    5. Enter the tracking loop.
    6. Disconnect cleanly on exit or exception.
    """

    print("\n" + "=" * 60)
    print("  Laser Wavelength Tracking System")
    print("  Tiger Ti:Sapph  |  PIXIS 1024  |  Triax")
    print("=" * 60)
    print(f"\n  Acquisition defaults applied automatically:")
    print(f"    Exposure time : {EXPOSURE_MS:.1f} ms")
    print(f"    Avg frames    : {AVG_FRAMES}")
    print(f"    Laser steps   : {LASER_STEPS_PER_MOVE} per move")
    print(f"    Target pixel  : {TARGET_PIXEL:.0f}")

    # ── Step direction — only user prompt before calibration ──────────
    direction = input(
        "\n  Step direction — increase or decrease wavelength? (i/d) [i]: "
    ).strip().lower()
    if direction not in ('i', 'd'):
        print("  Invalid — defaulting to increase.")
        direction = 'i'

    # ── Instrument connections ─────────────────────────────────────────
    laser_ser = None
    cam       = None
    triax     = None

    try:
        # --- Laser: Codebase 1 serial protocol ---
        print(f"\n[INIT] Connecting to laser on {LASER_COM_PORT}...")
        laser_ser = laser_connect(LASER_COM_PORT, LASER_BAUD_RATE)

        # --- Camera: Codebase 2 pylablib interface ---
        print(f"\n[INIT] Connecting to PIXIS camera ({CAMERA_SERIAL})...")
        cam = camera_connect(CAMERA_SERIAL)

        # Set acquisition parameters automatically — no user prompt
        camera_configure(cam, EXPOSURE_MS, AVG_FRAMES)

        # --- Triax: Codebase 3 serial protocol ---
        print(f"\n[INIT] Connecting to Triax on {TRIAX_COM_PORT}...")
        triax = TriaxController(port=TRIAX_COM_PORT)
        triax.connect()

        initial_position = triax.get_position()
        print(f"[INIT] Triax initial position: {initial_position} steps")

        print("\n[INIT] All instruments connected successfully.")

        # ── Gradient calibration ───────────────────────────────────────
        laser_gradient, triax_gradient, triax_steps_per_laser_step = (
            run_gradient_calibration(
                laser_ser   = laser_ser,
                cam         = cam,
                triax       = triax,
                avg_frames  = AVG_FRAMES,
                exposure_ms = EXPOSURE_MS,
            )
        )

        # ── Tracking loop ──────────────────────────────────────────────
        run_tracking_loop(
            laser_ser                  = laser_ser,
            cam                        = cam,
            triax                      = triax,
            laser_gradient             = laser_gradient,
            triax_gradient             = triax_gradient,
            triax_steps_per_laser_step = triax_steps_per_laser_step,
            step_direction             = direction,
            laser_steps_per_move       = LASER_STEPS_PER_MOVE,
            target_pixel               = TARGET_PIXEL,
            exposure_ms                = EXPOSURE_MS,
            avg_frames                 = AVG_FRAMES,
        )

    except KeyboardInterrupt:
        print("\n\n[EXIT] Interrupted by user (Ctrl+C).")

    except Exception as exc:
        print(f"\n[ERROR] Unhandled exception: {exc}")
        raise

    finally:
        # ── Clean disconnection of all instruments ─────────────────────
        print("\n[SHUTDOWN] Closing instrument connections...")

        if laser_ser is not None and laser_ser.is_open:
            laser_ser.close()
            print("[SHUTDOWN] Laser serial connection closed.")

        if cam is not None:
            try:
                cam.stop_acquisition()
            except Exception:
                pass
            cam.close()
            print("[SHUTDOWN] Camera connection closed.")

        if triax is not None:
            triax.disconnect()

        print("[SHUTDOWN] All connections closed. Goodbye.")


if __name__ == '__main__':
    main()

