import os
import numpy as np
import json
from types import SimpleNamespace

class PolySinModulation:
    def __init__(self, a2, a1, a0, A, B, C, D):
        """
        Initialize the polynomial and sinusoidal coefficients.
        Polynomial: a2*x^2 + a1*x + a0
        Sinusoidal modulation: A*sin(B*x + C) + D
        """
        self.a2 = a2
        self.a1 = a1
        self.a0 = a0
        self.A = A
        self.B = B
        self.C = C
        self.D = D

    def __call__(self, x):
        """
        Evaluate the polynomial + sinusoidal modulation at the given x value.
        """
        poly = self.a2 * x**2 + self.a1 * x + self.a0
        modulation = self.A * np.sin(self.B * x + self.C) + self.D
        return poly + modulation

    def __repr__(self):
        """
        String representation of the polynomial and sinusoidal components.
        """
        poly_part = f"{self.a2}*x^2 + {self.a1}*x + {self.a0}"
        sin_part = f"{self.A}*sin({self.B}*x + {self.C}) + {self.D}"
        return f"PolySinModulation: ({poly_part}) + ({sin_part})"

class LinSinModulation:
    '''Class for linear + sinusoidal modulation fit.'''
    def __init__(self, a1, a0, A, B, C, D):
        self.a1 = a1
        self.a0 = a0
        self.A = A
        self.B = B
        self.C = C
        self.D = D

    def __call__(self, x):
        linear = self.a1 * x + self.a0
        modulation = self.A * np.sin(self.B * x + self.C) + self.D
        return linear + modulation
    
    def __repr__(self):
        linear_part = f"{self.a1}*x + {self.a0}"
        sin_part = f"{self.A}*sin({self.B}*x + {self.C}) + {self.D}"
        return f"LinSinModulation: ({linear_part}) + ({sin_part})"
    

class LdrScan:


    def __init__(self, motor, scan_range, resolution):
        self.motor = motor
        self.scan_range = scan_range
        self.resolution = resolution

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

    def __call__(self):
        self.run_scan()
    
    def run_scan(self):
        pass

    
