# l1: 46 steps
# l2: -5 steps
# l3: -247 steps
import inspect
import serial
import time
import pyvisa
import numpy as np
import os
import json
import ctypes
from copy import copy
from ctypes import *
try:
    from tucsen.TUCam import *
except Exception as e:  # catch all exceptions, not just ImportError
    print(f"TUcam error: {e}. Can continue with simulated camera but will crash if camera is required.")
import sys
if sys.platform == "win32":
    from ctypes import OleDLL
if sys.platform == "linux":
    print("Linux detected, using libtucam.so")
    print("implementation not yet available")
else:
    print("Unsupported platform. Please use Windows or Linux.")


from enum import Enum
import time
import numpy as np
import os
import threading

from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import wraps

from calibration import Calibration, LdrScan

def simulate(expected_value=None, function_handler=None):
    """
    Decorator that returns a simulated response when self.simulate is True.
    
    Args:
        expected_value: Static value to return when simulating
        function_handler: Optional callable that receives self and original args/kwargs
                         and returns a dynamic simulated value
    """
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            if self.simulate:
                # If a function handler is provided, use it to get dynamic response
                if function_handler is not None:
                    return function_handler(self, *args, **kwargs)
                # Otherwise return the static expected value
                return expected_value
            return func(self, *args, **kwargs)
        return wrapper
    return decorator

def ui_callable(func):
    """
    Decorator that marks a method as UI-callable by
    setting a custom attribute on the function object.
    """
    func.is_ui_process_callable = True
    return func

def string_to_float(value, message=''):
    try:
        return float(value)
    except ValueError:
        print('Invalid value {}- use a number'.format(message))

@dataclass
class MotorPositions:
    x: int
    y: int
    z: int
    a: int

class AcquitisionParameters:
    '''Holds the acquisition parameters for the microscope, and is passed to acquisition methods to perform actions.'''
    def __init__(self):
        self.scan_min = 0
        self.scan_max = 0
        self.scan_resolution = 0
        self.acq_time = 0

    @property
    def scan_min(self):
        return self._scan_min

    @scan_min.setter
    def scan_min(self, value):
        try:
            self._scan_min = int(value)
        except ValueError:
            print('Invalid value for scan min')
        print('Scan Min Set: {}'.format(self._scan_min))

    @property
    def scan_max(self):
        return self._scan_max
    
    @scan_max.setter
    def scan_max(self, value):
        try:
            self._scan_max = int(value)
        except ValueError:
            print('Invalid value for scan max')
        print('Scan Max Set: {}'.format(self._scan_max))

    @property
    def scan_resolution(self):
        return self._scan_resolution
    
    @scan_resolution.setter
    def scan_resolution(self, value):
        try:
            self._scan_resolution = int(value)
        except ValueError:
            print('Invalid value for scan resolution')
        print('Scan Resolution Set: {}'.format(self._scan_resolution))
    
    @property
    def acq_time(self):
        return self._acq_time
    
    @acq_time.setter
    def acq_time(self, value):
        try:
            self._acq_time = float(value)
        except ValueError:
            print('Invalid value for acquisition time')
        print('Acquisition Time Set: {}'.format(self._acq_time))


class MotionControl:
    '''Handles the motion control of the microscope. Needs access to the controller to move the motors.'''
    def __init__(self, controller, motor_map):
        self.controller = controller
        self.motor_map = motor_map  # Dictionary mapping motor names to IDs
        self._monochromator_steps = None
        self._laser_steps = None
        self._spectrometer_position = None

        self._laser_wavelength = None
        self._monochromator_wavelength = None
        self._spectrometer_wavelength = None

    def extract_coms_flag(self, message):
        return message[0].split(':')[1].strip(' ')

    @ui_callable
    def home_motor(self, motor_label):
        """
        Home the specified motor.
        
        Parameters:
        motor_label (str): The label of the motor to home, e.g., '1X', '2Y', etc.
        
        Returns:
        str: The response from the controller after homing the motor.
        """
        motor_id = self.motor_map.get(motor_label)
        command = f'h{motor_id}'
        print(f"Homing motor {motor_label}...")
        response = self.controller.send_command(command)
        print(response[0])
        home_pos = int(response[0].split(' ')[-1])
        self.move_motors({motor_label: 0-home_pos})
        return response

    def wait_for_motors(self, motors=None, delay=0.1):
        """
        Wait until all motors in the provided list are no longer running.
        
        Parameters:
        motors (list, optional): List of motor identifiers, e.g., ["1X", "2Y", "1Z"].
                               If None, uses a default set of motors.
        delay (float): Delay between polls in seconds.
        
        Returns:
        str: A status flag (e.g., 'S0') when all motors have stopped.
        """
        if motors is None:
            motors = ["1X", "1Y", "1Z", "2X", "2Y", "2Z"]
            
        while True:
            command = 'c' + ' '.join(motors) + 'c'
            response = self.controller.send_command(command)
            status = self.extract_motor_status(response)
            if all(not running for running in status.values()):
                break
            time.sleep(delay)
        return 'S0'

    def extract_motor_status(self, response):
        """
        Parses the response string from a 'check moving' command into a dictionary.
        
        Expected response format:
        "1X:false 2Y:true 1Z:false"
        
        Returns:
        dict: e.g., {"1X": False, "2Y": True, "1Z": False}
        
        Raises:
        ValueError: If response is in unexpected format
        """
        status = {}
        errors = []
        
        if isinstance(response, list) and len(response) > 0:
            response = response[0]
        elif not response:
            raise ValueError(f"Empty response received from motor status check")
            
        tokens = response.strip().split()
        for token in tokens:
            try:
                motor, val = token.split(':')
                if val.lower() not in ["true", "false"]:
                    errors.append(f"Invalid motor status value: {val} for motor {motor}")
                    continue
                status[motor] = (val.lower() == "true")
            except ValueError:
                errors.append(f"Invalid motor status format: {token}")
        
        if errors and not status:
            # If we have errors and no valid statuses, raise an exception
            raise ValueError(f"Failed to parse motor status: {', '.join(errors)}")
        elif errors:
            # If we have some errors but still have valid statuses, print warnings
            print(f"Warning: Some motor status parsing errors: {', '.join(errors)}")
            
        return status

    def generate_motor_dict(self, motor_list):
        """
        Generate a dictionary mapping motor names to their IDs.
        
        Parameters:
        motor_list (list): List of motor names, e.g., ["1X", "2Y", "1Z"].
        
        Returns:
        dict: Dictionary mapping motor names to IDs.
        """
        return {motor: self.motor_map[motor] for motor in motor_list if motor in self.motor_map}

    def confirm_motor_positions(self, target_positions):
        """
        Confirm that motors have reached their target positions.
        
        Parameters:
        target_positions (dict): Dictionary of motor names and their target positions

        Returns:
        bool: True if all motors reached their targets, False otherwise
        """

        # Check if all target positions match current positions
        all_match = True
        discrepancies = {}
        
        # retrieve current positions
        motor_dict = self.generate_motor_dict(target_positions.keys())
        current_positions = self.get_motor_positions(motor_dict)

        for motor, value in current_positions.items():
            target = target_positions.get(motor)
            if target is None:
                continue
            if value != target:
                all_match = False
                discrepancies[motor] = {
                    'expected': target,
                    'actual': value
                }
        
        if all_match:
            print("Motors at target positions")
            return True
        else:
            print("ERROR: Motors not at target positions")
            for motor, info in discrepancies.items():
                print(f"Motor {motor}: Expected {info['expected']}, Actual {info['actual']}")
            return False
        
    def get_motor_positions(self, motor_dict):
        '''Get the current positions of the motors. Takes a dictionary of motor names and returns a list of positions. Motor dict contains the mapping of motor label to motor ID.'''
        motors = [motor_dict[i] for i in motor_dict.keys()]
        print("Getting motor positions {}".format(motors))
        response = self.controller.get_motor_positions(motors)
        pos_dict = self._parse_motor_positions(response)
        labelled_dict = self._return_labelled_positions(pos_dict, motor_dict)
        
        return labelled_dict
    
    def write_motor_positions(self, motor_dict):
        '''Writes the motor positions as defined in motor_dict. Takes a dictionary of motor names and their positions. Returns the response from the controller.'''
        motor_id_dict = {self.motor_map[motor]: steps for motor, steps in motor_dict.items()}
        print("Writing motor positions {}".format(motor_id_dict))
        response = self.controller.write_motor_positions(motor_id_dict)

        print("Motor positions written: {}".format(response))


    def _return_labelled_positions(self, pos_dict, motor_dict):
        '''Returns a dictionary of motor positions with the motor names as keys.'''
        labelled_positions = {}
        for motor in motor_dict.keys():
            labelled_positions[motor] = pos_dict[motor_dict[motor]]
        return labelled_positions

    def _parse_motor_positions(self, response):
        '''Parses the motor positions from the response string.'''
        comstring = response[0].strip(' ')
        positions = comstring.split(' ')
        pos_dict = {}
        for position in positions:
            motor, val = position.split(':')
            pos_dict[motor] = int(val)
        return pos_dict

        
    def backlash_correction(self, motor_steps: dict):
        """
        Apply backlash correction to previously moved motors.
        
        Parameters:
        motor_steps (dict): Dictionary of motor IDs and steps that were moved
        """
        # Only apply correction to motors that actually moved
        if not motor_steps:
            return
            
        # Create backlash correction steps (-20 back, then +20 forward)
        back_steps = {motor_id: -20 for motor_id in motor_steps.keys()}
        forward_steps = {motor_id: 20 for motor_id in motor_steps.keys()}
        
        # Execute the backlash correction with a delay between commands
        self.move_motors(back_steps, backlash=False)
        time.sleep(0.1)  # Small delay to ensure controller processes the first command
        self.move_motors(forward_steps, backlash=False)
        
        return
    
    def resolve_motor_ids(self, motor_dict: dict) -> dict:
        """
        Convert a dictionary of {motor_label: steps} to {motor_id: steps},
        using action_groups as the lookup. If keys are already motor_ids,
        returns the dictionary unchanged.

        Parameters:
        motor_dict (dict): Dictionary with keys as motor_labels or motor_ids.

        Returns:
        dict: Dictionary with keys as motor_ids.
        """
        # # Flatten all label: id pairs from action_groups
        # label_to_id = {
        #     label: motor_id
        #     for group in self.action_groups.values()
        #     for label, motor_id in group.items()
        # }

        label_to_id = self.motor_map

        # Check if all keys are already motor IDs
        if all(k in label_to_id.values() for k in motor_dict):
            return motor_dict  # already using motor_ids

        # If any key is a label, convert all labels to IDs
        result = {}
        for label, steps in motor_dict.items():
            if label in label_to_id:
                motor_id = label_to_id[label]
                result[motor_id] = steps
            else:
                raise ValueError(f"Unknown motor label or ID: {label}")

        return result


    def move_motors(self, motor_id_steps: dict, backlash=True):
        """
        Move motors by specified steps.
        
        Parameters:
        motor_id_steps (dict): Dictionary mapping motor IDs to step counts, e.g. {'1X': 100, '1Y': -50}
        backlash (bool): Whether to apply backlash correction
        
        Returns:
        str: Response from the controller
        """
        motor_id_steps = self.resolve_motor_ids(motor_id_steps)

        if not motor_id_steps:
            return "No movement needed"
            
        # Filter out zero-step movements
        motor_id_steps = {motor: steps for motor, steps in motor_id_steps.items() if steps != 0}
        if not motor_id_steps:
            return "No movement needed"
            
        # Build command in the format o1X100 1Y-50o
        motor_commands = [f"{motor_id}{steps}" for motor_id, steps in motor_id_steps.items()]
        motion_command = 'o' + ' '.join(motor_commands) + 'o'
        
        response = self.controller.send_command(motion_command)
        self.wait_for_motors(list(motor_id_steps.keys()))
        
        return response

    @ui_callable
    def get_laser_motor_positions(self, *args):
        '''Get the current positions of the laser motors.'''
        self.laser_steps = self.get_motor_positions(self.action_groups['laser_wavelength'])
        print('Current laser pos: {}'.format(self.laser_steps))
        return self.laser_steps
    
    @ui_callable
    def get_monochromator_motor_positions(self, *args):
        '''Get the current positions of the monochromator motors.'''
        self.monochromator_steps = self.get_motor_positions(self.action_groups['monochromator_wavelength'])
        print('Current monochromator pos: {}'.format(self.monochromator_steps))
        return self.monochromator_steps

    @property
    def laser_wavelength(self):
        return self._laser_wavelength

    @laser_wavelength.setter
    def laser_wavelength(self, value): 
        self._laser_wavelength = value

    @property
    def monochromator_steps(self):
        return self._monochromator_steps
    
    @monochromator_steps.setter
    def monochromator_steps(self, value):
        if len(value) != 4 or not all(isinstance(x, int) for x in value):
            print('Invalid grating steps')
        self._monochromator_steps = value

    @property
    def laser_steps(self):
        return self._laser_steps
    
    @laser_steps.setter
    def laser_steps(self, value):
        if len(value) != 4 or not all(isinstance(x, int) for x in value):
            print('Invalid laser steps')
        self._laser_steps = value





