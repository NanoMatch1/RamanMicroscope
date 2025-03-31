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
        self.calibrationDir = os.path.join(self.scriptDir, 'calibrations')
        self.generate_calibrations()
    
    def _load_calibrations(self):
        """
        Load the calibration data from the calibrations_main.json file.
        """
        with open(os.path.join(self.scriptDir, 'calibrations', 'calibrations_main.json'), 'r') as f:
            calibrations = json.load(f)
            print('Calibrations loaded from file')
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

    def wl_to_steps(self, wavelength, action_group):
        '''Convert wavelength to motor steps. Takes a dictionary of motors and their wavelengths'''
        steps_dict = {}

        for motor in action_group.keys():
            calibration_name = 'wl_to_{}'.format(motor)
            if hasattr(self, calibration_name):
                calibration = getattr(self, calibration_name)
                steps_dict[motor] = calibration(wavelength)
            else:
                print(f'{motor} not found in calibrations')
                steps_dict[motor] = None

        return steps_dict
    
    def steps_to_wl(self, motor_steps: dict):
        '''Convert motor steps to wavelength. Takes a dictionary of motor labels ('l1', ...) and their steps'''
        wl_dict = {}

        for motor, steps in motor_steps.items():
            calibration_name = '{}_to_wl'.format(motor)
            if hasattr(self, calibration_name):
                calibration = getattr(self, calibration_name)
                wl_dict[motor] = calibration(steps)
            else:
                print(f'{motor} not found in calibrations')
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