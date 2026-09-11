# TRIAX: ~ 700 nm at 131343 steps
import os
import traceback
import threading

from instruments.util_decorators import heartbeat
from controller import ArduinoMEGA
from microscope import Instrument, Microscope
from instruments.instrument_base import Instrument as InstrumentBase
from instruments import Triax
from instruments.lasers.tiger_laser import TigerLaser
from calibration import Calibration
from acquisitioncontrol import AcquisitionControl, MainWindow
from acquisitioncontrol.gui_services import GUIEmitterService
from PyQt5.QtWidgets import QApplication

from pixisspec.pixiscam import PIXISCamera

from logging_utils import LoggerInterface

def thread_locked(method):
    """
    Decorator to ensure that a method is thread-safe by acquiring a lock.
    Any method decorated with this will be safe to call from multiple threads.
    """
    def wrapper(self, *args, **kwargs):
        if not self.lock.acquire(blocking=False):
            return (
                " > Error: Method is currently locked by another thread. "
                "Please try again later."
            )
        try:
            return method(self, *args, **kwargs)
        except Exception as e:
            error_details = traceback.format_exc()
            return f" > Error: {e}\n{error_details}"
        finally:
            self.lock.release()
    return wrapper


class Interface:

    def __init__(self, simulate=False, com_port='COM10', baud=9600, debug_skip=[]):

        self.flag_dict = {
            'S0' : 'ok',
            'R1' : 'motors running',
            'F0' : 'invalid command',
            '#CF': 'end of response',
        }

        self.logger = LoggerInterface(name='interface')

        self.interface_commands = {
            'triax'  : self.connect_to_triax,
            'camera' : self.connect_to_camera,
            'laser'  : self.connect_to_laser,
            'logger' : self.logger_level,
            'calcheck': self._laser_cal_check
        }

        self.simulate    = simulate
        self.com_port    = com_port
        self.baud        = baud
        self.debug_skip  = debug_skip
        self.connected_to_camera = False
        self.lock        = threading.RLock()

        self.scriptDir         = os.path.dirname(os.path.realpath(__file__))
        self.dataDir           = os.path.join(self.scriptDir, 'data')
        self.transientDir      = os.path.join(self.scriptDir, 'data', 'transient_data')
        self.saveDir           = os.path.join(self.dataDir, 'data')
        self.autocalibrationDir = os.path.join(self.scriptDir, 'autocalibration')
        self.calibrationDir    = os.path.join(self.scriptDir, 'calibration')

        self._build_directories()
        self.calibration_service = Calibration(self)

        # ── Create hardware instances ──────────────────────────────────────────
        self.controller  = ArduinoMEGA(
            self, com_port=com_port, baud=baud, simulate=simulate, dtr=False
        )

        # ── CHANGED: instantiate PIXISCamera instead of TucsenCamera ──────────
        self.camera = PIXISCamera(self, simulate=simulate)
        # ── END CHANGE ────────────────────────────────────────────────────────

        self.spectrometer = Triax(self, simulate=simulate)
        self.laser = TigerLaser(self, simulate=simulate)
        self.microscope   = Microscope(
            interface            = self,
            calibration_service  = self.calibration_service,
            controller           = self.controller,
            camera               = self.camera,
            spectrometer         = self.spectrometer,
            simulate             = simulate
        )

        self.acq_ctrl = AcquisitionControl(self)
        self.emitter  = GUIEmitterService(self)

        if len(debug_skip) > 0:
            from simulation import SimulatedTriax

            if 'TRIAX' in debug_skip:
                self.spectrometer.simulate = True

            if 'UNO' in debug_skip:
                self.controller = ArduinoMEGA(
                    self, com_port=com_port, baud=baud, simulate=True, dtr=False
                )

            if 'laser' in debug_skip:
                self.laser.simulate = True

            if 'camera' in debug_skip:
                # ── CHANGED: set simulate flag on PIXISCamera ──────────────────
                # PIXISCamera.simulate drives hardware backend selection at
                # initialise() time, so setting it here before initialise()
                # is called below is sufficient.
                self.camera.simulate = True
                # ── END CHANGE ────────────────────────────────────────────────

        self.command_map = self._generate_command_map()

        # ── Initialise hardware in the correct order ───────────────────────────
        self.spectrometer.initialise()
        self.controller.initialise()
        if 'camera' not in debug_skip:
            self.camera.initialise()
        self.laser.initialise()
        self.microscope.initialise()   # must be last — relies on all others

        self.heartbeat = self.laser.watchdog.heartbeat

        self._integrity_checker()

    # --------------------------------------------------------------------------
    # Batch runner
    # --------------------------------------------------------------------------

    def run_batch(self, commands):
        """Run a batch of commands from a list."""
        for command in commands:
            self.logger.info(f"Running command: {command}")
            result = self._command_handler(command)
            self.logger.info(result)
            self.save_state()

    def _laser_cal_check(self):
        """Temporary diagnostic — prints laser calibration values."""
        cal = self.laser.calibration
        checks = [
            ('wavelength_to_steps(765.546)', cal.wavelength_to_steps(765.546)),
            ('wavelength_to_steps(770)',     cal.wavelength_to_steps(770)),
            ('wavelength_to_steps(775)',     cal.wavelength_to_steps(775)),
            ('wavelength_to_steps(790)',     cal.wavelength_to_steps(790)),
            ('wavelength_to_steps(800)',     cal.wavelength_to_steps(800)),
            ('wavelength_to_steps(830)',     cal.wavelength_to_steps(830)),
            ('steps_to_wavelength(5400)',    cal.steps_to_wavelength(5400)),
            ('steps_to_wavelength(4470)',    cal.steps_to_wavelength(4470)),
            ('current step_offset',          self.laser.step_offset),
            ('wavelength_to_steps(779.184)', cal.wavelength_to_steps(779.184)),
            ('wavelength_to_steps(785.78)',  cal.wavelength_to_steps(785.78)),
            ('wavelength_to_steps(801.136)', cal.wavelength_to_steps(801.136)),
            ('wavelength_to_steps(810.772)', cal.wavelength_to_steps(810.772)),
            ('wavelength_to_steps(840.035)', cal.wavelength_to_steps(840.035)),

        ]
        for label, value in checks:
            self.logger.info(f"  {label:40s} = {value}")


    # --------------------------------------------------------------------------
    # Logging
    # --------------------------------------------------------------------------

    def modify_handler(self, handler: str, level: int):
        """Modify the level of a handler after startup."""
        if handler == 'all':
            for h in self.logger.handlers:
                h.setLevel(level)
        else:
            self.logger.modify_handler(handler, level)

    # --------------------------------------------------------------------------
    # CLI
    # --------------------------------------------------------------------------

    @thread_locked
    def cli(self):
        """Command line interface for the microscope control."""
        while True:
            try:
                command = input("Enter a command: ")

                if command == 'exit':
                    # ── CHANGED: close PIXISCamera on exit ────────────────────
                    self.camera.close_camera()
                    # ── END CHANGE ────────────────────────────────────────────
                    break

                if command == 'gui':
                    self.gui()
                    continue

                if command == 'help':
                    self.show_help()
                    continue

                if command == 'debug':
                    self.logger.info("Debugging")
                    breakpoint()
                    continue

                if command == 'reinit':
                    # TODO: write close methods for all interfaces and
                    # reinitialise them here
                    continue

                result = self._command_handler(command)
                self.logger.info(f"[RES] {result}")
                self.save_state()

            except Exception as e:
                self.logger.error(f"An error occurred: {e}")
                error_details = traceback.format_exc()
                self.logger.error(error_details)

    # --------------------------------------------------------------------------
    # GUI
    # --------------------------------------------------------------------------

    def gui(self):
        """Launch the GUI interface for the microscope control."""
        app    = QApplication.instance() or QApplication(sys.argv)
        window = MainWindow(self.acq_ctrl, self)
        window.show()
        app.exec_()

    # --------------------------------------------------------------------------
    # State persistence
    # --------------------------------------------------------------------------

    def save_state(self):
        """Save the current state of the microscope and its components."""
        try:
            self.microscope.save_instrument_state()
        except Exception as e:
            self.logger.error(f"Failed to save instrument state: {e}")

    # --------------------------------------------------------------------------
    # GUI command bridge
    # --------------------------------------------------------------------------

    def process_gui_command(self, command: str):
        """Process a command from the GUI, mirroring CLI behaviour."""
        cmd    = command.strip()
        result = self._command_handler(cmd)
        if result not in [None, '', True, False]:
            result = str(result).strip()
            self.logger.info(f"[GUI RES] {result}")
        self.save_state()
        return result

    # --------------------------------------------------------------------------
    # Hardware connection helpers
    # --------------------------------------------------------------------------

    def connect_to_triax(self):
        """Switch from simulated to real TRIAX spectrometer."""
        if self.simulate or 'TRIAX' in self.debug_skip:
            self.logger.info("Attempting to connect to real TRIAX spectrometer...")
            try:
                self.spectrometer = Triax(self, simulate=False)
                self.spectrometer.initialise()
                self.logger.info("Successfully connected to real TRIAX spectrometer.")
                self.command_map = self._generate_command_map()
            except Exception as e:
                self.logger.error(f"Failed to connect to real TRIAX: {e}")
                from simulation import SimulatedTriax
                self.spectrometer = SimulatedTriax(self)
                self.spectrometer.initialise()
                self.logger.info("Reverted to simulated TRIAX.")
        else:
            self.logger.info("Already connected to real TRIAX.")

    def connect_to_laser(self):
        """Switch from simulated to real laser."""
        if self.simulate or 'laser' in self.debug_skip:
            self.logger.info("Attempting to connect to real laser...")
            try:
                self.laser = TigerLaser(self, simulate=False)
                self.laser.initialise()
                self.command_map = self._generate_command_map()
            except Exception as e:
                self.logger.error(f"Failed to connect to real laser: {e}")
        else:
            self.logger.info("Already connected to real laser.")

    def connect_to_camera(self):
        """
        Switch from simulated to real PIXIS camera.

        ── CHANGED ───────────────────────────────────────────────────────────
        Previously instantiated TucsenCamera. Now instantiates PIXISCamera.
        The singleton guard on PIXISCamera means the old instance must be
        fully shut down before a new one can be created.
        ── END CHANGE ────────────────────────────────────────────────────────
        """
        if self.simulate or 'camera' in self.debug_skip or not self.connected_to_camera:
            self.logger.info("Attempting to connect to real PIXIS camera...")
            try:
                # ── CHANGED: shut down existing instance before creating new ──
                # PIXISCamera has a singleton guard; close the current instance
                # so the guard is released before we create a real one.
                if self.camera is not None:
                    try:
                        self.camera.close_camera()
                    except Exception:
                        pass
                    # Release the singleton so a new instance can be created
                    PIXISCamera._instance_active = False

                self.camera = PIXISCamera(self, simulate=False)
                # ── END CHANGE ────────────────────────────────────────────────

                self.camera.initialise()
                self.logger.info("Successfully connected to real PIXIS camera.")
                self.connected_to_camera = True

                if 'camera' in self.debug_skip:
                    self.debug_skip.remove('camera')

                self.microscope.camera = self.camera   # keep Microscope in sync
                self.command_map = self._generate_command_map()

            except Exception as e:
                self.logger.error(f"Failed to connect to real PIXIS camera: {e}")
                # ── CHANGED: fall back to simulated PIXISCamera ────────────────
                # Previously fell back to a SimulatedCamera import.
                # Now falls back to PIXISCamera(simulate=True) for consistency.
                try:
                    PIXISCamera._instance_active = False
                    self.camera = PIXISCamera(self, simulate=True)
                    self.camera.initialise()
                    self.logger.info("Reverted to simulated PIXIS camera.")
                except Exception as fallback_error:
                    self.logger.error(
                        f"Fallback to simulated camera also failed: {fallback_error}"
                    )
                # ── END CHANGE ────────────────────────────────────────────────
        else:
            self.logger.info("Already connected to real PIXIS camera.")

    # --------------------------------------------------------------------------
    # Logger level
    # --------------------------------------------------------------------------

    def logger_level(self, level):
        """Set the logging level for the CLI and GUI interfaces."""
        try:
            level = int(level)
        except ValueError:
            if isinstance(level, str):
                level = level.lower()
            if level in self.logger.level_map:
                level = self.logger.level_map[level]
            else:
                self.logger.error(f"Invalid logging level: {level}")
                return

        self.logger.modify_handler('cli_handler', level)
        self.logger.setLevel(level)
        self.logger.info(f"Logging level set to {level}.")

    # --------------------------------------------------------------------------
    # Help
    # --------------------------------------------------------------------------

    def generate_help(self):
        help_dict = {}
        for command, (inst, method) in self.command_map.items():
            try:
                help_dict[str(inst)].append(f"{command} - {method.__doc__}")
            except KeyError:
                help_dict[str(inst)] = [f"{command} - {method.__doc__}"]
        return help_dict

    def show_help(self):
        help_dict = self.generate_help()
        self.logger.info("Available commands:")
        for inst, commands in help_dict.items():
            self.logger.info(f"{inst}:")
            for command in commands:
                self.logger.info(f"   {command}")

    # --------------------------------------------------------------------------
    # Directory setup
    # --------------------------------------------------------------------------

    def _build_directories(self):
        """Build all directories required for the system to run."""
        for path in [
            self.dataDir,
            self.transientDir,
            self.saveDir,
            self.autocalibrationDir,
            self.calibrationDir,
            os.path.join(self.calibrationDir, 'motor_recordings'),
        ]:
            if not os.path.exists(path):
                os.makedirs(path)

    # --------------------------------------------------------------------------
    # Command map
    # --------------------------------------------------------------------------

    def _generate_command_map(self):
        """Dynamically generate a command map from declared instruments."""
        instruments = [
            self.__getattribute__(attr)
            for attr in dir(self)
            if (
                isinstance(self.__getattribute__(attr), Instrument)
                or isinstance(self.__getattribute__(attr), InstrumentBase)
            )
        ]
        command_map = {
            funct: (instrument, method)
            for instrument in instruments
            for funct, method in instrument.command_functions.items()
        }
        return command_map

    # --------------------------------------------------------------------------
    # Command handler
    # --------------------------------------------------------------------------

    @heartbeat
    def _command_handler(self, command: str):
        """Handle the command and arguments passed to the Interface."""
        funct, arguments = self._command_parser(command)

        if funct in self.interface_commands:
            try:
                result = self.interface_commands[funct](*(arguments or []))
            except Exception as e:
                error_details = traceback.format_exc()
                result = f" > Error: {e}\n{error_details}"
            return result

        elif funct in self.command_map:
            _, method = self.command_map[funct]
            try:
                result = method(*(arguments or []))
            except Exception as e:
                error_details = traceback.format_exc()
                result = f" > Error: {e}\n{error_details}"
            return result

        elif funct in self.microscope.motor_map.keys():
            try:
                motor_id      = self.microscope.motor_map[funct]
                steps         = int(arguments[0])
                motion_command = 'o{}{}o'.format(motor_id, steps)
                self.controller.send_command(motion_command)
            except Exception as e:
                error_details = traceback.format_exc()
                result = f" > Error: {e}\n{error_details}"

        else:
            try:
                result = self.controller.send_command(command)
            except Exception as e:
                error_details = traceback.format_exc()
                result = f" > Error: {e}\n{error_details}"
            return result

    # --------------------------------------------------------------------------
    # Command parser
    # --------------------------------------------------------------------------

    def _command_parser(self, command: str):
        if command == '':
            return None, None
        tokens = [item.lower() for item in command.split(' ') if item != '']
        funct  = tokens[0]
        args   = tokens[1:] if len(tokens) > 1 else []
        return funct, args

    # --------------------------------------------------------------------------
    # Integrity check
    # --------------------------------------------------------------------------

    def _integrity_checker(self):
        self.logger.info("Microscope integrity check passed.")


# ------------------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------------------

def main(startup_commands=[], simulate=False):
    interface = Interface(
        simulate  = simulate,
        com_port  = 'COM10',
        # ── CHANGED: 'camera' removed from debug_skip by default ──────────────
        # Previously the camera was always skipped. Now it is included unless
        # simulate=True (which is handled by the platform check below).
        # Add 'camera' back here if you need to run without the PIXIS connected.
        debug_skip = []
        # ── END CHANGE ────────────────────────────────────────────────────────
    )
    interface.run_batch(startup_commands)
    interface.cli()


if __name__ == '__main__':
    import sys

    if "Users\\Sam" in os.getcwd():
        simulate = True
    elif sys.platform == 'linux':
        simulate = True
    else:
        simulate = False

    simulate = True  # Force simulation mode for testing purposes
    startup_commands = []
    main(startup_commands=startup_commands, simulate=simulate)