class Instrument(ABC):
    def __init__(self):
        self.command_functions = {}

    def _integrity_checker(self):
        """
        Checks that every UI-callable method is in command_functions
        and that every command_functions entry is actually UI-callable.
        """

        # 1) Gather all methods (bound or unbound) decorated with @ui_callable
        ui_callable_methods = set()
        # Because we want bound methods for the instance, we use `inspect.ismethod`.
        # That ensures we get `self.run_scan_spectrum` bound to `self`, etc.
        for _, method in inspect.getmembers(self, predicate=inspect.ismethod):
            if getattr(method, 'is_ui_process_callable', False):
                ui_callable_methods.add(method)

        # 2) Gather all methods that appear in your command_functions dict
        cmd_methods = set(self.command_functions.values())

        # 3) Compare them
        if ui_callable_methods != cmd_methods:
            # This means at least one UI-callable method is missing
            # from self.command_functions or vice versa.
            missing_in_dict = ui_callable_methods - cmd_methods
            missing_in_ui = cmd_methods - ui_callable_methods

            message = []
            if missing_in_dict:
                message.append(
                    f"These @ui_callable methods are not in command_functions: "
                    f"{[m.__name__ for m in missing_in_dict]}"
                )
            if missing_in_ui:
                message.append(
                    f"These methods in command_functions are not decorated with @ui_callable: "
                    f"{[m.__name__ for m in missing_in_ui]}"
                )
            raise ValueError("\n".join(message))

        print(f"{self.__class__} integrity check passed")



