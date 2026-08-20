# instruments/lasers/tiger_laser.py

import os
import json
import serial
import time
import threading

from instruments.instrument_base import Instrument
from instruments.util_decorators import ui_callable
from instruments.lasers.tiger_calibration import TigerCalibration


def laser_locked(method):
    """
    Decorator to ensure that a method is called with the serial lock held.
    Prevents concurrent access to the RS-232 port.
    """
    def wrapper(self, *args, **kwargs):
        with self._serial_lock:
            return method(self, *args, **kwargs)
    return wrapper


class TigerLaser(Instrument):
    """
    Instrument wrapper for the Tiger Ti:Sapphire laser with 1DBuP piezomotor
    tuning controller.

    Hardware facts
    --------------
    - Tuning  : piezomotor via RS-232, commands *M1!SInnnnnn# / *M1!SDnnnnnn#
    - Status  : laser broadcasts a whitespace-delimited status line every ~5 s
                automatically — no query command needed
    - Power   : read-only from status string (column 4, diode current in Amps)
    - Temp    : read-only from status string (column 3, controller temp in °C)
    - On/Off  : no known serial command — hardware switch only
    - Shutter : no known serial command
    - Watchdog: not applicable — removed

    Status string column map (0-indexed, whitespace split)
    -------------------------------------------------------
    0  hours
    1  minutes
    2  seconds
    3  Ctrl Tact      °C   ← temperature
    4  Diode Iact     A    ← diode current (proxy for power)
    5  Diode Imon
    6  Crystal 1 Tact °C
    7  Crystal 2 Tact °C
    8  Crystal 2 Utec V
    9  Crystal 2 Itec A
    10 Crystal 2 Tact °C
    11 Crystal 2 Utec V
    12 Crystal 2 Itec A
    13 LasDC
    14 LasPeak

    The Tiger sometimes prepends an event flag character 'E' to a status
    line, e.g.:
        E    0 22  3 29.3 23.00 ...
    This is stripped before parsing.

    Wavelength calibration
    ----------------------
    Managed by TigerCalibration (cubic spline, measured data).
    Calibrated range: 765.546 – 847.876 nm (steps 1500 – 5400).
    Beyond step 5400 the laser outputs 750.117 nm.

    Step position is persisted to disk after every move so it survives
    restarts. Home position is STEP_MAX (5400 steps, 765.546 nm).
    """

    # ── Serial configuration — fixed per hardware spec ────────────────────────
    PORT     = 'COM17'
    BAUD     = 9600
    BYTESIZE = serial.EIGHTBITS
    PARITY   = serial.PARITY_NONE
    STOPBITS = serial.STOPBITS_ONE
    TIMEOUT  = 2          # seconds

    # ── Piezomotor defaults ────────────────────────────────────────────────────
    DEFAULT_AMPLITUDE = 600
    DEFAULT_WIDTH     = 0
    DEFAULT_TIME_OFF  = 1000

    # ── Status string column indices ──────────────────────────────────────────
    COL_TEMP    = 3
    COL_CURRENT = 4

    # ── Status read timeout ───────────────────────────────────────────────────
    STATUS_TIMEOUT = 10    # seconds to wait for a broadcast status line

    # ── Persistent step position filename ────────────────────────────────────
    STEP_STATE_FILENAME = 'tiger_step_position.json'

    def __init__(self, interface, simulate=False):
        super().__init__()
        self.interface     = interface
        self.logger        = interface.logger.getChild('TigerLaser')
        self.simulate      = simulate or interface.simulate
        self.serial        = None
        self._serial_lock  = threading.Lock()

        # ── State ─────────────────────────────────────────────────────────────
        # The Tiger has no on/off command so status is always 'ON' once
        # connected. These attributes exist so the rest of the codebase
        # (Microscope, SimulatedHardware) can read them without crashing.
        self.status        = 'ON'
        self.current_power = 0.0    # diode current in Amps
        self.current_temp  = None   # controller temperature in °C

        # ── Calibration ───────────────────────────────────────────────────────
        self.calibration   = TigerCalibration()

        # ── Step position — loaded from disk, persisted after every move ──────
        self.step_offset   = self._load_step_position()

        # ── Watchdog stub ─────────────────────────────────────────────────────
        # LaserWatchdog is not applicable to the Tiger (no remote on/off).
        # A minimal stub is kept so Interface.__init__ can still call
        # self.heartbeat = self.laser.watchdog.heartbeat without crashing.
        self.watchdog      = _WatchdogStub()

        # ── Command map ───────────────────────────────────────────────────────
        self.command_functions = {
            'connectlaser'   : self.connect,
            'disconnectlaser': self.disconnect,
            'reconnectlaser' : self.reconnect,
            'gettemp'        : self.get_temperature,
            'getpower'       : self.get_power,
            'laserstatus'    : self.get_status,
            'stepup'         : self.move_steps_increase,
            'stepdown'       : self.move_steps_decrease,
            'setamplitude'   : self.set_step_amplitude,
            'setwidth'       : self.set_step_width,
            'settimeoff'     : self.set_step_time_off,
            'resetpiezo'     : self.restore_defaults,
            'wavelength'     : self.get_estimated_wavelength,
            'gotowavelength' : self.go_to_wavelength,
            'laserhome'      : self.laser_home,
            # ── Stubs for Microscope compatibility ────────────────────────────
            'laseron'        : self.turn_on,
            'laseroff'       : self.turn_off,
            'setpower'       : self.set_power,
            'enable'         : self.enable_laser,
            'warmup'         : self.get_warmup_status,
            'cycleshutter'   : self.cycle_shutter,
        }

        self._integrity_checker()

    # --------------------------------------------------------------------------
    # Initialise
    # --------------------------------------------------------------------------

    def initialise(self):
        """Connect to the Tiger controller and read initial status."""
        self.connect()
        if not self.simulate:
            try:
                temp    = self.get_temperature()
                current = self.get_power()
                self.logger.info(
                    f"Tiger laser initialised  |  "
                    f"temp: {temp:.1f} °C  |  "
                    f"diode current: {current:.3f} A  |  "
                    f"step position: {self.step_offset}  |  "
                    f"est. wl: "
                    f"{self.calibration.steps_to_wavelength(self.step_offset):.3f} nm"
                )
            except Exception as e:
                self.logger.warning(
                    f"TigerLaser: could not read initial status: {e}"
                )

    # --------------------------------------------------------------------------
    # Persistent step position
    # --------------------------------------------------------------------------

    @property
    def _step_state_path(self):
        """Full path to the step position JSON file."""
        return os.path.join(
            self.interface.calibrationDir,
            self.STEP_STATE_FILENAME
        )

    def _load_step_position(self):
        """
        Load the last known step position from disk.
        Returns STEP_MAX (home, 765.546 nm) if no file exists.
        """
        try:
            with open(self._step_state_path, 'r') as f:
                data  = json.load(f)
                steps = int(data['step_offset'])
                self.logger.info(
                    f"TigerLaser: loaded step position {steps} from disk  |  "
                    f"est. wl: "
                    f"{self.calibration.steps_to_wavelength(steps):.3f} nm"
                )
                return steps
        except FileNotFoundError:
            default = int(self.calibration.get_step_range()[1])  # STEP_MAX
            self.logger.info(
                f"TigerLaser: no step position file found — "
                f"defaulting to home ({default} steps)."
            )
            return default
        except Exception as e:
            default = int(self.calibration.get_step_range()[1])
            self.logger.warning(
                f"TigerLaser: could not load step position ({e}) — "
                f"defaulting to home ({default} steps)."
            )
            return default

    def _save_step_position(self):
        """
        Save the current step position to disk so it survives restarts.
        Called after every successful move.
        """
        try:
            with open(self._step_state_path, 'w') as f:
                json.dump(
                    {
                        'step_offset'         : self.step_offset,
                        'estimated_wavelength': self.calibration.steps_to_wavelength(
                            self.step_offset
                        ),
                    },
                    f,
                    indent=2
                )
        except Exception as e:
            self.logger.warning(
                f"TigerLaser: could not save step position: {e}"
            )

    # --------------------------------------------------------------------------
    # Connect / disconnect
    # --------------------------------------------------------------------------

    @ui_callable
    def connect(self):
        """Open the RS-232 connection to the Tiger piezomotor controller."""
        if self.simulate:
            self.serial = _SimulatedTigerSerial(self)
            self.logger.info("TigerLaser: using simulated serial.")
            return

        self.logger.info(f"TigerLaser: connecting on {self.PORT}...")
        try:
            self.serial = serial.Serial(
                port     = self.PORT,
                baudrate = self.BAUD,
                bytesize = self.BYTESIZE,
                parity   = self.PARITY,
                stopbits = self.STOPBITS,
                timeout  = self.TIMEOUT,
            )
            if not self.serial.is_open:
                self.serial.open()
            self.logger.info(f"TigerLaser: connected on {self.PORT}.")
        except serial.SerialException as e:
            self.logger.error(f"TigerLaser: connection failed: {e}")
            self.serial = None

    @ui_callable
    def disconnect(self):
        """Close the RS-232 connection."""
        if self.serial and self.serial.is_open:
            self.serial.close()
            self.logger.info("TigerLaser: disconnected.")

    @ui_callable
    def reconnect(self):
        """Close and reopen the RS-232 connection."""
        self.disconnect()
        self.connect()

    # --------------------------------------------------------------------------
    # Status string reader
    # --------------------------------------------------------------------------

    def _read_status_line(self):
        """
        Wait up to STATUS_TIMEOUT seconds for the laser to broadcast a
        well-formed status line (15 whitespace-delimited numeric fields).

        The Tiger broadcasts status automatically every ~5 s — we never
        send a query command, we just listen.

        The Tiger sometimes prepends an event flag character 'E' to a
        status line. This is stripped before parsing.

        Returns
        -------
        list[str] or None
            The split fields of the status line, or None on timeout.
        """
        if self.serial is None:
            self.logger.error("TigerLaser: serial not connected.")
            return None

        deadline    = time.time() + self.STATUS_TIMEOUT
        line_buffer = b''

        with self._serial_lock:
            self.serial.reset_input_buffer()

            while time.time() < deadline:
                if self.serial.in_waiting > 0:
                    chunk       = self.serial.read(self.serial.in_waiting)
                    line_buffer += chunk

                    while b'\n' in line_buffer:
                        line, line_buffer = line_buffer.split(b'\n', 1)
                        decoded = line.decode('ascii', errors='replace').strip()

                        # Strip leading event flag character (e.g. 'E')
                        # A valid data line starts with a digit or whitespace.
                        # Any single leading non-numeric character is an event
                        # flag and is discarded before parsing.
                        if decoded and not decoded[0].lstrip('+-').replace(
                            '.', '', 1
                        ).isdigit():
                            decoded = decoded[1:].strip()

                        fields = decoded.split()
                        if len(fields) < 15:
                            continue

                        # Validate: every field must be parseable as float
                        try:
                            [float(f) for f in fields]
                            return fields
                        except ValueError:
                            continue

                time.sleep(0.05)

        self.logger.warning(
            f"TigerLaser: no status line received within "
            f"{self.STATUS_TIMEOUT} s."
        )
        return None

    # --------------------------------------------------------------------------
    # Temperature and power
    # --------------------------------------------------------------------------

    @ui_callable
    def get_temperature(self):
        """
        Return the controller temperature in °C (column 3 of status string).
        Waits up to STATUS_TIMEOUT seconds for the next broadcast.
        """
        fields = self._read_status_line()
        if fields is None:
            return self.current_temp
        temp = float(fields[self.COL_TEMP])
        self.current_temp = temp
        return temp

    @ui_callable
    def get_power(self):
        """
        Return the diode current in Amps (column 4 of status string).
        This is the closest available proxy for laser power on the Tiger.
        Waits up to STATUS_TIMEOUT seconds for the next broadcast.

        Updates self.current_power so SimulatedHardware threshold checks
        (current_power >= 3) remain meaningful. The simulated diode current
        is set to 4.52 A so the simulated laser line renders correctly.
        """
        fields = self._read_status_line()
        if fields is None:
            return self.current_power
        current = float(fields[self.COL_CURRENT])
        self.current_power = current
        return current

    # --------------------------------------------------------------------------
    # Status
    # --------------------------------------------------------------------------

    @ui_callable
    def get_status(self):
        """
        Return a status summary string.
        Tiger has no remote on/off so status is always 'ON' once connected.
        """
        self.logger.info(
            f"TigerLaser status: {self.status}  |  "
            f"diode current: {self.current_power:.3f} A  |  "
            f"step position: {self.step_offset}  |  "
            f"est. wl: "
            f"{self.calibration.steps_to_wavelength(self.step_offset):.3f} nm"
        )
        return self.status

    # --------------------------------------------------------------------------
    # Wavelength
    # --------------------------------------------------------------------------

    @ui_callable
    def get_estimated_wavelength(self):
        """
        Return the estimated wavelength based on the current step position
        and the cubic spline calibration.
        """
        wl = self.calibration.steps_to_wavelength(self.step_offset)
        self.logger.info(
            f"Estimated wavelength: {wl:.3f} nm  |  "
            f"step position: {self.step_offset}"
        )
        return wl

    @ui_callable
    def go_to_wavelength(self, target_nm):
        """
        Move the piezomotor to achieve the target wavelength.

        Uses the cubic spline calibration to convert wavelength → steps,
        then moves relative to the current step position.

        Parameters
        ----------
        target_nm : float or str
            Target wavelength in nm. Must be within the calibrated range
            (765.546 – 847.876 nm).

        Returns
        -------
        bool
        """
        try:
            target_nm = float(target_nm)
        except (ValueError, TypeError):
            self.logger.error(
                f"TigerLaser.go_to_wavelength: invalid value {target_nm!r}."
            )
            return False

        if not self.calibration.is_in_range(target_nm):
            wl_min, wl_max = self.calibration.get_range()
            self.logger.warning(
                f"TigerLaser.go_to_wavelength: {target_nm:.3f} nm is outside "
                f"the calibrated range ({wl_min:.3f}–{wl_max:.3f} nm)."
            )
            return False

        target_steps   = self.calibration.wavelength_to_steps(target_nm)
        current_steps  = self.step_offset
        relative_steps = target_steps - current_steps
        current_wl     = self.calibration.steps_to_wavelength(current_steps)

        self.logger.info(
            f"TigerLaser: go_to_wavelength {target_nm:.3f} nm  |  "
            f"current: {current_wl:.3f} nm ({current_steps} steps)  |  "
            f"target: {target_steps} steps  |  "
            f"move: {relative_steps:+d} steps"
        )

        if relative_steps == 0:
            self.logger.info("TigerLaser: already at target wavelength.")
            return True

        if relative_steps > 0:
            success = self.move_steps_increase(relative_steps)
        else:
            success = self.move_steps_decrease(abs(relative_steps))

        if success:
            actual_wl = self.calibration.steps_to_wavelength(self.step_offset)
            self.logger.info(
                f"TigerLaser: move complete  |  "
                f"estimated wavelength: {actual_wl:.3f} nm  |  "
                f"step position: {self.step_offset}"
            )
        return success

    # --------------------------------------------------------------------------
    # Home
    # --------------------------------------------------------------------------

    @ui_callable
    def laser_home(self):
        """
        Home the piezomotor by moving to STEP_MAX (5400 steps, 765.546 nm).

        Home is defined as the position where the laser outputs its shortest
        calibrated wavelength (765.546 nm). From this known reference point,
        step counts are meaningful across sessions.

        An extra 1000 steps are added to the physical move to guarantee the
        motor reaches the hard stop regardless of any accumulated drift or
        hysteresis. The step_offset is then reset to the exact STEP_MAX value
        (not STEP_MAX + 1000) so the calibration remains correct.

        After a successful home move, step_offset is reset to the exact home
        value, clearing any accumulated counting errors.
        """
        _, step_max       = self.calibration.get_step_range()
        current           = self.step_offset
        steps_to_target   = step_max - current

        # ── CHANGED: add 1000 extra steps to the physical move ────────────────────
        # This guarantees the motor reaches the hard stop even if the stored
        # step_offset has drifted. The logical position is still reset to
        # step_max (not step_max + 1000) so calibration is unaffected.
        OVERSHOOT         = 1000
        steps_to_move     = steps_to_target + OVERSHOOT
        # ── END CHANGE ────────────────────────────────────────────────────────────

        self.logger.info(
            f"TigerLaser: homing  |  "
            f"current: {current} steps  |  "
            f"target: {step_max} steps (765.546 nm)  |  "
            f"physical move: {steps_to_move:+d} steps "
            f"(includes {OVERSHOOT} step overshoot)"
        )

        if steps_to_move == 0:
            self.logger.info("TigerLaser: already at home position.")
            return True

        if steps_to_move > 0:
            command = f'*M1!SI{self._fmt(steps_to_move)}#'
        else:
            command = f'*M1!SD{self._fmt(abs(steps_to_move))}#'

        success = self._send_piezo_command(command)

        if success:
            # Reset to exact STEP_MAX — not STEP_MAX + OVERSHOOT.
            # The overshoot physically drives the motor to the hard stop but
            # the logical position is the calibrated home value.
            self.step_offset = step_max
            self._save_step_position()
            self.logger.info(
                f"TigerLaser: homed successfully  |  "
                f"step position reset to: {self.step_offset}  |  "
                f"wavelength: "
                f"{self.calibration.steps_to_wavelength(self.step_offset):.3f} nm"
            )
        else:
            self.logger.error("TigerLaser: home move failed.")

        return success


    # --------------------------------------------------------------------------
    # Piezomotor control
    # --------------------------------------------------------------------------

    @ui_callable
    def move_steps_increase(self, steps):
        """
        Move the piezomotor in the wavelength-increase direction.

        Parameters
        ----------
        steps : int or str
            Number of steps (1 – 999999).
        """
        steps = self._validate_steps(steps, 1, 999999)
        if steps is None:
            return False

        command = f'*M1!SI{self._fmt(steps)}#'
        success = self._send_piezo_command(command)
        if success:
            self.step_offset += steps
            self._save_step_position()
            self.logger.info(
                f"Piezomotor +{steps} steps  |  "
                f"position: {self.step_offset}  |  "
                f"est. wl: "
                f"{self.calibration.steps_to_wavelength(self.step_offset):.3f} nm"
            )
        return success

    @ui_callable
    def move_steps_decrease(self, steps):
        """
        Move the piezomotor in the wavelength-decrease direction.

        Parameters
        ----------
        steps : int or str
            Number of steps (1 – 999999).
        """
        steps = self._validate_steps(steps, 1, 999999)
        if steps is None:
            return False

        command = f'*M1!SD{self._fmt(steps)}#'
        success = self._send_piezo_command(command)
        if success:
            self.step_offset -= steps
            self._save_step_position()
            self.logger.info(
                f"Piezomotor -{steps} steps  |  "
                f"position: {self.step_offset}  |  "
                f"est. wl: "
                f"{self.calibration.steps_to_wavelength(self.step_offset):.3f} nm"
            )
        return success

    @ui_callable
    def set_step_amplitude(self, value):
        """
        Set piezomotor step amplitude (400–1000, default 600).
        Higher = faster rotation and larger steps.
        Do not set below 400.
        """
        value = self._validate_steps(value, 400, 1000)
        if value is None:
            return False
        return self._send_piezo_command(f'*M1!SA{self._fmt(value)}#')

    @ui_callable
    def set_step_width(self, value):
        """
        Set piezomotor step width / prolongation in microseconds (default 0).
        """
        value = self._validate_steps(value, 0, 999999)
        if value is None:
            return False
        return self._send_piezo_command(f'*M1!SW{self._fmt(value)}#')

    @ui_callable
    def set_step_time_off(self, value):
        """
        Set time between piezomotor steps in microseconds (default 1000).
        """
        value = self._validate_steps(value, 0, 999999)
        if value is None:
            return False
        return self._send_piezo_command(f'*M1!SO{self._fmt(value)}#')

    @ui_callable
    def restore_defaults(self):
        """Restore piezomotor settings to factory defaults."""
        self.logger.info("TigerLaser: restoring piezomotor defaults...")
        ok = all([
            self._send_piezo_command(
                f'*M1!SA{self._fmt(self.DEFAULT_AMPLITUDE)}#'
            ),
            self._send_piezo_command(
                f'*M1!SW{self._fmt(self.DEFAULT_WIDTH)}#'
            ),
            self._send_piezo_command(
                f'*M1!SO{self._fmt(self.DEFAULT_TIME_OFF)}#'
            ),
        ])
        if ok:
            self.logger.info("TigerLaser: defaults restored.")
        return ok

    # --------------------------------------------------------------------------
    # Stubs — required by Microscope / Interface but not available on Tiger
    # --------------------------------------------------------------------------

    @ui_callable
    def turn_on(self):
        """
        Not available on Tiger — no remote on/off command.
        Logs a warning and returns True (laser assumed always on when connected).
        """
        self.logger.warning(
            "TigerLaser.turn_on(): no remote on/off on Tiger — "
            "use the hardware key switch."
        )
        self.status = 'ON'
        return True

    @ui_callable
    def turn_off(self):
        """
        Not available on Tiger — no remote on/off command.
        Logs a warning. Does NOT change self.status to avoid breaking
        SimulatedHardware laser line rendering.
        """
        self.logger.warning(
            "TigerLaser.turn_off(): no remote on/off on Tiger — "
            "use the hardware key switch."
        )
        return False

    @ui_callable
    def set_power(self, power_watts):
        """
        Not available on Tiger — power is set by the pump laser hardware.
        Logs a warning and returns False.
        """
        self.logger.warning(
            f"TigerLaser.set_power({power_watts}): "
            "power control not available on Tiger."
        )
        return False

    @ui_callable
    def enable_laser(self):
        """
        Not available on Tiger — no remote enable command.
        Returns True so Microscope.enable_laser() does not raise.
        """
        self.logger.warning(
            "TigerLaser.enable_laser(): not applicable to Tiger."
        )
        return True

    @ui_callable
    def get_warmup_status(self):
        """
        Not available on Tiger — no warmup query command.
        Returns 100 so Microscope warmup checks pass immediately.
        """
        return 100

    @ui_callable
    def cycle_shutter(self):
        """
        Not available on Tiger — no remote shutter command.
        Logs a warning and returns False.
        """
        self.logger.warning(
            "TigerLaser.cycle_shutter(): no shutter control on Tiger."
        )
        return False

    # --------------------------------------------------------------------------
    # Private helpers
    # --------------------------------------------------------------------------

    def _send_piezo_command(self, command, max_retries=3):
        """
        Send a piezomotor command and wait for ACK or status string.

        Parameters
        ----------
        command : str
        max_retries : int

        Returns
        -------
        bool
        """
        if self.serial is None:
            self.logger.error("TigerLaser: serial not connected.")
            return False

        raw = command.encode('ascii')

        with self._serial_lock:
            for attempt in range(1, max_retries + 1):
                self.serial.reset_input_buffer()
                self.serial.reset_output_buffer()

                self.logger.debug(
                    f"TigerLaser: sending {command!r} "
                    f"(attempt {attempt}/{max_retries})"
                )
                self.serial.write(raw)

                deadline       = time.time() + 2
                received_bytes = b''

                while time.time() < deadline:
                    if self.serial.in_waiting > 0:
                        byte            = self.serial.read(1)
                        received_bytes += byte

                        if byte == b'\x06':
                            self.logger.debug("TigerLaser: ACK received.")
                            return True

                        if byte == b'\x15':
                            self.logger.warning(
                                f"TigerLaser: NAK on attempt {attempt}."
                            )
                            break

                        if (len(received_bytes) > 3 and all(
                            32 <= b <= 126 or b in (10, 13)
                            for b in received_bytes
                        )):
                            self.logger.debug(
                                "TigerLaser: status string received — "
                                "treating as success."
                            )
                            return True

                    time.sleep(0.01)

                if attempt < max_retries:
                    self.logger.debug("TigerLaser: retrying...")
                    time.sleep(0.5)

        self.logger.error(
            f"TigerLaser: command {command!r} failed after "
            f"{max_retries} attempts."
        )
        return False

    @staticmethod
    def _validate_steps(value, min_val, max_val):
        """
        Parse and range-check a step value.

        Returns
        -------
        int or None
        """
        try:
            int_value = int(value)
        except (ValueError, TypeError):
            return None
        if min_val <= int_value <= max_val:
            return int_value
        return None

    @staticmethod
    def _fmt(value):
        """Format an integer as a 6-digit zero-padded string."""
        return str(int(value)).zfill(6)

    # --------------------------------------------------------------------------
    # Dunder
    # --------------------------------------------------------------------------

    def __str__(self):
        return "Tiger Ti:Sapphire Laser"

    def __del__(self):
        try:
            self.disconnect()
        except Exception:
            pass


