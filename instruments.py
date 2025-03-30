import inspect
import serial
import time
import pyvisa
import numpy as np
import os
import json
import ctypes
from ctypes import *
from tuscen.TUCam import *
from enum import Enum
import time
import numpy as np
import os
import threading

from abc import ABC, abstractmethod
from dataclasses import dataclass
from functools import wraps

from calibration import Calibration, LdrScan

def simulate(expected_value=None):
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            if self.simulate:
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
    def __init__(self, controller):
        self.controller = controller
        self._monochromator_steps = None
        self._laser_steps = None
        self._spectrometer_position = None

        self._laser_wavelength = None
        self._monochromator_wavelength = None
        self._spectrometer_wavelength = None

    def extract_coms_flag(self, message):
        return message[0].split(':')[1].strip(' ')

    def wait_for_motors(self, delay=0.1):
        '''Waits for the motors to finish moving by polling the motors until they are no longer running.'''
        count = 0
        running_A = True
        running_B = True
        while running_A is True or running_B is True:

            if running_A is True:
                response = self.controller.send_command('Aisrun')
                res1 = self.extract_coms_flag(response)

                if res1 == 'S0':
                    running_A = False
                else:
                    time.sleep(delay)
                    continue

            if running_B is True:
                response = self.controller.send_command('Bisrun')
                res2 = self.extract_coms_flag(response)
                if res2 == 'S0':
                    running_B = False
                else:
                    time.sleep(delay)
                    continue
                
            if count > 0:
                print("Loop broke")
                
            count += 1

        return 'S0'
    


    def confirm_motor_positions(self, targets, motors):
        motor_dict = {
            'A': self.get_laser_motor_positions,
            'B': self.get_monochromator_motor_positions,
            # Add more motors here as needed
        }

        get_positions = motor_dict.get(motors)
        if get_positions is None:
            raise ValueError(f"Unexpected motor identifier: {motors}")

        positions = get_positions()
        if positions[0] == targets[0] and positions[1] == targets[1] and positions[2] == targets[2] and positions[3] == targets[3]:
            print("Motors at target positions")
            return True
        else:
            print("ERROR: Motors not at target positions")
            print("Expected: ", targets)
            print("Actual: ", positions)
            return False
        
    def backlash_correction(self, steps, motors):
        correct_back = [-20 if i != 0 else 0 for i in steps]
        self.move_motors(correct_back, motors)

        correct_forward = [20 if i != 0 else 0 for i in steps]
        self.move_motors(correct_forward, motors)
        return

    def move_motors(self, steps: tuple, motors: str, backlash=True):
        '''Move the motors to the specified positions. #TODO: modify firmware to accept all motor positions in one command.'''
        motion_command = '{}X{}Y{}Z{}A{}'.format(motors, steps[0], steps[1], steps[2], steps[3])

        response = self.controller.send_command('{}'.format(motion_command))
        self.wait_for_motors()

        return response

    @ui_callable
    def get_laser_motor_positions(self, *args):
        '''Get the current positions of the laser motors.'''
        self.laser_steps = self.controller.get_laser_motor_positions()
        print('Current laser pos: {}'.format(self.laser_steps))

        return self.laser_steps
    
    @ui_callable
    def get_monochromator_motor_positions(self, *args):
        '''Get the current positions of the grating motors.'''
        self.monochromator_steps = self.controller.get_monochromator_motor_positions()
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



    def __init__(self, interface, simulate=False):
        super().__init__()
        self.interface = interface
        self.scriptDir = interface.scriptDir
        self.controller = interface.controller
        self.simulate = simulate

        self.ldr_scan_dict = {
            'l1': {
                'range': 150,
                'resolution': 5,
            },
            'l2': {
                'range': 150,
                'resolution': 5,
            },
            'l3': {
                'range': 150,
                'resolution': 5,
            },
            'g1': {
                'range': 150,
                'resolution': 5,
            },
            'g2': {
                'range': 150,
                'resolution': 5,
            }
        }
        # Microscope hard limits for hardware
        self.hard_limits = {
            'laser_wavelength': [650, 1000],
            'monochromator_wavelength': [500, 1300],
        }

        # acquisition parameters
        self.acquisition_parameters = AcquitisionParameters()

        # Motion control
        self.motion_control = MotionControl(self.controller)

        self.command_functions = {
            # general commands
            'wai': self.where_am_i,
            'rg': self.get_spectrometer_position,
            'sl': self.go_to_laser_wavelength,
            'sm': self.go_to_monochromator_wavelength,
            'sall': self.go_to_wavelength_all,
            'st': self.go_to_spectrometer_wavelength,
            'reference': self.reference_calibration,
            'shift': self.go_to_wavenumber,
            'triax': self.connect_to_triax,
            'camera': self.connect_to_camera,
            # 'calshift': self.simple_calibration_shift, #TODO: Decide if I need this
            'report': self.report_status,
            'writemotora': self.set_absolute_positions_A,
            'writemotorb': self.set_absolute_positions_B,
            'rldr': self.read_ldr0,
            'calibrate': self.run_calibration,
            # motor commands
            'apos': self.get_laser_motor_positions,
            'bpos': self.get_monochromator_motor_positions,
            'slsteps': self.go_to_laser_steps,
            'smsteps': self.go_to_monochromator_steps,
            'recmot': self.record_motors,
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
            'close': self.close_camera,
            'camspec': self.set_acq_spectrum_mode,
            'camimage': self.set_acq_image_mode,
            'setgain': self.set_camera_gain,




        }

        # scientific attributes
        # self.laser_steps = None
        self.laser_wavelength = [700, 700, 700, 700]
        self.monochromator_wavelength = [700, 700, 700, 700]
        # self.spectrometer_position = None
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
            
        with open(os.path.join(self.scriptDir, 'motor_recordings.txt'), 'a') as f:
            f.write('{}:{}:{}:{}\n'.format(laser_motor_positions, monochromator_motor_positions, triax_position, extra))
        print("Exporting: {}:{}:{}:{}".format(laser_motor_positions, monochromator_motor_positions, triax_position, extra))
        return f"{laser_motor_positions}:{monochromator_motor_positions}:{triax_position}:{extra}"

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
        
    def initialise(self):
        '''Initialises the microscope by querying all connections to instruments and setting up the necessary parameters.'''
        self.calibrations = self._generate_calibrations()
        self.calibrations.ammend_calibrations()
        self.calibrations.fix_subtractive_calibrations() # TODO: Remove this line once the calibration files are fixed

        # camera
        self.camera = self.interface.camera

        self.get_laser_motor_positions()
        self.get_monochromator_motor_positions()
        self.get_spectrometer_position()
        self.report_status(initialise=True)
        pass

    @ui_callable
    def report_status(self, initialise=False):
        '''Prints the current status of the system. If initialise is True, the function will recalculate all parameters. If False, it will use the current values obtained from the initialisation.'''

        if initialise is False:
            # recalculate all parameters
            self.laser_steps = self.get_laser_motor_positions()
            self.monochromator_steps = self.get_monochromator_motor_positions()
            self.get_spectrometer_position()


        report = {
            'laser l1, l2 lambda': self.calculate_laser_wavelength(self.laser_steps),
            'g1 lambda': self.calculate_monochromator_wavelength(self.monochromator_steps),
            'TRIAX lambda': self.calculate_spectrometer_wavelength(self.spectrometer_position),
            'laser motor positions': self.laser_steps,
            'monochromator motor positions': self.monochromator_steps,
            'laser wavenumber': self.current_laser_wavenumber,
            'monochromator wavenumber': self.current_monochromator_wavenumber,
            # 'Raman wavelength': self.current_raman_wavelength,
            'Raman shift': self.current_shift,
            # 'pinhole': self.pinhole
        }
        

        if  report['g1 lambda'][0] < 500 or report['g1 lambda'][0] > 2000:
            print('Grating wavelength out of range - please check monochromator mode')

        # self.pinhole = report['monochromator motor positions'][2]
        # report['pinhole'] = self.pinhole

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
        response = self.controller.send_command('ld0')
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

        initial_grating = [i for i in self.monochromator_steps]
        initial_laser = [i for i in self.laser_steps]

        wavelengths = np.arange(*wavelength_range, resolution)
        print(f"Running {motor} calibration for wavelengths: ", wavelengths)
        condition = input("Continue? (y/n): ")
        if condition.lower() == 'n':
            return
        index = len([file for file in os.listdir(os.path.join(self.scriptDir, 'autocalibration')) if file.endswith('.json')])
        
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

            with open(os.path.join(self.scriptDir, 'autocalibration', 'autocal_{}_{}.json'.format(index, motor)), 'w') as f:
                json.dump(calibrationDict, f)

        print(f"{motor.lower()} Scan complete. Data saved to autocal_{index}_{motor}.json")

        self.detector_safety = True
        # self.open_pinhole_shutter()
        print("Returning to initial position")
        self.go_to_laser_steps(initial_laser)
        self.go_to_monochromator_steps(initial_grating)

    @ui_callable
    def go_to_laser_steps(self, target_pos):
        '''Moves the laser motors to the specified position in steps.'''
        move_steps = [i - j for i, j in zip(target_pos, self.laser_steps)]
        self.motion_control.move_motors(move_steps, 'A')
        self.motion_control.wait_for_motors()
        self.motion_control.backlash_correction(move_steps, 'A')
        self.motion_control.confirm_motor_positions(target_pos, 'A')

        print("Moved to laser steps: ", target_pos)

    @ui_callable
    def go_to_monochromator_steps(self, target_pos):
        '''Moves the grating motors to the specified position in steps.'''
        move_steps = [i - j for i, j in zip(target_pos, self.monochromator_steps)]
        self.motion_control.move_motors(move_steps, 'B')
        self.motion_control.wait_for_motors()
        self.motion_control.backlash_correction(move_steps, 'B')

        self.motion_control.confirm_motor_positions(target_pos, 'B')
        print("Moved to monochromator steps: ", target_pos)

    def run_ldr0_scan(self, motor, search_length=None, resolution=None):
        if motor not in self.ldr_scan_dict.keys():
            print("Invalid motor. Must be 'g1', 'g2', or 'l2'")
            return
        if search_length is None:
            search_length = self.ldr_scan_dict[motor]['range']
        if resolution is None:
            resolution = self.ldr_scan_dict[motor]['resolution']

        # build a dictionary of motor positions
        posDict = {
            'l1': self.laser_steps[0],
            'l2': self.laser_steps[1],
            'l3': self.laser_steps[2], 
            'l4': self.laser_steps[3],
            'g1': self.monochromator_steps[0],
            'g2': self.monochromator_steps[1],
            'g3': self.monochromator_steps[2],
            'g4': self.monochromator_steps[3]
        }

        current_pos = posDict[motor]
        scan_data = []
        scan_points = np.arange(current_pos - search_length, current_pos + search_length, resolution)

        for idx, final_pos in enumerate(scan_points):
            self.controller.send_command("{} {}".format(motor, final_pos - current_pos))
            if idx == 0:
                # self.wait_for_motors_manual([final_pos, self.monochromator_steps[1]], 'B')
                self.motion_control.wait_for_motors()
            scan_data.append([int(final_pos), 6000-int(self.read_ldr0())])
            current_pos = final_pos
        
        return scan_data
    
    @property
    def current_laser_wavenumber(self):
        '''Takes the current laser wavelength and calculates the absolute wavenumbers.'''
        return 10_000_000/self.laser_wavelength[0]
    
    @property
    def current_monochromator_wavenumber(self):
        '''Takes the current grating wavelength and calculates the absolute wavenumbers.'''
        return 10_000_000/self.monochromator_wavelength[0]

    @property
    def laser_steps(self):
        return self.motion_control._laser_steps
    
    @laser_steps.setter
    def laser_steps(self, value):
        valid_steps = True
        try:
            value = [int(x) for x in value]
            if not all(isinstance(x, int) for x in value) and len(value) != 4:
                print('Invalid laser steps')
                valid_steps = False
        except ValueError:
            print('Invalid laser steps')

        if valid_steps is False:
            return self.motion_control._laser_steps
        else:
            self.motion_control._laser_steps = value

    @property
    def monochromator_steps(self):
        return self.motion_control._monochromator_steps
    
    @monochromator_steps.setter
    def monochromator_steps(self, value):
        valid_steps = True
        try:
            value = [int(x) for x in value]
            if not all(isinstance(x, int) for x in value) and len(value) != 4:
                print('Invalid grating steps')
                valid_steps = False
        except ValueError:
            print('Invalid grating steps')

        if valid_steps is False:
            return self.motion_control._grating_steps
        else:
            self.motion_control._grating_steps = value

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
        '''Closes the camera connection.'''
        self.camera.close_camera()

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
        return self.motion_control.get_laser_motor_positions()
    
    @ui_callable
    def get_monochromator_motor_positions(self):
        '''Get the current positions of the grating motors.'''
        return self.motion_control.get_monochromator_motor_positions()
    
    @ui_callable
    def go_to_wavelength_all(self, wavelength, shift=True):
        self.go_to_laser_wavelength(wavelength)
        # raman_shift = self.calculate_raman_shift_wavelength(wavelength)
        if shift is True:
            
            self.go_to_wavenumber(self.current_shift)
        else:
            self.go_to_monochromator_wavelength(wavelength)

        self.go_to_spectrometer_wavelength(wavelength)

    @ui_callable
    def go_to_spectrometer_wavelength(self, wavelength):
        '''Moves the spectrometer to the specified wavelength.'''
        self.interface.spectrometer.go_to_wavelength(wavelength)

    @ui_callable
    def reference_calibration(self, steps=None, shift=True):
        '''Used to reference the current motor position to the laser wavelength, as defined by the current calibration. Measure a spectrum on the TRIAX and enter the stepper motor position and pixel count of the peak wavelength here. In the future, this will be automated with a peak detection algorithm.'''
        # Instructions: Ensure that the entire system is well aligned, and that the stepper motors are in the correct positions relative to one another for passing the laser wavelength to the spectrograph.
        # Centre the laser peak in pixel 50 of the CCD. Enter the stepper motor position here.
        # correct for current Raman shift (usually zero, but might be different if performing Raman measurements)
            
        if steps is None:
            steps = self.get_spectrometer_position()
        true_wavelength_laser = self.calibrations.triax_steps_to_wl(float(steps))
        print('True wavelength: {}. Shifting motor positions to true wavelength'.format(true_wavelength_laser))
        
        if shift is True:
            grating_wavelength = (10_000_000/true_wavelength_laser) - self.current_shift
            # grating_wavelength = self.current_laser_wavenumber - self.current_shift
            true_wavelength_grating = 10_000_000/grating_wavelength
        else:
            true_wavelength_grating = true_wavelength_laser


        l1_target = round(self.calibrations.wl_to_l1(true_wavelength_laser))
        l2_target = round(self.calibrations.wl_to_l2(true_wavelength_laser))
        g1_target = round(self.calibrations.wl_to_g1(true_wavelength_grating))
        g2_target = round(self.calibrations.wl_to_g2(true_wavelength_grating))

        #  #378617

        self.set_absolute_positions_A(f'{l1_target},{l2_target},0,0')
        self.set_absolute_positions_B(f'{g1_target},{g2_target},0,0')

        laser_pos = self.get_laser_motor_positions()
        grating_pos = self.get_monochromator_motor_positions()

        if l1_target == laser_pos[0] and l2_target == laser_pos[1]:
            print('Laser motors successfully calibrated')
        else:
            print('Error calibrating laser motors')
            print('Expected: {}, {}'.format(l1_target, l2_target))
            print('Actual: {}, {}'.format(laser_pos[0], laser_pos[1]))
        
        if g1_target == grating_pos[0] and g2_target == grating_pos[1]:
            print('Grating motors successfully calibrated')
        else:
            print('Error calibrating grating motors')
            print('Expected: {}, {}'.format(g1_target, g2_target))
            print('Actual: {}, {}'.format(grating_pos[0], grating_pos[1]))

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

    @ui_callable
    def set_absolute_positions_A(self, positions):
        print("Setting absolute positions A: {}".format(positions))
        response = self.controller.send_command('setposA {}'.format(positions))
    
    @ui_callable
    def set_absolute_positions_B(self, positions):
        print("Setting absolute positions B: {}".format(positions))
        response = self.controller.send_command('setposB {}'.format(positions))
    
    def _generate_calibrations(self):
        return Calibration(self)
    
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
    
    # def get_steps_calibration_wavelength(self, calibration, wavelength):
    #     '''Determines the motor steps for a given wavelength using the calibration function.'''
    #     return int(round(calibration(wavelength)))

    def calculate_laser_steps_to_wavelength(self, target_wavelength):
        '''Calculates the number of steps needed to move the laser motors to the target wavelength.'''
        current_pos = self.get_laser_motor_positions()
        target_steps = [i for i in self.laser_steps]

        target_steps[0] = round(self.calibrations.wl_to_l1(target_wavelength))
        target_steps[1] = round(self.calibrations.wl_to_l2(target_wavelength))

        # implement new logic for other motors here
        print('Current laser position: {}'.format(current_pos))
        print('Target laser position: {}'.format(target_steps))
        move_steps = [i - j for i, j in zip(target_steps, current_pos)]
        if all(x == 0 for x in move_steps):
            print('Laser already at target position')

        return move_steps, target_steps
    
    def move_laser_motors(self, move_steps, backlash=True):
        '''Moves the laser motors the specified number of steps.'''
        self.motion_control.move_motors(move_steps, 'A')
        if backlash is True:
            self.motion_control.backlash_correction(move_steps, 'A')

    
    @ui_callable
    def go_to_laser_wavelength(self, wavelength):

        wavelength = self.check_laser_wavelength(wavelength)
        if wavelength is False:
            return False
        
        self.close_mono_shutter()
        
        move_steps, target_steps = self.calculate_laser_steps_to_wavelength(wavelength)
        if all(x == 0 for x in move_steps):
            return
        self.move_laser_motors(move_steps)
        self.motion_control.confirm_motor_positions(target_steps, 'A') # TODO: Refactor this to use the motion control class
        # confirm motor positions updates the current motor positions, so we can use them to calculate the wavelength. The call is necessary for the UI to update the current positions.
        new_wavelength = self.calculate_laser_wavelength(self.laser_steps)

        self.laser_safety_check()
        self.open_mono_shutter()
        print('Laser excitation at {} nm'.format(new_wavelength[0]))


    @ui_callable
    def go_to_monochromator_wavelength(self, wavelength):

        wavelength = self.check_monochromator_wavelength(wavelength)
        if wavelength is False:
            return False
        
        self.close_mono_shutter()
        move_steps, target_steps = self.calculate_monochromator_steps_to_wavelength(wavelength)
        if all(x == 0 for x in move_steps):
            return
        
        self.move_monochromator_motors(move_steps)
        self.motion_control.confirm_motor_positions(target_steps, 'B')
        new_wavelength = self.calculate_monochromator_wavelength(self.monochromator_steps)

        self.laser_safety_check()
        self.open_mono_shutter()
        print(f'Monochromator set to {new_wavelength[0]} nm')

    def check_monochromator_wavelength(self, wavelength):
        wavelength = string_to_float(wavelength)
        if not self.check_hard_limits(wavelength, self.hard_limits['monochromator_wavelength']):
            print('Wavelength out of range. Pick a wavelength between {} and {} nm'.format(
                *self.hard_limits['monochromator_wavelength']))
            return False
        return wavelength

    def calculate_monochromator_steps_to_wavelength(self, target_wavelength):
        current_pos = self.get_monochromator_motor_positions()
        target_steps = [i for i in self.monochromator_steps]

        target_steps[0] = round(self.calibrations.wl_to_g1(target_wavelength))
        target_steps[1] = round(self.calibrations.wl_to_g2(target_wavelength))

        print('Current monochromator position: {}'.format(current_pos))
        print('Target monochromator position: {}'.format(target_steps))

        move_steps = [i - j for i, j in zip(target_steps, current_pos)]

        if all(x == 0 for x in move_steps):
            print('Monochromator already at target position')

        return move_steps, target_steps

    def move_monochromator_motors(self, move_steps, backlash=True):
        self.motion_control.move_motors(move_steps, 'B')
        if backlash is True:
            self.motion_control.backlash_correction(move_steps, 'B')

    def calculate_monochromator_wavelength(self, current_pos=None):
        if current_pos is None:
            current_pos = [i for i in self.get_monochromator_motor_positions()]

        self.monochromator_steps = current_pos
        g1_pos, g2_pos = current_pos[0], current_pos[1]
        g1_wavelength = round(self.calibrations.g1_to_wl(g1_pos), 4)
        g2_wavelength = round(self.calibrations.g2_to_wl(g2_pos), 4)

        self.monochromator_wavelength[0] = g1_wavelength
        self.monochromator_wavelength[1] = g2_wavelength
        return self.monochromator_wavelength

    @ui_callable
    def close_mono_shutter(self):
        self.controller.send_command('gsh on')

    @ui_callable
    def open_mono_shutter(self):
        self.controller.send_command('gsh off')




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

        self.spectrometer_wavelength = self.calibrations.triax_steps_to_wl(self.spectrometer_position) # TODO: rename triax_steps_to_wl to spectrometer_steps_to_wl - requires change to calibration files and will be breaking until otherwise completed
        return self.spectrometer_wavelength
    
    def report_all_current_positions(self):
        '''Formats and prints the current positions of the microscope.'''

        l1_wavelength, l2_wavelength, _, _ = [round(x, 2) for x in self.laser_wavelength]
        g1_wavelength, g2_wavelength, g3_wavelength, g4_wavelength = [round(x, 2) for x in self.monochromator_wavelength]
        spectrometer_wavelength = round(self.spectrometer_wavelength, 2)

        print('laser pos: {}'.format(self.laser_steps))
        print('monochromator pos: {}'.format(self.monochromator_steps))
        print('triax pos: {}'.format(self.spectrometer_position))

        print('triax wavelength: {}'.format(spectrometer_wavelength))
        print('l1 wavelength: {}'.format(l1_wavelength))
        print('l2 wavelength: {}'.format(l2_wavelength))
        print('g1 wavelength: {}'.format(g1_wavelength))
        print('g2 wavelength: {}'.format(g2_wavelength))
        print('Raman shift: {}'.format(self.current_shift))

        return 
    
    def calculate_laser_wavelength(self, current_pos=None):
        if current_pos is None:
            current_pos = [i for i in self.get_laser_motor_positions()]

        self.laser_steps = current_pos
        l1_pos = current_pos[0]
        l2_pos = current_pos[1]
        l1_wavelength = round(self.calibrations.l1_to_wl(l1_pos), 4)
        l2_wavelength = round(self.calibrations.l2_to_wl(l2_pos), 4)

        self.laser_wavelength[0] = l1_wavelength
        self.laser_wavelength[1] = l2_wavelength
        return self.laser_wavelength

    @ui_callable
    def go_to_wavenumber(self, wavenumber):
        try:
            wavenumber = float(wavenumber)
        except ValueError:
            print('Invalid value for wavenumber - use a number')
            return
        if self.laser_wavelength is None:
            self.get_all_current_positions()
        
        # ;
        laser_wavenumber = self.current_laser_wavenumber
        # 
        wave = laser_wavenumber - wavenumber
        new_wavelength = 10_000_000/wave
        self.go_to_monochromator_wavelength(new_wavelength)
        self.current_shift = wavenumber
        
        print('Moving to wavenumber: {} for {} nm excitation'.format(wavenumber, self.laser_wavelength[0]))

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
        from tuscen.TUCam import get_camera_gain_attributes

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
        
        target_steps = round(self.interface.microscope.calibrations.wl_to_triax_steps(wavelength))
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
    def __init__(self, interface, simulate=False):
        super().__init__()
        self.interface = interface
        self.simulate = simulate
        self.command_functions = {
            'move': self.move_stage,
            'home': self.home_stage
        }

        self._integrity_checker()

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
    def __init__(self, interface, simulate=False):
        super().__init__()
        self.interface = interface
        self.simulate = simulate
        self.command_functions = {
            'set_wavelength': self.set_wavelength,
            'get_wavelength': self.get_wavelength
        }

        self._integrity_checker()

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
    def __init__(self, interface, simulate=False):
        super().__init__()
        self.interface = interface
        self.simulate = simulate
        self.command_functions = {
            'set_power': self.set_power,
            'get_power': self.get_power
        }

        self._integrity_checker()

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