class Microscope(Instrument):

    implementation_info = [
        'Microscope implementation: v 0.1', 
        'Notes: Use "help" to see available commands. Note than unknown commands are attempted to be passed to the controller for interpretation. If the controller does not recognise the command, it will return an error.',
        '"x", "y" and "z" single letter commands are resered for the stage control, and will call the motion control methods in microscope.'
    
    ]



    def __init__(self, interface, calibration_service=None, controller=None, camera=None, 
                 spectrometer=None, simulate=False):
        super().__init__()
        self.interface = interface
        self.scriptDir = interface.scriptDir
        self.autocalibrationDir = interface.autocalibrationDir
        self.controller = controller or interface.controller
        self.camera = camera or interface.camera
        self.spectrometer = spectrometer or interface.spectrometer
        self.calibration_service = calibration_service
        self.simulate = simulate


        self.config_path = os.path.join(self.scriptDir, "microscope_config.json")
        self.config = self.load_config()

        self.ldr_scan_dict = self.config.get("ldr_scan_dict", {})
        self.hard_limits = self.config.get("hard_limits", {})
        self.action_groups = self.config.get("action_groups", {})

        # Create a flattened motor map for easy lookup of any motor ID by label
        self.motor_map = {}
        for group in self.action_groups.values():
            self.motor_map.update(group)

        # acquisition parameters
        self.acquisition_parameters = AcquitisionParameters()

        # Motion control
        self.motion_control = MotionControl(self.controller, self.motor_map)

        self.command_functions = {
            # general commands
            'wai': self.where_am_i,
            'rg': self.get_spectrometer_position,
            'sl': self.go_to_laser_wavelength,
            'sm': self.go_to_monochromator_wavelength,
            'sall': self.go_to_wavelength_all,
            'st': self.go_to_spectrometer_wavelength,
            'reference': self.reference_calibration_from_wavelength,
            'referencetriax': self.reference_calibration_from_triax,
            'shift': self.go_to_wavenumber,
            'triax': self.connect_to_triax,
            'camera': self.connect_to_camera,
            # 'calshift': self.simple_calibration_shift, #TODO: Decide if I need this
            'report': self.report_status,
            'writemotors': self.write_motor_positions,
            'rldr': self.read_ldr0,
            'calibrate': self.run_calibration,
            # motor commands
            'laserpos': self.get_laser_motor_positions,
            'monopos': self.get_monochromator_motor_positions,
            'slsteps': self.go_to_laser_steps,
            'smsteps': self.go_to_monochromator_steps,
            'recmot': self.record_motors,
            'calhome': self.recalibrate_home,
            'home': self.home_motor,
            'homeall': self.home_all_motors,
            'homelaser': self.home_laser,
            'homemono': self.home_monochromator,
            # acquisition commands
            'scanmin': self.set_scan_min,
            'scanmax': self.set_scan_max,
            'scanres': self.set_scan_resolution,
            'acqtime': self.set_acquisition_time,
            'mshut': self.close_mono_shutter,
            'mopen': self.open_mono_shutter,
            # 'isrun': self.motion_control.wait_for_motors,
            # camera commands
            'acq': self.acquire_one_frame,
            'run': self.start_continuous_acquisition,
            'stop': self.stop_continuous_acquisition,
            'roi': self.set_roi,
            'setbin': self.set_camera_binning,
            'caminfo': self.camera_info,
            'temp': self.get_camera_temperature,
            'refresh': self.refresh_camera,
            'camclose': self.close_camera,
            'camspec': self.set_acq_spectrum_mode,
            'camimage': self.set_acq_image_mode,
            'setgain': self.set_camera_gain,
            'closecamera': self.close_camera_connection,
        }

        self.current_shift = 0
        self.current_wavenumber = None

        self.detector_safety = True

        self.acquire_mode = 'spectrum'

        self._integrity_checker()  # Validate on init


    def __str__(self):
        return "Microscope"

    def __call__(self, command: str, *args, **kwargs):
        if command not in self.command_functions:
            raise ValueError(f"Unknown command: '{command}'")
        return self.command_functions[command](*args, **kwargs)
    
    def load_config(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r') as f:
                config = json.load(f)
            print('Config loaded from file')
            return config
        else:
            raise FileNotFoundError(f"Config file not found at {self.config_path}")

    def write_config(self):
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=2)

    @ui_callable
    def recalibrate_home(self, label):
        if label not in self.action_groups:
            raise ValueError(f"Unknown action group: {label}")

        group = self.action_groups[label]
        for axis, motor_id in group.items():
            if motor_id == "triax":  # skip dummy entries
                continue

            # Send homing command
            if self.simulate:
                print(f"[Sim] Homing motor {motor_id}")
                position = 12345  # dummy value
            else:
                self.controller.write(f"h{motor_id}\n")
                response = self.controller.readline().decode().strip()
                print(f"Homing response: {response}")
                if "at position" in response:
                    position = int(response.split("position")[-1].strip())
                else:
                    raise RuntimeError(f"Unexpected response: {response}")

            # Save to config
            self.config.setdefault("home_positions", {})
            self.config["home_positions"][motor_id] = position
            print(f"Saved home position {position} for {motor_id}")

        self.write_config()

    @ui_callable
    def home_all_motors(self):
        # """
        # Home all motors in the system.
        
        # Returns:
        # str: The response from the controller after homing all motors.
        # """

        # for motor_label in self.motor_map.keys():
        #     response = self.motion_control.home_motor(motor_label)
        #     print(f"Homing motor {motor_label}: {response}")
        # return response
        print("Home all motors not implemented yet")
    
        return "Home all motors not implemented yet"

    @ui_callable
    def home_laser(self):
        """
        Home the laser motors.
        
        Returns:
        str: The response from the controller after homing the laser motors.
        """
        for motor_label in self.action_groups['laser_wavelength'].keys():
            response = self.motion_control.home_motor(motor_label)
            print(f"Homing motor {motor_label}: {response}")
        return response
    
    @ui_callable
    def home_monochromator(self):
        """
        Home the monochromator motors.
        
        Returns:
        str: The response from the controller after homing the monochromator motors.
        """
        for motor_label in self.action_groups['monochromator_wavelength'].keys():
            response = self.motion_control.home_motor(motor_label)
            print(f"Homing motor {motor_label}: {response}")
        return response

    @ui_callable
    def home_motor(self, motor_label):
        """
        Home the specified motor.
        
        Parameters:
        motor_label (str): The label of the motor to home, e.g., '1X', '2Y', etc.
        
        Returns:
        str: The response from the controller after homing the motor.
        """
        response = self.motion_control.home_motor(motor_label)
        return response

    
    def get_home_position(self, motor_id):
        return self.config.get("home_positions", {}).get(motor_id)


    @ui_callable
    def connect_to_triax(self):
        '''Connects to the spectrometer after already running.'''
        self.interface.connect_to_triax()
        print('Connected to TRIAX spectrometer')

    @ui_callable
    def connect_to_camera(self):
        '''Connects to the camera after already running.'''
        self.interface.connect_to_camera()

    @ui_callable
    def write_motor_positions(self, motor_positions, motor_dict=None):
        '''Writes the current motor positions to a file for a string entered by the user. Optionally, a dictionary of motor names to positions can be passed.'''

        if motor_dict is None:
            motor_dict = {}
            try:
                # example = 'l1:300,l2:400,l3:500,g1:600,g2:700'
                for motor in motor_positions.split(','):
                    name, position = motor.split(':')

                    motor_dict[name] = int(position)
            except ValueError:
                print('Invalid motor positions format. Use "name:position" delimited by space " " between motors')
                return
            
        motor_id_dict = {self.motor_map[motor]: steps for motor, steps in motor_dict.items() if motor in self.motor_map}
            
        self.controller.write_motor_positions(motor_id_dict)
        print('Motor positions written to file')

    
    @ui_callable
    def record_motors(self, extra=None):
        '''Records the current motor positions to a file.'''

        laser_motor_positions = self.get_laser_motor_positions()
        monochromator_motor_positions = self.get_monochromator_motor_positions()
        try:
            triax_position = self.get_spectrometer_position()
        except Exception as e:
            triax_position = 0
        
        if extra is None:
            extra = self.calculate_laser_wavelength()

        try:
            with open(os.path.join(self.interface.calibrationDir, 'motor_recordings', 'motor_recordings.json'), 'r') as f:
                current_data = json.load(f)
        except FileNotFoundError:
            current_data = {}


        data = {'laser_positions':laser_motor_positions, 'monochromator_positions':monochromator_motor_positions, 'triax_positions':triax_position,'wavelength':float(extra)}

        current_data[f'{len(current_data)}'] = data
        # breakpoint()
        # dump the data to a json file
        with open(os.path.join(self.interface.calibrationDir, 'motor_recordings', 'motor_recordings.json'), 'w') as f:
            json.dump(current_data, f)
            # f.write('\n')
            
        # with open(os.path.join(self.interface.calibrationDir, 'motor_recordings', 'motor_recordings.txt'), 'a') as f:
        #     f.write('{}:{}:{}:{}\n'.format(laser_motor_positions, monochromator_motor_positions, triax_position, extra))
        # print("Exporting: {}:{}:{}:{}".format(laser_motor_positions, monochromator_motor_positions, triax_position, extra))
        # return f"{laser_motor_positions}:{monochromator_motor_positions}:{triax_position}:{extra}"

    @ui_callable
    def set_camera_gain(self, imagemode, gain):
        '''Sets the camera gain to the specified value.'''
        try:
            imagemode = int(imagemode)
            gain = int(gain)
        except ValueError:
            print("Values for image mode and gain must be integers")
            return

        self.camera.set_image_and_gain(imagemode, gain)
        
    @simulate(expected_value='Microscope initialised')
    def initialise(self):
        '''Initialises the microscope by querying all connections to instruments and setting up the necessary parameters.'''
        # Use the injected calibration service
        self.calibrations = self.calibration_service
        # Update calibrations with auto-calibration data if available
        # self.calibrations.ammend_calibrations()

        # Initialize components
        self.calculate_laser_wavelength()
        self.calculate_monochromator_wavelength()
        self.calculate_spectrometer_wavelength()
        self.report_status(initialise=True)
        
        return 'Microscope initialised'

    @ui_callable
    def report_status(self, initialise=False):
        '''Prints the current status of the system. If initialise is True, the function will recalculate all parameters. If False, it will use the current values obtained from the initialisation.'''

        if initialise is False:
            # recalculate all parameters
            self.laser_steps = self.get_laser_motor_positions()
            self.monochromator_steps = self.get_monochromator_motor_positions()
            self.get_spectrometer_position()


        report = {
            'laser': self.calculate_laser_wavelength(self.laser_steps),
            'monochromator': self.calculate_monochromator_wavelength(self.monochromator_steps),
            'TRIAX lambda': self.calculate_spectrometer_wavelength(self.spectrometer_position),
            'laser motor positions': self.laser_steps,
            'monochromator motor positions': self.monochromator_steps,
            'laser wavenumber': self.current_laser_wavenumber,
            'monochromator wavenumber': self.current_monochromator_wavenumber,
            # 'Raman wavelength': self.current_raman_wavelength,
            'Raman shift': self.current_shift,
            # 'pinhole': self.pinhole
        }
        


        print('-'*20)
        for key, value in report.items():
            print('{}: {}'.format(key, value))
        print('-'*20)

    #? Stage control commands
    def move_stage(self, command):
        pass

    def start_camera_ui(self):
        self.camera.start_ui()

    def camera_set_acquisition_time(self, time):
        self.acq_time = float(time)*1000 #ms
        self.camera.cam.set_attribute_value("Exposure Time", self.acq_time)

    @ui_callable
    def read_ldr0(self):
        '''Reads the light-dependent resistor value from the microscope. Used to detect laser light in autocalibrations.'''
        response = self.controller.read_ldr0()
        ldr_value = int(response[0][1:])
        print("LDR0:", ldr_value)
        return ldr_value
    
    @ui_callable
    def run_calibration(self, motor:str, wavelength_range=(750, 850), resolution=5, safety=False):
       
        if motor.lower() not in self.ldr_scan_dict.keys():
            print("Invalid motor. Must be one of: ", self.ldr_scan_dict.keys())
            return
        
        if safety is True:
            self.detector_safety = True
        else:
            self.detector_safety = False

        calibrationDict = {'data_type': 'autocal'}

        if isinstance(wavelength_range, str):
            vals = wavelength_range.split(',')
            wavelength_range = (float(vals[0]), float(vals[1]))

        resolution = float(resolution)

        initial_grating = copy(self.monochromator_steps)
        initial_laser = copy(self.laser_steps)

        wavelengths = np.arange(*wavelength_range, resolution)
        print(f"Running {motor} calibration for wavelengths: ", wavelengths)
        condition = input("Continue? (y/n): ")
        if condition.lower() == 'n':
            return

        index = len([file for file in os.listdir(self.autocalibrationDir) if file.endswith('.json')])
        
        # initial_pinhole_pos = int(self.pinhole)
        # self.close_pinhole(pinhole_size)
        self.close_mono_shutter()
        
        for wl in wavelengths:
            self.go_to_laser_wavelength(wl)
            self.go_to_monochromator_wavelength(wl)
            scan_data = self.run_ldr0_scan(motor)
            # Apply the conversion to ensure the data is serializable
            calibrationDict[float(wl)] = scan_data

            print("Saving state...")        

            with open(os.path.join(self.autocalibrationDir, 'autocal_{}_{}.json'.format(index, motor)), 'w') as f:
                json.dump(calibrationDict, f)

        print(f"{motor.lower()} Scan complete. Data saved to autocal_{index}_{motor}.json")

        self.detector_safety = True
        # self.open_pinhole_shutter()
        print("Returning to initial position")
        self.go_to_laser_steps(initial_laser)
        self.go_to_monochromator_steps(initial_grating)

    @ui_callable
    def go_to_laser_steps(self, target_positions):
        '''
        Moves the laser motors to the specified positions in steps.
        
        Parameters:
        target_positions (dict): Dictionary of motor names to target positions {'l1': 1000, 'l2': 2000}
        '''
        # Get current positions
        current_positions = self.get_laser_motor_positions()
        # Calculate steps to move
        motor_steps = {}
        for motor, target in target_positions.items():
            if target is None:
                continue
            if motor in current_positions:
                steps = target - current_positions[motor]
                if steps != 0:
                    # Get the Arduino motor ID from motor_map
                    motor_id = self.motor_map.get(motor)
                    if motor_id:
                        motor_steps[motor_id] = steps
        
        # Move motors if needed
        if motor_steps:
            self.motion_control.move_motors(motor_steps)
            self.motion_control.backlash_correction(motor_steps)
            self.motion_control.confirm_motor_positions(target_positions)
            
            # Update laser wavelength
            self.calculate_laser_wavelength(target_positions)
            print("Moved to laser steps: ", self.laser_steps)

    @ui_callable
    def go_to_monochromator_steps(self, target_positions):
        '''
        Moves the monochromator motors to the specified positions in steps.
        
        Parameters:
        target_positions (dict): Dictionary of motor names to target positions {'g1': 1000, 'g2': 2000}
        '''
        # Get current positions
        current_positions = self.get_monochromator_motor_positions()
        
        # Calculate steps to move
        motor_steps = {}
        for motor, target in target_positions.items():
            if motor in current_positions:
                steps = target - current_positions[motor]
                if steps != 0:
                    # Get the Arduino motor ID from motor_map
                    motor_id = self.motor_map.get(motor)
                    if motor_id:
                        motor_steps[motor_id] = steps
        
        # Move motors if needed
        if motor_steps:
            self.motion_control.move_motors(motor_steps)
            self.motion_control.backlash_correction(motor_steps)
            self.motion_control.confirm_motor_positions(target_positions)
            
            # Update monochromator wavelength
            self.calculate_monochromator_wavelength()
            print("Moved to monochromator steps: ", self.monochromator_steps)


    def run_ldr0_scan(self, motor, search_length=None, resolution=None):
        """
        Run an LDR scan by moving a specific motor through a range.
        
        Parameters:
        motor (str): Motor name ('l1', 'l2', 'g1', etc.)
        search_length (int, optional): Range to scan in steps
        resolution (int, optional): Step size for scan
        
        Returns:
        list: List of [position, LDR value] pairs
        """
        if motor not in self.ldr_scan_dict.keys():
            print("Invalid motor. Must be one of:", list(self.ldr_scan_dict.keys()))
            return
            
        # Get scan parameters
        if search_length is None:
            search_length = self.ldr_scan_dict[motor]['range']
        if resolution is None:
            resolution = self.ldr_scan_dict[motor]['resolution']

        # Get the current position of the specified motor
        if motor.startswith('l'):
            motor_positions = self.get_laser_motor_positions()
        elif motor.startswith('g'):
            motor_positions = self.get_monochromator_motor_positions()
        else:
            print(f"Unknown motor type: {motor}")
            return []
            
        if motor not in motor_positions:
            print(f"Motor {motor} not found in current positions")
            return []
            
        current_pos = motor_positions[motor]
        scan_data = []
        scan_points = np.arange(current_pos - search_length, current_pos + search_length, resolution)

        # Get motor ID from the flattened motor map
        motor_id = self.motor_map.get(motor)
        if not motor_id:
            print(f"Could not find motor ID for {motor}")
            return []

        # Perform the scan
        for idx, final_pos in enumerate(scan_points):
            # Move the motor by the specified amount
            steps = final_pos - current_pos
            move_command = {motor_id: steps}
            self.motion_control.move_motors(move_command)
            
            # Wait for the motor to stop on the first movement
            if idx == 0:
                self.motion_control.wait_for_motors([motor_id])
                
            # Read the LDR value and store with position
            ldr_value = 6000 - int(self.read_ldr0())
            scan_data.append([int(final_pos), ldr_value])
            current_pos = final_pos
        
        return scan_data
    
    @property
    def current_laser_wavenumber(self):
        '''Takes the current laser wavelength and calculates the absolute wavenumbers.'''
        wavelength_sample = next(iter(self.laser_wavelengths.values()))
        return 10_000_000/wavelength_sample
    
    @property
    def current_monochromator_wavenumber(self):
        '''Takes the current grating wavelength and calculates the absolute wavenumbers.'''
        wavelength_sample = next(iter(self.monochromator_wavelengths.values()))
        return 10_000_000/wavelength_sample

    @property
    def spectrometer_position(self):
        return self.interface.spectrometer.spectrometer_position

    @ui_callable
    def set_scan_min(self, value):
        self.acquisition_parameters.scan_min = value
    
    @ui_callable
    def set_scan_max(self, value):
        self.acquisition_parameters.scan_max = value

    @ui_callable
    def set_scan_resolution(self, value):
        self.acquisition_parameters.scan_resolution = value

    @ui_callable
    def set_acq_spectrum_mode(self):
        '''Sets the acquisition mode to spectrum.'''
        self.camera.acquire_mode = 'spectrum'
        print('Acquisition mode set to spectrum')
    
    @ui_callable
    def set_acq_image_mode(self):
        '''Sets the acquisition mode to CCD image.'''
        self.camera.acquire_mode = 'image'
        print('Acquisition mode set to image')

    #? camera commands

    @ui_callable
    def close_camera_connection(self):
        '''Closes the camera connection.'''
        self.camera.close_camera_connection()

    @ui_callable
    def set_acquisition_time(self, value):
        self.acquisition_parameters.acq_time = value
        self.camera.set_acqtime(value)

    @ui_callable
    def set_camera_binning(self, value):
        self.camera.set_hardware_binning(value)

    @ui_callable
    def refresh_camera(self):
        '''Refreshes the camera connection.'''
        self.camera.refresh()

    @ui_callable
    def close_camera(self):
        '''Closes the hardware camera connection. Allows connection via Mosaic UI.'''
        self.camera.close_camera()
        self.interface.debug_skip.append('camera')

    @ui_callable
    def acquire_one_frame(self):
        '''Acquires a single frame from the camera.'''
        return self.camera.safe_acquisition()
    
    # def frame_to_spectrum(frame, bin_x=1):
    #     """
    #     Converts a 2D image frame into a 1D spectrum.
        
    #     - Bins pixels along the x-axis (`bin_x` adjacent pixels are averaged).
    #     - Sums all remaining pixels in the y-axis.

    #     :param frame: 2D numpy array representing the image.
    #     :param bin_x: Number of pixels to bin along the x-dimension.
    #     :return: 1D numpy array representing the spectrum.
    #     """
    #     if frame.ndim != 2:
    #         raise ValueError("Input frame must be a 2D numpy array.")

    #     height, width = frame.shape

    #     # Ensure bin_x is within valid range
    #     if bin_x < 1 or bin_x > width:
    #         raise ValueError(f"Invalid bin_x value: {bin_x}. Must be between 1 and {width}.")

    #     # Step 1: Bin along X (average adjacent pixels)
    #     new_width = width // bin_x  # Number of new columns after binning
    #     frame_binned_x = frame[:, :new_width * bin_x].reshape(height, new_width, bin_x).sum(axis=2)

    #     # Step 2: Sum along Y to create a 1D spectrum
    #     spectrum = frame_binned_x.sum(axis=0)

    #     return spectrum
    
    @ui_callable
    def start_continuous_acquisition(self):
        '''Starts continuous acquisition on the camera.'''
        self.camera.start_continuous_acquisition()

    @ui_callable
    def stop_continuous_acquisition(self):
        '''Stops continuous acquisition on the camera.'''
        self.camera.stop_continuous_acquisition()

    @ui_callable
    def set_roi(self, roi:str):
        '''Sets the region of interest on the camera.'''
        self.camera.set_roi(roi)
    
    @ui_callable
    def camera_info(self):
        '''Prints the camera information.'''
        self.camera.camera_info()

    @ui_callable
    def get_camera_temperature(self):
        '''Returns the camera temperature.'''
        return self.camera.check_camera_temperature()

    @ui_callable
    def get_laser_motor_positions(self):
        '''Get the current positions of the laser motors.'''
        return self.motion_control.get_motor_positions(self.action_groups['laser_wavelength'])
    
    @ui_callable
    def get_monochromator_motor_positions(self):
        '''Get the current positions of the grating motors.'''
        return self.motion_control.get_motor_positions(self.action_groups['monochromator_wavelength'])
        
    @ui_callable
    def go_to_wavelength_all(self, wavelength, shift=True):
        """
        Move all components (laser, monochromator, and spectrometer) to the specified wavelength.
        
        Parameters:
        wavelength (float): Target wavelength in nm
        shift (bool): If True, maintains the current Raman shift. If False, sets monochromator to same wavelength.
        """
        # First move the laser
        self.go_to_laser_wavelength(wavelength)
        
        # Then handle the monochromator
        if shift is True:
            # Maintain the current Raman shift by calculating new monochromator position
            self.go_to_wavenumber(self.current_shift)
        else:
            # Set monochromator to the same wavelength as the laser
            self.go_to_monochromator_wavelength(wavelength)

        # Finally, move the spectrometer
        self.go_to_spectrometer_wavelength(wavelength)
        
        print(f"All components set to wavelength: {wavelength} nm")
        return True
    


    @ui_callable
    def go_to_spectrometer_wavelength(self, wavelength):
        '''Moves the spectrometer to the specified wavelength.'''
        self.interface.spectrometer.go_to_wavelength(wavelength)

    @ui_callable
    def reference_calibration_from_triax(self, steps=None, shift=True):
        '''Used to reference the current motor position to the laser wavelength, as defined by the current calibration. Measure a spectrum on the TRIAX and enter the stepper motor position and pixel count of the peak wavelength here. In the future, this will be automated with a peak detection algorithm.'''
        # Instructions: Ensure that the entire system is well aligned, and that the stepper motors are in the correct positions relative to one another for passing the laser wavelength to the spectrograph.
        # Centre the laser peak in pixel 50 of the CCD. Enter the stepper motor position here.
        # correct for current Raman shift (usually zero, but might be different if performing Raman measurements)
            
        if steps is None:
            steps = self.get_spectrometer_position()
        true_wavelength_laser = self.calibrations.triax_to_wl(float(steps))
        print('True wavelength: {}. Shifting motor positions to true wavelength'.format(true_wavelength_laser))
        
        if shift is True:
            grating_wavelength = (10_000_000/true_wavelength_laser) - self.current_shift
            # grating_wavelength = self.current_laser_wavenumber - self.current_shift
            true_wavelength_grating = 10_000_000/grating_wavelength
        else:
            true_wavelength_grating = true_wavelength_laser


        # Calculate target positions for laser and monochromator motors
        laser_steps = self.calibrations.wl_to_steps(true_wavelength_laser, self.action_groups['laser_wavelength'])
        mono_steps = self.calibrations.wl_to_steps(true_wavelength_grating, self.action_groups['monochromator_wavelength'])
        
        # Use dictionary-based go_to methods which use the motor_map and move_motors under the hood
        self.go_to_laser_steps(laser_steps)
        self.go_to_monochromator_steps(mono_steps)

        # Get current positions after movement
        current_laser_pos = self.get_laser_motor_positions()
        current_mono_pos = self.get_monochromator_motor_positions()

        # Verify all laser motors reached their targets
        laser_calibrated = True
        for motor, target in laser_steps.items():
            if motor in current_laser_pos and current_laser_pos[motor] != target:
                laser_calibrated = False
                print(f'Laser motor {motor}: Expected {target}, got {current_laser_pos[motor]}')
        
        if laser_calibrated:
            print('Laser motors successfully calibrated')
        else:
            print('Error calibrating laser motors')
            
        # Verify all monochromator motors reached their targets
        mono_calibrated = True
        for motor, target in mono_steps.items():
            if motor in current_mono_pos and current_mono_pos[motor] != target:
                mono_calibrated = False
                print(f'Monochromator motor {motor}: Expected {target}, got {current_mono_pos[motor]}')
        
        if mono_calibrated:
            print('Monochromator motors successfully calibrated')
        else:
            print('Error calibrating monochromator motors')

    @ui_callable
    def reference_calibration_from_wavelength(self, wavelength, shift=True):
        '''
        Reference the current system configuration to a known laser wavelength (in nm).
        Provide the true laser wavelength from an external reference.

        Parameters
        ----------
        wavelength : float
            Known laser wavelength (in nm).
        shift : bool, optional
            Whether to apply Raman shift correction. Default is True.
        '''
        true_wavelength_laser = float(wavelength)
        print(f'True wavelength provided: {true_wavelength_laser} nm')

        if shift:
            grating_wavenumber = (10_000_000 / true_wavelength_laser) - self.current_shift
            true_wavelength_grating = 10_000_000 / grating_wavenumber
        else:
            true_wavelength_grating = true_wavelength_laser

        # Calculate target motor positions from the provided wavelength
        target_laser_steps = self.calibrations.wl_to_steps(true_wavelength_laser, self.action_groups['laser_wavelength'])
        target_mono_steps = self.calibrations.wl_to_steps(true_wavelength_grating, self.action_groups['monochromator_wavelength'])

        # Move motors using high-level go_to methods
        self.go_to_laser_steps(target_laser_steps)
        self.go_to_monochromator_steps(target_mono_steps)

        # Check laser motor positions
        current_laser_pos = self.get_laser_motor_positions()
        current_mono_pos = self.get_monochromator_motor_positions()

        laser_calibrated = True
        for motor, target in target_laser_steps.items():
            if motor in current_laser_pos and current_laser_pos[motor] != target:
                laser_calibrated = False
                print(f'Laser motor {motor}: Expected {target}, got {current_laser_pos[motor]}')
        
        if laser_calibrated:
            print('Laser motors successfully calibrated')
        else:
            print('Error calibrating laser motors')

        mono_calibrated = True
        for motor, target in target_mono_steps.items():
            if motor in current_mono_pos and current_mono_pos[motor] != target:
                mono_calibrated = False
                print(f'Monochromator motor {motor}: Expected {target}, got {current_mono_pos[motor]}')
        
        if mono_calibrated:
            print('Monochromator motors successfully calibrated')
        else:
            print('Error calibrating monochromator motors')


    def wavenumber_to_wavelength(self, wavenumber):
        return 10_000_000/wavenumber
    
    def wavelength_to_wavenumber(self, wavelength):
        return 10_000_000/wavelength
    
    # @ui_callable
    # def simple_calibration_shift(self, raman_shift=None):
    #     '''We observe a known Raman shift at this wavelength, but the wavelength does not match the shift. This function takes the current motor positions as the new position for the current wavelength. Simply sets the motor steps to the calcualted position for the current wavelength.'''

    #     def obtain_

    #     if raman_shift is not None:
    #         self.current_shift = float(raman_shift)

        
        
    #     current_laser_pos = [i for i in self.get_laser_motor_positions()]
    #     current_laser_wavelength = self.calculate_laser_wavelength(current_laser_pos)
    #     current_grating_pos = [i for i in self.get_monochromator_motor_positions()]

    #     # What the current wavelength should be at the detector
    #     current_monochromator_wavelength = self.wavenumber_to_wavelength(self.current_monochromator_wavenumber)

    #     current_laser_pos[0] = round(self.calibrations.wl_to_l1(current_laser_wavelength[0]))
    #     current_laser_pos[1] = round(self.calibrations.wl_to_l2(current_laser_wavelength[0]))
    #     current_grating_pos[0] = round(self.calibrations.wl_to_g1(current_monochromator_wavelength[0]))
    #     current_grating_pos[1] = round(self.calibrations.wl_to_g2(current_monochromator_wavelength[0]))

    #     print('Current Positions:\n Laser: {}\n Monochromator: {}'.format(current_laser_pos, current_grating_pos))
    #     print('Target Positions:\n Laser: {}\n Monochromator: {}'.format([l1_target, l2_target], [g1_target, g2_target]))

    #     # set the motor positions to the calculated positions, shifting the calibration to the current wavelength
    #     self.set_absolute_positions_A(f'{l1_target},{l2_target},0,0')
    #     self.set_absolute_positions_B(f'{g1_target},{g2_target},0,0')
        
    #     new_laser_pos = self.get_laser_motor_positions()
    #     new_laser_wavelength, l2_wavelength = self.calculate_laser_wavelength(new_laser_pos)
    #     new_grating_pos = self.get_monochromator_motor_positions()
    #     new_grating_wavelength = self.calculate_monochromator_wavelength(new_grating_pos)[0]
        
    #     if new_grating_pos[0] == g1_target and new_grating_pos[1] == g2_target and new_laser_pos[0] == l1_target and new_laser_pos[1] == l2_target:
    #         print('Calibration shift successful')
    #         print('New Positions:\n Laser: {}\n Grating: {}'.format(new_laser_wavelength, new_grating_wavelength))
    #     else:
    #         print('Calibration shift failed')
    #         print('New Positions:\n Laser: {}\n Grating: {}'.format(new_laser_wavelength, new_grating_wavelength))

    def check_hard_limits(self, value, limits):
        '''Checks the hard limits dictionary of the microscope for the allowed range of values.'''
        if not limits[0] < value < limits[1]:
            return False
        return True
        
    def check_laser_wavelength(self, wavelength):
        '''Checks the validity of the entered value for laser wavelength.'''

        wavelength = string_to_float(wavelength)

        if not self.check_hard_limits(wavelength, self.hard_limits['laser_wavelength']):
            print('Wavelength out of range. Pick a wavelength between {} and {} nm'.format(*self.hard_limits['laser_wavelength']))
            return False
        
        return wavelength

    def calculate_laser_steps_to_wavelength(self, target_wavelength):
        '''
        Calculates the target steps and move steps needed for laser motors to reach target wavelength.
        
        Parameters:
        target_wavelength (float): Target wavelength in nm
        
        Returns:
        tuple: (move_steps, target_steps) where both are dictionaries mapping motor IDs to steps
        '''
        # Get current position of laser motors
        current_pos = self.get_laser_motor_positions()
        
        # Calculate target positions based on wavelength
        target_steps = self.calibrations.wl_to_steps(target_wavelength, self.action_groups['laser_wavelength'])
        
        # Calculate steps to move (difference between target and current)
        move_steps = {}
        for motor, target in target_steps.items():
            if motor in current_pos:
                steps_to_move = target - current_pos[motor]
                if steps_to_move != 0:
                    # Get Arduino motor ID from motor_map
                    motor_id = self.motor_map.get(motor)
                    if motor_id:
                        move_steps[motor_id] = steps_to_move
        
        # Log the calculated positions
        print(f'Current laser position: {current_pos}')
        print(f'Target laser position: {target_steps}')
        
        if not move_steps:
            print('Laser already at target position')
            
        return move_steps, target_steps
    

    
    @ui_callable
    def go_to_laser_wavelength(self, wavelength):
        """
        Move the laser to the specified wavelength.
        
        Parameters:
        wavelength (float): Target wavelength in nm
        
        Returns:
        bool: True if successful, False otherwise
        """
        # Validate the wavelength is within allowed range
        wavelength = self.check_laser_wavelength(wavelength)
        if wavelength is False:
            return False
        
        # Safety: close shutter during movement
        self.close_mono_shutter()
        
        # Get target positions from calibration service
        # Assumes the calibration service has a wl_to_steps method that returns a dictionary
        target_positions = self.calibrations.wl_to_steps(wavelength, self.action_groups['laser_wavelength'])
        
        # Move to target positions
        self.go_to_laser_steps(target_positions)
              
        # Safety checks and reopen shutter
        self.laser_safety_check()
        self.open_mono_shutter()
        
        # Report primary wavelength
        print("New laser wavelength: ", next(iter(self.laser_wavelengths.values())))
        
        return True


    @ui_callable
    def go_to_monochromator_wavelength(self, wavelength):
        """
        Move the monochromator to the specified wavelength.
        
        Parameters:
        wavelength (float): Target wavelength in nm
        
        Returns:
        bool: True if successful, False otherwise
        """
        # Validate the wavelength is within allowed range
        wavelength = self.check_monochromator_wavelength(wavelength)
        if wavelength is False:
            return False
        
        # Safety: close shutter during movement
        self.close_mono_shutter()
        
        # Get target positions from calibration service
        target_positions = self.calibrations.wl_to_steps(wavelength, self.action_groups['monochromator_wavelength'])
        
        # Move to target positions
        self.go_to_monochromator_steps(target_positions)
        # self.laser_safety_check()
        self.open_mono_shutter()
        
        # Report primary wavelength
        print("New monochromator wavelength: ", next(iter(self.monochromator_wavelengths.values())))
        
        return True
    def check_monochromator_wavelength(self, wavelength):
        wavelength = string_to_float(wavelength)
        if not self.check_hard_limits(wavelength, self.hard_limits['monochromator_wavelength']):
            print('Wavelength out of range. Pick a wavelength between {} and {} nm'.format(
                *self.hard_limits['monochromator_wavelength']))
            return False
        return wavelength

    def calculate_monochromator_steps_to_wavelength(self, target_wavelength):
        '''
        Calculates the target steps and move steps needed for monochromator motors to reach target wavelength.
        
        Parameters:
        target_wavelength (float): Target wavelength in nm
        
        Returns:
        tuple: (move_steps, target_steps) where both are dictionaries mapping motor IDs to steps
        '''
        # Get current position of monochromator motors
        current_pos = self.get_monochromator_motor_positions()
        
        # Calculate target positions based on wavelength
        target_steps = self.calibrations.wl_to_steps(target_wavelength, self.action_groups['monochromator_wavelength'])
        
        # Calculate steps to move (difference between target and current)
        move_steps = {}
        for motor, target in target_steps.items():
            if motor in current_pos:
                steps_to_move = target - current_pos[motor]
                if steps_to_move != 0:
                    # Get Arduino motor ID from motor_map
                    motor_id = self.motor_map.get(motor)
                    if motor_id:
                        move_steps[motor_id] = steps_to_move
        
        # Log the calculated positions
        print(f'Current monochromator position: {current_pos}')
        print(f'Target monochromator position: {target_steps}')
        
        if not move_steps:
            print('Monochromator already at target position')
            
        return move_steps, target_steps


    def calculate_monochromator_wavelength(self, current_pos=None):
        """
        Calculate monochromator wavelength from motor positions.
        
        Parameters:
        current_pos (dict, optional): Current motor positions. If None, gets current positions.
        
        Returns:
        dict: Dictionary of motor names to calculated wavelengths {'g1': 800.0, 'g2': 800.5}
        """
        if current_pos is None:
            current_pos = self.get_monochromator_motor_positions()

        self.monochromator_steps = current_pos
        

        # Calculate wavelengths for each motor using calibration functions
        self.monochromator_wavelengths = self.calibrations.steps_to_wl(current_pos)
      
        return self

    @ui_callable
    def close_mono_shutter(self):
        self.controller.close_mono_shutter()

    @ui_callable
    def open_mono_shutter(self):
        self.controller.open_mono_shutter()




    def laser_safety_check(self, limit=50):
        '''If the detector wavelength is within 20 wavenumbers of the laser wavelength, warn the user and prompt to overwrite or revert to a safe position.'''

        # grating_wavelength = self.calculate_grating_wavelength()[0]
        if self.detector_safety is False:
            return
        
        if self.current_laser_wavenumber + limit > self.current_monochromator_wavenumber > self.current_laser_wavenumber - limit:
            print(f'Warning: Detection is within {limit} wavenumbers of the laser wavelength - press enter to revert to safety')
            command = input()
            if command.lower() == 'overwrite':
                return
            else:
                print(f'Moving to raman shift of {limit} cm-1')
                self.current_shift = limit + 25
                self.go_to_wavenumber(self.current_shift)

    @ui_callable
    def where_am_i(self):
        self.get_all_current_positions()
        self.report_all_current_positions()

    @ui_callable
    def get_spectrometer_position(self):
        '''Get the current position of the spectrometer in motor steps.'''
        self.interface.spectrometer.get_spectrometer_position()
        print('Current spectrometer position: {}'.format(self.interface.spectrometer.spectrometer_position))
        return self.interface.spectrometer.spectrometer_position
    

    def get_laser_wavelength(self):
        '''Get the current laser wavelength in nm.'''
        return self.calculate_laser_wavelength()
    
    def get_monochromator_wavelength(self):
        '''Get the current monochromator wavelength in nm.'''
        return self.calculate_monochromator_wavelength()
    
    def get_all_current_positions(self):
        '''Get the current positions of all motors and calculate the corresponding wavelengths.'''
        laser_positions = self.calculate_laser_wavelength()
        monochromator_positions = self.calculate_monochromator_wavelength()
        spectrometer_position = self.calculate_spectrometer_wavelength()

        return (laser_positions, monochromator_positions, spectrometer_position)
    
    def calculate_spectrometer_wavelength(self, steps=None):
        '''Uses calibration to calculate wavelength from reported position. For spectrometers that report wavelength, this is a pass-through.'''
        if steps is None:
            steps = self.interface.spectrometer.get_spectrometer_position()


        self.spectrometer_wavelength = self.calibrations.steps_to_wl({'triax':self.spectrometer_position}) # TODO: rename triax_to_wl to spectrometer_steps_to_wl - requires change to calibration files and will be breaking until otherwise completed
        return self.spectrometer_wavelength
    
    def report_all_current_positions(self):
        '''Formats and prints the current positions of the microscope.'''
        print("---Laser---")
        for motor, position in self.laser_steps.items():
            print(f'{motor}: {position} steps')
        for motor, position in self.monochromator_steps.items():
            print(f'{motor}: {position} steps')

        print('---Monochromator---')
        for motor, wavelength in self.laser_wavelengths.items():
            if wavelength is None:
                print(f'{motor}: None')
                continue
            print(f'{motor}: {round(wavelength, 2)} nm')
        for motor, wavelength in self.monochromator_wavelengths.items():
            if wavelength is None:
                print(f'{motor}: None')
                continue
            print(f'{motor}: {round(wavelength, 2)} nm')

        print('---Spectrometer---')
        print(f'Spectrometer position: {self.spectrometer_position} steps')
        print(f'Spectrometer wavelength: {self.spectrometer_wavelength} nm')
        

        return 
    
    def calculate_laser_wavelength(self, current_pos=None):
        """
        Calculate laser wavelength from motor positions.
        
        Parameters:
        current_pos (dict, optional): Current motor positions. If None, gets current positions.
        
        Returns:
        dict: Dictionary of motor names to calculated wavelengths {'l1': 800.0, 'l2': 800.5}
        """
        if current_pos is None:
            current_pos = self.get_laser_motor_positions()

        self.laser_steps = current_pos
               
        # Calculate wavelengths for each motor using calibration functions
        self.laser_wavelengths = self.calibrations.steps_to_wl(current_pos)
      
        return self.laser_wavelengths

    @ui_callable
    def go_to_wavenumber(self, wavenumber):
        """
        Move monochromator to achieve a specific Raman shift relative to the laser wavelength.
        
        Parameters:
        wavenumber (float): Desired Raman shift in cm^-1
        """
        try:
            wavenumber = float(wavenumber)
        except ValueError:
            print('Invalid value for wavenumber - use a number')
            return
            
        # Get the current laser wavelength
        laser_wavelengths = self.calculate_laser_wavelength()
        
        if not laser_wavelengths:
            print("Failed to get laser wavelength <Microscope.go_to_wavenumber()>")
            return
            
        # Use l1 wavelength (primary laser wavelength) for calculations
        laser_wavelength = next(iter(laser_wavelengths.values()))
        if not laser_wavelength:
            print("Failed to determine primary laser wavelength <Microscope.go_to_wavenumber()>")
            return
            
        # Calculate the target wavelength for the monochromator
        laser_wavenumber = 10_000_000 / laser_wavelength
        target_wavenumber = laser_wavenumber - wavenumber
        target_wavelength = 10_000_000 / target_wavenumber
        
        # Move monochromator to the calculated wavelength
        self.go_to_monochromator_wavelength(target_wavelength)
        self.current_shift = wavenumber
        
        print(f'Set Raman shift to {wavenumber} cm^-1 for {laser_wavelength} nm excitation')

    def acquire_spectrum(self, overwrite=False, save=True):
        '''Acquires a single spectrum and saves it in the saved_data directory.'''

        print("Acquiring...")
        data = self.interface.camera.acquire_one_frame()
        np.save(os.path.join(self.interface.transientDir, "transient_data.npy"), data) # save to transient dir for immediate plotting/viewing

        data = np.array(data, dtype=np.int32) # convert to numpy array for fast saving
        if overwrite is False:
            file_index = len([x for x in os.listdir(self.saveDir) if x.split('_')[0] == self.filename])
        else:
            file_index = 0

        filename = os.path.join(self.saveDir, f'{self.filename}_{file_index}.npy')
        
        while True:
            try:
                if save is True:
                    np.save(filename, data)
                return data
            except PermissionError:
                print('File in use. Waiting 0.1 s...')
                time.sleep(0.1)
                continue

    def continuous_acquire(self):
        '''Runs the continuous acquisition of the camera and saves the data to the transient directory.'''
        self.camera.start_continuous_acquisition() # threaded for non-blocking use
        # self.camera.continuous_acquisition() # for debugging

    def stop_continuous_acquire(self):
        '''Stops the continuous acquisition of the camera.'''
        self.camera.stop_continuous_acquisition()


