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
import tkinter as tk
from tkinter import ttk, messagebox

from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import wraps

from calibration import Calibration, LdrScan
from acquisitioncontrol import AcquisitionControl, AcquisitionGUI

# def simulate(expected_value=None, function_handler=None):
#     """
#     Decorator that returns a simulated response when self.simulate is True.
    
#     Args:
#         expected_value: Static value to return when simulating
#         function_handler: Optional callable that receives self and original args/kwargs
#                          and returns a dynamic simulated value
#     """
#     def decorator(func):
#         @wraps(func)
#         def wrapper(self, *args, **kwargs):
#             if self.simulate:
#                 # If a function handler is provided, use it to get dynamic response
#                 if function_handler is not None:
#                     return function_handler(self, *args, **kwargs)
#                 # Otherwise return the static expected value
#                 return expected_value
#             return func(self, *args, **kwargs)
#         return wrapper
#     return decorator

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


class MotionControl:
    '''Handles the motion control of the microscope. Needs access to the controller to move the motors.
    
    Notes:
    - Backlash is applied to all move_motor commands if the direction of travel is negative.
    - Homing commands to not apply backlash corrections to the homed position. This means if the backlash changes, the motor homes need to be recalibrated.
    - Home calibration is performed at the microscope level by calling "calhome" at the interface level. Home positions are stored in the config file.'''

    def __init__(self, controller, motor_map, config):
        self.controller = controller
        self.motor_map = motor_map  # Dictionary mapping motor names to IDs
        self.config = config
        self.home_positions = config.get("home_positions", {})
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
        Home the specified motor, then writes the position as the home position. Then moves to zero to release from limit switch.
        
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
        expected_home = self.home_positions.get(motor_id, None)
        self.write_motor_positions({motor_label: expected_home})  # Write the expected motor position to the controller (set home position)
        print("Moving to zero position to release from limit switch...")
        self.move_motors({motor_label: -expected_home}, backlash=False) # Move to zero to release from limit switch

        return home_pos

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
        
    def get_motor_positions(self, motor_dict, report=True):
        '''Get the current positions of the motors. Takes a dictionary of motor names and returns a list of positions. Motor dict contains the mapping of motor label to motor ID.'''
        motors = [motor_dict[i] for i in motor_dict.keys()]
        if report:
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
        back_steps = {motor_id: -100 for motor_id in motor_steps.keys()}
        forward_steps = {motor_id: 100 for motor_id in motor_steps.keys()}
        
        # Execute the backlash correction with a delay between commands
        self.move_motors(back_steps, backlash=False)
        # time.sleep(0.2)  # Small delay to ensure controller processes the first command
        
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
        Move motors by specified steps. Actively waits for motors to stop moving by polling controller. Backlash correction is applied to movements in the negative direction.
        
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

        if backlash:
            motors_for_correction = {motor: steps for motor, steps in motor_id_steps.items() if int(steps) < 0} # Only apply backlash if moving backwards. i.e. forwards direction should already have the backlash taken up
            self.backlash_correction(motors_for_correction)

        
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
        '"x", "y" and "z" single letter commands are resered for the stage control, and will call the motion control methods in microscope.',
        'Stage positions in microns are held by the microscope in the stage_positions_microns dictionary. Every move XYZ axis command will update the dictionary and call an AcquisitionControl.update_stage_positions to ensure the stage positions are in sync with the acquisition control, which needs them to calculate scan positions.',
        
    
    ]



    def __init__(self, interface, calibration_service=None, controller=None, camera=None, 
                 spectrometer=None, simulate=False):
        super().__init__()
        self.interface = interface
        self.scriptDir = interface.scriptDir
        self.dataDir = interface.dataDir
        self.autocalibrationDir = interface.autocalibrationDir
        self.controller = controller or interface.controller
        self.camera = camera or interface.camera
        self.spectrometer = spectrometer or interface.spectrometer
        self.calibration_service = calibration_service
        self.simulate = simulate

        self.microscope_mode = 'ramanmode'

        self.wavelength_axis = None
        self.instrument_state = {}
        self.autosave = True

        self.config_path = os.path.join(self.scriptDir, "microscope_config.json")
        self.config = self.load_config()

        self.stage_positions_microns = {
            'x': 0, 'y': 0, 'z': 0
        }

        # self.ldr_scan_dict = self.config.get("ldr_scan_dict", {})
        # self.hard_limits = self.config.get("hard_limits", {})
        # self.action_groups = self.config.get("action_groups", {})

        # Create a flattened motor map for easy lookup of any motor ID by label
        self.motor_map = {}
        for group in self.action_groups.values():
            self.motor_map.update(group)

        # acquisition parameters
        self.acquisition_control = AcquisitionControl(self)

        # Motion control
        self.motion_control = MotionControl(self.controller, self.motor_map, self.config)

        self.command_functions = {
            # general commands
            'wai': self.where_am_i,
            'rg': self.get_spectrometer_position,
            'sl': self.go_to_laser_wavelength,
            'sm': self.go_to_monochromator_wavelength,
            'sg': self.go_to_grating_wavelength,
            'sall': self.go_to_wavelength_all,
            'st': self.go_to_spectrometer_wavelength,
            'reference': self.reference_calibration_from_wavelength,
            'referencetriax': self.reference_calibration_from_triax,
            'invertcal': self.invert_calibrations,
            'allmotors': self.get_all_motor_positions,
            'ramanmode': self.raman_mode,
            'imagemode': self.image_mode,
            'wavelengthaxis': self.generate_wavelength_axis,
            # 'calshift': self.simple_calibration_shift, #TODO: Decide if I need this
            'report': self.report_status,
            'writemotors': self.write_motor_positions,
            'rldr': self.read_ldr0,
            'autocal': self.run_calibration,
            'loadconfig': self.load_config,
            # Stage motion
            'x': self.move_x,
            'y': self.move_y,
            'z': self.move_z,
            'stagepos': self.get_stage_positions_microns,

            'stagehome': self.set_stage_home,
            # motor commands
            'laserpos': self.get_laser_motor_positions,
            'monopos': self.get_monochromator_motor_positions,
            'slsteps': self.go_to_laser_steps,
            'smsteps': self.go_to_monochromator_steps,
            'sgsteps': self.go_to_grating_steps,
            'recmot': self.record_motors,
            'calhome': self.recalibrate_home,
            'home': self.home_motor,
            'homeall': self.home_all_motors,
            'homelaser': self.home_laser,
            'homemono': self.home_monochromator,
            'homegratings': self.home_gratings,
            'testhoming': self.test_homing,
            'polin': self.go_to_polarization_in,
            'polout': self.go_to_polarization_out,
            # acquisition commands
            'acqtime': self.set_acquisition_time,
            'filename': self.set_filename,
            'ramanshift': self.set_raman_shift,
            'laserpower': self.set_laser_power,
            'runscan': self.run_scan_thread,
            'cancel': self.cancel_scan,
            'gui': self.open_acquisition_gui,

            'mshut': self.close_mono_shutter,
            'mopen': self.open_mono_shutter,
            # 'isrun': self.motion_control.wait_for_motors,
            # camera commands
            'acquire': self.acquire_one_frame,
            'run': self.start_continuous_acquisition,
            'stop': self.stop_continuous_acquisition,
            'roi': self.set_roi,
            'setbin': self.set_camera_binning,
            'caminfo': self.camera_info,
            'temp': self.get_detector_temperature,
            'refresh': self.refresh_camera,
            'camclose': self.close_camera,
            'camspec': self.set_acq_spectrum_mode,
            'camimage': self.set_acq_image_mode,
            'setgain': self.set_camera_gain,
            'closecamera': self.close_camera_connection,
            'allocate': self.allocate_camera_buffer,
            'deallocate': self.deallocate_camera_buffer,
            # laser commands
            'low': self.low_power,
            'high': self.high_power,
        }

        self.current_shift = 0
        self.current_wavenumber = None

        self.detector_safety = False

        self.acquire_mode = 'spectrum'

        self._integrity_checker()  # Validate on init


    def __str__(self):
        return "Microscope"

    def __call__(self, command: str, *args, **kwargs):
        if command not in self.command_functions:
            raise ValueError(f"Unknown command: '{command}'")
        return self.command_functions[command](*args, **kwargs)
    
    @property
    def filename(self):
        return self.acquisition_control.filename
    
    # TODO: use setter and getter for stage_pos_microns and update_stage
    @ui_callable
    def get_stage_positions_microns(self):
        '''Get the current stage positions in microns. Returns a dictionary of stage positions.'''
        stage = " ".join([f"{axis}{pos}" for axis, pos in self.stage_positions_microns.items()])
        print("Current stage positions: {}".format(stage))
        return
    
    @ui_callable
    def generate_wavelength_axis(self):
        spectrometer_wavelength = self.calculate_spectrometer_wavelength()['triax'] # TODO:change to getter
        self.wavelength_axis = self.calibration_service.generate_wavelength_axis(spectrometer_wavelength)

    
    @ui_callable
    def open_acquisition_gui(self):
        root = tk.Tk()
        params = self.acquisition_control
        app = AcquisitionGUI(root, params)
        root.mainloop()


    @ui_callable
    def run_scan_thread(self):
        '''Executes a scan based on the heirarchical acquisition scan built by the AcquisitionControl class.'''
        self.cancel_event = threading.Event()

        self.scan_thread = threading.Thread(target=self.acquisition_control.acquire_scan, args=(self, self.cancel_event))
        self.scan_thread.start()
        return self.scan_thread

    
    def save_instrument_state(self):
        '''Saves the state of the microscope and motors to a config, in case of reboot or crash. Uses motor labels as keys.'''
        if self.autosave == False:
            return
        
        self.controller.report = False
        motor_positions = self.get_all_motor_positions(report=False)
        self.controller.report = True

        instrument_state = {
            "motor_dict": motor_positions,
            "stage_positions": self.stage_positions_microns
            }
        
        save_state_path = os.path.join(self.scriptDir, 'instrument_state.json')
        
        with open(save_state_path, 'w') as f:
            json.dump(instrument_state, f, indent=2)

    def load_instrument_state(self):
        '''Loads the state of the microscope and motors from a config, in case of reboot or crash.'''
        save_state_path = os.path.join(self.scriptDir, 'instrument_state.json')
        if os.path.exists(save_state_path):
            with open(save_state_path, 'r') as f:
                instrument_state = json.load(f)
            motor_positions = instrument_state.get('motor_dict', {})
            stage_positions = instrument_state.get('stage_positions', {})
            print('Instrument state loaded from file')
            self.write_motor_positions(motor_dict=motor_positions)
            self.stage_positions_microns = stage_positions
            
            self.get_all_current_wavelengths()
            self.detect_microscope_mode()
        else:
            print('Instrument state file not found. Saving current state.')
            self.save_instrument_state()
            # raise FileNotFoundError(f"Instrument state file not found at {save_state_path}")
    
    def load_config_file(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r') as f:
                config = json.load(f)
            print('Config loaded from file')
            return config
        else:
            raise FileNotFoundError(f"Config file not found at {self.config_path}")
        
    def detect_microscope_mode(self):
        '''Determines Raman or Imagemode depending on the current position of the mode motor.'''

        mode_steps = self.get_stage_steps()['mode']
        if -160_000 < mode_steps < -10_000:
            self.microscope_mode = 'ramanmode'
        elif -10_000 < mode_steps < 10_000:
            self.microscope_mode = 'imagemode'

        else:
            raise ValueError(f"Unknown mode motor position: {mode_steps}. Please check the motor positions.")

        print("Microscope mode detected: {}".format(self.microscope_mode))
        return self.microscope_mode
        
    
    def get_stage_steps(self):
        '''Get the current position of the mode motor. Returns the position in steps.'''
        steps_dict = self.motion_control.get_motor_positions(self.action_groups['stage_movement'])
        return steps_dict

        
    @ui_callable
    def load_config(self):
        self.config = self.load_config_file()
        self.ldr_scan_dict = self.config.get("ldr_scan_dict", {})
        self.hard_limits = self.config.get("hard_limits", {})
        self.action_groups = self.config.get("action_groups", {})
        self.mode_steps = self.config.get("mode_steps", {}).get("mode", 0)

        return self.config

    def write_config(self):
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=2)

    #? Motor and Homing

    @ui_callable
    def raman_mode(self):
        '''Set the acquisition mode to Raman mode.'''
        if self.microscope_mode == 'ramanmode':
            # print("Microscope already in Raman mode")
            response = input("Microscope already in Raman mode. Do you want to continue? (y/n)")
            if response.lower() != 'y':
                print("aborting mode change, staying in raman mode")
                return
            
        self.motion_control.move_motors({'mode':-self.mode_steps})
        self.microscope_mode = 'ramanmode'
        print("Microscope set to Raman mode")
    
    @ui_callable
    def image_mode(self):
        '''Set the acquisition mode to image mode.'''
        if self.microscope_mode == 'imagemode':
            # print("Microscope already in Image mode")
            response = input("Microscope already in Image mode. Do you want to continue? (y/n)")
            if response.lower() != 'y':
                print("aborting mode change, staying in image mode")
                return

        self.motion_control.move_motors({'mode':self.mode_steps})
        self.microscope_mode = 'imagemode'
        print("Microscope set to Image mode")


    @ui_callable
    def test_homing(self, label, series_name, cycles=20):
        '''Test the reproducibility of the motor homing by moving to home and back in a cycle, n times.'''
        if label not in self.motor_map:
            raise ValueError(f"Unknown action group: {label}")
        
        home_positions = {series_name: []}
        for index in range(cycles):
            response = self.home_motor(label)
            print(f"Homing motor {label}: {response}")
            home_positions[series_name].append(response)
            time.sleep(1)
        
        # Save to config
        if os.path.exists(os.path.join(self.scriptDir, 'motor_tests.json')):
            with open(os.path.join(self.scriptDir, 'motor_tests.json'), 'r') as f:
                current_data = json.load(f)
            home_positions.update(current_data)

        with open(os.path.join(self.scriptDir, 'motor_tests.json'), 'w') as f:
            json.dump(home_positions, f, indent=2)

    @ui_callable
    def recalibrate_home(self, label):
        if label not in self.motor_map:
            raise ValueError(f"Unknown action group: {label}")

        motor_id = self.motor_map[label]
        # Send homing command

        response = self.controller.send_command(f"h{motor_id}")
        response = response[0]
        print(f"Homing response: {response}")
        if "at position" in response:
            position = int(response.split(' ')[-1].strip())
        else:
            raise RuntimeError(f"Unexpected response: {response}")

        # Save to config
        self.config.setdefault("home_positions", {})
        self.config["home_positions"][motor_id] = position
        print(f"Saved home position {position} for {motor_id}")

        self.write_config()
        time.sleep(0.01)
        self.motion_control.move_motors({label: -position})  # Move to home position


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
    def home_laser(self, move_to_calibrated_position=True):
        """
        Home the laser motors.
        
        Returns:
        str: The response from the controller after homing the laser motors.
        """
        for motor_label in self.action_groups['laser_wavelength'].keys():
            response = self.home_motor(motor_label)
            print(f"Homing motor {motor_label}: {response}")
        
        # if move_to_calibrated_position:
        #     self.go_to_laser_wavelength(800)
        return response
    
    @ui_callable
    def home_monochromator(self, move_to_calibrated_position=True):
        """
        Home the monochromator motors.
        
        Returns:
        str: The response from the controller after homing the monochromator motors.
        """
        for motor_label in self.action_groups['monochromator_wavelength'].keys():
            response = self.motion_control.home_motor(motor_label)
            print(f"Homing motor {motor_label}: {response}")

        # if move_to_calibrated_position:
        #     self.go_to_laser_wavelength(800)
        return response
    
    @ui_callable
    def home_gratings(self, move_to_calibrated_position=True):
        """
        Home the grating motors.
        
        Returns:
        str: The response from the controller after homing the grating motors.
        """
        for motor_label in self.action_groups['grating_wavelength'].keys():
            response = self.motion_control.home_motor(motor_label)
            print(f"Homing motor {motor_label}: {response}")

        # if move_to_calibrated_position:
        #     self.go_to_laser_wavelength(800)
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


    # @ui_callable
    # def connect_to_triax(self):
    #     '''Connects to the spectrometer after already running.'''
    #     self.interface.connect_to_triax()
    #     print('Connected to TRIAX spectrometer')
    #     self.generate_wavelength_axis()

    # @ui_callable
    # def connect_to_camera(self):
    #     '''Connects to the camera after already running.'''
    #     self.interface.connect_to_camera()

    @ui_callable
    def write_motor_positions(self, motor_positions='', motor_dict=None):
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
        grating_motor_positions = self.get_grating_motor_positions()
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


        data = {'laser_positions':laser_motor_positions, 'grating_positions':grating_motor_positions, 'triax_positions':triax_position,'wavelength':float(extra)}

        current_data[f'{len(current_data)}'] = data
        # dump the data to a json file
        with open(os.path.join(self.interface.calibrationDir, 'motor_recordings', 'motor_recordings.json'), 'w') as f:
            json.dump(current_data, f)
            # f.write('\n')
            
        # with open(os.path.join(self.interface.calibrationDir, 'motor_recordings', 'motor_recordings.txt'), 'a') as f:
        #     f.write('{}:{}:{}:{}\n'.format(laser_motor_positions, monochromator_motor_positions, triax_position, extra))
        # print("Exporting: {}:{}:{}:{}".format(laser_motor_positions, monochromator_motor_positions, triax_position, extra))
        # return f"{laser_motor_positions}:{monochromator_motor_positions}:{triax_position}:{extra}"


    def initialise(self):
        '''Initialises the microscope by querying all connections to instruments and setting up the necessary parameters.'''
        # Use the injected calibration service
        # Update calibrations with auto-calibration data if available
        # self.calibration_service.ammend_calibrations()
        # finally, update with the monochromator calibrations
        # self.calibration_service.update_monochromator_calibrations()

        # TODO: Remove unnecessary calibrations later
        # One calibration to rule them all
        self.calibration_service.generate_master_calibration(microsteps=32)

        # load the previous known state of the instrument from file
        self.load_instrument_state()

        self.calculate_laser_wavelength()
        self.calculate_grating_wavelength()
        self.calculate_monochromator_wavelength()
        self.calculate_spectrometer_wavelength()
        self.report_status(initialise=True)
        
        return 'Microscope initialised'

    @ui_callable
    def report_status(self, initialise=False):
        '''Prints the current status of the system. If initialise is True, the function will recalculate all parameters. If False, it will use the current values obtained from the initialisation.'''

        if initialise is False:
            # recalculate all parameters
            all_motors = self.get_all_motor_positions()
            self.microscope_mode = self.calibration_service.identify_microscope_mode({all_motors})

            self.laser_steps = self.get_laser_motor_positions()
            self.grating_steps = self.get_grating_motor_positions()
            self.monochromator_steps = self.get_monochromator_motor_positions()
            self.monochromator_wavelengths = self.calculate_monochromator_wavelength()

            self.get_spectrometer_position()


        report = {
            'laser': self.calculate_laser_wavelength(self.laser_steps),
            'grating': self.calculate_grating_wavelength(self.grating_steps),
            'TRIAX lambda': self.calculate_spectrometer_wavelength(self.spectrometer_position),
            'laser motor positions': self.laser_steps,
            'grating motor positions': self.grating_steps,
            'laser wavenumber': self.current_laser_wavenumber,
            'monochromator wavenumber': self.current_monochromator_wavenumber,
            # 'Raman wavelength': self.current_raman_wavelength,
            'Raman shift': self.current_shift,
            # 'pinhole': self.pinhole
            'Microscope mode': self.microscope_mode,
        }
        


        print('-'*20)
        for key, value in report.items():
            print('{}: {}'.format(key, value))
        print('-'*20)

    #? Stage control commands




    @ui_callable
    def cancel_scan(self):
        '''Cancels the current scan.'''
        if hasattr(self, 'scan_thread'):
            self.cancel_event.set()
            self.scan_thread.join()
            print("Scan cancelled")
        else:
            print("No scan to cancel")
 


    @ui_callable
    def go_to_polarization_in(self, angle):
        '''Moves the polarizer to the specified angle.'''
        print("Not implemented yet")
        return
        self.motion_control.move_motors({'p_in': angle})
        print('Polarizer moved to {} degrees'.format(angle))

    @ui_callable
    def go_to_polarization_out(self, angle):
        '''Moves the polarizer to the specified angle.'''
        print("Not implemented yet")
        return
        self.motion_control.move_motors({'p_out': angle})
        print('Polarizer moved to {} degrees'.format(angle))

    def _parse_stage_motion_command(self, command):
        """
        Accepts either:
        - A string such as 'x100 y200 z200', 'y21 z34', or 'y2 x5 z2'
        - A tuple of 3 floats
        Returns a dictionary mapping keys "x", "y", "z" to their respective float values.
        For string inputs, only keys present in the string are added.
        For tuple inputs, assumes order is (X, Y, Z).
        """
        if isinstance(command, dict):
            return command  # If command is already a dictionary, return it as is.
        # If command is a string
        if isinstance(command, str):
            result = {}
            print(" Need to inplement calibration first. Retrurnign")
            return
            # Split string by whitespace and iterate through each component
            for part in command.split():
                # The first character represents the key, which we capitalize
                # and the rest is the numeric part.
                if len(part) < 2:
                    continue  # skip any malformed parts
                key = part[0].upper()
                try:
                    value = float(part[1:])
                    # Only add key if it is one of the expected options.
                    if key in ['X', 'Y', 'Z']:
                        result[key] = value
                except ValueError:
                    raise ValueError(f"Invalid numeric value in part: {part}")
            return result

        # If command is a tuple or list of length 3
        elif isinstance(command, (tuple, list)):
            if len(command) != 3:
                raise ValueError("Tuple input must have exactly three numeric values.")
            # Validate that each element is a float (or convertible to float)
            try:
                x, y, z = float(command[0]), float(command[1]), float(command[2])
            except ValueError:
                raise ValueError("All tuple elements must be numeric values.")
            return {"x": x, "y": y, "z": z}

        else:
            raise TypeError("Input must be either a string or a tuple/list of three floats.")
        
    def update_stage_positions(self, motion_dict):
        '''Updates the stage positions dictionary with the new values from the motion command in MICRONS. Accepts relative motion commands.'''
        for key, value in motion_dict.items():
            if key in self.stage_positions_microns:
                self.stage_positions_microns[key] += value
            else:
                raise ValueError(f"Invalid stage position: {key}")
            
        self.acquisition_control.update_stage_positions()
        
    # def move_stage(self, motor_steps):
    #     '''Moves the microcsope sample stage in steps in the X, Y and Z directions'''

    #     motion_dict = self._parse_stage_motion_command(motor_steps)
    #     self.motion_control.move_motors(motion_dict)
    #     if "x" in motion_dict:
    #         # self.move_x(motion_dict['X'])
    #         x_steps = self.calibration_service.microns_to_steps(motion_dict['X'])
    #     if "y" in motion_dict:
    #         self.move_y(motion_dict['Y'])
    #     if "z" in motion_dict:
    #         self.move_z(motion_dict['Z'])
    #     self.update_stage_positions(motion_dict)

    #     print('Stage moved to {}'.format(self.acquisition_control.current_stage_coordinates))
    
    @ui_callable
    def move_x(self, travel_distance):
        '''Moves the microcsope sample stage in the X direction, by travel distance in micrometers.'''
        try:
            travel_distance = float(travel_distance)
        except ValueError:
            print("Invalid travel distance. Must be a number.")
            return
        
        motor_dict = self.calibration_service.microns_to_steps({"x": travel_distance})
        self.motion_control.move_motors(motor_dict)
        self.update_stage_positions({"x": travel_distance})
        print('x stage moved by {} micrometers'.format(travel_distance))
    
    @ui_callable
    def move_y(self, travel_distance):
        '''Moves the microcsope sample stage in the Y direction, by travel distance in micrometers.'''
        try:
            travel_distance = float(travel_distance)
        except ValueError:
            print("Invalid travel distance. Must be a number.")
            return
        
        motor_dict = self.calibration_service.microns_to_steps({"y": travel_distance})
        self.motion_control.move_motors(motor_dict)
        self.update_stage_positions({"y": travel_distance})
        print('y stage moved by {} micrometers'.format(travel_distance))

    @ui_callable
    def move_z(self, travel_distance):
        '''Moves the microcsope sample stage in the Z direction, by travel distance in micrometers.'''
        try:
            travel_distance = float(travel_distance)
        except ValueError:
            print("Invalid travel distance. Must be a number.")
            return
        
        motor_dict = self.calibration_service.microns_to_steps({"z": travel_distance})
        self.motion_control.move_motors(motor_dict)
        self.update_stage_positions({"z": travel_distance})
        print('z stage moved by {} micrometers'.format(travel_distance))

    @ui_callable
    def set_stage_home(self):
        '''Sets the current stage position as the home position.'''
        self.motion_control.set_stage_home()
        for key in self.stage_positions_microns.keys():
            self.stage_positions_microns[key] = 0
        print('Stage home ({}) set to current position'.format(self.acquisition_control.current_stage_coordinates))

    def enter_focus_mode(self):
        '''Enters the mode for incrementally adjusting the microscope focus at the sample.'''
        print("Entering focus mode.\nType focus steps in microns.\nType 'exit' to exit focus mode.")
        while True:
            command = input()
            if command == 'exit':
                return
            try:
                command = float(command)
                self.move_z(command)
            except ValueError:
                print("Invalid command. Type 'exit' to exit focus mode.")
                continue


    #? camera commands
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


        calibrationDict = {'data_type': 'autocal'}

        if isinstance(wavelength_range, str):
            vals = wavelength_range.split(',')
            wavelength_range = (float(vals[0]), float(vals[1]))

        resolution = float(resolution)

        initial_grating = copy(self.grating_steps)
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
            self.go_to_grating_wavelength(wl)
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
        self.go_to_grating_steps(initial_grating)

    @ui_callable
    def low_power(self):
        '''sets the laser power to low to save on the diode lifetimes'''
        self.set_laser_power(0.00)

        print("Laser power set to low")
    
    @ui_callable
    def high_power(self, power=4.5):
        '''Sets the laser power to 4.5 W or otherwise provided in the kwarg for standard ops.'''
        self.set_laser_power(power)
        print("Laser power set to {power}".format(power))

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
            print("backlash correction")
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
        # Check if the motor is valid
        if motor not in self.motion_control.motor_map:
            print("Invalid motor. Must be one of:", list(self.motion_control.motor_map.keys()))

        if motor not in self.ldr_scan_dict.keys():
            print("Invalid motor. Must be one of:", list(self.ldr_scan_dict.keys()))
            return
            
        # Get scan parameters
        if search_length is None:
            search_length = self.ldr_scan_dict[motor]['range']
        if resolution is None:
            resolution = self.ldr_scan_dict[motor]['resolution']

        # Get the current position of the specified motor
        motor_dict = self.motion_control.generate_motor_dict([motor])
        motor_positions = self.motion_control.get_motor_positions(motor_dict)
         
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
            self.motion_control.move_motors(move_command, backlash = False)

            ldr_value = 11000 - int(self.read_ldr0())
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
        self.acquisition_control.general_parameters['acquisition_time'] = value
        self.camera.set_acqtime(value)

    @ui_callable
    def set_filename(self, filename):
        self.acquisition_control.general_parameters['filename'] = filename
        print("Filename set to: ", filename)

    @ui_callable
    def set_laser_power(self, value):
        self.interface.laser.set_power(value)
        self.acquisition_control.general_parameters['laser_power'] = value

    @ui_callable
    def set_raman_shift(self, value):
        self.current_shift = value
        self.go_to_wavenumber(value)
        self.acquisition_control.general_parameters['raman_shift'] = value

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
    def acquire_one_frame(self, filename=None, scan_index=0, export_raw=False):
        if filename is None:
            filename = self.acquisition_control.general_parameters['filename']

        image_data = self.camera.safe_acquisition(export=export_raw)


        self.acquisition_control.save_spectrum(image_data, wavelength_axis=self.wavelength_axis, save_dir='data', filename=filename, scan_index=scan_index)
        self.acquisition_control.save_spectrum_transient(image_data, wavelength_axis=self.wavelength_axis)

        return image_data
    
    # @ui_callable
    
    # def save_acquisition(self, image_data, filename=None, save_folder=None, scan_index=0):
        
    #     if self.wavelength_axis is None:
    #         self.wavelength_axis = np.arange(image_data.shape[1]) 

    #     if not save_folder:
    #         save_folder = self.dataDir
    #     out_path = os.path.join(self.scriptDir, save_folder, self.filename, f"{self.filename}_{scan_index:06}.npz")

    #     print(out_path)
        
    #     if not os.path.exists(os.path.dirname(out_path)):
    #         os.makedirs(os.path.dirname(out_path))

    #     np.savez_compressed(out_path,
    #                         image=image_data,
    #                         wavelength=self.wavelength_axis,
    #                         metadata=json.dumps(self.acquisition_control.metadata))
    @ui_callable
    def allocate_camera_buffer(self):
        '''Allocates the camera buffer for the acquisition.'''
        self.camera.allocate_buffer_and_start()
    
    @ui_callable
    def deallocate_camera_buffer(self):
        '''Deallocates the camera buffer and stops the acquisition.'''
        self.camera.deallocate_buffer_and_stop()


    def prepare_dataset_acquisition(self):
        '''Prepares the dataset acquisition by setting the parameters.'''
        self.acquisition_control.prepare_acquisition()
    
    def acquire_dataset(self):
        '''Prepares and executes a multidimensional dataset acquisition.'''
    
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
    def get_detector_temperature(self):
        '''Returns the camera temperature.'''
        return round(self.camera.check_camera_temperature(), 2)

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
        self.go_to_grating_wavelength(wavelength) # move all grating motors
        
        # Then handle the monochromator
        if shift is True:
            # Maintain the current Raman shift by calculating new monochromator position
            self.go_to_wavenumber(self.current_shift)

        # Finally, move the spectrometer
        self.go_to_spectrometer_wavelength(wavelength)
        
        print("Laser set at {} nm".format(self.laser_wavelengths['l1']))
        print(f"All components set to wavelength: {wavelength} nm")
        return True
    


    @ui_callable
    def go_to_spectrometer_wavelength(self, wavelength):
        '''Moves the spectrometer to the specified wavelength.'''
        self.interface.spectrometer.go_to_wavelength(wavelength)
        self.generate_wavelength_axis()

    @ui_callable
    def reference_calibration_from_triax(self, steps=None, shift=True):
        '''Used to reference the current motor position to the laser wavelength, as defined by the current calibration. Measure a spectrum on the TRIAX and enter the stepper motor position and pixel count of the peak wavelength here. In the future, this will be automated with a peak detection algorithm.'''
        # Instructions: Ensure that the entire system is well aligned, and that the stepper motors are in the correct positions relative to one another for passing the laser wavelength to the spectrograph.
        # Centre the laser peak in pixel 50 of the CCD. Enter the stepper motor position here.
        # correct for current Raman shift (usually zero, but might be different if performing Raman measurements)
            
        if steps is None:
            steps = self.get_spectrometer_position()
        true_wavelength_laser = self.calibration_service.triax_to_wl(float(steps))
        print('True wavelength: {}. Shifting motor positions to true wavelength'.format(true_wavelength_laser))
        
        if shift is True:
            grating_wavelength = (10_000_000/true_wavelength_laser) - self.current_shift
            # grating_wavelength = self.current_laser_wavenumber - self.current_shift
            true_wavelength_grating = 10_000_000/grating_wavelength
        else:
            true_wavelength_grating = true_wavelength_laser


        # Calculate target positions for laser and monochromator motors
        laser_steps = self.calibration_service.wl_to_steps(true_wavelength_laser, self.action_groups['laser_wavelength'])
        mono_steps = self.calibration_service.wl_to_steps(true_wavelength_grating, self.action_groups['monochromator_wavelength'])
        
        

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
        target_laser_steps = self.calibration_service.wl_to_steps(true_wavelength_laser, self.action_groups['laser_wavelength'])
        target_mono_steps = self.calibration_service.wl_to_steps(true_wavelength_grating, self.action_groups['grating_wavelength'])


        # write current position to motors
        motor_dict = {}
        motor_dict.update(target_laser_steps)
        motor_dict.update(target_mono_steps)
        self.write_motor_positions(motor_dict=motor_dict)

        print('Motors successfully shifted')

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

    #     current_laser_pos[0] = round(self.calibration_service.wl_to_l1(current_laser_wavelength[0]))
    #     current_laser_pos[1] = round(self.calibration_service.wl_to_l2(current_laser_wavelength[0]))
    #     current_grating_pos[0] = round(self.calibration_service.wl_to_g1(current_monochromator_wavelength[0]))
    #     current_grating_pos[1] = round(self.calibration_service.wl_to_g2(current_monochromator_wavelength[0]))

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
        target_steps = self.calibration_service.wl_to_steps(target_wavelength, self.action_groups['laser_wavelength'])
        
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
    def invert_calibrations(self):
        '''Inverts the calibration for the laser and monochromator motors.'''
        self.calibration_service.invert_calibrations()
        print('Calibration inverted')
    
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
        target_positions = self.calibration_service.wl_to_steps(wavelength, self.action_groups['laser_wavelength'])
        
        # Move to target positions
        self.go_to_laser_steps(target_positions)
              
        # Safety checks and reopen shutter
        # self.laser_safety_check()
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
        target_positions = self.calibration_service.wl_to_steps(wavelength, self.action_groups['monochromator_wavelength'])
        
        # Move to target positions
        self.go_to_monochromator_steps(target_positions)
        # self.laser_safety_check()
        self.open_mono_shutter()
        
        # Report primary wavelength
        print("New monochromator wavelength: ", next(iter(self.monochromator_wavelengths.values())))
        
        return True
    
    @ui_callable
    def go_to_grating_wavelength(self, wavelength):
        """
        Move all gratings (first and second tunable filters) to the specified wavelength.
        
        Parameters:
        wavelength (float): Target wavelength in nm
        
        Returns:
        bool: True if successful, False otherwise
        """
        # Validate the wavelength is within allowed range
        wavelength = self.check_grating_wavelength(wavelength)
        if wavelength is False:
            return False
        
        # Safety: close shutter during movement
        self.close_mono_shutter()
        
        # Get target positions from calibration service
        target_positions = self.calibration_service.wl_to_steps(wavelength, self.action_groups['grating_wavelength'])
        
        # Move to target positions
        self.go_to_grating_steps(target_positions)
        # self.laser_safety_check()
        self.open_mono_shutter()
        
        # Report primary wavelength
        print("New grating wavelength: ", next(iter(self.grating_wavelengths.values())))
        
        return True

    def check_grating_wavelength(self, wavelength):
        '''Checks the validity of the entered value for grating wavelength.'''
        wavelength = string_to_float(wavelength)

        if not self.check_hard_limits(wavelength, self.hard_limits['grating_wavelength']):
            print('Wavelength out of range. Pick a wavelength between {} and {} nm'.format(*self.hard_limits['grating_wavelength']))
            return False
        
        return wavelength
    
    @ui_callable
    def go_to_grating_steps(self, target_positions):
        '''
        Moves the grating motors to the specified positions in steps.
        
        Parameters:
        target_positions (dict): Dictionary of motor names to target positions {'g1': 1000, 'g2': 2000}
        '''
        # Get current positions
        current_positions = self.get_grating_motor_positions()
        
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
            
            # Update grating wavelength
            self.calculate_grating_wavelength()
            print("Moved to grating steps: ", self.grating_steps)

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
        target_steps = self.calibration_service.wl_to_steps(target_wavelength, self.action_groups['monochromator_wavelength'])
        
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
        self.monochromator_wavelengths = self.calibration_service.steps_to_wl(current_pos)
      
        return self.monochromator_wavelengths

    def calculate_grating_wavelength(self, current_pos=None):
        """
        Calculate all grating wavelengths from motor positions.
        
        Parameters:
        current_pos (dict, optional): Current motor positions. If None, gets current positions.
        
        Returns:
        dict: Dictionary of motor names to calculated wavelengths {'g1': 800.0, 'g2': 800.5}
        """
        if current_pos is None:
            current_pos = self.get_grating_motor_positions()

        self.grating_steps = current_pos
        
        # Calculate wavelengths for each motor using calibration functions
        self.grating_wavelengths = self.calibration_service.steps_to_wl(current_pos)
        
        return self.grating_wavelengths

    def get_grating_motor_positions(self):
        '''Get the current positions of all grating motors.'''
        return self.motion_control.get_motor_positions(self.action_groups['grating_wavelength'])

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
        self.get_all_current_wavelengths()
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
    
    def get_grating_wavelength(self):
        '''Get all the current grating wavelengths in nm.'''
        return self.calculate_grating_wavelength()
    
    @ui_callable
    def get_all_motor_positions(self, report=False):
        '''Get the current positions of all motors in the motor_map'''
        excluded_motors = ['triax']
        current_positions = self.motion_control.get_motor_positions({key: value for key, value in self.motor_map.items() if key not in excluded_motors}, report=report)
        return current_positions
    
    def get_all_current_wavelengths(self):
        '''Get the current positions of all motors and calculate the corresponding wavelengths.'''
        laser_positions = self.calculate_laser_wavelength()
        grating_positions = self.calculate_grating_wavelength()
        monochromator_positions = self.calculate_monochromator_wavelength()
        spectrometer_position = self.calculate_spectrometer_wavelength()
        return (laser_positions, grating_positions, monochromator_positions, spectrometer_position)
    
    def calculate_spectrometer_wavelength(self, steps=None):
        '''Uses calibration to calculate wavelength from reported position. For spectrometers that report wavelength, this is a pass-through.'''
        if steps is None:
            self.spectrometer_position = self.interface.spectrometer.get_spectrometer_position()
        else:
            self.spectrometer_position = steps

        self.spectrometer_wavelength = self.calibration_service.steps_to_wl({'triax':self.spectrometer_position}) # TODO: rename triax_to_wl to spectrometer_steps_to_wl - requires change to calibration files and will be breaking until otherwise completed
        return self.spectrometer_wavelength
    
    def report_all_current_positions(self):
        '''Formats and prints the current positions of the microscope.'''
        stage_steps = self.get_stage_steps()

        print("---Steps---")
        for motor, position in self.laser_steps.items():
            print(f'{motor}: {position} steps')
        for motor, position in self.grating_steps.items():
            print(f'{motor}: {position} steps')

        print('---Wavelengths---')
        for motor, wavelength in self.laser_wavelengths.items():
            if wavelength is None:
                print(f'{motor}: None')
                continue
            print(f'{motor}: {round(wavelength, 2)} nm')
        for motor, wavelength in self.grating_wavelengths.items():
            if wavelength is None:
                print(f'{motor}: None')
                continue
            print(f'{motor}: {round(wavelength, 2)} nm')

        print('---Spectrometer---')
        print(f'Spectrometer position: {self.spectrometer_position} steps')
        print(f'Spectrometer wavelength: {self.spectrometer_wavelength} nm')

        # stage
        print('---Stage---')
        
        for motor, position in stage_steps.items():
            print(f'{motor}: {position} steps')
        for motor, position in self.stage_positions_microns.items():
            print(f'{motor}: {position} microns')

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
        self.laser_wavelengths = self.calibration_service.steps_to_wl(current_pos)

        return self.laser_wavelengths
    
    def calculate_polarization_angles(self):
        pass

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
        return True

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
    
    def connect(self):
        print("Connecting to the camera.")
        self.serial = self.connect_to_camera()

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

    def connect(self):
        print("Connecting to Tucsen...")
        self.TUCAMINIT = TUCAM_INIT(0, self.scriptDir.encode('utf-8'))
        self.TUCAMOPEN = TUCAM_OPEN(0, 0)
        self.handle = self.TUCAMOPEN.hIdxTUCam
        TUCAM_Api_Init(pointer(self.TUCAMINIT), 5000)
        print("Connected to Tucsen.")
        
        # self.open_camera(0)
        # self.SetROI(set_ROI=self.set_ROI)

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
        if not 'transient_data' in filename:
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
        self.simulate = simulate or interface.simulate
        self.calibration_service = interface.calibration_service

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
            'specgrat1': self.default_grating,
            'specgrat2': self.other_grating,
        }

        self.spectrometer_position = 380000

        # 108659 = 750 nm

        self.message_map = {
            'initialise': 'A',
            'specgrat1': 'a0',
            'specgrat2': 'b0',
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
    
    def initialise(self):
        '''Connect and establish primary attributes.'''
        self.connect()
        self.get_spectrometer_position()
        # self.generate_wavelength_axis()
        self.interface.microscope.generate_wavelength_axis() # TODO: move from microscope to spectrometer. Use @property to generate wavelength axis on the fly
        return self.spectrometer_position

    @ui_callable
    def initialise_spectrometer(self):
        '''Initialise the spectrometer.'''
        response = self.send_command('initialise')

    @ui_callable
    def default_grating(self):
        '''Set the default gratin;'g for the spectrometer.'''
        response = self.send_command('specgrat1')
        # print(response)
        return response

    @ui_callable
    def other_grating(self):
        '''Set the other grating for the spectrometer.'''

        response = self.send_command('specgrat2')
        # print(response)
        return response
    
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
    def get_spectrometer_position(self):
        '''Get the current position of the spectrometer in motor steps.'''
        self.spectrometer_position = self.get_triax_steps()
        return self.spectrometer_position
    
    @ui_callable
    def go_to_position(self, position):
        print("Going to the position: {}".format(position))
        command = self.message_map['move_grating'] + str(position)
        response = self._send_command_to_spectrometer(command)
        return response

    def connect(self):
        # Open a connection to the instrument
        print("Connecting to TRIAX spectrometer...")
        rm = pyvisa.ResourceManager()
        rm.list_resources()
        self.spectrometer = rm.open_resource('GPIB0::1::INSTR')  # Replace with the actual VISA address of your instrument

        self.spectrometer.write('WHERE AM I')
        time.sleep(0.0001)
        self.state = self.spectrometer.read()
        print(self.state)

        print('Connected to TRIAX spectrometer.')

        return self.spectrometer, self.state

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
    
    def send_command(self, command):
        '''Send a command to the spectrometer.'''
        coms = self._command_parser(command)
        response = self._send_command_to_spectrometer(coms)
        return response
    
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


# class Laser(Instrument):
#     def __init__(self, interface, controller=None, calibration_service=None, simulate=False):
#         super().__init__()
#         self.interface = interface
#         self.controller = controller or interface.laser_controller
#         self.calibration_service = calibration_service or interface.calibration_service
#         self.simulate = simulate
#         self.command_functions = {
#             'set_power': self.set_power,
#             'get_power': self.get_power,
#             'turn_on': self.turn_on,
#             'turn_off': self.turn_off
#         }

#         self._integrity_checker()
        
#     def initialise(self):
#         """Initialize the laser"""
#         if hasattr(self.controller, 'initialise'):
#             self.controller.initialise()
#         print("Laser initialized")
#         return "Laser initialized"
        
#     @ui_callable
#     def turn_on(self):
#         """Turn the laser on"""
#         if hasattr(self.controller, 'turn_on'):
#             return self.controller.turn_on()
#         print("Turning laser on")
#         return "Laser turned on"
        
#     @ui_callable
#     def turn_off(self):
#         """Turn the laser off"""
#         if hasattr(self.controller, 'turn_off'):
#             return self.controller.turn_off()
#         print("Turning laser off")
#         return "Laser turned off"

#     def __str__(self):
#         return "Laser"

#     def __call__(self, command: str, *args, **kwargs):
#         if command not in self.command_functions:
#             raise ValueError(f"Unknown laser command: '{command}'")
#         return self.command_functions[command](*args, **kwargs)
    
#     def initialise(self):
#         self.connect()
    
#     def connect(self):
#         print("Connecting to the laser.")
#         pass

#     @ui_callable
#     def set_power(self):
#         '''Set the laser power.'''
#         print("Setting the laser power.")

#     @ui_callable
#     def get_power(self):
#         '''Get the laser power.'''
#         print("Getting the laser power.")

# class StageControl(Instrument):
#     '''Handles functions and generating of commands for the controller.'''
#     def __init__(self, interface, controller=None, simulate=False):
#         super().__init__()
#         self.interface = interface
#         self.controller = controller or interface.controller
#         self.simulate = simulate
#         self.command_functions = {
#             'movestage': self.move_stage,
#             'homestage': self.home_stage
#         }

#         self._integrity_checker()
        
#     def initialise(self):
#         """Initialize the stage controller"""
#         print("Stage controller initialized")
#         return "Stage controller initialized"

#     def __str__(self):
#         return "Stage Control"

#     def __call__(self, command: str, *args, **kwargs):
#         if command not in self.command_functions:
#             raise ValueError(f"Unknown stage command: '{command}'")
#         return self.command_functions[command](*args, **kwargs)
    
#     @ui_callable
#     def move_stage(self, motor_positions:str):
#         '''Moves the stage to the specified position.'''
#         # print("Moving the stage to the specified position.")
#         motor_dict = {}

#         # example = 'x300 y200'
#         motor_dict = {}
#         for motor in motor_positions.split(' '):
#             try:
#                 name = motor[0]
#                 position = int(motor[1:])
#             except Exception as e:
#                 print(f"Error parsing motor position: {e}")
#                 continue
#             if name not in self.motor_map:
#                 print(f"Unknown motor name: {name}")
#                 continue
#             if name in motor_dict:
#                 print(f"Duplicate motor name: {name}")
#                 continue
            
#             if position != 0:
#                 motor_dict[name] = position
            
#         motor_id_dict = {self.motor_map[motor]: steps for motor, steps in motor_dict.items() if motor in self.motor_map}

#         self.controller.move_stage(motor_id_dict)
            
    
#     @ui_callable
#     def move_x(self, distance):
#         '''Moves the stage in the x direction by the specified distance in micro meters.'''
#         print("Moving stage X {} microns".format(distance))
        
        

#     @ui_callable
#     def move_y(self, distance):
#         '''Moves the stage in the y direction by the specified distance in micro meters.'''
#         pass

#     @ui_callable
#     def move_stage(self, motor_dict):
#         '''Sends the move command to the motion controller.'''

#         print("Moving the stage.")

#     @ui_callable
#     def home_stage(self):
#         print("Homing the stage.")



# class MillenniaLaser(Instrument):
#     def __init__(self, interface, port='COM13', baudrate=9600, simulate=False):
#         super().__init__()
#         self.interface = interface
#         self.port = port
#         self.baudrate = baudrate
#         self.simulate = simulate
#         self.ser = None
#         self.status = "OFF"

#         self.command_functions = {
#             'laseron': self.turn_on,
#             'laseroff': self.turn_off,
#             'setpower': self.set_power,
#             'getpower': self.get_power,
#             'warmup': self.get_warmup_status,
#             'openshutter': self.open_shutter,
#             'closeshutter': self.close_shutter,
#             'identify': self.identify,
#             'getdiode': self.get_diode_status,
#             'enable': self.enable_laser,
#             'status': self.get_status,
#             'shutterstatus': self.get_shutter_status,
#             'getpowerset' : self.get_power_setpoint,
#             'cycleshutter': self.cycle_shutter,
#             'diagnosis': self.laser_diagnosis,
#             'connect': self.connect,
#         }

#     def initialise(self):
#         '''Initialise the laser and establish a connection.'''
#         if self.simulate:
#             print("Simulated connection.")
#             return
#         self.connect()
#         setpoint = self.get_power_setpoint()
#         current_power = self.get_power()
#         warmup = self.get_warmup_status()

#         print("Laser initialised.")
#         print("Current power setpoint: {}W".format(setpoint))
#         print("Current power: {}W".format(current_power))
#         print("Warmup status: {}%".format(warmup))

#         if warmup == 0:
#             self.enable_laser()

#         return setpoint, current_power, warmup

#     @ui_callable
#     def connect(self):
#         if self.simulate:
#             print("Simulated connection.")
#             return
        
#         print("Connecting to the laser on port {}...".format(self.port))

#         self.ser = serial.Serial(
#             port=self.port,
#             baudrate=self.baudrate,
#             parity=serial.PARITY_NONE,
#             stopbits=serial.STOPBITS_ONE,
#             bytesize=serial.EIGHTBITS,
#             timeout=1
#         )

#         if not self.ser.is_open:
#             self.ser.open()

#         time.sleep(2)
#         print(f"Connected to laser on port {self.port}")

#     @ui_callable
#     def get_status(self):
#         print("Laser Status: {}".format(self.status))
#         return self.status

#     @ui_callable
#     def get_shutter_status(self):
#         '''Returns the current status of the shutter. This is a simple command to check if the shutter is open or closed.'''
#         response = self.send_command('?SHUTTER')
#         if response == "1":
#             print("Shutter is OPEN.")
#         elif response == "0":
#             print("Shutter is CLOSED.")
#         else:
#             print("Unknown shutter status.")
#         return response

#     @ui_callable
#     def laser_diagnosis(self):
#         '''Runs through a series of checks to determine the status of the laser. This includes checking the power setpoint, actual power, and diode status.'''
#         print("Running laser diagnostics...")

#         def check_status():

#             diode_power = self.get_diode_status()
#             diode_power = [float(x[:-2]) for x in diode_power]
#             power_setpoint = self.get_power_setpoint()
#             power_actual = self.get_power()
#             warmup = self.get_warmup_status()

#             print("Current status: {}".format(self.status))
#             print("Warmup: {}".format(warmup))
#             print("Power setpoint: {}, Power actual: {}".format(power_setpoint, power_actual))
#             print("Diode power: {}".format(diode_power))

#             return {
#                 'amps': diode_power,
#                 'setpoint': power_setpoint, 
#                 'power': power_actual,
#                 'warmup': warmup
#             }
        
#         def cycle_power_setpoint(diag_dict):

#             power_actual = diag_dict['power']
#             power_setpoint = diag_dict['setpoint']
#             warmup = diag_dict['warmup']
            
#             if power_actual < power_setpoint * 0.8:
#                 print("Power not yet stabilised.")
#             print("Cycling setpoint...")

#             self.set_power(0.05)
#             time.sleep(2)
#             self.set_power(power_setpoint)
#             time.sleep(5)
#             power_actual = self.get_power()

#             if power_actual < power_setpoint * 0.8:
#                 print("Power not stabilised after cycling setpoint. Inspect laser manually.")
#                 return False
#             else:
#                 print("Power stabilised after cycling setpoint.")
#                 self.status = "ON"
#                 print("Laser is ON at {}.".format(power_setpoint))
#                 return True

#         diag_dict = check_status()
#         if diag_dict['warmup'] != 100:
#             print("Laser is warming up. Please wait.")
#             return False
        
#         cycle_power_setpoint(diag_dict)

#         print("Laser diagnostics complete. All checks passed. If any issues persist, please inspect the laser manually.")
#         print("Remember to cycle the shutter - it sometimes gets stuck.")

#     @ui_callable
#     def cycle_shutter(self):
#         '''Cycles the shutter to ensure it is functioning properly. This is a simple command to open and close the shutter.'''
#         self.close_shutter()
#         time.sleep(1)
#         self.open_shutter()
#         print("Shutter cycled.")
#         return True

#     @ui_callable
#     def enable_laser(self):
#         '''Handles the turning on of the laser, from warmup to on state. The final step is to open the shutter.'''

#         warmup = self.get_warmup_status()
#         power = self.get_power()
        
#         if power >= 3.5:
#             print("Laser is already ON at {} watts. Change power with 'setpower' command.".format(power))
#             return True

#         if self.status == "ON":
#             power = self.get_power()
#             print("Laser is ON at {} watts. Ramping to 4.0 Watts".format(power))
#             self.close_shutter()
#             self.set_power(4.0)
#             print("Laser is now ON at 4.0 watts. Open the shutter to pump the tunable cavity (NIR laser).")
#             return True
        
#         elif warmup == 100:
#             response = self.send_command('ON')
#             print("Laser is now ON")
#             self.set_power(0.05)
#             self.status = "ON"
#             print("Low-power mode (not lasing). Return in 2 minutes to increase power.")
#             return True
        
#         elif 0 < warmup < 100:
#             self.status = "WARMUP"
#             print("Laser is warming up at {}%. Please wait...".format(warmup))
#             return False

#         elif warmup == 0:
#             print(f"In standby mode. Beginning warmup: {warmup}")
#             self.send_command('ON')
#             self.status = "WARMUP"
#             return False
        
#     def disconnect(self):
#         if self.ser and self.ser.is_open:
#             self.ser.close()
#             print("Serial connection closed.")

#     def send_command(self, command):
#         if self.simulate:
#             print(f"Simulated command sent: {command}")
#             return "SIMULATED RESPONSE"

#         full_command = command.strip() + '\r\n'
#         self.ser.write(full_command.encode('ascii'))
#         time.sleep(0.2)
#         response = self.ser.read_all().decode('ascii').strip()
#         return response

#     @ui_callable
#     def turn_on(self):
#         warmup = self.get_warmup_status()
#         if warmup == 100:
#             response = self.send_command('ON')
#             self.status = "ON"
#             print("Laser is now ON.")
#             return True
#         else:
#             warmup = self.send_command('ON')
#             self.status = "WARMUP"
#             print("In standby mode. Beginning warmup: {warmup}")
#             return False
        
#     @ui_callable
#     def get_diode_status(self):
#         response_1 = self.send_command('?C1')
#         breakpoint()
#         print(f"Diode 1 status: {response_1}")
#         response_2 = self.send_command('?C2')
#         print(f"Diode 2 status: {response_2}")
#         return (response_1, response_2)

#     @ui_callable
#     def turn_off(self):
#         response = self.send_command('OFF')
#         self.status = "OFF"
#         self.close_shutter()
#         print("Laser is now OFF.")
#         return response

#     @ui_callable
#     def set_power(self, power_watts):
#         try:
#             power_watts = round(float(power_watts), 2)
#         except ValueError:
#             raise ValueError("Power must be a numeric value.")

#         if power_watts < 0 or power_watts > 6:
#             raise ValueError("Power must be between 0 and 6 Watts.")
        
#         response = self.send_command('P:{}'.format(power_watts))
#         print("Power set to {} Watts.".format(power_watts))
#         return response

#     @ui_callable
#     def get_power(self):
#         response = self.send_command('?P')
#         return float(response[:-1])
    
#     @ui_callable
#     def get_power_setpoint(self):
#         response = self.send_command('?PSET')
#         # print(f"Power setpoint: {response}")
#         return float(response[:-1])

#     @ui_callable
#     def get_warmup_status(self):
#         response = self.send_command('?WARMUP%')
#         return float(response[:-1])

#     @ui_callable
#     def open_shutter(self):
#         response = self.send_command('SHUTTER:1')
#         return response

#     @ui_callable
#     def close_shutter(self):
#         response = self.send_command('SHUTTER:0')
#         return response

#     @ui_callable
#     def identify(self):
#         response = self.send_command('?IDN')
#         return response

#     def __str__(self):
#         return f"Millennia Laser"

#     def __call__(self, command: str, *args, **kwargs):
#         if command not in self.command_functions:
#             raise ValueError(f"Unknown laser command: '{command}'")
#         return self.command_functions[command](*args, **kwargs)

#     def __del__(self):
#         self.disconnect()

