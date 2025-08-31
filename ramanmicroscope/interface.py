# TRIAX: ~ 700 nm at 131343 steps
from __future__ import annotations
import os
import traceback
import threading

from .command.registry import build_command_map  # package-relative import
from .drivers import (
    ControllerProtocol,
    LaserProtocol,
    SpectrometerProtocol,
    CameraProtocol,
)

from .instruments.util_decorators import heartbeat
from .controller import ArduinoMEGA
from .instruments_old import Instrument, Microscope
from .instruments.instrument_base import Instrument as InstrumentBase
from .instruments import MillenniaLaser, Triax
from .calibration import Calibration
from .acquisitioncontrol import AcquisitionControl, MainWindow
from .acquisitioncontrol.gui_services import GUIEmitterService
# from PyQt5.QtWidgets import QApplication  # deferred import; only import inside gui()

from .instruments.cameras.tucsencam import TucsenCamera
from .subsystems import (
    MotionService,
    LaserService,
    SpectrometerService,
    AcquisitionService,
    GratingService,
)

# from tucsen.tucsen_camera_wrapper import TucsenCamera
from .logging_utils import LoggerInterface

def thread_locked(method):
    """
    Decorator to ensure that a method is thread-safe by acquiring a lock. Any method decorated with this will be safe to call from multiple threads.
    """
    def wrapper(self, *args, **kwargs):
        # with self.lock:
        if not self.lock.acquire(blocking=False):
            return " > Error: Method is currently locked by another thread. Please try again later."
        try:
            return method(self, *args, **kwargs)
        except Exception as e:
            error_details = traceback.format_exc()
            return f" > Error: {e}\n{error_details}"
        finally:
            self.lock.release()
    return wrapper