class Calibration:

    def __init__(self):
        self.scriptDir = os.path.dirname(os.path.abspath(__file__))
        self.calibrationDir = os.path.join(self.scriptDir, 'calibration')
        # self.generate_calibrations()

        self.mode_change_steps = 5000 # number of steps required for change from raman to image mode
        self.x_steps_per_micron = 100 # number of steps per micron for the x stage
        self.y_steps_per_micron = 100 # number of steps per micron for the y stage
        self.z_steps_per_micron = 100 # number of steps per micron for the z stage
    
    def _load_calibrations(self):
        """
        Load the calibration data from the calibrations_main.json file.
        """
        with open(os.path.join(self.scriptDir, 'calibration', 'calibrations_main.json'), 'r') as f:
            calibrations = json.load(f)
            print('Calibrations loaded from file')

        calibrations.update(self.load_triax_calibration())
        return calibrations
    
    def load_triax_calibration(self):
        """
        Load the triax calibration data from the triax_calibration.json file.
        """
        with open(os.path.join(self.scriptDir, 'calibration', 'triax_calibrations.json'), 'r') as f:
            calibrations = json.load(f)
            print('Triax calibrations loaded from file')
        return calibrations

    def generate_calibrations(self, report=False):
        self.all_calibrations = self._load_calibrations()
        # self.calibrations = SimpleNamespace()
        
        for name, calib in self.all_calibrations.items():
            if len(calib) == 7:
                print("Loading {} as poly_sin".format(name))
                self.__setattr__(name, PolySinModulation(*calib))
            if len(calib) == 6:
                print("Loading {} as poly_sin".format(name))
                self.__setattr__(name, LinSinModulation(*calib))
            else:
                print("Loading {} as poly1d".format(name))
                self.__setattr__(name, np.poly1d(calib))

        print("Calibrations successfully built.")

    def invert_calibrations(self):
        '''Inverts the calibrations for use in the controller. Takes a dictionary of motor names and their calibration functions'''
        for name, calib in self.all_calibrations.items():
            if len(calib) == 7:
                self.__setattr__(name, PolySinModulation(*calib) * -1)
            elif len(calib) == 6:
                self.__setattr__(name, LinSinModulation(*calib) * -1)
            else:
                self.__setattr__(name, np.poly1d(calib) * -1)

        print('Inverted calibrations successfully.')

    def load_master_calibration(self, microsteps=32):
        with open(os.path.join(self.scriptDir, 'calibration', 'master_calibration_microsteps_{}.json'.format(microsteps)), 'r') as f:
            calibrations = json.load(f)
            print('Master calibrations at {} microsteps loaded from file'.format(microsteps))

        # calibrations.update(self.load_triax_calibration())
        return calibrations
    
    def generate_master_calibration(self, microsteps=32):
        master_calibration = self.load_master_calibration(microsteps)

        for action_group, dataset in master_calibration.items():
            print("---> Loading {} calibrations".format(action_group))
            for name, calib in dataset.items():
                if len(calib) == 7:
                    print("Loading {} as poly_sin".format(name))
                    self.__setattr__(name, PolySinModulation(*calib))
                if len(calib) == 6:
                    print("Loading {} as poly_sin".format(name))
                    self.__setattr__(name, LinSinModulation(*calib))
                else:
                    print("Loading {} as poly1d".format(name))
                    self.__setattr__(name, np.poly1d(calib))
        
        print("Master calibrations successfully built.")

    def identify_microscope_mode(self, action_group):
        '''Identify if the microscope is in RamanMode or ImageMode based on the position of motor 2A (beamsplitters).'''
        if action_group['mode'] > 1000:
            self.mode = 'imagemode'
        else:
            self.mode = 'ramanmode'
        print(f'Microscope mode identified as {self.mode}')

        return self.mode
    
    def micron_to_steps(self, action_group):
        '''Convert microns to motor steps. Takes a dictionary of motors and their microns'''
        steps_dict = {}

        for motor in action_group.keys():
            if motor == 'x':
                steps_dict[motor] = round(action_group[motor] * self.x_steps_per_micron)
            elif motor == 'y':
                steps_dict[motor] = round(action_group[motor] * self.y_steps_per_micron)
            elif motor == 'z':
                steps_dict[motor] = round(action_group[motor] * self.z_steps_per_micron)
            else:
                print(f'{motor} not found in calibrations')
                steps_dict[motor] = action_group[motor]

        return steps_dict
    
    def steps_to_micron(self, action_group):
        '''Convert motor steps to microns. Takes a dictionary of motors and their steps'''
        micron_dict = {}

        for motor in action_group.keys():
            if motor == 'x':
                micron_dict[motor] = action_group[motor] / self.x_steps_per_micron
            elif motor == 'y':
                micron_dict[motor] = action_group[motor] / self.y_steps_per_micron
            elif motor == 'z':
                micron_dict[motor] = action_group[motor] / self.z_steps_per_micron
            else:
                print(f'{motor} not found in calibrations')
                micron_dict[motor] = action_group[motor]

        return micron_dict

    def wl_to_steps(self, wavelength, action_group):
        '''Convert wavelength to motor steps. Takes a dictionary of motors and their wavelengths'''
        steps_dict = {}

        for motor in action_group.keys():
            calibration_name = 'wl_to_{}'.format(motor)
            if hasattr(self, calibration_name):
                calibration = getattr(self, calibration_name)
                steps_dict[motor] = round(calibration(wavelength)) # round to nearest integer
            else:
                print(f'{motor} not found in calibrations')
                self.__dict__[calibration_name] = np.poly1d([0]) # default to zero
                steps_dict[motor] = 0

        return steps_dict
    
    def steps_to_wl(self, motor_steps: dict):
        '''Convert motor steps to wavelength. Takes a dictionary of motor labels ('l1', ...) and their steps'''
        wl_dict = {}

        # if 'triax' in motor_steps.keys():
        #     breakpoint()
        # g3 -2740 50 inside
        # IMPORTANT: triax steps at 805 nm = 142073

        for motor, steps in motor_steps.items():
            calibration_name = '{}_to_wl'.format(motor)
            if hasattr(self, calibration_name):
                calibration = getattr(self, calibration_name)
                wl_dict[motor] = calibration(steps)
            else:
                print(f'{motor} not found in calibrations')
                self.__dict__[calibration_name] = np.poly1d([0]) # default to zero
                wl_dict[motor] = None

        return wl_dict
    
    def ammend_calibrations(self, report=True):
        '''If an autocalibration has been performed, this function will update the current calibrations with the new data. Loads individual files'''
        json_files = [f for f in os.listdir(self.calibrationDir) if f.endswith('autocal.json')]


        if len(json_files) == 0:
            print('No autocalibration data found.')
            return
        
        report_dict = {}

        for file in json_files:

            with open(os.path.join(self.calibrationDir, file), 'r') as f:
                data = json.load(f)

            for name, calib in data.items():
                # print("Updating {} with autocalibration data".format(name))
                if len(calib) == 7:
                    # print("Loading {} as poly_sin".format(name))
                    report_dict[name] ='poly_sin'
                    self.all_calibrations[name] = calib
                    self.__setattr__(name, PolySinModulation(*calib))
                elif len(calib) == 6:
                    # print("Loading {} as lin_sin".format(name))
                    report_dict[name] = 'lin_sin'
                    self.all_calibrations[name] = calib
                    self.__setattr__(name, LinSinModulation(*calib))
                else:
                    # print("Loading {} as poly1d".format(name))
                    report_dict[name] = 'poly1d'
                    self.all_calibrations[name] = calib
                    self.__setattr__(name, np.poly1d(calib))

        if report:
            for key, value in report_dict.items():
                print(f'{key} updated as {value}')
        print('Calibrations updated with autocalibration data')
        print('-'*20)

    def update_monochromator_calibrations(self, report=True):
        '''Updates g3 and g4 calibrations using the final monochromator calibration'''

        try:
            with open(os.path.join(self.calibrationDir, 'monochromator_calibrations.json'), 'r') as f:
                data = json.load(f)
        except FileNotFoundError:
            print('No monochromator calibration data found.')
            return
        except Exception as e:
            print(f'Error loading monochromator calibration data: {e}')
            return

        report_dict = {}
        
        for name, calib in data.items():
            #TODO: refactor the generation code into a function

            if len(calib) == 7:
                # print("Loading {} as poly_sin".format(name))
                report_dict[name] ='poly_sin'
                self.all_calibrations[name] = calib
                self.__setattr__(name, PolySinModulation(*calib))
            elif len(calib) == 6:
                # print("Loading {} as lin_sin".format(name))
                report_dict[name] = 'lin_sin'
                self.all_calibrations[name] = calib
                self.__setattr__(name, LinSinModulation(*calib))
            else:
                # print("Loading {} as poly1d".format(name))
                report_dict[name] = 'poly1d'
                self.all_calibrations[name] = calib
                self.__setattr__(name, np.poly1d(calib))

        if report:
            for key, value in report_dict.items():
                print(f'{key} updated as {value}')
        print('Monochromator calibration added.')
        print('-'*20)


class ldrScans:

    def __init__(self):
        self.l2 = {
            'range': 150,
            'resolution': 5,
        }
        self.g1 = {
            'range': 150,
            'resolution': 5,
        }
        self.g2 = {
            'range': 150,
            'resolution': 5,
        }