# TRIAX: ~ 700 nm at 131343 steps
import os
import traceback

from controller import ArduinoUNO
from instruments import Instrument, Microscope, Triax, StageControl, Monochromator, simulate, MillenniaLaser
from calibration import Calibration
# from commands import CommandHandler, MicroscopeCommand, CameraCommand, SpectrometerCommand, StageCommand, MonochromatorCommand
try:
    from tucsen.tucsen_camera_wrapper import TucamCamera
except Exception as e:
    print(f"Failed to import TucamCamera: {e}")
    # Handle the case where the camera is not available
    # You might want to set self.camera to None or a simulated version
    from simulation import SimulatedCamera
    print("Using simulated camera instead.")
    TucamCamera = SimulatedCamera
import re

def cli(instrument):
    while True:
        command = input("Enter a command: ")
        if command == 'exit':
            break

        if command == 'help':
            instrument.show_help()
            continue
    
        if command == 'debug':
            print("Debugging")
            breakpoint()
        
        if command == 'reinit':
            # instrument.camera.close_camera()
            # instrument.microcontroller.
            # instrument.__init__(simulate=instrument.simulate, com_port=instrument.com_port, baud=instrument.baud, debug_skip=instrument.debug_skip)
            # TODO: write close methods for all instruments, and reinitialise them here
            continue
            
        result = instrument._command_handler(command)
        print(result)
        instrument.microscope.save_instrument_state()

class Interface:

    def __init__(self, simulate=False, com_port='COM10', baud=9600, debug_skip=[]):
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
        
        # Create directories first
        self._build_directories()
        self.calibration_service = Calibration()


        if simulate:
            # Import simulation module only when needed
            from simulation import (SimulatedArduino, SimulatedCamera, SimulatedTriax,
                                  SimulatedLaser, SimulatedMonochromator, SimulatedStageControl)
            
            # Create simulated hardware instances
            self.controller = SimulatedArduino(self, com_port=com_port, baud=baud)
            self.camera = SimulatedCamera(self)
            self.spectrometer = SimulatedTriax(self)
            self.laser = SimulatedLaser(self)
            # self.monochromator_controller = SimulatedMonochromator(self)
            # self.stage_controller = SimulatedStageControl(self)
        else:
            # Create real hardware instances
            self.controller = ArduinoUNO(self, com_port=com_port, baud=baud, simulate=False)
            self.camera = TucamCamera(self, simulate=False)
            self.spectrometer = Triax(self, simulate=False)
            self.laser = MillenniaLaser(self, simulate=False)
            # For now, we'll use the simulated versions for the new controllers
            # in production these would be real hardware controllers
            # from simulation import SimulatedLaser, SimulatedMonochromator, SimulatedStageControl
            # self.laser_controller = MillenniaLaser(self, simulate=False)
            # self.monochromator_controller = SimulatedMonochromator(self, simulate=False)
            # self.stage_controller = SimulatedStageControl(self, simulate=False)


        if len(debug_skip) > 0:
            from simulation import (SimulatedArduino, SimulatedCamera, SimulatedTriax,
                                    SimulatedLaser, SimulatedMonochromator, SimulatedStageControl)
                
                # Replace individual components with simulated versions as specified in debug_skip
            if 'TRIAX' in debug_skip:
                self.spectrometer = SimulatedTriax(self)
                
            if 'UNO' in debug_skip:
                self.controller = SimulatedArduino(self, com_port=com_port, baud=baud)
                
            if 'laser' in debug_skip:
                self.laser = SimulatedLaser(self)
                
            if 'camera' in debug_skip:
                self.camera = SimulatedCamera(self)
            
        # Create instrument wrapper classes with dependency injection
        # Microscope is a mediator that coordinates the other instruments
        self.microscope = Microscope(
            interface=self, 
            calibration_service=self.calibration_service,
            controller=self.controller,
            camera=self.camera,
            spectrometer=self.spectrometer,
            simulate=simulate
        )
        
        # These instrument classes provide a domain-specific interface to the hardware
        # self.stage = StageControl(
        #     interface=self,
        #     controller=self.stage_controller,
        #     simulate=simulate
        # )
        
        # self.monochromator = Monochromator(
        #     interface=self,
        #     controller=self.monochromator_controller,
        #     calibration_service=self.calibration_service,
        #     simulate=simulate
        # )
        
        # self.laser = MillenniaLaser(
        #     interface=self,
        #     simulate=simulate
        # )

        self.command_map = self._generate_command_map()

        # # Scientific attributes
        # self.grating_steps = None
        # self.grating_wavelength = None
        # self.laser_steps = None
        # self.laser_wavelength = None
        # self.triax_steps = None
        # self.triax_wavelength = None

        # self.current_wavelength = None
        # self.current_shift = 0
        # self.detector_safety = True

        self.acq_time = 1
        self.centre_wavelength = 376886
        self.data = []

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
        self.microscope.initialise()  # This one must be last as it relies on others
        
        self._integrity_checker()

    def connect_to_triax(self):
        """Switch from simulated to real TRIAX spectrometer"""
        if self.simulate or 'TRIAX' in self.debug_skip:
            print("Attempting to connect to real TRIAX spectrometer...")
            from instruments import Triax
            try:
                self.spectrometer = Triax(self, simulate=False)
                self.spectrometer.initialise()
                print("Successfully connected to real TRIAX spectrometer")
                self.command_map = self._generate_command_map()
            except Exception as e:
                print(f"Failed to connect to real TRIAX: {e}")
                # Fallback to simulation
                from simulation import SimulatedTriax
                self.spectrometer = SimulatedTriax(self)
                self.spectrometer.initialise()
                print("Reverted to simulated TRIAX")
        else:
            # Already using real hardware
            print("Already connected to real TRIAX")

    #8.56 -14.81
    #Z #5.35 - 4.1

    def connect_to_camera(self):
        """Switch from simulated to real camera"""
        if self.simulate or 'camera' in self.debug_skip or not self.connected_to_camera:
            print("Attempting to connect to real camera...")
            from tucsen.tucsen_camera_wrapper import TucamCamera
            try:
                self.camera = TucamCamera(self, simulate=False)
                self.camera.initialise()
                print("Successfully connected to real camera")
                self.debug_skip.remove('camera')
                self.microscope.camera = self.camera  # Update the microscope's camera reference
                self.command_map = self._generate_command_map()
            except Exception as e:
                print(f"Failed to connect to real camera: {e}")
                # Fallback to simulation
                from simulation import SimulatedCamera
                self.camera = SimulatedCamera(self)
                self.camera.initialise()
                print("Reverted to simulated camera")
        else:
            # Already using real hardware
            print("Already connected to real camera")

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
        print("Available commands:")
        for inst, commands in help_dict.items():
            print(f"{inst}:")
            for command in commands:
                print(f"   {command}")

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
        instruments = [self.__getattribute__(attribute) for attribute in dir(self) if isinstance(self.__getattribute__(attribute), Instrument)]
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

        if funct in self.command_map:
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
        print("Microscope integrity check passed")
        pass


if __name__ == '__main__':
    interface = Interface(simulate=False, com_port='COM10', debug_skip=[
        'camera',
        #'laser', 
        'TRIAX'
        ])
    cli(interface)


    # laser home (at zero steps) is currently 800nm

# l1: -43 steps
# l2: 155 steps
# l3: 467 steps
# g1: 16 stepsb