class Camera(Instrument):
    def __init__(self, interface, simulate=False):
        super().__init__()
        self.interface = interface
        self.simulate = simulate
        self.command_functions = {
        }

        self._integrity_checker()

    def __str__(self):
        return "Camera"

    def __call__(self, command: str, *args, **kwargs):
        if command not in self.command_functions:
            raise ValueError(f"Unknown camera command: '{command}'")
        return self.command_functions[command](*args, **kwargs)
    
    def initialise(self):
        self.connect()
    
    @simulate(expected_value=serial.Serial)
    def connect(self):
        print("Connecting to the camera.")
        self.serial = self.connect_to_camera()

    @simulate(expected_value=serial.Serial)
    def connect_to_camera(self):
        return serial.Serial

    def acquire_one_frame(self):
        '''Acquires a single frame from the camera.'''
        return self.acquire_frame()
    
class TucsenCamera(Camera):
    def __init__(self, interface, simulate=False, set_ROI=(0, 0, 2048, 2048)):
        self.simulate = simulate
        self.scriptDir = interface.scriptDir
        self.transientDir = interface.transientDir
        self.set_ROI = set_ROI

        self.camera_lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.is_running = False

        self.command_functions = {
            'acquire_one_frame': self.acquire_one_frame,
            'start_continuous_acquire': self.start_continuous_acquisition,
            'stop_continuous_acquire': self.stop_continuous_acquisition
        }

    @simulate(expected_value=serial.Serial)
    def connect(self):
        print("Connecting to Tucsen...")
        self.TUCAMINIT = TUCAM_INIT(0, self.scriptDir.encode('utf-8'))
        self.TUCAMOPEN = TUCAM_OPEN(0, 0)
        self.handle = self.TUCAMOPEN.hIdxTUCam
        TUCAM_Api_Init(pointer(self.TUCAMINIT), 5000)
        print("Connected to Tucsen.")
        
        # self.open_camera(0)
        # self.SetROI(set_ROI=self.set_ROI)

    @simulate(expected_value=np.arange(1024))
    @ui_callable
    def acquire_one_frame(self):
        self.open_camera(0)
        self.SetROI(set_ROI=(0, 0, 2048, 2048))
        self.SetExposure(200)
        dataDict = self.WaitForImageData(nframes=1)
        self.close_camera()
        return dataDict[0] if dataDict else None

    @ui_callable
    def continuous_acquisition(self):
        self.stop_flag.clear()
        self.open_camera(0)
        self.SetROI(set_ROI=(0, 0, 2048, 2048))
        self.SetExposure(200)
        self.write_dir = self.transientDir

        while not self.stop_flag.is_set():
            try:
                with self.camera_lock:
                    dataDict = self.WaitForImageData(nframes=1)
                if not dataDict:
                    continue
                data = dataDict[0]
                np.save(os.path.join(self.transientDir, "transient_data.npy"), data)
                time.sleep(0.001)
            except Exception as e:
                print(f"Acquisition error: {e}")
                break

        self.close_camera()

    @ui_callable
    def start_continuous_acquisition(self):
        acq_thread = threading.Thread(target=self.continuous_acquisition)
        acq_thread.daemon = True
        acq_thread.start()
        print("Started continuous acquisition.")
        self.is_running = True

    def stop_continuous_acquisition(self):
        print("Stopping continuous acquisition.")
        self.stop_flag.set()
        self.is_running = False

    def open_camera(self, Idx):

        if  Idx >= self.TUCAMINIT.uiCamCount:
            return

        self.TUCAMOPEN = TUCAM_OPEN(Idx, 0)

        TUCAM_Dev_Open(pointer(self.TUCAMOPEN))

        if 0 == self.TUCAMOPEN.hIdxTUCam:
            print('Open the camera failure!')
            return
        else:
            print('Open the camera success!')

    def close_camera(self):
        if 0 != self.TUCAMOPEN.hIdxTUCam:
            TUCAM_Dev_Close(self.TUCAMOPEN.hIdxTUCam)
        print('Close the camera success')

    def UnInitApi(self):
        TUCAM_Api_Uninit()

    def SetROI(self, set_ROI=(0, 0, 2048, 2048)):
        if len(set_ROI) != 4:
            print('ROI must be a tuple of 4 elements, (HOffset, VOffset, Width, Height)')
            return
        roi = TUCAM_ROI_ATTR()
        roi.bEnable  = 1
        roi.nHOffset = set_ROI[0]
        roi.nVOffset = set_ROI[1]
        roi.nWidth   = set_ROI[2]
        roi.nHeight  = set_ROI[3]

        try:
           TUCAM_Cap_SetROI(self.TUCAMOPEN.hIdxTUCam, roi)
           print('Set ROI state success, HOffset:%#d, VOffset:%#d, Width:%#d, Height:%#d'%(roi.nHOffset,
                    roi.nVOffset, roi.nWidth, roi.nHeight))
        except Exception:
            print('Set ROI state failure, HOffset:%#d, VOffset:%#d, Width:%#d, Height:%#d' % (roi.nHOffset,
                    roi.nVOffset, roi.nWidth,roi.nHeight))

    def convert_to_numpy(self, m_frame):
        # Convert buffer to list
        buffer = ctypes.cast(m_frame.pBuffer, ctypes.POINTER(ctypes.c_ubyte))
        buffer_list = list(buffer[:m_frame.uiImgSize])
        # Create numpy array from buffer list
        np_array = np.array(buffer_list, dtype=np.uint8)
        # Reshape array to match image dimensions
        np_array = np_array.reshape((m_frame.usHeight, m_frame.usWidth, m_frame.ucElemBytes))
        return np_array
        # return buffer_list

    def WaitForImageData(self, nframes=10):
        dataDict = {}
        m_frame = TUCAM_FRAME()
        m_format = TUIMG_FORMATS
        m_frformat = TUFRM_FORMATS
        m_capmode = TUCAM_CAPTURE_MODES

        m_frame.pBuffer = 0;
        m_frame.ucFormatGet = m_frformat.TUFRM_FMT_USUAl.value
        m_frame.uiRsdSize = 1

        TUCAM_Buf_Alloc(self.TUCAMOPEN.hIdxTUCam, pointer(m_frame))
        TUCAM_Cap_Start(self.TUCAMOPEN.hIdxTUCam, m_capmode.TUCCM_SEQUENCE.value)

        for i in range(nframes):
            try:
                result = TUCAM_Buf_WaitForFrame(self.TUCAMOPEN.hIdxTUCam, pointer(m_frame), 1000)

                # print("Buffer as list:", buffer_list)
                print(
                    "Grab the frame success, index number is %#d, width:%d, height:%#d, channel:%#d, elembytes:%#d, image size:%#d"%(i, m_frame.usWidth, m_frame.usHeight, m_frame.ucChannels,
                    m_frame.ucElemBytes, m_frame.uiImgSize)
                    )
            except Exception:
                print('Grab the frame failure, index number is %#d',  i)
                continue
                # Convert buffer to list
            # buffer = ctypes.cast(m_frame.pBuffer, ctypes.POINTER(ctypes.c_ubyte))
            try:
                data = self.convert_to_numpy(m_frame)
            # dataDict[i] = data
            # buffer_list = list(buffer[:m_frame.uiImgSize])
                dataDict[i] = data
            except Exception as e:
                print(e)
                print('Convert to numpy failed')
                continue

        TUCAM_Buf_AbortWait(self.TUCAMOPEN.hIdxTUCam)
        TUCAM_Cap_Stop(self.TUCAMOPEN.hIdxTUCam)
        TUCAM_Buf_Release(self.TUCAMOPEN.hIdxTUCam)

        return dataDict
    
    def export_data(self, data, filename='default', spectrum=False):
        self.save_dir = os.path.join(self.scriptDir, 'data')
        if not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir)
    
            # plt.plot(data[:, 0], data[:, 1])
        filepath = os.path.join(self.save_dir, filename)
        np.save(filepath, data)
        print('Data saved to %s' % filepath)

    def SetExposure(self, value):

        TUCAM_Capa_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDCAPA.TUIDC_ATEXPOSURE.value, 0)
        TUCAM_Prop_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDPROP.TUIDP_EXPOSURETM.value, value, 0);
        print("Set exposure:", value)
        # self.ShowAverageGray()

    def get_camera_info(self):
        from tucsen.TUCam import get_camera_gain_attributes

        gain = get_camera_gain_attributes(self.handle)
        print(gain)
        self.gain = gain

    def refresh_camera(self):
        print("refreshing camera")
        self.close_camera()
        self.open_camera(0)
        # demo.get_camera_info()
        self.get_camera_info()




