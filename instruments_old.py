
import inspect
import serial
import time
import numpy as np
import os
import json
from copy import copy

import time
import numpy as np
import os
import threading

from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import wraps

from datafit.laser_detection import LaserDetection
from instruments.instrument_base import Instrument

def enforce_response(func, expected_response=True, callback=None):
    """
    Decorator to assert that a function returns the expected response.
    If the response does not match, it logs the error and runs a callback if defined.
    """
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        response = func(self, *args, **kwargs)
        if response != expected_response:
            self.logger.error(f"Expected response: {expected_response}, but got: {response}")
            if callback:
                self.logger.error(f"Running callback: {callback.__name__}")
                callback(response)
            elif hasattr(self, 'call_on_failure'):
                self.call_on_failure(response)
                self.logger.error(f"Running default failure callback: {self.call_on_failure.__name__}")
        return response
    return wrapper


def debug_return(success_criteria=lambda x: x is True and x is not None):
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            result = func(self, *args, **kwargs)
            if self.apply_debug_mode:
                func_name = f"{self.__class__.__name__}.{func.__name__}"
                if not success_criteria(result):
                    self.micro_log.warning(f"[WARNING] {func_name} returned suspicious result: {result}")
                else:
                    self.micro_log.coms(f"{func_name} returned OK: {result}")
            return result
        return wrapper
    return decorator


def apply_pseudocal_forwards(func):
    @wraps(func)
    def wrapper(self, wavelength, *args, **kwargs):
        if getattr(self, 'apply_pseudocal', False) is True:
            # Apply offset correction before the function runs
            wavelength = float(self.pseudocal_forwards(wavelength))
        return func(self, wavelength, *args, **kwargs)
    return wrapper

def apply_pseudocal_backwards(func):
    def wrapper(self, *args, **kwargs):
        # Apply offset correction after the function runs
        result = func(self, *args, **kwargs)
        if getattr(self, 'apply_pseudocal', False) is True:
            # If apply_pseudocal is True, apply the backwards correction
            if isinstance(result, dict):
                # If result is a dictionary, apply to each wavelength
                result = {key: float(self.pseudocal_backwards(value)) for key, value in result.items()}
                # result = self.pseudocal_backwards(result['l1'])
                self.laser_wavelengths = result
        return result
    return wrapper

def live_laser_calibration(func):
    """
    Decorator to automatically calculate the laser wavelength when using go_to_laser_wavelength.
    Needs the triax to be connected to correctly identify wavelength.
    """
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        response = True
        # Call the original function first, catch the 
        func(self, *args, **kwargs)
        # Then run the live calibration
        if self.apply_live_calibration is True:
            response = self.live_calibration_laser()

        return response  # Indicate success
    return wrapper

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

    def __init__(self, interface, motor_map, config):
        self.interface = interface
        self.controller = interface.controller
        self.logger = interface.logger.getChild('MotionControl')
        self.motor_map = motor_map  # Dictionary mapping motor names to IDs
        self.config = config
        self.home_positions = config.get("home_positions", {})
        self._monochromator_steps = None
        self._laser_steps = None
        self._spectrometer_position = None

        self._laser_wavelength = None
        self._monochromator_wavelength = None
        self._spectrometer_wavelength = None

        self.last_direction = True


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
            self.logger.debug("Motors at target positions")
            return True
        else:
            self.logger.warning("ERROR: Motors not at target positions")
            for motor, info in discrepancies.items():
                self.logger.warning(f"Motor {motor}: Expected {info['expected']}, Actual {info['actual']}")
            return False
        
    def get_motor_positions(self, motor_dict, report=True):
        '''Get the current positions of the motors. Takes a dictionary of motor_labels:hardware_names and returns a list of positions. Motor dict contains the mapping of motor label to motor ID.'''

        motors = [motor_dict[i] for i in motor_dict.keys()]
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


    def move_motors(self, motor_id_steps: dict, backlash=True, report=True):
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

        if self.controller.report is True:
            self.controller.report = False
        
            response = self.controller.send_command(motion_command)
            self.wait_for_motors(list(motor_id_steps.keys()))

        else:
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