class Interface:

    def __init__(self, simulate=False, com_port='COM10', baud=9600, debug_skip=None, initialise_hardware=True):
        if debug_skip is None:
            debug_skip = []

        self.flag_dict = { 
            'S0': 'ok',
            'R1': 'motors running',
            'F0': 'invalid command',
            '#CF': 'end of response',
        }

        self.logger = LoggerInterface(name='interface')

        self.interface_commands = {
            'triax': self.connect_to_triax,
            'camera': self.connect_to_camera,
            'laser': self.connect_to_laser,
            'logger' : self.logger_level,
        }

        self.simulate = simulate
        self.com_port = com_port
        self.baud = baud
        self.debug_skip = debug_skip
        self.connected_to_camera = False
        self.lock = threading.RLock()

        self.scriptDir = os.path.dirname(os.path.realpath(__file__))
        self.dataDir = os.path.join(self.scriptDir, 'data')
        self.transientDir = os.path.join(self.scriptDir, 'data', 'transient_data')
        self.saveDir = os.path.join(self.dataDir, 'data')
        self.autocalibrationDir = os.path.join(self.scriptDir, 'autocalibration')
        self.calibrationDir = os.path.join(self.scriptDir, 'calibration')
        
        self._build_directories()
        self.calibration_service = Calibration(self)

        # Create hardware instances (typed against Protocol contracts for refactor safety)
        self.controller: ControllerProtocol = ArduinoMEGA(self, com_port=com_port, baud=baud, simulate=simulate, dtr=False)
        self.camera: CameraProtocol = TucsenCamera(self, simulate=simulate)
        self.spectrometer: SpectrometerProtocol = Triax(self, simulate=simulate)
        self.laser: LaserProtocol = MillenniaLaser(self, simulate=simulate)
        self.microscope = Microscope(
            interface=self,
            calibration_service=self.calibration_service,
            controller=self.controller,
            camera=self.camera,
            spectrometer=self.spectrometer,
            simulate=simulate,
        )

        self.acq_ctrl = AcquisitionControl(self)
        self.emitter = GUIEmitterService(self)

        if len(debug_skip) > 0:
            if 'TRIAX' in debug_skip:
                self.spectrometer.simulate = True
            if 'UNO' in debug_skip:
                self.controller = ArduinoMEGA(self, com_port=com_port, baud=baud, simulate=True, dtr=False)
            if 'laser' in debug_skip:
                self.laser.simulate = True
            if 'camera' in debug_skip:
                from .instruments.cameras.simulated_camera import SimulatedCameraInterface
                self.camera.simulate = True
                    
        # Build initial command map (backwards compatible)
        self.command_map = build_command_map(
            *[self.__getattribute__(attribute) for attribute in dir(self)
              if isinstance(self.__getattribute__(attribute), (Instrument, InstrumentBase))]
        )

        if initialise_hardware:
            self.spectrometer.initialise()
            self.controller.initialise()
            if 'camera' not in debug_skip:
                self.camera.initialise()
            self.laser.initialise()
            self.microscope.initialise()
            if hasattr(self.laser, 'watchdog'):
                self.heartbeat = self.laser.watchdog.heartbeat
            else:
                self.heartbeat = lambda *a, **k: None
        else:
            # Provide no-op heartbeat until manual initialisation in tests
            self.heartbeat = lambda *a, **k: None

        # --- Subsystem service layer instantiation (Phase 3 integration) ---
        # These are thin façades; creation is side-effect free so we can always
        # create them even if hardware not yet initialised (tests may init later).
        self.motion_service = MotionService()
        self.laser_service = LaserService(self.laser)
        self.spectrometer_service = SpectrometerService.from_interface(self)
        self.acquisition_service = AcquisitionService.from_interface(self)
        # Grating service needs microscope for calibration + action groups
        self.grating_service = GratingService(self.microscope)
        self._integrity_checker()

    def run_batch(self, commands):
        """
        Run a batch of commands from a list.
        """
        for command in commands:
            self.logger.info(f"Running command: {command}")
            result = self._command_handler(command)
            self.logger.info(result)

            self.save_state()

    def modify_handler(self, handler: str, level: int):
        """
        Modify the level of a handler. Call after startup to set the level of the loggers.
        """
        if handler == 'all':
            for h in self.logger.handlers:
                h.setLevel(level)
        else:
            self.logger.modify_handler(handler, level)
        
    @thread_locked
    def cli(self):
        '''Command line interface for the microscope control.'''
        while True:
            try:
                command = input("Enter a command: ")
                if command == 'exit':
                    self.camera.close_camera()
                    # self.camera.shutdown_api()
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
                    # interface.camera.close_camera()
                    # interface.microcontroller.
                    # interface.__init__(simulate=interface.simulate, com_port=interface.com_port, baud=interface.baud, debug_skip=interface.debug_skip)
                    # TODO: write close methods for all interfaces, and reinitialise them here
                    continue
                    
                result = self._command_handler(command)
                self.logger.info(f"[RES] {result}")

                self.save_state()
            except Exception as e:
                self.logger.error(f"An error occurred: {e}")
                error_details = traceback.format_exc()
                self.logger.error(error_details)
    def gui(self):
        # TODO: Implement thread event monitoring on closure of the GUI to stop the threads
        '''Launch the GUI interface for the microscope control.'''
        # Local import to avoid PyQt dependency during non-GUI test runs
        from PyQt5.QtWidgets import QApplication
        import sys
        app = QApplication.instance() or QApplication(sys.argv)

        window = MainWindow(self.acq_ctrl, self)
        window.show()
        app.exec_()

    def save_state(self):
        """
        Save the current state of the microscope and its components.
        """
        try:
            self.microscope.save_instrument_state()
        except Exception as e:
            self.logger.error(f"Failed to save instrument state: {e}")

    def process_gui_command(self, command:str):
        """
        Process a command from the GUI, mirroring CLI behavior.
        """
        cmd = command.strip()
        result = self._command_handler(cmd)
        # if result is None:
        #     result = " > No result returned from command"
        # else:
        if result not in [None, '', True, False]:
            result = str(result).strip()
            self.logger.info(f"[GUI RES] {result}")
        self.save_state()

        return result
        

    def connect_to_triax(self):
        """Switch from simulated to real TRIAX spectrometer"""
        if self.simulate or 'TRIAX' in self.debug_skip:
            self.logger.info("Attempting to connect to real TRIAX spectrometer...")
            try:
                self.spectrometer = Triax(self, simulate=False)
                self.spectrometer.initialise()
                self.logger.info("Successfully connected to real TRIAX spectrometer")
                self.command_map = build_command_map(
                    *[self.__getattribute__(attribute) for attribute in dir(self)
                      if isinstance(self.__getattribute__(attribute), (Instrument, InstrumentBase))]
                )
            except Exception as e:
                self.logger.error(f"Failed to connect to real TRIAX: {e}")
                from .simulation import SimulatedTriax
                self.spectrometer = SimulatedTriax(self)
                self.spectrometer.initialise()
                self.logger.info("Reverted to simulated TRIAX")
        else:
            self.logger.info("Already connected to real TRIAX")

    def connect_to_laser(self):
        """Switch from simulated to real laser"""
        if self.simulate or 'laser' in self.debug_skip:
            self.logger.info("Attempting to connect to real laser...")
            try:
                self.laser = MillenniaLaser(self, simulate=False)
                self.laser.initialise()
                self.command_map = build_command_map(
                    *[self.__getattribute__(attribute) for attribute in dir(self)
                      if isinstance(self.__getattribute__(attribute), (Instrument, InstrumentBase))]
                )
            except Exception as e:
                self.logger.error(f"Failed to connect to real laser: {e}")
        else:
            self.logger.info("Already connected to real laser")

    def connect_to_camera(self):
        """Switch from simulated to real camera"""
        if self.simulate or 'camera' in self.debug_skip or not self.connected_to_camera:
            self.logger.info("Attempting to connect to real camera...")
            try:
                self.camera = TucsenCamera(self, simulate=False)
                self.camera.initialise()
                self.logger.info("Successfully connected to real camera")
                if 'camera' in self.debug_skip:
                    self.debug_skip.remove('camera')
                self.microscope.camera = self.camera
                self.command_map = build_command_map(
                    *[self.__getattribute__(attribute) for attribute in dir(self)
                      if isinstance(self.__getattribute__(attribute), (Instrument, InstrumentBase))]
                )
            except Exception as e:
                self.logger.error(f"Failed to connect to real camera: {e}")
                from .simulation import SimulatedCamera
                self.camera = SimulatedCamera(self)
                self.camera.initialise()
                self.logger.info("Reverted to simulated camera")
        else:
            self.logger.info("Already connected to real camera")

    def logger_level(self, level):
        """
        Set the logging level for the CLI and GUI interfaces.
        """

        try:
            level = int(level)
        except ValueError:
            # If level is not an integer, try to convert it to a logging level
            if isinstance(level, str):
                level = level.lower()
            if level in self.logger.level_map:
                level = self.logger.level_map[level]
            else:
                self.logger.error(f"Invalid logging level: {level}")
                return

        self.logger.modify_handler('cli_handler', level)
        self.logger.setLevel(level)
        self.logger.info(f"Logging level set to {level}")

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

    def _build_directories(self):
        '''Builds all the directories required for the system to run.'''

        if not os.path.exists(self.dataDir):
            os.makedirs(self.dataDir)
        if not os.path.exists(self.transientDir):
            os.makedirs(self.transientDir)
        if not os.path.exists(self.saveDir):
            os.makedirs(self.saveDir)
        if not os.path.exists(self.autocalibrationDir):
            os.makedirs(self.autocalibrationDir)
        if not os.path.exists(self.calibrationDir):
            os.makedirs(self.calibrationDir)

        if not os.path.exists(os.path.join(self.calibrationDir, 'motor_recordings')):
            os.makedirs(os.path.join(self.calibrationDir, 'motor_recordings'))

    # _generate_command_map retained for backwards compatibility (deprecated)
    def _generate_command_map(self):  # pragma: no cover - legacy path
        return build_command_map(
            *[self.__getattribute__(attribute) for attribute in dir(self)
              if isinstance(self.__getattribute__(attribute), (Instrument, InstrumentBase))]
        )
    
    # @thread_locked
    @heartbeat
    def _command_handler(self, command:str):
        '''Handles the command and arguments passed to the Interface'''

        funct, arguments = self._command_parser(command)

        # Check for interface level commands first
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
            # This is a motion command, so we need to format it first
                motor_id = self.microscope.motor_map[funct]
                steps = int(arguments[0])
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
            # return f" > Unknown command: {funct}"
    
    def _command_parser(self, command:str):
        if command == '':
            return None, None
        tokens = [item.lower() for item in command.split(' ') if item != '']
        funct = tokens[0]
        if len(tokens) > 1:
            args = tokens[1:]
        else:
            args = []
        return funct, args

    def _integrity_checker(self):
        self.logger.info("Microscope integrity check passed")
        pass

    # ---------------------- Aggregated status helpers ----------------------
    def system_snapshot(self):
        """Return a consolidated dictionary of subsystem snapshots.

        Each entry is either the dataclass __dict__ from the service snapshot
        or None if the underlying instrument/service is not ready. Errors are
        swallowed to protect call-sites during incremental refactor.
        """
        snap = {}
        # Laser
        try:
            snap['laser'] = self.laser_service.snapshot().__dict__
        except Exception:
            snap['laser'] = None
        # Spectrometer
        try:
            snap['spectrometer'] = self.spectrometer_service.snapshot().__dict__
        except Exception:
            snap['spectrometer'] = None
        # Acquisition / camera
        try:
            snap['acquisition'] = self.acquisition_service.snapshot().__dict__
        except Exception:
            snap['acquisition'] = None
        return snap

def main(startup_commands=[], simulate=False):
    # Create your CLI-backed controller
    
    interface = Interface(simulate=simulate, com_port='COM10', debug_skip=[
        #'camera', 
        #'TRIAX'
        ])
    # Start the command line interface
    interface.run_batch(startup_commands)
    # interface.modify_handler('all', logging.INFO)
    interface.cli()

if __name__ == '__main__':
    import sys
    # quick switch for testing
    if "Users\\Sam" in os.getcwd():
        simulate = True 
    elif sys.platform == 'linux':
        simulate = True
    else:
        simulate = False

    startup_commands = [
    ]
    main(startup_commands=startup_commands, simulate=simulate)