# ------------------------------------------------------------------------------
# Watchdog stub
# ------------------------------------------------------------------------------

class _WatchdogStub:
    """
    Minimal stub so Interface.__init__ can call
    self.heartbeat = self.laser.watchdog.heartbeat
    without crashing.

    The Tiger has no remote on/off so a real watchdog is not applicable.
    """
    def heartbeat(self):
        pass

    def start(self):
        pass

    def stop(self):
        pass


# ------------------------------------------------------------------------------
# Simulated serial
# ------------------------------------------------------------------------------

class _SimulatedTigerSerial:
    """
    Simulated RS-232 interface for the Tiger piezomotor controller.
    Broadcasts a realistic status line every ~5 s, exactly as the real
    hardware does, so _read_status_line() works correctly in simulation.
    Every third broadcast uses the 'E' event flag prefix to mirror real
    hardware behaviour.
    """

    _CTRL_TEMP   = 26.2
    _DIODE_IACT  = 4.52    # Amps — above SimulatedHardware threshold of 3
    _DIODE_IMON  = 0.000
    _XTAL1_TACT  = 18.39
    _XTAL2_TACT  = 27.19
    _XTAL2_UTEC  = +0.38
    _XTAL2_ITEC  = +0.15
    _XTAL2_TACT2 = 22.00
    _XTAL2_UTEC2 = +0.08
    _XTAL2_ITEC2 = +0.06
    _LAS_DC      = 0.012
    _LAS_PEAK    = 0.012

    def __init__(self, laser):
        self.laser    = laser
        self.is_open  = True
        self._buffer  = b''
        self._lock    = threading.Lock()
        self._stop    = threading.Event()

        self._thread  = threading.Thread(
            target=self._broadcast_loop, daemon=True
        )
        self._thread.start()

    def _broadcast_loop(self):
        """Push a status line into the buffer every 5 seconds."""
        t = 0
        while not self._stop.is_set():
            hours   = t // 3600
            minutes = (t % 3600) // 60
            seconds = t % 60

            # Every third broadcast uses the 'E' event flag prefix
            prefix = 'E ' if (t // 5) % 3 == 0 else '  '

            line = (
                f"{prefix}{hours:4d} {minutes:2d} {seconds:2d} "
                f"{self._CTRL_TEMP:.1f} "
                f"{self._DIODE_IACT:.2f} "
                f"{self._DIODE_IMON:.3f} "
                f"{self._XTAL1_TACT:.2f} "
                f"{self._XTAL2_TACT:.2f} "
                f"{self._XTAL2_UTEC:+.2f} "
                f"{self._XTAL2_ITEC:+.2f} "
                f"{self._XTAL2_TACT2:.2f} "
                f"{self._XTAL2_UTEC2:+.2f} "
                f"{self._XTAL2_ITEC2:+.2f} "
                f"{self._LAS_DC:.3f} "
                f"{self._LAS_PEAK:.3f}\n"
            )
            with self._lock:
                self._buffer += line.encode('ascii')

            t += 5
            self._stop.wait(5)

    @property
    def in_waiting(self):
        with self._lock:
            return len(self._buffer)

    def read(self, n=1):
        with self._lock:
            data         = self._buffer[:n]
            self._buffer = self._buffer[n:]
            return data

    def reset_input_buffer(self):
        with self._lock:
            self._buffer = b''

    def reset_output_buffer(self):
        pass

    def write(self, data):
        """Accept piezomotor commands silently and return ACK."""
        with self._lock:
            self._buffer += b'\x06'

    def close(self):
        self._stop.set()
        self.is_open = False