class Microscope(Instrument):

    implementation_info = [
        'Microscope implementation: v 0.1', 
        'Notes: Use "help" to see available commands. Note than unknown commands are attempted to be passed to the controller for interpretation. If the controller does not recognise the command, it will return an error.',
        '"x", "y" and "z" single letter commands are resered for the stage control, and will call the motion control methods in microscope.',
        'Stage positions in microns are held by the microscope in the stage_positions_microns dictionary. Every move XYZ axis command will update the dictionary and call an AcquisitionControl.update_stage_positions to ensure the stage positions are in sync with the acquisition control, which needs them to calculate scan positions.',
        'All @ui_callable methods are callable from the GUI and the CLI. Some commands serve as a bridge for the '
        
    ]

    def __init__(self, interface, calibration_service=None, controller=None, camera=None, 
                 spectrometer=None, simulate=False):
        super().__init__()
        self.interface = interface
        self.logger = interface.logger
        self.micro_log = self.logger.getChild('Microscope')
        self.micro_log
        self.laser_detection = LaserDetection(interface=interface) # set up laser calibration capability
        self.laser_wavelength_calibrated = None # this holds the true laser calibration when measured live.
        self.cam_temp = None

        self.scriptDir = interface.scriptDir
        self.dataDir = interface.dataDir
        self.autocalibrationDir = interface.autocalibrationDir
        self.acquisitionControlDir = os.path.join(self.scriptDir, 'acquisitioncontrol')
        self.controller = controller or interface.controller
        self.camera = camera or interface.camera
        self.spectrometer = spectrometer or interface.spectrometer
        self.calibration_service = calibration_service
        self.simulate = simulate
        self.apply_pseudocal = False  # Whether to apply pseudocalibration corrections
        self.apply_live_calibration = True
        self.apply_debug_mode = True  # Whether to apply debug mode, which logs all commands and responses
        self.laser_calibrated = False

        self.microscope_mode = 'ramanmode'
        camera_roi = self.interface.camera.roi
        self.wavelength_axis = np.arange(camera_roi[0], camera_roi[2], 1)
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

        # Motion control
        self.motion_control = MotionControl(interface, self.motor_map, self.config)

        self.command_functions = {
            'nyi': self.not_yet_implemented,
            'threads': self.list_threads,
            # calibration commands
            'pscal': self.toggle_pseudocal,
            'livecal': self.toggle_live_calibration,
            'debugmode': self.toggle_debug_mode,
            # general commands
            'wai': self.where_am_i,
            'rg': self.get_spectrometer_position,
            'sl': self.go_to_laser_wavelength,
            'sm': self.go_to_monochromator_wavelength,
            'sg': self.go_to_grating_wavelength,
            'sall': self.go_to_wavelength_all,
            'st': self.go_to_spectrometer_wavelength,
            'referenceall': self.reference_calibration_from_wavelength,
            'referencelaser': self.reference_laser_from_wavelength,
            'referencegratings': self.reference_gratings_from_wavelength,
            'referencemono': self.reference_monochromator_from_wavelength,
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

            # Spectrometer Commands:
            'readenterslit': self.read_entrance_slit,

            # Stage motion
            'x': self.move_x,
            'y': self.move_y,
            'z': self.move_z,
            'focus': self.enter_focus_mode,
            'stagepos': self.get_stage_positions_microns,
            'stagehome': self.set_stage_home,
            'setstart': self.set_start_pos,
            'setstop': self.set_end_pos,
            'scanres': self.set_scan_resolution,
            'scanmode': self.toggle_scan_mode,
            'acquirescan': self.cli_acquire_scan,

            # GUI commands
            
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
            'runscan': self.run_scan_thread,
            'cancel': self.cancel_scan,

            'mshut': self.close_mono_shutter,
            'mopen': self.open_mono_shutter,
            # 'isrun': self.motion_control.wait_for_motors,
            # camera commands
            'nframe': self.set_number_of_frames,
            'acquire': self.acquire_once,
            'acquirecustom': self.acquire_custom_scan,
            'run': self.start_continuous_acquisition,
            'stop': self.stop_continuous_acquisition,
            'roi': self.set_roi,
            'setbin': self.set_camera_binning,
            'caminfo': self.camera_info,
            'temp': self.get_detector_temperature,
            'settemp': self.set_detector_temperature,
            'autotemp': self.camera_auto_temperature_control,
            'refresh': self.refresh_camera,
            'camclose': self.close_camera,
            'camopen': self.open_camera,
            'camspec': self.set_acq_spectrum_mode,
            'camimage': self.set_acq_image_mode,
            'setgain': self.set_camera_gain,
            # 'closecamera': self.close_camera_connection,
            'checkfan': self.check_camera_fan_speed,

            # laser hardware commands
            'setpower': self.set_laser_power,
            'getpower': self.get_laser_power,
            'laseron': self.laser_on,
            'laseroff': self.laser_off,
            'cycleshutter': self.cycle_laser_shutter,
            'laserstatus': self.get_laser_status,
            'enable': self.enable_laser,
            'warmup': self.get_warmup_status,
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
    
    @ui_callable
    def list_threads(self):
        """
        Lists all active threads in the current process.
        Returns a list of thread names.
        """
        threads = threading.enumerate()
        thread_names = [thread.name for thread in threads]
        self.micro_log.info(f"Active threads:")
        for thread in threads:
            if thread.is_alive():
                self.micro_log.info(f"{thread.name} is alive")
            else:
                self.micro_log.info(f"{thread.name} is not alive")
        return thread_names

    @property
    def laser_status(self):
        laser_on = self.interface.laser.status
        if laser_on == 'ON':
            return True
        elif laser_on == 'OFF' or laser_on == 'WARMUP':
            return False
        else:
            self.micro_log.warning(f"Unknown laser status: {laser_on}. Returning False.")
            return False

    def capture_instrument_state(self):
        '''Not yet implemented. #TODO
        Capture the current state of the instrument by getting all relavent attributes.
        Needs new attributes for instrument state, and porting of old commands. For instance, self.laser_wavelength needs to be the stored wavelength, not a wrapper for calculating the wavelength from the controller.'''
        pass

    def set_calibrated_laser_wavelength(self, calibrated_wavelength):
        '''Sets the calibrated wavelength attribute, and updates the acqctrl dictionary with the calibrated wavelength'''
        self.interface.acq_ctrl._current_parameters['laser_wavelength'] = calibrated_wavelength
        self.interface.acq_ctrl._current_parameters['laser_wavelength_uncalibrated'] = self.laser_wavelengths.get('l1', None) # for legacy support and calibrations
        self.laser_calibrated = True
        self.laser_wavelength_calibrated = round(calibrated_wavelength, 3)

    def live_calibration_laser(self):
        '''Handles the calibration of the laser wavelength on the fly. This function is called by the @live_calibration wrapper which is applied to the go_to_laser_wavelength function. It is used to automatically calibrate the laser wavelength when moving to a new laser wavelength. After a new go_to_laser_wavelength command, st will move the spectrometer to the new laser wavelength, acquire a spectrum, and then run the laser detection and peak fitting functions. If the laser is found, it will set the laser wavelength and return the true laser wavelength. Further functions can then use this true laser wavelength to move the monochromator or spectrometer to the correct wavelength.

        NOTE: Currently does not restore original motor positions. Assumes user is not doing grating-related operations. If grating position needs to be maintained, live calibration should be disabled in the developer options or with "livecal" command.

        Logic:
        1. Move spectrograph to laser wavelength
        2. Move slit to zero
        3. Loop:
            a. Acquire spectrum for 0.2s
            b. Run laser detectg and peakfit
        4. If laser found, set laser wavelength and move monochromator to that wavelength
            a. if not found, move g4 2 steps and repeat, up to 5 times. If no laser is found, report issue and stay at current wavelength
        5. return true laser wavelength for passing to other functions
        '''
        # if self.interface.spectrometer.is_simulated:
            # self.micro_log.debug("Simulated spectrometer, skipping live laser calibration.")
            # return None


        estimated_wavelength = self.laser_wavelengths.get('l1')
        
        original_slit_width = self.report_enterance_slit_width
        original_acqtime = copy(self.interface.acq_ctrl.general_parameters['acquisition_time'])
        original_motor_positions = self.motion_control.get_motor_positions(self.motion_control.generate_motor_dict(self.action_groups['grating_wavelength'])) # grab the original motor positions for the grating motors to restore later
        original_spec_wl = self.report_spectrometer_wavelength
        calibrated_wavelength = None
        current_laser_wavelength = self.laser_wavelengths.get('l1') #TODO change to self.laser_wavelengh when static reporting is implemented
        
        self.set_acquisition_time(0.2)  # Set acquisition time to 0.2s for laser detection
        self.go_to_grating_wavelength(estimated_wavelength)
        self.go_to_spectrometer_wavelength(estimated_wavelength)  # Move spectrometer to laser wavelength
        self.set_spectrometer_enter_slit(5)
        self.go_to_monochromator_wavelength(current_laser_wavelength - 10) # moves the laser line past the intermediate slit (spatial filter) in the double monochromator so that a strong laser signal can be passed to the spectrometer

        attempts = 0
        while attempts < 5:
            image_data, wavelength_axis = self.interface.acq_ctrl._acquire_laser()
            result = self.laser_detection.detect_laser(image_data, wavelength_axis) # returns "Peak" object with pos and height attributes, or None if no peak is found
            if result is not None:
                calibrated_wavelength = result.pos
                break

            if attempts == 0:
                self.micro_log.info("Adjusting camera to 1s acquisition time for laser detection.")
                self.set_acquisition_time(1)  # Set acquisition time to 1s for laser detection
            else:
                self.micro_log.debug(f"Laser not found, moving g4 + 1. Attempt {attempts}/5")
                self.move_motors({'g4': 2}, backlash=False)  # Move grating 4 two steps
                time.sleep(0.5)
                
            attempts += 1

        if result is None:
            self.micro_log.info("Laser not found after 5 attempts. Staying at current wavelength.")
            calibrated_wavelength = current_laser_wavelength
            self.laser_wavelength_calibrated = None
            self.laser_calibrated = False
        else:
            self.laser_wavelength_calibrated = calibrated_wavelength
            self.laser_calibrated = True

        # restore to original state
        self.set_spectrometer_enter_slit(original_slit_width)
        self.set_acquisition_time(original_acqtime)
        # self.restore_motor_state(original_motor_positions) 
        # self.go_to_spectrometer_wavelength(original_spec_wl)

        self.micro_log.info(f"Live laser calibration complete. Calibrated wavelength: {calibrated_wavelength}")

        return True

    
    def _get_motor_positions(self, motor_dict):
        '''Get the current positions of the motors, based on the keys of the motor_dict. Values are ignored, converts to hardware IDs by calling MotionControl methods'''

        motor_IDs = self.motion_control.generate_motor_dict(motor_dict.keys())
        current_motor_pos = self.motion_control.get_motor_positions(motor_IDs)

        return current_motor_pos



    def restore_motor_state(self, motor_dict):
        '''Takes an original dictionary of motor positions and restores the motors to those positions. This is used to restore the state of the motors after a live calibration or other operation that changes the motor positions.'''

        current_motor_dict = self._get_motor_positions(motor_dict)
        relative_motion_dict = {}
        # Check if the current positions match the original positions
        for key, value in motor_dict.items():
            current_pos = current_motor_dict[key]
            if current_pos != value:
                relative_motion_dict[key] = value - current_pos
            
        self.motion_control.move_motors(relative_motion_dict, backlash=True)  # Move motors to original positions
        current_positions = self.get_grating_motor_positions()

        if any(current_positions[key] != value for key, value in motor_dict.items()):
            self.micro_log.error("Failed to restore motor positions to original values.")
        else:
            self.micro_log.debug("PASSED: restore motors returned to initial values.")

        
    def move_motors(self, motor_dict, backlash=False):
        """
        Moves the motors by the values specified in the motor_dict. This is a wrapper for motion_control.move_motors. 
        Actively waits for motors to stop moving by polling controller. Backlash correction is applied to movements in the negative direction.
        
        Parameters:
        motor_dict (dict): Dictionary mapping motor labels to step counts, e.g. {'1X': 100, '1Y': -50}
        backlash (bool): Whether to apply backlash correction
        
        Returns:
        str: Response from the controller
        """
        return self.motion_control.move_motors(motor_dict, backlash=backlash)
    
    @ui_callable
    def not_yet_implemented(self, *args):
        '''Placeholder for commands that are not yet implemented.'''
        self.micro_log.info("Not yet implemented")

    @ui_callable
    def toggle_pseudocal(self, *args):
        '''Toggle the pseudocalibration correction.'''
        if not args:
            self.apply_pseudocal = not self.apply_pseudocal
        elif len(args) == 1 and isinstance(args[0], bool):
            self.apply_pseudocal = args[0]
        else:
            self.micro_log.error('Invalid argument for toggle_pseudocal. Use True or False to set the state.')
        status = "enabled" if self.apply_pseudocal else "disabled"
        self.micro_log.info(f"Pseudocalibration correction {status}")

        return status
    
    @ui_callable
    def toggle_live_calibration(self, *args):
        '''Toggle the live calibration of the laser wavelength.'''
        if not args:
            self.apply_live_calibration = not self.apply_live_calibration
        elif len(args) == 1 and isinstance(args[0], bool):
            self.apply_live_calibration = args[0]
        else:
            self.micro_log.error('Invalid argument for toggle_live_calibration. Use True or False to set the state.')
        status = "enabled" if self.apply_live_calibration else "disabled"
        self.micro_log.info(f"Live calibration {status}")

        return status
    
    @ui_callable
    def toggle_debug_mode(self, *args):
        '''Toggle the debug mode. In debug mode, all commands and responses are logged.'''
        if not args:
            self.apply_debug_mode = not self.apply_debug_mode
        elif len(args) == 1 and isinstance(args[0], bool):
            self.apply_debug_mode = args[0]
        else:
            self.micro_log.error('Invalid argument for toggle_debug_mode. Use True or False to set the state.')
        status = "enabled" if self.apply_debug_mode else "disabled"
        self.micro_log.info(f"DEBUG MODE {status}")

        return status
    
    @property
    def filename(self):
        return self.interface.acq_ctrl.filename



    @ui_callable
    def set_start_pos(self):
        self.interface.acq_ctrl.motion_parameters['start_position'] = self.stage_positions_microns.copy()
        self.micro_log.info("Scan Start position set to {}".format(self.interface.acq_ctrl.motion_parameters['start_position']))
        self.interface.acq_ctrl.save_config()

    @ui_callable
    def set_end_pos(self):
        self.interface.acq_ctrl.motion_parameters['end_position'] = self.stage_positions_microns.copy()
        self.micro_log.info("Scan End position set to {}".format(self.interface.acq_ctrl.motion_parameters['end_position']))
        self.interface.acq_ctrl.save_config()

    @ui_callable
    def set_scan_resolution(self, resolution):
        '''Set the scan resolution in microns.'''
        try:
            resolution = float(resolution)
            self.interface.acq_ctrl.motion_parameters['resolution'] = {'x': resolution, 'y': resolution, 'z': resolution}
            self.micro_log.info("Scan resolution set to {}".format(resolution))
        except ValueError:
            self.micro_log.error("Invalid scan resolution value")
            raise

    @ui_callable
    def toggle_scan_mode(self):
        '''Toggle between linescan and map in acquisition control'''
        self.interface.acq_ctrl.toggle_scan_mode()

    @ui_callable
    def cli_acquire_scan(self):
        '''CLI command to acquire a scan.'''
        self.interface.acq_ctrl.cli_acquire_scan()
        return

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

    def pseudocal_forwards(self, wavelength):
        '''Wrapper for the pseudocalibration forward function.'''
        return self.calibration_service.pseudocal.cal_forward(wavelength)
    
    def pseudocal_backwards(self, wavelength):
        '''Wrapper for the pseudocalibration backward function.'''
        return self.calibration_service.pseudocal.cal_backward(wavelength)


    



    @ui_callable
    def run_scan_thread(self):
        '''Executes a scan based on the heirarchical acquisition scan built by the AcquisitionControl class.'''
        self.cancel_event = threading.Event()

        self.scan_thread = threading.Thread(target=self.interface.acq_ctrl.acquire_scan, args=(self, self.cancel_event))
        self.scan_thread.start()
        return self.scan_thread

    
    def save_instrument_state(self):
        '''Saves the state of the microscope and motors to a config, in case of reboot or crash. Uses motor labels as keys.'''
        if self.autosave == False:
            return
        
        self.controller.report = False
        self.micro_log.coms("Saving instrument state: Polling controller for motor positions")
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
            self.micro_log.info('Instrument state loaded from file')
        
            self.write_motor_positions(motor_dict=motor_positions) #PATCH: reenable and make check for motors being the same and selecting to write or not
            self.stage_positions_microns = stage_positions
            
            self.get_all_current_wavelengths()
            self.detect_microscope_mode()
        else:
            self.micro_log.info('Instrument state file not found. Saving current state.')
            self.save_instrument_state()
            # raise FileNotFoundError(f"Instrument state file not found at {save_state_path}")
    
    def load_config_file(self):
        if os.path.exists(self.config_path):
            with open(self.config_path, 'r') as f:
                config = json.load(f)
            self.micro_log.info('Config loaded from file')
            return config
        else:
            raise FileNotFoundError(f"Config file not found at {self.config_path}")
        
    def detect_microscope_mode(self):
        '''Determines Raman or Imagemode depending on the current position of the mode motor.'''

        mode_steps = self.get_stage_steps()['mode']
        if mode_steps == 50000:
            self.microscope_mode = 'imagemode'
        elif mode_steps == -50000:
            self.microscope_mode = 'ramanmode'

        else:
            self.micro_log.info('Microscope mode not recognised. Please check state and enter "imagemode" or "ramanmode"')
            while True:
                newmode = input("Enter current mode (imagemode/ramanmode): ").strip().lower()
                if newmode in ['imagemode', 'ramanmode']:
                    self.microscope_mode = newmode
                    self.motion_control.write_motor_positions({'mode': -50000 if newmode == 'ramanmode' else 50000})
                    break
                else:
                    print("Invalid mode. Please enter 'imagemode' or 'ramanmode'.")

        self.micro_log.info("Microscope mode detected: {}".format(self.microscope_mode))
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
            response = input("Microscope already in Raman mode. Do you want to continue? (y/n)")
            if response.lower() != 'y':
                self.micro_log.info("aborting mode change, staying in raman mode")
                return
            
        self.micro_log.info("Moving to Raman mode...")
        self.motion_control.move_motors({'mode':-self.mode_steps})
        self.microscope_mode = 'ramanmode'
        self.micro_log.info("Microscope set to Raman mode")
    
    @ui_callable
    def image_mode(self):
        '''Set the acquisition mode to image mode.'''
        if self.microscope_mode == 'imagemode':
            response = input("Microscope already in Image mode. Do you want to continue? (y/n)")
            if response.lower() != 'y':
                self.micro_log.info("aborting mode change, staying in image mode")
                return

        self.micro_log.info("Moving to Image mode...")
        self.motion_control.move_motors({'mode':self.mode_steps})
        self.microscope_mode = 'imagemode'
        self.micro_log.info("Microscope set to Image mode")


    @ui_callable
    def test_homing(self, label, series_name, cycles=20):
        '''Test the reproducibility of the motor homing by moving to home and back in a cycle, n times.'''
        if label not in self.motor_map:
            raise ValueError(f"Unknown action group: {label}")
        
        home_positions = {series_name: []}
        for index in range(cycles):
            response = self.home_motor(label)
            self.micro_log.info(f"Homing motor {label}: {response}")
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
        self.micro_log.info(f"Recalibrating home position for motor {motor_id}")
        response = self.controller.send_command(f"h{motor_id}")

        response = response[0]
        self.micro_log.info(f"Homing response: {response}")
        if "at position" in response:
            position = int(response.split(' ')[-1].strip())
        else:
            raise RuntimeError(f"Unexpected response: {response}")

        # Save to config
        self.config.setdefault("home_positions", {})
        self.config["home_positions"][motor_id] = position
        self.micro_log.info(f"Saved home position {position} for {motor_id}")

        self.write_config()
        time.sleep(0.01)
        self.motion_control.move_motors({label: -position})  # Move to home position
        self.micro_log.info(f"Moved motor {motor_id} to home position {position}")


    @ui_callable
    def home_all_motors(self):
        """
        # Home all motors in the system.
        
        """
        self.home_laser()
        self.home_gratings()
        # home polarization NYI
    
        return 

    @ui_callable
    def home_laser(self, move_to_calibrated_position=True):
        """
        Home the laser motors.
        
        Returns:
        str: The response from the controller after homing the laser motors.
        """
        for motor_label in self.action_groups['laser_wavelength'].keys():
            response = self.home_motor(motor_label)
            self.micro_log.info(f"Homing motor {motor_label}: {response}")
        
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
            self.micro_log.info(f"Homing motor {motor_label}: {response}")

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
            self.micro_log.info(f"Homing motor {motor_label}: {response}")

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
        self.micro_log.info('Motor positions written to file')

    
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
        except Exception as e:
            print('recmot Error:', e)
            current_data = {}


        data = {'laser_positions':laser_motor_positions, 'grating_positions':grating_motor_positions, 'triax_positions':triax_position,'wavelength':float(extra)}

        current_data[f'{len(current_data)}'] = data
        # dump the data to a json file
        with open(os.path.join(self.interface.calibrationDir, 'motor_recordings', 'motor_recordings.json'), 'w') as f:
            json.dump(current_data, f)
            # f.write('\n')


    def initialise(self):
        '''Initialises the microscope by querying all connections to instruments and setting up the necessary parameters.'''

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
        


        self.micro_log.info('-'*20)
        for key, value in report.items():
            self.micro_log.info('{}: {}'.format(key, value))
        self.micro_log.info('-'*20)

    #? Stage control commands




    @ui_callable
    def cancel_scan(self):
        '''Cancels the current scan.'''
        if hasattr(self, 'scan_thread'):
            self.cancel_event.set()
            self.scan_thread.join()
            self.micro_log.info("Scan cancelled")
        else:
            self.micro_log.info("No scan to cancel")
 


    @ui_callable
    def go_to_polarization_in(self, angle):
        '''Moves the polarizer to the specified angle.'''
        self.motion_control.move_motors({'p_in': angle})
        self.micro_log.info('Input polarization set to {} degrees'.format(angle))

    @ui_callable
    def go_to_polarization_out(self, angle):
        '''Moves the polarizer to the specified angle.'''
        print("Not implemented yet")
        return
        self.motion_control.move_motors({'p_out': angle})
        print('Output polarization set to {} degrees'.format(angle))

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
            
        self.interface.acq_ctrl.update_stage_positions()
        

    @ui_callable
    def move_x(self, travel_distance):
        '''Moves the microcsope sample stage in the X direction, by travel distance in micrometers. Note no backlash compensation is applied.'''
        try:
            travel_distance = float(travel_distance)
        except ValueError:
            self.micro_log.info("Invalid travel distance. Must be a number.")
            return
        
        motor_dict = self.calibration_service.microns_to_steps({"x": travel_distance})
        self.motion_control.move_motors(motor_dict, backlash=False, report=False)
        self.update_stage_positions({"x": travel_distance})
        self.micro_log.info('x stage moved by {} micrometers'.format(travel_distance))
    
    @ui_callable
    def move_y(self, travel_distance):
        '''Moves the microcsope sample stage in the Y direction, by travel distance in micrometers. Note no backlash compensation is applied.'''
        try:
            travel_distance = float(travel_distance)
        except ValueError:
            self.micro_log.info("Invalid travel distance. Must be a number.")
            return
        
        motor_dict = self.calibration_service.microns_to_steps({"y": travel_distance})
        self.motion_control.move_motors(motor_dict, backlash=False, report=False)
        self.update_stage_positions({"y": travel_distance})
        self.micro_log.info('y stage moved by {} micrometers'.format(travel_distance))

    @ui_callable
    def move_z(self, travel_distance):
        '''Moves the microcsope sample stage in the Z direction, by travel distance in micrometers. Note no backlash compensation is applied.'''
        try:
            travel_distance = float(travel_distance)
        except ValueError:
            self.micro_log.info("Invalid travel distance. Must be a number.")
            return
        
        motor_dict = self.calibration_service.microns_to_steps({"z": travel_distance})
        self.motion_control.move_motors(motor_dict, backlash=False, report=False)
        self.update_stage_positions({"z": travel_distance})
        self.micro_log.info('z stage moved by {} micrometers'.format(travel_distance))

    @ui_callable
    def set_stage_home(self):
        '''Sets the current stage position as the home position.'''
        motor_dict = {'x': 0, 'y': 0, 'z': 0}
        self.write_motor_positions(motor_dict=motor_dict)

        for key in self.stage_positions_microns.keys():
            self.stage_positions_microns[key] = 0
        self.micro_log.info('Stage home ({}) set to current position'.format(self.interface.acq_ctrl.current_stage_coordinates))

    @ui_callable
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
        # self.close_mono_shutter()
        
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
    def go_to_laser_steps(self, target_positions, confirm_pos=True):
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
            self.micro_log.debug("Moved: ", motor_steps)
            return True
        else:
            return False


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
            self.micro_log.info("Moved: {}".format(motor_steps))
            # self.micro_log.info("Monochromator now at {} nm".format(self.report_monochromator_wavelength))
            return True
        else:
            self.micro_log.info("Monochromator already at target steps - no movement initiated.")
            return False


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
    def report_laser_wavelength(self):
        return round(self.laser_wavelengths.get('l1', 'KeyError'), 2)

    @property
    def report_calibrated_laser_wavelength(self):
        return self.laser_wavelength_calibrated

    @property
    def report_grating_wavelength(self):
        return round(self.grating_wavelengths.get('g1', 'KeyError'), 2)

    @property
    def report_monochromator_wavelength(self):
        return round(self.grating_wavelengths.get('g3', 'KeyError'), 2)

    @property
    def report_spectrometer_wavelength(self):
        return round(self.spectrometer_wavelength.get('triax', 'KeyError'), 2)

    @property
    def report_laser_power(self):
        return(round(getattr(self.interface.laser, 'current_power', 'AttErr'), 2))
    
    @property
    def report_enterance_slit_width(self):
        return self.interface.spectrometer.read_enterance_slit()
    
    @property
    def report_camera_temp(self):
        '''Returns the current camera temperature.'''
        return self.camera.get_temperature()
    
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

    # @ui_callable
    # def close_camera_connection(self):
    #     '''Closes the camera connection.'''
    #     self.camera.close_camera()

    @ui_callable
    def check_camera_fan_speed(self):
        speed = self.camera.get_fan_speed()
        self.micro_log.info("Fan Speed: {}".format(speed))
        return speed

    @ui_callable
    # @debug_return()
    @enforce_response
    def set_acquisition_time(self, value):
        try:
            value = float(value)
        except ValueError:
            print("Invalid acquisition time. Must be a number.")
            return
        if value < 0:
            print("Acquisition time must be positive.")
            return
        
        self.interface.acq_ctrl.general_parameters['acquisition_time'] = value
        self.camera.set_exposure_time(str(value))
        return True

    @ui_callable
    def set_filename(self, filename):
        self.interface.acq_ctrl.general_parameters['filename'] = filename
        print("Filename set to: ", filename)

    @ui_callable
    def set_laser_power(self, value):
        '''Sets the laser power to the specified value.'''
        try:
            value = float(value)
        except ValueError:
            self.micro_log.info("Invalid laser power {}. Must be a number.".format(value))
            return
        
        self.interface.laser.set_power(value)
        self.interface.acq_ctrl.general_parameters['laser_power'] = value

    @ui_callable
    def get_laser_power(self):
        '''Returns the current laser power.'''
        power = self.interface.laser.get_power()
        self.interface.acq_ctrl.general_parameters['laser_power'] = power
        return power
    
    @ui_callable
    def laser_on(self):
        '''Turns the laser on.'''
        self.interface.laser.turn_on()
        self.micro_log.info("Laser turned on")
        self.interface.emitter.update_laser_status(True)
    
    @ui_callable
    def laser_off(self):
        '''Turns the laser off.'''
        self.interface.laser.turn_off()
        self.micro_log.info("Laser turned off")
        self.interface.emitter.update_laser_status(False)

    @ui_callable
    def cycle_laser_shutter(self):
        '''Cycles the laser shutter.'''
        self.interface.laser.cycle_shutter()
    
    @ui_callable
    def get_laser_status(self):
        '''Returns the current laser status.'''
        status = self.interface.laser.get_status()
        return status
    
    @ui_callable
    def enable_laser(self):
        '''Enables the laser.'''
        self.interface.laser.enable_laser()

    @ui_callable
    def get_warmup_status(self):
        '''Returns the current laser warmup status.'''
        status = self.interface.laser.get_warmup_status()
        self.micro_log.info("Laser warmup status: {}%".format(status))
        return status

    @ui_callable
    def set_raman_shift(self, value):
        self.current_shift = value
        self.go_to_wavenumber(value)
        self.interface.acq_ctrl.general_parameters['raman_shift'] = value

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
        # self.interface.debug_skip.append('camera')

    @ui_callable
    def open_camera(self):
        '''Opens the hardware camera connection. '''
        self.camera.initialise()

    @ui_callable
    def set_number_of_frames(self, n_frames):
        '''Sets the number of frames to acquire.'''
        try:
            n_frames = int(n_frames)
        except ValueError:
            print("Invalid number of frames. Must be an integer.")
            return
        
        self.interface.acq_ctrl.general_parameters['n_frames'] = n_frames
        print('Number of frames set to: ', n_frames)

    @ui_callable
    def acquire_once(self, filename=None):
        self.interface.acq_ctrl.prepare_acquisition_params()
        self.interface.acq_ctrl.acquire_once(filename)
        return
    
    @ui_callable
    def acquire_custom_scan(self):
        self.interface.acq_ctrl.acquire_custom_scan()
        return


    def prepare_dataset_acquisition(self):
        '''Prepares the dataset acquisition by setting the parameters.'''
        self.interface.acq_ctrl.prepare_acquisition()
    
    def acquire_dataset(self):
        '''Prepares and executes a multidimensional dataset acquisition.'''
    
    @ui_callable
    def start_continuous_acquisition(self):
        '''Starts continuous acquisition on the camera.'''
        self.interface.acq_ctrl.prepare_acquisition_params()
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
        # self.micro_log.debug
        cam_temp = self.camera.get_temperature()
        return cam_temp
    
    @ui_callable
    def set_detector_temperature(self, temperature):
        status = self.interface.camera.set_target_temperature(temperature)

    @ui_callable
    def camera_auto_temperature_control(self, state):
        try:
            state = bool(int(state))
        except ValueError:
            print("Invalid state. Must be 0 or 1.")
            return
        self.interface.camera.enable_auto_temperature_control(state)

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
        self.micro_log.info(f"Moving all components to wavelength: {wavelength} nm")
        # First move the laser
        self.go_to_laser_wavelength(wavelength)
        # If the laser wavelength is calibrated, use that instead
        if self.laser_wavelength_calibrated is not None:
            wavelength = self.laser_wavelength_calibrated

        self.go_to_grating_wavelength(wavelength) # move all grating motors
        
        # Then handle the monochromator
        if shift is True:
            # Maintain the current Raman shift by calculating new monochromator position
            self.go_to_wavenumber(self.current_shift)

        # Finally, move the spectrometer
        self.go_to_spectrometer_wavelength(wavelength)
        
        self.micro_log.info(f"All components set to wavelength: {wavelength} nm")
        return True
    
    def check_spectrometer_wavelength(self, wavelength):
        wavelength = string_to_float(wavelength)

        if not self.check_hard_limits(wavelength, self.hard_limits['spectrometer_wavelength']):
            self.micro_log.info('Spectrometer wavelength "{}" out of range. Pick a wavelength between {} and {} nm'.format(wavelength, *self.hard_limits['spectrometer_wavelength']))
            return False
        
        return True


    @ui_callable
    # @debug_return()
    @enforce_response
    def go_to_spectrometer_wavelength(self, wavelength):
        '''Moves the spectrometer to the specified wavelength.'''
        wavelength = string_to_float(wavelength)
        if self.check_spectrometer_wavelength(wavelength) is False:
            return False
        
        self.interface.spectrometer.go_to_wavelength(wavelength)
        self.generate_wavelength_axis()
        return True

    @ui_callable
    def read_entrance_slit(self):
        '''Reads the current entrance slit width of the spectrometer.'''
        try:
            slit_width = self.interface.spectrometer.read_enterance_slit()
            return slit_width
        except Exception as e:
            self.micro_log.error(f"Error reading entrance slit: {e}")
            return None
        

    # @debug_return()
    @enforce_response
    def set_spectrometer_enter_slit(self, slit_width: int):
        '''Sets the entrance slit width of the spectrometer.'''
        try:
            slit_width = int(slit_width)
        except ValueError:
            self.micro_log.info("Invalid slit width. Must be an integer.")
            return
        if slit_width < 0:
            self.micro_log.info("Slit width must be positive.")
            return
        current_width = self.report_enterance_slit_width
        move_slit = slit_width - current_width
        if move_slit == 0:
            self.micro_log.debug("Slit width is already set to {} microns".format(slit_width))
            return True
        self.interface.spectrometer.move_enterance_slit(move_slit)

        # poll to see if current width is achieved, wait until it is
        count = 0
        while slit_width != self.report_enterance_slit_width:
            time.sleep(0.2)
            count += 1
            if count > 50:
                self.micro_log.error("Failed to set slit width to {} microns".format(slit_width))
                return False
        
        self.micro_log.info("Slit width set to {} microns".format(slit_width))

        return True
            




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

        print('All Motors successfully shifted')

    @ui_callable
    def reference_laser_from_wavelength(self, wavelength):
        '''
        Reference the current laser motor configuration to a known laser wavelength (in nm).
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


        # Calculate target motor positions from the provided wavelength
        target_laser_steps = self.calibration_service.wl_to_steps(true_wavelength_laser, self.action_groups['laser_wavelength'])

        # write current position to motors
        motor_dict = {}
        motor_dict.update(target_laser_steps)
        self.write_motor_positions(motor_dict=motor_dict)

        print('Laser Motors successfully shifted')


    @ui_callable
    def reference_gratings_from_wavelength(self, wavelength, shift=True):
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
        target_mono_steps = self.calibration_service.wl_to_steps(true_wavelength_grating, self.action_groups['grating_wavelength'])


        # write current position to motors
        motor_dict = {}
        motor_dict.update(target_mono_steps)
        self.write_motor_positions(motor_dict=motor_dict)

        print('Grating Motors successfully shifted')

    @ui_callable
    def reference_monochromator_from_wavelength(self, wavelength, shift=True):
        '''
        Reference the current monochromator motor configuration to a known laser wavelength (in nm).
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
        target_mono_steps = self.calibration_service.wl_to_steps(true_wavelength_grating, self.action_groups['monochromator_wavelength'])


        # write current position to motors
        motor_dict = {}
        motor_dict.update(target_mono_steps)
        self.write_motor_positions(motor_dict=motor_dict)

        print('Monochromator Motors successfully shifted')

    def wavenumber_to_wavelength(self, wavenumber):
        return 10_000_000/wavenumber
    
    def wavelength_to_wavenumber(self, wavelength):
        return 10_000_000/wavelength
    

  

    def check_hard_limits(self, value, limits):
        '''Checks the hard limits dictionary of the microscope for the allowed range of values.'''
        if not limits[0] < value < limits[1]:
            return False
        return True
        
    def check_laser_wavelength(self, wavelength):
        '''Checks the validity of the entered value for laser wavelength.'''

        if not self.check_hard_limits(wavelength, self.hard_limits['laser_wavelength']):
            print('Laser wavelength "{}" out of range. Pick a wavelength between {} and {} nm'.format(wavelength, *self.hard_limits['laser_wavelength']))
            return False
        
        return True

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
    @live_laser_calibration
    @apply_pseudocal_forwards
    def go_to_laser_wavelength(self, wavelength):
        """
        Move the laser to the specified wavelength.
        
        Parameters:
        wavelength (float): Target wavelength in nm
        
        Returns:
        bool: True if successful, False otherwise
        """
        wavelength = string_to_float(wavelength)
        # Validate the wavelength is within allowed range
        if self.check_laser_wavelength(wavelength) is False:
            return False

        if not self.camera.stop_flag.is_set():
            self.stop_continuous_acquisition() # Stop camera if running to avoid conflicts during calibration
            self.micro_log.debug("NOTE: Live camera was running. Stopped")
        # Safety: close shutter during movement
        # self.close_mono_shutter()
        
        # Get target positions from calibration service
        # Assumes the calibration service has a wl_to_steps method that returns a dictionary
        target_positions = self.calibration_service.wl_to_steps(wavelength, self.action_groups['laser_wavelength'])
        
        # Move to target positions
        moved = self.go_to_laser_steps(target_positions)
              
        # Safety checks and reopen shutter
        # self.laser_safety_check()
        # self.open_mono_shutter()
        
        # Report primary wavelength
        if moved:
            self.laser_calibrated = False # for tracking live calibration status
            self.laser_wavelength_calibrated = None
            self.micro_log.debug("Laser no longer calibrated...")
        else:
            self.micro_log.info("Laser motors already at target position - no motion initiated.")
        return True


    @ui_callable
    @debug_return()
    def go_to_monochromator_wavelength(self, wavelength):
        """
        Move the monochromator to the specified wavelength.
        
        Parameters:
        wavelength (float): Target wavelength in nm
        
        Returns:
        bool: True if successful, False otherwise
        """
        wavelength = string_to_float(wavelength)
        # Validate the wavelength is within allowed range
        if self.check_monochromator_wavelength(wavelength) is False:
            return False

        target_positions = self.calibration_service.wl_to_steps(wavelength, self.action_groups['monochromator_wavelength'])
        
        # Move to target positions
        self.go_to_monochromator_steps(target_positions)
        self.micro_log.debug("Monochromator sent to {} nm".format(wavelength))
        self.micro_log.debug("Monochromator reading at {} nm".format(self.report_monochromator_wavelength))

        return True
    
    @ui_callable
    # @debug_return()
    @enforce_response
    def go_to_grating_wavelength(self, wavelength):
        """
        Move all gratings (first and second tunable filters) to the specified wavelength.
        
        Parameters:
        wavelength (float): Target wavelength in nm
        
        Returns:
        bool: True if successful, False otherwise
        """
        # Validate the wavelength is within allowed range
        wavelength = string_to_float(wavelength)
        if self.check_grating_wavelength(wavelength) is False:
            return False
        
        # Get target positions from calibration service
        target_positions = self.calibration_service.wl_to_steps(wavelength, self.action_groups['grating_wavelength'])
        
        moved = self.go_to_grating_steps(target_positions)

        if moved is True:
            self.micro_log.info("New grating wavelength: {}".format(self.report_grating_wavelength))
        else:
            self.micro_log.info("Grating motors already at target position - no motion initiated.")

        return True

    def check_grating_wavelength(self, wavelength):
        '''Checks the validity of the entered value for grating wavelength.'''
        wavelength = string_to_float(wavelength)

        if not self.check_hard_limits(wavelength, self.hard_limits['grating_wavelength']):
            self.micro_log.info('Grating wavelength "{}" out of range. Pick a wavelength between {} and {} nm'.format(wavelength, *self.hard_limits['grating_wavelength']))
            return False
        
        return True
    
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
            self.micro_log.debug("Moved: ", motor_steps)
            return True
        
        else:
            return False

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
        self.interface.acq_ctrl._current_parameters['spectrometer_steps'] = self.interface.spectrometer.spectrometer_position
        self.logger.info('Current spectrometer position: {}'.format(self.interface.spectrometer.spectrometer_position))
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
        self.detect_microscope_mode()


        self.micro_log.info("---Steps---")
        for motor, position in self.laser_steps.items():
            self.micro_log.info(f'{motor}: {position} steps')
        for motor, position in self.grating_steps.items():
            self.micro_log.info(f'{motor}: {position} steps')

        self.micro_log.info('---Wavelengths---')
        for motor, wavelength in self.laser_wavelengths.items():
            if wavelength is None:
                self.micro_log.info(f'{motor}: None')
                continue
            self.micro_log.info(f'{motor}: {round(wavelength, 2)} nm')
        for motor, wavelength in self.grating_wavelengths.items():
            if wavelength is None:
                self.micro_log.info(f'{motor}: None')
                continue
            self.micro_log.info(f'{motor}: {round(wavelength, 2)} nm')

        self.micro_log.info('---Spectrometer---')
        self.micro_log.info(f'Spectrometer position: {self.spectrometer_position} steps')
        self.micro_log.info(f'Spectrometer wavelength: {self.spectrometer_wavelength} nm')

        # stage
        self.micro_log.info('---Stage---')
        
        for motor, position in stage_steps.items():
            self.micro_log.info(f'{motor}: {position} steps')
        for motor, position in self.stage_positions_microns.items():
            self.micro_log.info(f'{motor}: {position} microns')
        self.micro_log.info(f"Mode: {self.microscope_mode}")

        return 
    
    # @apply_pseudocal_backwards
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
        self.micro_log.info(f'Set Raman shift to {wavenumber} cm^-1 for {laser_wavelength} nm excitation')
        return True