class Spectrometer(Instrument):
    def __init__(self, interface, simulate=False):
        super().__init__()
        self.interface = interface
        self.simulate = simulate
        self.command_functions = {
            'get_spectrometer_position': self.get_spectrometer_position,
            'go_to_position': self.go_to_position
        }

        self._integrity_checker()

    def __str__(self):
        return "Spectrometer"

    def __call__(self, command: str, *args, **kwargs):
        if command not in self.command_functions:
            raise ValueError(f"Unknown spectrometer command: '{command}'")
        return self.command_functions[command](*args, **kwargs)

    @abstractmethod
    @ui_callable
    def get_spectrometer_position(self):
        print("Getting the current position of the spectrometer.")

    @abstractmethod
    @ui_callable
    def go_to_position(self, position):
        print("Going to the position: {}".format(position))



class Triax(Instrument):
    def __init__(self, interface, simulate=False):
        super().__init__()
        self.interface = interface
        self.simulate = simulate


        self.command_functions = {
            'get_spectrometer_position': self.get_spectrometer_position,
            'rg': self.get_spectrometer_position,
            'go_to_position': self.go_to_position,
            'ren': self.read_enterance_slit,
            'rex': self.read_exit_slit,
            'men': self.move_enterance_slit,
            'mex': self.move_exit_slit,
            'mg': self.move_grating_relative,
            'initialise': self.initialise_spectrometer,
        }

        self.spectrometer_position = 380000

        self.message_map = {
            'initialise': 'A',
            'comsmode': '02000',
            'get_grating_steps': 'H0',
            'read_grating': 'H0',
            'rg': 'H0',
            'grating': 'F0,',
            'move_grating': 'F0,',
            'mg': 'F0,',
            'read_enter': 'j0,0',
            'ren': 'j0,0',
            'read_exit': 'j0,3',
            'rex': 'j0,3',
            'move_enter': 'k0,0,',
            'men': 'k0,0,',
            'move_exit': 'k0,3,',
            'mex': 'k0,3,',
            'tpol': 'E', # poll motors after move command sent
            'ccd_mode': 'f0',
            'ccd': 'f0',
            'apd_mode': 'e0',
            'apd': 'e0',
            # 'gotoir': 'F0,375131'
            #'entrance mirror to front enterance': 'c0',
            #'entrance mirror to side enterance': 'd0'
        }

        self._integrity_checker()

    def __str__(self):
        return "TRIAX Spectrometer"
    
    # @simulate(expected_value=380000) # TODO: Change to actual response
    def initialise(self):
        '''Connect and establish primary attributes.'''
        self.connect()
        self.get_spectrometer_position()
        # self.calibrations = self.interface.microscope.calibrations

        return self.spectrometer_position

    @ui_callable
    def initialise_spectrometer(self):
        '''Initialise the spectrometer.'''
        self.send_command('initialise')
    
    @ui_callable
    def read_enterance_slit(self):
        '''Read the current position of the entrance slit.'''
        response = self.send_command('read_enter')
        return response
    
    @ui_callable
    def read_exit_slit(self):
        '''Read the current position of the exit slit.'''
        response = self.send_command('read_exit')
        return response
    
    @ui_callable
    def move_enterance_slit(self, position):
        '''Move the entrance slit to the specified position.'''
        response = self.send_command('men {}'.format(position))
        return response
    
    @ui_callable
    def move_exit_slit(self, position):
        '''Move the exit slit to the specified position.'''
        response = self.send_command('mex {}'.format(position))
        return response
    
    @ui_callable
    def move_grating_relative(self, position):
        '''Move the grating the specified number of steps.'''
        response = self.send_command('mg {}'.format(position))
        return response
    
    # @simulate(expected_value='S0') # TODO: Change to actual response
    def go_to_wavelength(self, wavelength):
        '''Moves the spectrometer to the specified wavelength.'''
        try:
            wavelength = float(wavelength)
        except ValueError:
            print('Invalid input')
            return
        
        triax_steps = self.get_triax_steps()
        
        target_steps = round(self.interface.microscope.calibrations.wl_to_triax(wavelength))
        # 
        new_steps = target_steps - triax_steps
        # return if no movement is required
        if new_steps == 0:
            return
        
        print('UNO>g {}>triax'.format(new_steps))

        response = self.send_command('mg {}'.format(new_steps))
        if response == 'o':
            triax_res = self.wait_for_triax(target_steps)
            if triax_res == 'S0':
                print('Triax moved to {} nm'.format(wavelength))
                self.triax_steps = target_steps
                return 'S0'
            else:
                print('Triax move failed: {}'.format(triax_res))
                return 'F0'

        else:
            print('Triax communication failed:')
            print(response)

    @simulate(expected_value='S0') # TODO: Change to actual response
    def wait_for_triax(self, target_steps, timeout=10):
        '''Polls the spectrometer until the target steps are reached. Note the MOTOR BUSY CHECK (E) on the spectrometer does not send a response with this configuration, so we use this command instead.'''
        start = time.time()
        while True:
            response = self.get_triax_steps()
            if response == target_steps:
                return 'S0'
            time.sleep(0.1)
            if time.time() - start > timeout:
                print('Timeout reached')
                return 'F0'

    

    @ui_callable
    @simulate(expected_value=380000) # TODO: Change to actual response
    def get_spectrometer_position(self):
        '''Get the current position of the spectrometer in motor steps.'''
        self.spectrometer_position = self.get_triax_steps()
        return self.spectrometer_position
    
    @ui_callable
    @simulate(expected_value='OK') # TODO: Change to actual response
    def go_to_position(self, position):
        print("Going to the position: {}".format(position))
        command = self.message_map['move_grating'] + str(position)
        response = self._send_command_to_spectrometer(command)
        return response

    @simulate(expected_value=True) # TODO: Change to actual response
    def connect(self):
        # Open a connection to the instrument
        rm = pyvisa.ResourceManager()
        rm.list_resources()
        self.spectrometer = rm.open_resource('GPIB0::1::INSTR')  # Replace with the actual VISA address of your instrument

        self.spectrometer.write('WHERE AM I')
        time.sleep(0.0001)
        self.state = self.spectrometer.read()
        print(self.state)

        print('Connected to TRIAX spectrometer.')

        return self.spectrometer, self.state

    @simulate(expected_value=380000) # TODO: Change to actual response
    def get_triax_steps(self):
        '''Polls the spectrometer for position and returns the current position in steps.'''
        response = self._send_command_to_spectrometer(self.message_map['get_grating_steps'])
        self.triax_steps = int(response.strip()[1:])
        return self.triax_steps
        
    def _command_parser(self, command):
        '''Parses the command to ensure it is in the correct format for the spectrometer.'''
        com_set = command.split(' ')
        new_command = self.message_map.get(com_set[0], None)
        if new_command is None:
            print('Unknown command: {}'.format(command))
            return None

        if len(com_set) > 1:
            new_command += com_set[1]
        
        return new_command
    
    @simulate(expected_value='o') # TODO: Change to actual response
    def send_command(self, command):
        '''Send a command to the spectrometer.'''
        coms = self._command_parser(command)
        response = self._send_command_to_spectrometer(coms)
        return response
    
    @simulate(expected_value='OK') # TODO: Change to actual response
    def _send_command_to_spectrometer(self, command, report=True):
        self.spectrometer.write(command)
        time.sleep(0.0001)

        if command == 'A':
            count = 100
            while count > 0:
                print('Initialising: Sleeping for {} seconds'.format(count))
                time.sleep(1)
                count -= 1
        
        response = self.spectrometer.read()
        return response

