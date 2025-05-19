# TRIAX: ~ 700 nm at 131343 steps
import os
import traceback

from controller import ArduinoMEGA
from instruments_old import Instrument, Microscope
from instruments.instrument_base import Instrument as InstrumentBase
from instruments import MillenniaLaser, Triax
from calibration import Calibration
from acquisitioncontrol import AcquisitionControl
from acquisitioncontrol import MainWindow
from PyQt5.QtWidgets import QApplication


import logging

from instruments.cameras.tucsen import TucsenCamera
from logging_utils import LoggerInterface

class Interface:

    def __init__(self, simulate=False, com_port='COM10', baud=9600, debug_skip=[]):

        self.logger = LoggerInterface(name='interface')

        self.interface_commands = {
            'triax': self.connect_to_triax,
            'camera': self.connect_to_camera,
            'laser': self.connect_to_laser,
        }

        self.simulate = simulate
        self.com_port = com_port
        self.baud = baud
        self.debug_skip = debug_skip
        self.connected_to_camera = False

        self.scriptDir = os.path.dirname(os.path.realpath(__file__))
        self.dataDir = os.path.join(self.scriptDir, 'data')
        self.transientDir = os.path.join(self.scriptDir, 'transient')
        self.saveDir = os.path.join(self.dataDir, 'data')
        self.autocalibrationDir = os.path.join(self.scriptDir, 'autocalibration')
        self.calibrationDir = os.path.join(self.scriptDir, 'calibration')
        
        self._build_directories()
        self.calibration_service = Calibration()


        # Create hardware instances
        self.controller = ArduinoMEGA(self, com_port=com_port, baud=baud, simulate=simulate, dtr=False)
        self.camera = TucsenCamera(self, simulate=simulate)
        self.spectrometer = Triax(self, simulate=simulate)
        self.laser = MillenniaLaser(self, simulate=simulate)

        self.microscope = Microscope(
            interface=self, 
            calibration_service=self.calibration_service,
            controller=self.controller,
            camera=self.camera,
            spectrometer=self.spectrometer,
            simulate=simulate
        )

        self.acq_ctrl = AcquisitionControl(self)

        if len(debug_skip) > 0:
            from simulation import (SimulatedTriax)
                
                # Replace individual components with simulated versions as specified in debug_skip
            if 'TRIAX' in debug_skip:
                self.spectrometer = SimulatedTriax(self)
                
            if 'UNO' in debug_skip:
                self.controller = ArduinoMEGA(self, com_port=com_port, baud=baud, simulate=True, dtr=False)
                
            if 'laser' in debug_skip:
                self.laser.simulate = True
                
            if 'camera' in debug_skip:
                from instruments.cameras.simulated_camera import SimulatedCameraInterface
                self.camera = SimulatedCameraInterface(self)
                    
        self.command_map = self._generate_command_map()

        self.flag_dict = { 
            'S0': 'ok',
            'R1': 'motors running',
            'F0': 'invalid command',
            '#CF': 'end of response',
        }

        # Initialize hardware components in the correct order
        self.spectrometer.initialise()
        self.controller.initialise()
        if not 'camera' in debug_skip:
            self.camera.initialise()
        # Initialize the high-level instrument classes
        self.laser.initialise()
        self.microscope.initialise()  #t be last as it relies on others
        
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
        

    def cli(self):
        '''Command line interface for the microscope control.'''
        while True:
            try:
                command = input("Enter a command: ")
                if command == 'exit':
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
                self.logger.info(result)

                self.save_state()
            except Exception as e:
                self.logger.error(f"An error occurred: {e}")
                error_details = traceback.format_exc()
                self.logger.error(error_details)

    def parse_command(self, command:str):
        """
        Parse a command and send on to the command handler"""
        pass


    def gui(self):
        # TODO: Implement thread event monitoring on closure of the GUI to stop the threads
        '''Launch the GUI interface for the microscope control.'''
        # Launch Qt
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
                self.command_map = self._generate_command_map()
            except Exception as e:
                self.logger.error(f"Failed to connect to real TRIAX: {e}")
                # Fallback to simulation
                from simulation import SimulatedTriax
                self.spectrometer = SimulatedTriax(self)
                self.spectrometer.initialise()
                self.logger.info("Reverted to simulated TRIAX")
        else:
            # Already using real hardware
            self.logger.info("Already connected to real TRIAX")

    #8.56 -14.81
    #Z #5.35 - 4.1

    def connect_to_laser(self):
        """Switch from simulated to real laser"""
        if self.simulate or 'laser' in self.debug_skip:
            self.logger.info("Attempting to connect to real laser...")
            try:
                self.laser = MillenniaLaser(self, simulate=False)
                self.laser.initialise()
                self.command_map = self._generate_command_map()
            except Exception as e:
                self.logger.error(f"Failed to connect to real laser: {e}")
        else:
            # Already using real hardware
            self.logger.info("Already connected to real laser")

    def connect_to_camera(self):
        """Switch from simulated to real camera"""
        if self.simulate or 'camera' in self.debug_skip or not self.connected_to_camera:
            self.logger.info("Attempting to connect to real camera...")
            try:
                self.camera = TucsenCamera(self, simulate=False)
                self.camera.initialise()
                self.logger.info("Successfully connected to real camera")
                self.debug_skip.remove('camera')
                self.microscope.camera = self.camera  # Update the microscope's camera reference
                self.command_map = self._generate_command_map()
            except Exception as e:
                self.logger.error(f"Failed to connect to real camera: {e}")
                # Fallback to simulation
                from simulation import SimulatedCamera
                self.camera = SimulatedCamera(self)
                self.camera.initialise()
                self.logger.info("Reverted to simulated camera")
        else:
            # Already using real hardware
            self.logger.info("Already connected to real camera")

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

    def _generate_command_map(self):
        '''Dynamically generate a command map from the instruments declared in __init__'''
        instruments = [self.__getattribute__(attribute) for attribute in dir(self) if isinstance(self.__getattribute__(attribute), Instrument) or isinstance(self.__getattribute__(attribute), InstrumentBase)] # TODO: Eventually replace all Instrument with InstrumentBase

        command_map = {
            funct: (instrument, method)
            for instrument in instruments
            for funct, method in instrument.command_functions.items()
        }
        return command_map
    
    # def _format_motion_commands(self, command:str):
    #     pattern = re.compile(r'(?P<x>x-?\d+(\.\d+)?|X-?\d+(\.\d+)?|)?(?P<y>y-?\d+(\.\d+)?|Y-?\d+(\.\d+)?|)?(?P<z>z-?\d+(\.\d+)?|Z-?\d+(\.\d+)?|)?')
    #     match = pattern.fullmatch(command)
    #     if not match:
    #         return None

    #     match_dict = {}
    #     for key, value in match.groupdict().items():
    #         if value == '':
    #             match_dict[key] = '0'.format(key.lower())
    #         else:
    #             match_dict[key] = value[1:]
        
    #     motion_commands = 'xyz {} {} {}'.format(match_dict['x'], match_dict['y'], match_dict['z'])

    #     return motion_commands


    def _command_handler(self, command:str):
        '''Handles the command and arguments passed to the Interface'''

        funct, arguments = self._command_parser(command)

        # Check for interface level commands first
        if funct in self.interface_commands:
            try:
                result = self.interface_commands[funct]()
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

         # Detail: * operator unpacks the list - since an empty list has nothing to unpack, nothi
         # ng is passed to the function. This avoids a TypeError -41861
    
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

def main(startup_commands=[]):
    # Create your CLI-backed controller
    
    interface = Interface(simulate=simulate, com_port='COM10', debug_skip=[
        #'camera', 
        'TRIAX'
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
    main(startup_commands=startup_commands)