class StageControl(Instrument):
    def __init__(self, interface, controller=None, simulate=False):
        super().__init__()
        self.interface = interface
        self.controller = controller or interface.stage_controller
        self.simulate = simulate
        self.command_functions = {
            'movestage': self.move_stage,
            'homestage': self.home_stage
        }

        self._integrity_checker()
        
    def initialise(self):
        """Initialize the stage controller"""
        print("Stage controller initialized")
        return "Stage controller initialized"

    def __str__(self):
        return "Stage Control"

    def __call__(self, command: str, *args, **kwargs):
        if command not in self.command_functions:
            raise ValueError(f"Unknown stage command: '{command}'")
        return self.command_functions[command](*args, **kwargs)

    @ui_callable
    def move_stage(self):
        print("Moving the stage.")

    @ui_callable
    def home_stage(self):
        print("Homing the stage.")

    


class Monochromator(Instrument):
    def __init__(self, interface, controller=None, calibration_service=None, simulate=False):
        super().__init__()
        self.interface = interface
        self.controller = controller or interface.monochromator_controller
        self.calibration_service = calibration_service or interface.calibration_service
        self.simulate = simulate
        self.command_functions = {
            'set_wavelength': self.set_wavelength,
            'get_wavelength': self.get_wavelength
        }

        self._integrity_checker()
        
    def initialise(self):
        """Initialize the monochromator"""
        print("Monochromator initialized")
        return "Monochromator initialized"

    def __str__(self):
        return "Monochromator"

    def __call__(self, command: str, *args, **kwargs):
        if command not in self.command_functions:
            raise ValueError(f"Unknown monochromator command: '{command}'")
        return self.command_functions[command](*args, **kwargs)

    @ui_callable
    def set_wavelength(self):
        print("Setting the monochromator wavelength.")


    @ui_callable
    def get_wavelength(self):
        print("Getting the monochromator wavelength.")

class Laser(Instrument):
    def __init__(self, interface, controller=None, calibration_service=None, simulate=False):
        super().__init__()
        self.interface = interface
        self.controller = controller or interface.laser_controller
        self.calibration_service = calibration_service or interface.calibration_service
        self.simulate = simulate
        self.command_functions = {
            'set_power': self.set_power,
            'get_power': self.get_power,
            'turn_on': self.turn_on,
            'turn_off': self.turn_off
        }

        self._integrity_checker()
        
    def initialise(self):
        """Initialize the laser"""
        if hasattr(self.controller, 'initialise'):
            self.controller.initialise()
        print("Laser initialized")
        return "Laser initialized"
        
    @ui_callable
    def turn_on(self):
        """Turn the laser on"""
        if hasattr(self.controller, 'turn_on'):
            return self.controller.turn_on()
        print("Turning laser on")
        return "Laser turned on"
        
    @ui_callable
    def turn_off(self):
        """Turn the laser off"""
        if hasattr(self.controller, 'turn_off'):
            return self.controller.turn_off()
        print("Turning laser off")
        return "Laser turned off"

    def __str__(self):
        return "Laser"

    def __call__(self, command: str, *args, **kwargs):
        if command not in self.command_functions:
            raise ValueError(f"Unknown laser command: '{command}'")
        return self.command_functions[command](*args, **kwargs)
    
    def initialise(self):
        self.connect()
    
    @simulate(expected_value=True) # TODO: Change to actual response
    def connect(self):
        print("Connecting to the laser.")
        pass

    @ui_callable
    def set_power(self):
        '''Set the laser power.'''
        print("Setting the laser power.")

    @ui_callable
    def get_power(self):
        '''Get the laser power.'''
        print("Getting the laser power.")