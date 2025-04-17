import csv
import json
from collections import defaultdict
from dataclasses import dataclass
import scipy.optimize as opt


'''make a quick plot of calibration data'''

'''eventually, create a calibration routine that goes to each wavelength and sweeps the laser frequency across the ccd. Collect spectra, peakfit, extract peak centre, and use to calibrate more efficiently.'''

'''
from most recent calibration
370-751 (delta 400 steps on l1) (558 (d 200))
857.44,,,-3473,405000,414
872.646,,,-4473,415000,152
pix_diff = 262 pix = 4.1793 nm

currently 410000,558

delta = 15.206/-1000 (nm_per_laser_steps)
15.206-4.1793 nm = 11.0267 nm
11.0267 nm/10000 steps on TRIAX = 0.00110267 nm/step
'''

import matplotlib.pyplot as plt

# import files in data folder
import os
import sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'analysis-spectroscopy','analysis_spectroscopy'))

# from analysis_spectroscopy import dataset_analysis as asp

calibration_records = {

    'manual_measurements': {
        'nm_per_laser_step': 0.0158,
        'lamba_change_for_400_steps': 6.32,
        'nm_per_pixel': 4/400, # retrieved from recent calibration sweep
        # nm_per_step = 0
        'triax_steps': 410000,
        'nm_per_triax_step': 0.00110267
    }
}



# nm_per_pixel = 6.38064/400 # retrieved from recent calibration sweep
# # nm_per_step = 0
# triax_steps = 375000
# nm_per_triax_step = 0.00110267

# absolute = 802.5-(643*nm_per_pixel)
# new = absolute + (nm_per_triax_step*(410000-375000)) + (nm_per_pixel*558)

#662/469

#731.162-734.432 = -3.27 nm
#-3.27nm/200steps = -0.01635 nm/step
#293-660pix=-367
#0.0168557nm/pix*-367pix = -6.186 nm/3000 steps triax
# -0.002062 nm/step triax



laser_calibration = {}


def simple_sin_fit(xvalues, a, b, c, d):
    return a * np.sin(b * xvalues + c) + d

def polynomial_fit(xvalues, a, b, c):
    return a*xvalues**2 + b*xvalues + c

def poly_sin_modulation_fit(x, a2, a1, a0, A, B, C, D):
    # Polynomial part
    poly = a2 * x**2 + a1 * x + a0
    # Sinusoidal modulation part
    modulation = A * np.sin(B * x + C) + D
    return poly + modulation

def review_report():
    with open(os.path.join(os.path.dirname(__file__), 'calibration_report.json'), 'r') as f:
        data = json.load(f)
        for key, value in data.items():
            print(key)
            for k, v in value.items():
                print(k)
                print(v)
                # print('\n')

def r_squared(y_true, y_pred):
    '''Calculate R^2 (coefficient of determination) for a regression model.'''
    ss_res = np.sum((y_true - y_pred) ** 2)  # Residual sum of squares
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)  # Total sum of squares
    return 1 - (ss_res / ss_tot)

def rmse(y_true, y_pred):
    '''Calculate the root mean squared error for a regression model.'''
    return np.sqrt(np.mean((y_true - y_pred) ** 2))

def mae(y_true, y_pred):
    '''Calculate the mean absolute error for a regression model.'''
    return np.mean(np.abs(y_true - y_pred))

def residual_std(residuals):
    '''Calculate the standard deviation of residuals for a regression model.'''
    return np.std(residuals)

def adjusted_r_squared(y_true, y_pred, p):
    '''Calculate the adjusted R^2 (coefficient of determination) for a regression model.'''
    n = len(y_true)
    r2 = r_squared(y_true, y_pred)
    return 1 - (1 - r2) * (n - 1) / (n - p - 1)

@dataclass
class FitMetrics:
    '''Dataclass for fit quality metrics.'''
    r2: int
    rmse: int
    mae: int
    res_std: int


class Calibration:

    calib_dict = {
    'pixels_per_laser_step': -194/200,
    'nm_per_laser_step': -0.01635,
    'nm_per_pixel': -0.01635/-0.97, #0.0168557

    # 'nm_per_pixel': -6.32/400, # retrieved from recent calibration sweep
    # nm_per_step = 0
    'triax_steps': 375000,
    'nm_per_triax_step': -0.002062
    }

    initial_fit_parameters = {
        'wl_to_g1': {'poly': [0.001, 8, -0.007],
                     'sin': [-17.06930504,   0.08537372, -27.92235843,   0.70444867]},
        'g1_to_wl': {'poly': [0.00, 0.1, 800],
                    'sin': [-1.53840861,  0.00463291, -1.04822887, -0.15844918]},
        'wl_to_g2': {'poly': [0.001, -0.4, 850],
                     'sin': [5.87970348,   0.08537372, -27.92235843,   0.70444867]},
        'g2_to_wl': {'poly': [0.00, 1, 600],
                    'sin': [-1.07, 0.04, -7, 0]},

        }
    
    lower_bound = [-50, 0.075, -150, -100]
    upper_bound = [50, 0.1, 150, 100]
    

    def __init__(self, showplots=False):
        # self.data = data
        self.calibrationDir = os.path.join(os.path.dirname(__file__), 'calibration')
        self.dataDir = os.path.join(self.calibrationDir, 'motor_recordings')

        self.showplots = showplots
        self.calibrations = {}
        self.calibration_metrics = {}
        self.report_dict = {'initial': {}, 'subtractive': {}, 'additive': {}}
        self.load_calibration_file()
    
    def load_calibration_file(self, calibration_name='calibrations_main.json'):
        '''Load the existing calibration file and update the calibrations dictionary. This means new calibrations are added to the existing ones.'''
        if os.path.exists(os.path.join(self.calibrationDir, calibration_name)):
            with open(os.path.join(self.calibrationDir, 'calibrations_main.json'), 'r') as f:
                calibrations = json.load(f)
            
            self.calibrations.update(calibrations)
        
        else:
            print(f"Calibration file '{calibration_name}' not found. Proceeding with empty calibration data.")


    def load_motor_recordings(self, filename=None):
        if not filename:
            motor_recordings_file = os.path.join(self.dataDir, 'motor_recordings.json')
        else:
            motor_recordings_file = os.path.join(self.dataDir, filename)

        if not os.path.exists(motor_recordings_file):
            raise FileNotFoundError(f"Calibration file '{motor_recordings_file}' not found.")
        
        
        with open(motor_recordings_file, 'r') as f:
            data = json.load(f)
        
        self.full_data = self._flatten_calibration_data(data)
        
        return self.full_data
    
    def assign_calibration_data(self):
        # self.wavelength_data = self.full_data['wavelength']
        # self.laser_positions = self.full_data['laser_positions']
        # self.monochromator_positions = self.full_data['monochromator_positions']
        # self.triax_positions = self.full_data['triax_positions']
        self.__dict__.update(self.full_data)

    def _flatten_calibration_data(self, data):
        # Prepare output structure
        flattened = {}

        # Sort top-level keys numerically
        sorted_entries = [data[key] for key in sorted(data, key=int)]

        for entry in sorted_entries:
            for key, value in entry.items():
                if isinstance(value, dict):
                    if key not in flattened:
                        flattened[key] = defaultdict(list)
                    for subkey, subval in value.items():
                        flattened[key][subkey].append(subval)
                else:
                    if key not in flattened:
                        flattened[key] = []
                    flattened[key].append(value)

        # Convert nested defaultdicts to dicts
        for key in flattened:
            if isinstance(flattened[key], defaultdict):
                flattened[key] = dict(flattened[key])

        return flattened
    
    def sort_flattened_data_by_wavelength(self):
        # Get the sorted indices from the wavelength list
        sorted_indices = np.argsort(self.full_data["wavelength"])

        sorted_data = {}

        for key, value in self.full_data.items():
            if isinstance(value, list):
                # Directly sort 1D lists
                sorted_data[key] = [value[i] for i in sorted_indices]
            elif isinstance(value, dict):
                # Recursively sort each subkey in nested dictionaries
                sorted_data[key] = {
                    subkey: [subval[i] for i in sorted_indices]
                    for subkey, subval in value.items()
                }
            else:
                raise ValueError(f"Unsupported type for key {key}: {type(value)}")

        self.full_data = sorted_data
        return sorted_data

    def build_motor_sorted_array(self, flattened_data, motor_set):
        # Extract motor positions
        wavelengths = np.array(flattened_data["wavelength"])
        # TODO: enable calibration of a list of unique motors, independent of the motor_set label
        
        # Extract laser_positions keys in a stable order
        data_keys = list(flattened_data[motor_set].keys())

        # Stack laser position values
        data_values = np.column_stack([flattened_data["laser_positions"][k] for k in data_keys])

        # Combine into one array with wavelength first
        combined = np.column_stack((wavelengths, data_values))

        # Sort by wavelength (column 0)
        sorted_data = combined[np.argsort(combined[:, 0])]

        # Insert labels as first row — cast all to object to mix types
        labels = ["wavelength"] + data_keys
        labeled_array = np.vstack([labels, sorted_data.astype(object)])

        return labeled_array
    
    def load_pixel_calibration(self):
        pixel_cal_dir = os.path.join(os.path.dirname(__file__), 'triax_calibration')
        files = [file for file in os.listdir(pixel_cal_dir) if file.endswith('.json')]
        plt.close()

        cal_dict = {}
        for file in files:
            with open(os.path.join(pixel_cal_dir, file), 'r') as f:
                data = json.load(f)
                ex_lambda = float(file.split('_')[0])
                for wl, spectrum in data.items():
                    if spectrum[0] == 0:
                        spectrum[0] = spectrum[1]

                # breakpoint()

                cal_dict[ex_lambda] = data
                    # plt.plot(spectrum, label=f'{wl} nm')

        # print(data)
        # ordering = [x for x in cal_dict.keys()]
        # ordering.sort()
        # ordering = sorted(ordering, key=lambda x: float(x.split('_')[0]))

        # for excitation in ordering:

        #     # print(excitation)
        #     data = cal_dict[excitation]
        #     for triax_wavelength, spectrum in data.items():
        #         if spectrum[0] == 0:
        #             spectrum[0] = spectrum[1]
        #         # print(triax_wavelength)
        #         # print(spectrum) 
        #         # plt.plot(spectrum, label=f'{triax_wavelength} nm')
        #     # plt.legend()
        #     # plt.title(f'Excitation: {excitation} nm')
        #     # plt.show()
        # breakpoint()

        return cal_dict

    def triax_pixel_calibration(self, show=True, manual=True):
        # pixel_dict = self.load_pixel_calibration()  
        plt.close()

        def pixel_peakfit():
            pixel_cal_dir = os.path.join(os.path.dirname(__file__), 'triax_calibration')
            files = [file for file in os.listdir(pixel_cal_dir) if file.endswith('.json')]
            
            # for excitation, data in pixel_dict.items():
            pixel_peak_dict = {}
            for file in files:
                dataSet = asp.DataSet(pixel_cal_dir, [file])

                fileObj = dataSet.dataDict.get(file)
                # note: DataSet class is designed to work on a set of files, but the calibration dataset contains one file with a set of data. The following line is a workaround to access the data.
                dataSet.dataDict = fileObj.data
                # dataSet.dataDict = mask_data(dataSet.dataDict, data_mask) # mask data to select only the wavelengths of interest. Ranges specified in the data_mask_dict

                for cal_obj in dataSet.dataDict.values():
                    cal_obj._fix_zero_pixel()
                    # cal_obj._invert_data()
                    cal_obj._minimise_data()
                    # cal_obj._apply_smoothing(window_length=smoothing)
                    # cal_obj._plot_individual()
                # dataSet.plot_current()

                dataSet.baseline_all(show=False)
                
                peakfitting_info = {
                    'peak_list': [],
                    'peak_type': 'voigt_pseudo',
                    'peak_sign': 'positive',
                    'threshold': 0.4, # percentage of max intensity;
                    'peak_detect': 'all',
                    'copy_peaks': False,
                    'show_ui': False,
                } 
                dataSet._peakfit(peakfitting_info=peakfitting_info)
                # dataSet.plot_peaks()
                # dataSet.save_database(tagList='', seriesName='peakfit_autocal_{}'.format(motor_type))
                peakList = []
                for triax_wl, peakDict in dataSet.peakfitDict.items():
                    # breakpoint()
                    peaks = peakDict['peaks']
                    if peaks is None or len(peaks) == 0:
                        continue
                    if len(peaks) == 1:
                        # breakpoint()
                        peak = peaks[0][1]
                        peakList.append([triax_wl, peak])
                    else:
                        # breakpo
                        # peakList = sorted(peakList, key=lambda x: x[2])
                        peaks = sorted(peaks, key=lambda x: x[2])
                        # breakpoint()
                        peakList.append([triax_wl, peaks[-1][1]])


                # breakpoint()
                pixel_peak_dict[file.split('_')[0]] = peakList
            with open(os.path.join(os.path.dirname(__file__), 'pixel_cpeak_dict.json'), 'w') as f:
                json.dump(pixel_peak_dict, f)

        def load_pixel_peak_dict():
            with open(os.path.join(os.path.dirname(__file__), 'pixel_cpeak_dict.json'), 'r') as f:
                data = json.load(f)
            return data
        
        # pixel_peakfit()
        data = load_pixel_peak_dict()
        newArray = []
        steps_array = []

        p_wl_to_triax_steps = np.poly1d(self.calibrations['wl_to_triax_steps'])

        for excitation, datapoints in data.items():
            delta_pixel = datapoints[1][1] - datapoints[0][1]


            # print(delta_pixel)
            # data = np.array(data)
            newArray.append([float(excitation), delta_pixel])
            steps_array.append([p_wl_to_triax_steps(float(excitation)), delta_pixel]) 
            # plt.plot(data[:, 0], data[:, 1], label=f'{excitation} nm')

        newArray = np.array(newArray).astype(float)
        steps_array = np.array(steps_array).astype(float)
        fix, ax = plt.subplots(2, 1)
        ax[0].plot(newArray[:, 0], newArray[:, 1], marker='o')

        ax[1].plot(steps_array[:, 0], steps_array[:, 1], marker='o')
        plt.show()

        with open(os.path.join(os.path.dirname(__file__), 'dump_calibrations.json'), 'r') as f:
            calibrations = json.load(f)

        excitation_axis = newArray[:, 0]
        pixel_axis = newArray[:, 1]
        p_wl_to_triax_steps = np.poly1d(calibrations['wl_to_triax_steps'])
        setA = np.column_stack((excitation_axis, p_wl_to_triax_steps(excitation_axis)))
        stepDiff = []
        setA_data = setA[:, 1]
        for idx, x in enumerate(setA):
            if idx == len(setA)-1:
                continue
            steps = setA_data[idx+1] - setA_data[idx]
            # print(steps)
            stepDiff.append(steps)

        pixeldiff = []
        for idx, x in enumerate(newArray):
            if idx == len(newArray)-1:
                continue
            diff = newArray[idx+1][1] - newArray[idx][1]
            pixeldiff.append(diff)
        

        plt.plot(list(range(len(pixeldiff))), pixeldiff, label='pixeldiff', marker='o')
        plt.legend()
        plt.show()


        
        plt.plot(list(range(len(stepDiff))), stepDiff, label='stepdiff', marker='o')
        plt.legend()
        plt.show()
        
        p_wl_to_l1 = np.poly1d(calibrations['wl_to_l1'])
        setB = np.column_stack((excitation_axis, p_wl_to_l1(excitation_axis)))

        plt.plot(setB[:, 0], setB[:, 1], marker='o', label='l1 steps')
        plt.legend()
        plt.show()

        l1_diff = []
        setB_data = setB[:, 1]
        for idx, x in enumerate(setB):
            if idx == len(setB)-1:
                continue
            steps = setB_data[idx+1] - setB_data[idx]
            l1_diff.append(steps)

        l1_prime_diff = []
        for idx, x in enumerate(l1_diff):
            if idx == len(l1_diff)-1:
                continue
            diff = l1_diff[idx+1] - l1_diff[idx]
            l1_prime_diff.append(diff)

        plt.plot(list(range(len(l1_diff))), l1_diff, label='l1_diff', marker='o')
        plt.legend()
        plt.show()

        fix, ax = plt.subplots(2, 1)
        ax[0].plot(list(range(len(pixeldiff))), pixeldiff, label='pixeldiff', marker='o')
        ax[0].legend()
        ax[1].plot(list(range(len(l1_prime_diff))), l1_prime_diff, label='l1_prime_diff', marker='o')

        plt.show()
        
        plt.legend()
        plt.show()

        fix, ax = plt.subplots(2, 1)
        ax[0].plot(excitation_axis, p_wl_to_triax_steps(excitation_axis), label='wl to triax steps')
        ax[0].legend()
        ax[1].plot(newArray[:, 0], newArray[:, 1], marker='o', label='pixel diff')
        ax[1].legend()
        plt.show()



        breakpoint()
        return dataSet
    
    def calculate_fit_metrics(self, actual, model):
        # Fit quality metrics
        r2 = r_squared(actual, model)
        rmse_val = rmse(actual, model)
        mae_val = mae(actual, model)
        residuals = actual - model
        res_std = residual_std(residuals)

        return FitMetrics(r2, rmse_val, mae_val, res_std)

    def initial_wavelength_calibration(self, show=True):

        fig, ax = plt.subplots(2,2)

        wavelength_data = self.load_motor_recordings()
        wavelength, l1_steps = wavelength_data[:, 0], wavelength_data[:, 1]

        coeff_wl_to_l1 = np.polyfit(wavelength, l1_steps, 2)
        p_l1_steps = np.poly1d(coeff_wl_to_l1)

        y_pred = p_l1_steps(wavelength)
        residuals = l1_steps - y_pred
        residuals_scaled = (residuals/abs(l1_steps[0]-l1_steps[1])) * 100

        # Fit quality metrics
        fit_metrics = self.calculate_fit_metrics(l1_steps, y_pred)
        self.report_dict['initial']['wl_to_l1'] = (fit_metrics, coeff_wl_to_l1.tolist())

        coeff_l1_to_wl = np.polyfit(l1_steps, wavelength, 2)
        p_wavelength = np.poly1d(coeff_l1_to_wl)

        y_pred2 = p_wavelength(l1_steps)
        residuals2 = wavelength - y_pred2
        residuals_scaled2 = (residuals2/wavelength) * 100

        # Fit quality metrics
        fit_metrics2 = self.calculate_fit_metrics(wavelength, y_pred2)
        self.report_dict['initial']['l1_to_wl'] = (fit_metrics2, coeff_l1_to_wl.tolist())

        if show is True or self.showplots is True:
            ax[0, 0].scatter(wavelength, l1_steps, label='l1 steps')
            ax[0, 0].plot(wavelength, p_l1_steps(wavelength), label='wl to l1 fit', color='tab:purple')
            ax[1, 0].plot(wavelength, residuals_scaled, label='residuals', marker='o')
            ax[1, 0].set_ylabel('% of $\Delta_{steps}$')
            ax[1, 0].set_xlabel('Wavelength (nm)')
            ax[0, 0].set_title('Wavelength to L1 Steps')
            # ax[0, 0].plot(wavelength, test_eq, label='test fit', color='tab:orange')
            ax[0, 0].legend()
            ax[1, 0].legend()

            ax[0, 1].scatter(l1_steps, wavelength, label='wavelength')
            ax[0, 1].plot(l1_steps, p_wavelength(l1_steps), label='l1 to wl fit', color='tab:purple')
            ax[1, 1].plot(l1_steps, residuals_scaled2, label='residuals', marker='o')
            ax[1, 1].set_ylabel('% of $\Delta_{\lambda}$')
            ax[1, 1].set_xlabel('L1 Steps')
            ax[0, 1].set_title('L1 Steps to Wavelength')
            ax[0, 1].legend()
            ax[1, 1].legend()


            plt.show()

        return {'wl_to_l1': (coeff_wl_to_l1, fit_metrics), 'l1_to_wl': (coeff_l1_to_wl, fit_metrics2)}
    
    def save_report(self):
        # unpack report_dict into dict for json serialization
        newDict = {x: y for x, y in self.report_dict.items()}
        for mode, data in self.report_dict.items():
            for key, value in data.items():
                newDict[mode][key] = (value[0].__dict__, value[1])

        calibrationDir = os.path.join(os.path.dirname(__file__), 'calibrations')
        with open(os.path.join(calibrationDir, 'calibration_report.json'), 'w') as f:
            json.dump(newDict, f)
    
    def build_wavelength_axis(self, initial_wavelength_cal, l1_data):
        p_l1_to_wl = np.poly1d(initial_wavelength_cal['l1_to_wl'][0])
        self.laser_wavelength_axis = p_l1_to_wl(l1_data)
        print('New wavelength axis calculated: \n', self.laser_wavelength_axis)
        return self.laser_wavelength_axis

    def save_triax_calibrations(self):
        triax_cals = {key: value for key, value in self.calibrations.items() if 'triax' in key}

        with open(os.path.join(os.path.dirname(__file__), 'TRIAX_calibration.json'), 'w') as f:
            json.dump(triax_cals, f)

        print("Successfully saved TRIAX calibration data to 'TRIAX_calibration.json' file.")

    def save_all_calibrations(self):
        
        with open(os.path.join(self.calibrationDir, 'calibrations_main.json'), 'w') as f:
            json.dump(calibration.calibrations, f)

        print("Calibration complete: Successfully saved calibration data to 'calibrations_main.json' file.")

    def save_new_calibrations(self):
        with open(os.path.join(os.path.dirname(__file__), 'c-new.json'), 'w') as f:
            json.dump(self.calibrations, f)

        print("temporary calibrations saved")

    def calculate_triax_steps(self, steps_and_pixels: tuple, wavelength_axis=None, calib_dict=None):
        '''Perparatory calculation. Calculates the correct number of steps for each wavelength in the calibration data to be at pixel 50 on the spectrometer'''

        if wavelength_axis is None:
            wavelength_axis = self.laser_wavelength_axis

        if calib_dict is None:
            calib_dict = Calibration.calib_dict

        spectrometer_position = []

        spectrometer_steps, pixel_number = steps_and_pixels

        for idx, steps in enumerate(spectrometer_steps):
            wavelength = wavelength_axis[idx]
            pixel = pixel_number[idx]
            wavelength_from_50 = calib_dict['nm_per_pixel']*(50-pixel)
            triax_steps_to_shift = wavelength_from_50/calib_dict['nm_per_triax_step']
            print(pixel, triax_steps_to_shift, steps, wavelength)
            triax_actual_steps = steps + (wavelength_from_50/calib_dict['nm_per_triax_step'])
            spectrometer_position.append(triax_actual_steps)

        self.spectrometer_position = spectrometer_position

        return spectrometer_position



    def wavelength_to_triax(self, spectrometer_position=None, wavelength_axis=None, show=False):
        '''Calibration for using laser wavelength to calculate spectrometer position in TRIAX steps. '''
        
        if spectrometer_position is None:
            spectrometer_position = self.spectrometer_position

        if wavelength_axis is None:
            wavelength_axis = self.laser_wavelength_axis

        triax_steps = np.polyfit(wavelength_axis, spectrometer_position, 2)
        p_triax_steps = np.poly1d(triax_steps)
        
        y_pred = p_triax_steps(wavelength_axis)
        residuals = spectrometer_position - y_pred

        # Fit quality metrics
        fit_metrics = self.calculate_fit_metrics(spectrometer_position, y_pred)
        self.report_dict['initial']['wl_to_triax_steps'] = (fit_metrics, triax_steps.tolist())

        if show is True or self.showplots is True:
            fig, ax = plt.subplots(2, 1)
            ax[0].scatter(wavelength_axis, spectrometer_position, label='Triax Steps')
            ax[0].plot(wavelength_axis, y_pred, label=f'Triax Steps fit (R2={fit_metrics.r2:.8f})', color='tab:purple')
            ax[1].plot(wavelength_axis, residuals, label='Triax Steps residuals', marker='o')
            ax[0].set_title('Wavelength to Triax Steps')
            ax[0].legend()
            ax[1].legend()
            plt.show()


        self.calibration_metrics['wl_to_triax_steps'] = fit_metrics
        self.calibrations['wl_to_triax_steps'] = triax_steps.tolist()

        return triax_steps, fit_metrics



    def triax_steps_to_wavelength(self, spectrometer_position=None, wavelength_axis=None, show=False):
        '''Reverse calibration for calculating laser wavelength from spectrometer position in TRIAX steps.'''

        if spectrometer_position is None:
            spectrometer_position = self.spectrometer_position
        
        if wavelength_axis is None:
            wavelength_axis = self.laser_wavelength_axis

        steps_to_wavelength = np.polyfit(spectrometer_position, wavelength_axis, 2)
        p_steps_to_wavelength = np.poly1d(steps_to_wavelength)

        y_pred = p_steps_to_wavelength(spectrometer_position)
        residuals = wavelength_axis - y_pred
        residuals_scaled = (residuals/wavelength_axis) * 100

        # Fit quality metrics
        fit_metrics = self.calculate_fit_metrics(wavelength_axis, y_pred)
        self.report_dict['initial']['triax_steps_to_wl'] = (fit_metrics, steps_to_wavelength.tolist())

        if show is True or self.showplots is True:
            fig, ax = plt.subplots(2, 1)
            ax[0].scatter(spectrometer_position, wavelength_axis, label='Wavelength')
            ax[0].plot(spectrometer_position, y_pred, label=f'Wavelength fit (R2={fit_metrics.r2:.8f})', color='tab:purple')
            ax[1].plot(spectrometer_position, residuals, label='Wavelength residuals', marker='o')
            ax[0].set_title('Triax Steps to Wavelength')
            ax[0].legend()
            ax[1].legend()

            plt.show()

        self.calibration_metrics['triax_steps_to_wl'] = fit_metrics
        self.calibrations['triax_steps_to_wl'] = steps_to_wavelength.tolist()

        return steps_to_wavelength, fit_metrics
        
    def calibrate_motor_axis(self, axis_label, poly_order=2, show=False):
        """Calibrate a given motor axis (e.g., 'l1') against wavelength using polynomial fit."""
        
        if axis_label in self.full_data['laser_positions']:
            data_group = 'laser_positions'
        elif axis_label in self.full_data['monochromator_positions']:
            data_group = 'monochromator_positions'
        
        elif 'triax' in axis_label:
            data_group = 'triax_positions'
            axis_label = 'triax'
        else:
            raise ValueError(f"Axis label '{axis_label}' not found in full_data. Check label or motor_positions file.")

        # Extract axes
        wavelength_axis = np.array(self.full_data['wavelength'])
        if data_group == 'triax_positions':
            motor_steps = np.array(self.full_data[data_group])
        else:
            motor_steps = np.array(self.full_data[data_group][axis_label])

        # Forward fit: wavelength → motor steps
        fit_coeff_fwd = np.polyfit(wavelength_axis, motor_steps, poly_order)
        poly_fwd = np.poly1d(fit_coeff_fwd)
        pred_steps = poly_fwd(wavelength_axis)
        residuals_fwd = motor_steps - pred_steps
        metrics_fwd = self.calculate_fit_metrics(motor_steps, pred_steps)

        # Inverse fit: motor steps → wavelength
        fit_coeff_inv = np.polyfit(motor_steps, wavelength_axis, poly_order)
        poly_inv = np.poly1d(fit_coeff_inv)
        pred_wl = poly_inv(motor_steps)
        residuals_inv = wavelength_axis - pred_wl
        metrics_inv = self.calculate_fit_metrics(wavelength_axis, pred_wl)

        # Store results
        self.calibrations[f'wl_to_{axis_label}'] = fit_coeff_fwd.tolist()
        self.calibrations[f'{axis_label}_to_wl'] = fit_coeff_inv.tolist()
        self.calibration_metrics[f'wl_to_{axis_label}'] = metrics_fwd
        self.calibration_metrics[f'{axis_label}_to_wl'] = metrics_inv

        # Plot forward calibration if requested
        if show or getattr(self, 'showplots', False):
            fig, ax = plt.subplots(2, 1)
            ax[0].scatter(wavelength_axis, motor_steps, label=f'{axis_label} steps', color='black')
            ax[0].plot(wavelength_axis, pred_steps, label='Fit', color='tab:purple')
            ax[0].set_ylabel('Steps')
            ax[0].set_title(f'Wavelength to {axis_label.upper()} Calibration')
            ax[0].legend()

            ax[1].plot(wavelength_axis, residuals_fwd, label='Residuals', marker='o')
            ax[1].set_ylabel('Residuals')
            ax[1].set_xlabel('Wavelength (nm)')
            ax[1].legend()
            plt.tight_layout()
            plt.show()

        return {
            'forward': {
                'coeff': fit_coeff_fwd,
                'metrics': metrics_fwd,
                'poly': poly_fwd,
            },
            'inverse': {
                'coeff': fit_coeff_inv,
                'metrics': metrics_inv,
                'poly': poly_inv,
            }
        }
    
    def triax_calibration_low_res(self, poly_order=2):
        """Calibrate the TRIAX motor axis against wavelength using polynomial fit."""
        self.calibrate_motor_axis('triax', poly_order=poly_order, show=False)
        breakpoint()

        pass

    def monochromator_calibration(self, poly_order=2, show=False):
        """Final monochromator calibration to overlay on the grating axis. Required due to misalignment of G1 and G2 wrt the monochromator."""
        
        g3_coefficients = self.calibrate_motor_axis('g3', poly_order=poly_order, show=show)
        g4_coefficients = self.calibrate_motor_axis('g4', poly_order=poly_order, show=show)

        self.save_monochromator_calibrations()

    def save_triax_calibrations(self):
        """Save the TRIAX calibration coefficients to a JSON file."""
        triax_calibrations = {key:value for key, value in self.calibrations.items() if 'triax' in key}

        with open(os.path.join(self.calibrationDir, 'triax_calibrations.json'), 'w') as f:
            json.dump(triax_calibrations, f)

        print("TRIAX calibration data saved successfully.")


    def save_monochromator_calibrations(self, keys=['g3', 'g4']):
        """Save the monochromator calibration coefficients to a JSON file."""
        monochromator_calibrations = {key:value for key, value in self.calibrations.items() if any(k in key for k in keys)}

        with open(os.path.join(self.calibrationDir, 'monochromator_calibrations.json'), 'w') as f:
            json.dump(monochromator_calibrations, f)

        print("Monochromator calibration data saved successfully.")

        
    def wavelength_to_l1(self, l1_steps, poly_order=2, mode=None, show=False):
        '''Calibration for using laser wavelength to calculate L1 steps.'''

        if mode is None:
            assert mode in ['subtractive', 'additive'], 'Invalid mode. Must be either "subtractive" or "additive".'

        # if mode == 'subtractive':
        #     wavelength_axis = self.laser_wavelength_axis
        #     print('using laser wavelength axis')
        # elif mode == 'additive':
        #     wavelength_axis = self.grating_wavelength_axis
        #     print('using grating wavelength axis')

        wavelength_axis = self.laser_wavelength_axis

        fit_coeff_wavelength_to_l1 = np.polyfit(wavelength_axis, l1_steps, poly_order)
        p_wavelength_to_l1 = np.poly1d(fit_coeff_wavelength_to_l1)

        y_pred = p_wavelength_to_l1(wavelength_axis)
        residuals = l1_steps - y_pred

        # Fit quality metrics
        fit_metrics = self.calculate_fit_metrics(l1_steps, y_pred)
        self.report_dict[mode]['wl_to_l1'] = (fit_metrics, fit_coeff_wavelength_to_l1.tolist())

        if show is True or self.showplots is True:
            fig, ax = plt.subplots(2, 1)
            ax[0].scatter(wavelength_axis, l1_steps, label='L1 Steps')
            ax[0].plot(wavelength_axis, p_wavelength_to_l1(wavelength_axis), label='L1 Steps fit', color='tab:purple')
            residuals = l1_steps - p_wavelength_to_l1(wavelength_axis)
            ax[1].plot(wavelength_axis, residuals, label='L1 Steps residuals', marker='o')
            ax[0].set_title('Wavelength to L1 Steps')
            ax[0].legend()
            ax[1].legend()
            plt.show()

        self.calibration_metrics['wl_to_l1'] = fit_metrics
        self.calibrations['wl_to_l1'] = fit_coeff_wavelength_to_l1.tolist()

        return fit_coeff_wavelength_to_l1, fit_metrics
        


    def l1_to_wavelength(self, l1_steps, poly_order=2, mode=None, show=False):
        '''Reverse calibration for calculating laser wavelength from L1 steps.'''

        if mode is None:
            assert mode in ['subtractive', 'additive'], 'Invalid mode. Must be either "subtractive" or "additive".'

        # if mode == 'subtractive':
        #     wavelength_axis = self.laser_wavelength_axis
        #     print('using laser wavelength axis')
        # elif mode == 'additive':
        #     wavelength_axis = self.grating_wavelength_axis
        #     print('using grating wavelength axis')

        wavelength_axis = self.laser_wavelength_axis

        fit_coeff_l1_to_wavelength = np.polyfit(l1_steps, wavelength_axis, poly_order)
        p_l1_to_wavelength = np.poly1d(fit_coeff_l1_to_wavelength)

        y_pred = p_l1_to_wavelength(l1_steps)
        residuals = wavelength_axis - y_pred

        # Fit quality metrics
        fit_metrics = self.calculate_fit_metrics(wavelength_axis, y_pred)
        self.report_dict[mode]['l1_to_wl'] = (fit_metrics, fit_coeff_l1_to_wavelength.tolist())

        if show is True or self.showplots is True:
            fig, ax = plt.subplots(2, 1)
            ax[0].scatter(l1_steps, wavelength_axis, label='Wavelength')
            ax[0].plot(l1_steps, p_l1_to_wavelength(l1_steps), label='Wavelength fit', color='tab:purple')
            residuals = wavelength_axis - p_l1_to_wavelength(l1_steps)
            ax[1].plot(l1_steps, residuals, label='Wavelength residuals', marker='o')
            ax[0].set_title('L1 Steps to Wavelength')
            ax[0].legend()
            ax[1].legend()
            plt.show()

        self.calibration_metrics['l1_to_wl'] = fit_metrics
        self.calibrations['l1_to_wl'] = fit_coeff_l1_to_wavelength.tolist()

        return fit_coeff_l1_to_wavelength, fit_metrics



    def wavelength_to_l2(self, l2_steps, poly_order=2, mode=None, show=False):
        '''Calibration for using laser wavelength to calculate L2 steps.'''

        assert mode in ['subtractive', 'additive'], 'Invalid mode. Must be either "subtractive" or "additive".'

        # if mode == 'subtractive':
        #     wavelength_axis = self.laser_wavelength_axis
        #     print('using laser wavelength axis')
        # elif mode == 'additive':
        #     wavelength_axis = self.grating_wavelength_axis
        #     print('using grating wavelength axis')

        wavelength_axis = self.laser_wavelength_axis

        fit_coeff_wavelength_to_l2 = np.polyfit(wavelength_axis, l2_steps, poly_order)
        p_wavelength_to_l2 = np.poly1d(fit_coeff_wavelength_to_l2)

        y_pred = p_wavelength_to_l2(wavelength_axis)
        residuals = l2_steps - y_pred

        # Fit quality metrics
        fit_metrics = self.calculate_fit_metrics(l2_steps, y_pred)
        self.report_dict[mode]['wl_to_l2'] = (fit_metrics, fit_coeff_wavelength_to_l2.tolist())

        if show is True or self.showplots is True:
            fig, ax = plt.subplots(2, 1)
            ax[0].scatter(wavelength_axis, l2_steps, label='L2 Steps')
            ax[0].plot(wavelength_axis, p_wavelength_to_l2(wavelength_axis), label='L2 Steps fit', color='tab:purple')
            residuals = l2_steps - p_wavelength_to_l2(wavelength_axis)
            ax[1].plot(wavelength_axis, residuals, label='L2 Steps residuals', marker='o')
            ax[0].set_title('Wavelength to L2 Steps')
            ax[0].legend()
            ax[1].legend()
            plt.show()

        self.calibration_metrics['wl_to_l2'] = fit_metrics
        self.calibrations['wl_to_l2'] = fit_coeff_wavelength_to_l2.tolist()

        return fit_coeff_wavelength_to_l2, fit_metrics
        
    def l2_to_wavelength(self, l2_steps, poly_order=2, mode=None, show=False):
        '''Reverse calibration for calculating laser wavelength from L2 steps.'''

        assert mode in ['subtractive', 'additive'], 'Invalid mode. Must be either "subtractive" or "additive".'

        # if mode == 'subtractive':
        #     wavelength_axis = self.laser_wavelength_axis
        #     print('using laser wavelength axis')
        # elif mode == 'additive':
        #     wavelength_axis = self.grating_wavelength_axis
        #     print('using grating wavelength axis')

        wavelength_axis = self.laser_wavelength_axis

        fit_coeff_l2_to_wavelength = np.polyfit(l2_steps, wavelength_axis, poly_order)
        p_l2_to_wavelength = np.poly1d(fit_coeff_l2_to_wavelength)

        y_pred = p_l2_to_wavelength(l2_steps)
        residuals = wavelength_axis - y_pred

        # Fit quality metrics
        fit_metrics = self.calculate_fit_metrics(wavelength_axis, y_pred)
        self.report_dict[mode]['l2_to_wl'] = (fit_metrics, fit_coeff_l2_to_wavelength.tolist())

        if show is True or self.showplots is True:
            fig, ax = plt.subplots(2, 1)
            ax[0].scatter(l2_steps, wavelength_axis, label='Wavelength')
            ax[0].plot(l2_steps, p_l2_to_wavelength(l2_steps), label='Wavelength fit', color='tab:purple')
            residuals = wavelength_axis - p_l2_to_wavelength(l2_steps)
            ax[1].plot(l2_steps, residuals, label='Wavelength residuals', marker='o')
            ax[0].set_title('L2 Steps to Wavelength')
            ax[0].legend()
            ax[1].legend()
            plt.show()

        self.calibration_metrics['l2_to_wl'] = fit_metrics
        self.calibrations['l2_to_wl'] = fit_coeff_l2_to_wavelength.tolist()

        return fit_coeff_l2_to_wavelength, fit_metrics
    
    def wavelength_to_g2_tester(self, g2_steps, poly_order=2, mode=None, show=False):
        '''Calibration for using laser wavelength to calculate G2 steps.'''

        assert mode in ['subtractive', 'additive'], 'Invalid mode. Must be either "subtractive" or "additive".'

        if mode == 'subtractive':
            wavelength_axis = self.laser_wavelength_axis
            print('using laser wavelength axis')
        elif mode == 'additive':
            wavelength_axis = self.grating_wavelength_axis
            print('using grating wavelength axis')
        

        # Calculate the polynomial fit for wavelength to g2 steps
        fit_coeff_wavelength_to_g2 = np.polyfit(wavelength_axis, g2_steps, poly_order)
        p_wavelength_to_g2 = np.poly1d(fit_coeff_wavelength_to_g2)

        y_pred = p_wavelength_to_g2(wavelength_axis)
        residuals = g2_steps - y_pred
        fit_metrics_poly = self.calculate_fit_metrics(g2_steps, y_pred)

        # Fit a sinusoidal correction to the residuals
        sin_fit_coeff, pcov = opt.curve_fit(simple_sin_fit, wavelength_axis, residuals, p0=Calibration.initial_fit_parameters['wl_to_g2']['sin'])
        y_pred_sin = simple_sin_fit(wavelength_axis, *sin_fit_coeff)
        sin_residuals = residuals - simple_sin_fit(wavelength_axis, *sin_fit_coeff)
        fit_metrics_sin = self.calculate_fit_metrics(residuals, y_pred_sin)
        polysin_model = lambda x: p_wavelength_to_g2(x) + simple_sin_fit(x, *sin_fit_coeff)

        # Fit quality metrics
        total_y_pred = polysin_model(wavelength_axis)
        total_residuals = g2_steps - total_y_pred
        fit_metrics_total = self.calculate_fit_metrics(g2_steps, total_y_pred)

        # Calculate a fit for the polynomial with sinusoidal modulation
        initial_fit_params = Calibration.initial_fit_parameters['wl_to_g2']['poly'].extend(Calibration.initial_fit_parameters['wl_to_g2']['sin'])
        psm_fit_coeff, pcov = opt.curve_fit(poly_sin_modulation_fit, wavelength_axis, g2_steps, p0=initial_fit_params)
        psm_y_pred = poly_sin_modulation_fit(wavelength_axis, *psm_fit_coeff)
        residuals_psm = g2_steps - psm_y_pred
        fit_metrics_psm = self.calculate_fit_metrics(g2_steps, psm_y_pred)
        psm_fit = lambda x: poly_sin_modulation_fit(x, *psm_fit_coeff)

        # List fit metrics
        print('Poly fit', fit_metrics_poly.__dict__)
        print('Sin correction', fit_metrics_sin.__dict__)
        print('Total fit', fit_metrics_total.__dict__)
        print('Poly sin mod', fit_metrics_psm.__dict__)

        p_sin_fit = lambda x: simple_sin_fit(x, *sin_fit_coeff)

        # prepare interpolated axis for plotting
        interpolated_wavelength = np.linspace(wavelength_axis[0], wavelength_axis[-1], 1000)


        if show is True or self.showplots is True:
            fig, ax = plt.subplots(3, 2)
            ax[0, 0].scatter(wavelength_axis, g2_steps, label='G2 Steps')
            ax[0, 0].plot(wavelength_axis, p_wavelength_to_g2(wavelength_axis), label='G2 Steps fit', color='tab:purple')
            residuals = g2_steps - p_wavelength_to_g2(wavelength_axis)
            ax[1, 0].scatter(wavelength_axis, residuals, label='G2 Steps residuals', marker='o')
            ax[1, 0].plot(interpolated_wavelength, p_sin_fit(interpolated_wavelength), label='sin fit', color='tab:orange')
            ax[2, 0].plot(wavelength_axis, sin_residuals, label='sin residuals', marker='o')
            # ax[2].plot
            ax[2, 0].set_ylabel('sin Residuals')

            ax[0, 1].scatter(wavelength_axis, g2_steps, label='G2 Steps')
            ax[0, 1].plot(wavelength_axis, psm_fit(wavelength_axis), label='G2 Steps PSM fit', color='tab:purple')
            residuals = g2_steps - psm_fit(wavelength_axis)
            ax[2, 1].plot(wavelength_axis, residuals, label='G2 Steps PSM residuals', marker='o')


            ax[0, 0].set_title('Wavelength to G2 Steps {} - TESTER'.format(mode))
            ax[0, 0].legend()
            ax[1, 0].legend()
            ax[2, 0].legend()
            ax[0, 1].legend()
            ax[2, 1].legend()

            plt.show()

        # self.report_dict[mode]['wl_to_g2'] = (fit_metrics_psm, psm_fit_coeff.tolist())
        # self.calibration_metrics['wl_to_g2_{}'.format(mode)] = fit_metrics_psm
        # self.calibrations['wl_to_g2_{}'.format(mode)] = psm_fit_coeff.tolist()

        print("Saving poly fit for wl_to_g2")
        self.report_dict[mode]['wl_to_g2_{}'.format(mode)] = (fit_metrics_poly, fit_coeff_wavelength_to_g2.tolist())
        self.calibration_metrics['wl_to_g2_{}'.format(mode)] = fit_metrics_poly
        self.calibrations['wl_to_g2_{}'.format(mode)] = fit_coeff_wavelength_to_g2.tolist()

        return fit_coeff_wavelength_to_g2, fit_metrics_psm
    
    def wavelength_to_g1_tester(self, g1_steps, poly_order=2, mode=None, show=False):
        # Same as other but using new fitting methods
        lower_bound = [-np.inf, -np.inf, -np.inf, -50, 0.075, -150, -100]
        upper_bound = [np.inf, np.inf, np.inf, 50, 0.1, 150, 100]
        initial_guess = [0.001, 7, -7149, 17, 0.085, -24, 0]

        assert mode in ['subtractive', 'additive'], 'Invalid mode. Must be either "subtractive" or "additive".'

        if mode == 'subtractive':
            wavelength_axis = self.laser_wavelength_axis
            print('using laser wavelength axis')
        elif mode == 'additive':
            wavelength_axis = self.grating_wavelength_axis
            print('using grating wavelength axis')


        fit_coeff_wavelength_to_g1 = np.polyfit(wavelength_axis, g1_steps, poly_order)
        p_wavelength_to_g1 = np.poly1d(fit_coeff_wavelength_to_g1)
        y_pred = p_wavelength_to_g1(wavelength_axis)
        residuals = g1_steps - y_pred
        # Fit quality metrics
        fit_metrics = self.calculate_fit_metrics(g1_steps, y_pred)
        # self.report_dict[mode]['wl_to_g1'] = (fit_metrics, fit_coeff_wavelength_to_g1.tolist())

        # Fit a sinusoidal correction to the residuals
        # lower_bound = [-50, 0.03, -150, -100]
        # upper_bound = [50, 0.06, 150, 100]
        # initial_guess = [17, 0.085, -24, 0]
        sin_fit_coeff, pcov = opt.curve_fit(simple_sin_fit, wavelength_axis, residuals, p0=initial_guess[3:], bounds=(lower_bound[3:], upper_bound[3:]))
        y_pred_sin = simple_sin_fit(wavelength_axis, *sin_fit_coeff)
        sin_residuals = residuals - simple_sin_fit(wavelength_axis, *sin_fit_coeff)
        fit_metrics_sin = self.calculate_fit_metrics(residuals, y_pred_sin)
        polysin_model = lambda x: p_wavelength_to_g1(x) + simple_sin_fit(x, *sin_fit_coeff)
        simple_sin_model = lambda x: simple_sin_fit(x, *sin_fit_coeff)

        # Fit quality metrics
        total_y_pred = polysin_model(wavelength_axis)
        total_residuals = g1_steps - total_y_pred
        fit_metrics_total = self.calculate_fit_metrics(g1_steps, total_y_pred)

        interpolated_wavelength = np.linspace(wavelength_axis[0], wavelength_axis[-1], 1000)

        print(fit_coeff_wavelength_to_g1)
        print(sin_fit_coeff)
        # quick plot:
        fig, ax = plt.subplots(2, 1)
        ax[0].set_title('Wavelength to G1 Steps initial sin fit testing')
        ax[0].scatter(wavelength_axis, g1_steps, label='G1 Steps')
        ax[0].plot(wavelength_axis, p_wavelength_to_g1(wavelength_axis), label='G1 Steps fit', color='tab:purple')
        ax[1].plot(interpolated_wavelength, simple_sin_model(interpolated_wavelength), label='G1 Steps fit with sin correction', color='tab:orange')
        residuals = g1_steps - p_wavelength_to_g1(wavelength_axis)
        ax[1].scatter(wavelength_axis, residuals, label='G1 Steps residuals', marker='o')
        ax[1].plot(wavelength_axis, sin_residuals, label='sin residuals', marker='o')
        ax[0].legend()
        ax[1].legend()
        plt.show()

        # Calculate a fit for the polynomial with sinusoidal modulation
        lower_bound = [-np.inf, -np.inf, -np.inf].extend(Calibration.lower_bound)
        upper_bound = [np.inf, np.inf, np.inf].extend(Calibration.upper_bound)
        initial_guess = [0.001, 7, -7149, -17, 0.08, -27, 0]
        psm_fit_coeff, pcov = opt.curve_fit(poly_sin_modulation_fit, wavelength_axis, g1_steps, p0=initial_guess, bounds=(lower_bound, upper_bound))

        psm_y_pred = poly_sin_modulation_fit(wavelength_axis, *psm_fit_coeff)
        residuals_psm = g1_steps - psm_y_pred
        fit_metrics_psm = self.calculate_fit_metrics(g1_steps, psm_y_pred)
        psm_fit = lambda x: poly_sin_modulation_fit(x, *psm_fit_coeff)

        # List fit metrics
        print('Poly fit', fit_metrics.__dict__)
        print('Sin correction', fit_metrics_sin.__dict__)
        print('Total fit', fit_metrics_total.__dict__)
        print('Poly sin mod', fit_metrics_psm.__dict__)

        p_sin_fit = lambda x: simple_sin_fit(x, *sin_fit_coeff)

        # prepare interpolated axis for plotting

        if show is True or self.showplots is True:
            fig, ax = plt.subplots(3, 2)
            ax[0, 0].scatter(wavelength_axis, g1_steps, label='G1 Steps')
            ax[0, 0].plot(wavelength_axis, p_wavelength_to_g1(wavelength_axis), label='G1 Steps fit', color='tab:purple')
            residuals = g1_steps - p_wavelength_to_g1(wavelength_axis)
            ax[1, 0].scatter(wavelength_axis, residuals, label='G1 Steps residuals', marker='o')
            ax[1, 0].plot(interpolated_wavelength, p_sin_fit(interpolated_wavelength), label='sin fit', color='tab:orange')
            ax[2, 0].plot(wavelength_axis, sin_residuals, label='sin residuals', marker='o')
            
            ax[0, 1].scatter(wavelength_axis, g1_steps, label='G1 Steps')
            ax[0, 1].plot(wavelength_axis, psm_fit(wavelength_axis), label='G1 Steps PSM fit', color='tab:purple')
            residuals = g1_steps - psm_fit(wavelength_axis)
            ax[2, 1].plot(wavelength_axis, residuals, label='G1 Steps PSM residuals', marker='o')

            ax[0, 0].set_title('Wavelength to G1 Steps {} - TESTER'.format(mode))
            ax[0, 0].legend()
            ax[1, 0].legend()
            ax[2, 0].legend()
            ax[0, 1].legend()
            ax[2, 1].legend()

            plt.show()

        print("Saving PSM fit for wl_to_g1")
        self.report_dict[mode]['wl_to_g1_{}'.format(mode)] = (fit_metrics_psm, psm_fit_coeff.tolist())
        self.calibration_metrics['wl_to_g1_{}'.format(mode)] = fit_metrics_psm
        self.calibrations['wl_to_g1_{}'.format(mode)] = psm_fit_coeff.tolist()

        return fit_coeff_wavelength_to_g1, fit_metrics

    def g1_to_wavelength_tester(self, g1_steps, poly_order=2, mode=None, show=False):
        '''Reverse calibration for calculating laser wavelength from G1 steps.'''

        lower_bound = [-np.inf, -np.inf, -np.inf, -20, 0.002, -150, -100]
        upper_bound = [np.inf, np.inf, np.inf, 20, 0.01, 150, 100]
        initial_guess = [0.00, 0.05, 800, -1.53, 0.0045, -1, 0]

        assert mode in ['subtractive', 'additive'], 'Invalid mode. Must be either "subtractive" or "additive".'

        if mode == 'subtractive':
            wavelength_axis = self.laser_wavelength_axis
            print('using laser wavelength axis')
        elif mode == 'additive':
            wavelength_axis = self.grating_wavelength_axis
            print('using grating wavelength axis')



        fit_coeff_g1_to_wavelength = np.polyfit(g1_steps, wavelength_axis, poly_order)
        p_g1_to_wavelength = np.poly1d(fit_coeff_g1_to_wavelength)

        y_pred = p_g1_to_wavelength(g1_steps)
        residuals = wavelength_axis - y_pred

        # Fit quality metrics
        fit_metrics = self.calculate_fit_metrics(wavelength_axis, y_pred)

        # # quickplot of sin component
        # fig, ax = plt.subplots(2, 1)
        # ax[0].set_title('G1_wl_ sin fit testing')
        # # ax[0].scatter(g1_steps, wavelength_axis, label='Wavelength')
        # ax[0].scatter(g1_steps, residuals, label='Wavelength residuals')
        # test_sin = lambda x: simple_sin_fit(x, -1.2, 0.0045, 5.5, 0.3)
        # interpolated_g1_steps = np.linspace(g1_steps[0], g1_steps[-1], 1000)
        # ax[0].plot(interpolated_g1_steps, test_sin(interpolated_g1_steps), label='sin fit', color='tab:orange')
        # ax[1].plot(g1_steps, residuals - test_sin(g1_steps), label='sin residuals', marker='o')
        # plt.show()


        # fit a sinusoidal correction to the residuals
        sin_fit_coeff, pcov = opt.curve_fit(simple_sin_fit, g1_steps, residuals, p0=initial_guess[3:], bounds=(lower_bound[3:], upper_bound[3:]))
        
        y_pred_sin = simple_sin_fit(g1_steps, *sin_fit_coeff)
        sin_residuals = residuals - simple_sin_fit(g1_steps, *sin_fit_coeff)
        fit_metrics_sin = self.calculate_fit_metrics(residuals, y_pred_sin)
        polysin_model = lambda x: p_g1_to_wavelength(x) + simple_sin_fit(x, *sin_fit_coeff)

        # Fit quality metrics
        total_y_pred = polysin_model(g1_steps)
        total_residuals = wavelength_axis - total_y_pred
        fit_metrics_total = self.calculate_fit_metrics(wavelength_axis, total_y_pred)

        test_sin = lambda x: simple_sin_fit(x, -1.2, 0.005, 5, 0.3)

        # interpolated axis for plotting
        interpolated_g1_steps = np.linspace(g1_steps[0], g1_steps[-1], 1000)

        print(fit_coeff_g1_to_wavelength)
        print(sin_fit_coeff)
        # # plot
        fig, ax = plt.subplots(2, 1)
        ax[0].set_title('G1 Steps to Wavelength initial sin fit testing')
        ax[0].scatter(g1_steps, residuals, label='Wavelength residuals')
        ax[0].plot(interpolated_g1_steps, simple_sin_fit(interpolated_g1_steps, *sin_fit_coeff), label='sin fit', color='tab:orange')
        ax[1].plot(g1_steps, sin_residuals, label='sin residuals', marker='o')
        ax[1].plot(interpolated_g1_steps, simple_sin_fit(interpolated_g1_steps, *sin_fit_coeff), label='test sin fit', color='tab:orange')
        ax[1].set_ylabel('sin Residuals')
        ax[0].legend()
        ax[1].legend()
        plt.show()


        # Calculate a fit for the polynomial with sinusoidal modulation
        psm_fit_coeff, pcov = opt.curve_fit(poly_sin_modulation_fit, g1_steps, wavelength_axis, p0=initial_guess, bounds=(lower_bound, upper_bound))
        psm_y_pred = poly_sin_modulation_fit(g1_steps, *psm_fit_coeff)
        residuals_psm = wavelength_axis - psm_y_pred
        fit_metrics_psm = self.calculate_fit_metrics(wavelength_axis, psm_y_pred)
        psm_fit = lambda x: poly_sin_modulation_fit(x, *psm_fit_coeff)

        # List fit metrics
        print('Poly fit', fit_metrics.__dict__)
        print('Sin correction', fit_metrics_sin.__dict__)
        print('Total fit', fit_metrics_total.__dict__)
        print('Poly sin mod', fit_metrics_psm.__dict__)

        p_sin_fit = lambda x: simple_sin_fit(x, *sin_fit_coeff)

        # prepare interpolated axis for plotting
        interpolated_g1_steps = np.linspace(g1_steps[0], g1_steps[-1], 1000)


        if show is True or self.showplots is True:
            fig, ax = plt.subplots(3, 2)
            ax[0, 0].scatter(g1_steps, wavelength_axis, label='Wavelength')
            ax[0, 0].plot(interpolated_g1_steps, p_g1_to_wavelength(interpolated_g1_steps), label='Wavelength fit', color='tab:purple')
            residuals = wavelength_axis - p_g1_to_wavelength(g1_steps)
            ax[1, 0].scatter(g1_steps, residuals, label='Wavelength residuals', marker='o')
            ax[1, 0].plot(interpolated_g1_steps, p_sin_fit(interpolated_g1_steps), label='sin fit', color='tab:orange')
            ax[2, 0].plot(g1_steps, sin_residuals, label='sin residuals', marker='o')
            ax[2, 0].set_ylabel('sin Residuals')

            ax[0, 1].scatter(g1_steps, wavelength_axis, label='Wavelength')
            ax[0, 1].plot(interpolated_g1_steps, psm_fit(interpolated_g1_steps), label='Wavelength PSM fit', color='tab:purple')
            residuals = wavelength_axis - psm_fit(g1_steps)
            ax[2, 1].plot(g1_steps, residuals, label='Wavelength PSM residuals', marker='o')

            ax[0, 0].set_title('G1 Steps to Wavelength {} - TESTER'.format(mode))
            ax[0, 0].legend()
            ax[1, 0].legend()
            ax[2, 0].legend()
            ax[0, 1].legend()
            ax[2, 1].legend()

            plt.show()
        
        print('Saving PSM fit for g1_to_wl')
        self.report_dict[mode]['g1_to_wl_{}'.format(mode)] = (fit_metrics_psm, psm_fit_coeff.tolist())
        self.calibration_metrics['g1_to_wl_{}'.format(mode)] = fit_metrics_psm
        self.calibrations['g1_to_wl_{}'.format(mode)] = psm_fit_coeff.tolist()
        
        return fit_coeff_g1_to_wavelength, fit_metrics
    
    # ''Reverse calibration for calculating laser wavelength from G2 steps. Uses new PSM fitting method.'''
    def g2_to_wavelength_tester(self, g2_steps, poly_order=2, mode=None, show=False):
        '''Reverse calibration for calculating laser wavelength from G2 steps. Uses new PSM fitting method.'''

        assert mode in ['subtractive', 'additive'], 'Invalid mode. Must be either "subtractive" or "additive".'

        if mode == 'subtractive':
            wavelength_axis = self.laser_wavelength_axis
            print('using laser wavelength axis')
        elif mode == 'additive':
            wavelength_axis = self.grating_wavelength_axis
            print('using grating wavelength axis')

        fit_coeff_g2_to_wavelength = np.polyfit(g2_steps, wavelength_axis, poly_order)
        p_g2_to_wavelength = np.poly1d(fit_coeff_g2_to_wavelength)

        y_pred = p_g2_to_wavelength(g2_steps)
        residuals = wavelength_axis - y_pred

        # Fit quality metrics
        fit_metrics = self.calculate_fit_metrics(wavelength_axis, y_pred)
        # self.report_dict[mode]['g2_to_wl'] = (fit_metrics, fit_coeff_g2_to_wavelength.tolist())


        # Fit a sinusoidal correction to the residuals
        sin_fit_coeff, pcov = opt.curve_fit(simple_sin_fit, g2_steps, residuals, p0=[-1.07, 0.04, -7, 0])
        y_pred_sin = simple_sin_fit(g2_steps, *sin_fit_coeff)
        sin_residuals = residuals - simple_sin_fit(g2_steps, *sin_fit_coeff)
        fit_metrics_sin = self.calculate_fit_metrics(residuals, y_pred_sin)
        polysin_model = lambda x: p_g2_to_wavelength(x) + simple_sin_fit(x, *sin_fit_coeff)

        # Fit quality metrics
        total_y_pred = polysin_model(g2_steps)
        total_residuals = wavelength_axis - total_y_pred
        fit_metrics_total = self.calculate_fit_metrics(wavelength_axis, total_y_pred)

        # Calculate a fit for the polynomial with sinusoidal modulation
        initial_guess = Calibration.initial_fit_parameters['g2_to_wl']['poly'].extend(Calibration.initial_fit_parameters['g2_to_wl']['sin'])
        psm_fit_coeff, pcov = opt.curve_fit(poly_sin_modulation_fit, g2_steps, wavelength_axis, p0=initial_guess)
        psm_y_pred = poly_sin_modulation_fit(g2_steps, *psm_fit_coeff)
        residuals_psm = wavelength_axis - psm_y_pred
        fit_metrics_psm = self.calculate_fit_metrics(wavelength_axis, psm_y_pred)
        psm_fit = lambda x: poly_sin_modulation_fit(x, *psm_fit_coeff)

        # List fit metrics
        print('Poly fit', fit_metrics.__dict__)
        print('Sin correction', fit_metrics_sin.__dict__)
        print('Total fit', fit_metrics_total.__dict__)
        print('Poly sin mod', fit_metrics_psm.__dict__)

        p_sin_fit = lambda x: simple_sin_fit(x, *sin_fit_coeff)

        # prepare interpolated axis for plotting
        interpolated_g2_steps = np.linspace(g2_steps[0], g2_steps[-1], 1000)



        if show is True or self.showplots is True:
            fig, ax = plt.subplots(3, 2)
            ax[0, 0].scatter(g2_steps, wavelength_axis, label='Wavelength')
            ax[0, 0].plot(g2_steps, p_g2_to_wavelength(g2_steps), label='Wavelength fit', color='tab:purple')
            residuals = wavelength_axis - p_g2_to_wavelength(g2_steps)
            ax[1, 0].scatter(g2_steps, residuals, label='Wavelength residuals', marker='o')
            ax[1, 0].plot(interpolated_g2_steps, p_sin_fit(interpolated_g2_steps), label='sin fit', color='tab:orange')
            ax[2, 0].plot(g2_steps, sin_residuals, label='sin residuals', marker='o')
            ax[2, 0].set_ylabel('sin Residuals')

            ax[0, 1].scatter(g2_steps, wavelength_axis, label='Wavelength')
            ax[0, 1].plot(g2_steps, psm_fit(g2_steps), label='Wavelength PSM fit', color='tab:purple')
            residuals = wavelength_axis - psm_fit(g2_steps)
            ax[2, 1].plot(g2_steps, residuals, label='Wavelength PSM residuals', marker='o')
            
            ax[0, 0].set_title('G2 Steps to Wavelength {} - TESTER'.format(mode))
            ax[0, 0].legend()
            ax[1, 0].legend()
            ax[2, 0].legend()
            ax[0, 1].legend()
            ax[2, 1].legend()

            plt.show()


        # self.report_dict[mode]['g2_to_wl'] = (fit_metrics_psm, psm_fit_coeff.tolist())
        # self.calibration_metrics['g2_to_wl_{}'.format(mode)] = fit_metrics_psm
        # self.calibrations['g2_to_wl_{}'.format(mode)] = psm_fit_coeff.tolist()

        print('saving poly fit for g2_to_wl_{}'.format(mode))
        self.report_dict[mode]['g2_to_wl_{}'.format(mode)] = (fit_metrics, fit_coeff_g2_to_wavelength.tolist())
        self.calibration_metrics['g2_to_wl_{}'.format(mode)] = fit_metrics
        self.calibrations['g2_to_wl_{}'.format(mode)] = fit_coeff_g2_to_wavelength.tolist()

        return fit_coeff_g2_to_wavelength, fit_metrics

    def wavelength_to_g1(self, g1_steps, poly_order=2, mode=None, show=False, polysin=False):
        '''Calibration for using laser wavelength to calculate G1 steps.'''

        assert mode in ['subtractive', 'additive'], 'Invalid mode. Must be either "subtractive" or "additive".'

        if mode == 'subtractive':
            wavelength_axis = self.laser_wavelength_axis
            print('using laser wavelength axis')
        elif mode == 'additive':
            wavelength_axis = self.grating_wavelength_axis
            print('using grating wavelength axis')

        if polysin is True:
            print('Fitting with polysin')
            initial_guess = [0.01, -5, 5000, 200, 0.05, 0, 100]
            # fit_coeff_wavelength_to_g1 = poly_sin_modulation_fit(wavelength_axis, *initial_guess)
            fit_coeff_wavelength_to_g1, pcov = opt.curve_fit(poly_sin_modulation_fit, wavelength_axis, g1_steps, p0=initial_guess)
            p_wavelength_to_g1 = lambda x: poly_sin_modulation_fit(x, *fit_coeff_wavelength_to_g1)
        else:
            fit_coeff_wavelength_to_g1 = np.polyfit(wavelength_axis, g1_steps, poly_order)
            p_wavelength_to_g1 = np.poly1d(fit_coeff_wavelength_to_g1)

        y_pred = p_wavelength_to_g1(wavelength_axis)
        residuals = g1_steps - y_pred

        # Fit quality metrics
        fit_metrics = self.calculate_fit_metrics(g1_steps, y_pred)
        self.report_dict[mode]['wl_to_g1_{}'.format(mode)] = (fit_metrics, fit_coeff_wavelength_to_g1.tolist())

        if show is True or self.showplots is True:
            fig, ax = plt.subplots(2, 1)
            ax[0].scatter(wavelength_axis, g1_steps, label='G1 Steps')
            ax[0].plot(wavelength_axis, p_wavelength_to_g1(wavelength_axis), label='G1 Steps fit', color='tab:purple')
            residuals = g1_steps - p_wavelength_to_g1(wavelength_axis)
            ax[1].plot(wavelength_axis, residuals, label='G1 Steps residuals', marker='o')
            ax[0].set_title('Wavelength to G1 Steps')
            ax[0].legend()
            ax[1].legend()
            plt.show()

        self.calibration_metrics['wl_to_g1_{}'.format(mode)] = fit_metrics
        self.calibrations['wl_to_g1_{}'.format(mode)] = fit_coeff_wavelength_to_g1.tolist()

        return fit_coeff_wavelength_to_g1, fit_metrics
        
    def g1_to_wavelength(self, g1_steps, poly_order=2, mode=None, show=False):
        '''Reverse calibration for calculating laser wavelength from G1 steps.'''

        assert mode in ['subtractive', 'additive'], 'Invalid mode. Must be either "subtractive" or "additive".'

        if mode == 'subtractive':
            wavelength_axis = self.laser_wavelength_axis
            print('using laser wavelength axis')
        elif mode == 'additive':
            wavelength_axis = self.grating_wavelength_axis
            print('using grating wavelength axis')

        fit_coeff_g1_to_wavelength = np.polyfit(g1_steps, wavelength_axis, poly_order)
        p_g1_to_wavelength = np.poly1d(fit_coeff_g1_to_wavelength)

        y_pred = p_g1_to_wavelength(g1_steps)
        residuals = wavelength_axis - y_pred

        # Fit quality metrics
        fit_metrics = self.calculate_fit_metrics(wavelength_axis, y_pred)
        self.report_dict[mode]['g1_to_wl_{}'.format(mode)] = (fit_metrics, fit_coeff_g1_to_wavelength.tolist())

        if show is True or self.showplots is True:
            fig, ax = plt.subplots(2, 1)
            ax[0].scatter(g1_steps, wavelength_axis, label='Wavelength')
            ax[0].plot(g1_steps, p_g1_to_wavelength(g1_steps), label='Wavelength fit', color='tab:purple')
            residuals = wavelength_axis - p_g1_to_wavelength(g1_steps)
            ax[1].plot(g1_steps, residuals, label='Wavelength residuals', marker='o')
            ax[0].set_title('G1 Steps to Wavelength')
            ax[0].legend()
            ax[1].legend()
            plt.show()

        self.calibration_metrics['g1_to_wl_{}'.format(mode)] = fit_metrics
        self.calibrations['g1_to_wl_{}'.format(mode)] = fit_coeff_g1_to_wavelength.tolist()
        
        return fit_coeff_g1_to_wavelength, fit_metrics
        
    def wavelength_to_g2(self, g2_steps, poly_order=2, mode=None, show=False):
        '''Calibration for using laser wavelength to calculate G2 steps.'''

        assert mode in ['subtractive', 'additive'], 'Invalid mode. Must be either "subtractive" or "additive".'

        if mode == 'subtractive':
            wavelength_axis = self.laser_wavelength_axis
            print('using laser wavelength axis')
        elif mode == 'additive':
            wavelength_axis = self.grating_wavelength_axis
            print('using grating wavelength axis')
        
        fit_coeff_wavelength_to_g2 = np.polyfit(wavelength_axis, g2_steps, poly_order)
        p_wavelength_to_g2 = np.poly1d(fit_coeff_wavelength_to_g2)

        y_pred = p_wavelength_to_g2(wavelength_axis)
        residuals = g2_steps - y_pred

        # Fit quality metrics
        fit_metrics = self.calculate_fit_metrics(g2_steps, y_pred)
        self.report_dict[mode]['wl_to_g2_{}'.format(mode)] = (fit_metrics, fit_coeff_wavelength_to_g2.tolist())

        if show is True or self.showplots is True:
            fig, ax = plt.subplots(2, 1)
            ax[0].scatter(wavelength_axis, g2_steps, label='G2 Steps')
            ax[0].plot(wavelength_axis, p_wavelength_to_g2(wavelength_axis), label='G2 Steps fit', color='tab:purple')
            residuals = g2_steps - p_wavelength_to_g2(wavelength_axis)
            ax[1].plot(wavelength_axis, residuals, label='G2 Steps residuals', marker='o')
            ax[0].set_title('Wavelength to G2 Steps {}'.format(mode))
            ax[0].legend()
            ax[1].legend()
            plt.show()

        self.calibration_metrics['wl_to_g2_{}'.format(mode)] = fit_metrics
        self.calibrations['wl_to_g2_{}'.format(mode)] = fit_coeff_wavelength_to_g2.tolist()

        return fit_coeff_wavelength_to_g2, fit_metrics
    
    def g2_to_wavelength(self, g2_steps, poly_order=2, mode=None, show=False):
        '''Reverse calibration for calculating laser wavelength from G2 steps.'''

        assert mode in ['subtractive', 'additive'], 'Invalid mode. Must be either "subtractive" or "additive".'

        if mode == 'subtractive':
            wavelength_axis = self.laser_wavelength_axis
            print('using laser wavelength axis')
        elif mode == 'additive':
            wavelength_axis = self.grating_wavelength_axis
            print('using grating wavelength axis')

        fit_coeff_g2_to_wavelength = np.polyfit(g2_steps, wavelength_axis, poly_order)
        p_g2_to_wavelength = np.poly1d(fit_coeff_g2_to_wavelength)

        y_pred = p_g2_to_wavelength(g2_steps)
        residuals = wavelength_axis - y_pred

        # Fit quality metrics
        fit_metrics = self.calculate_fit_metrics(wavelength_axis, y_pred)
        self.report_dict[mode]['g2_to_wl_{}'.format(mode)] = (fit_metrics, fit_coeff_g2_to_wavelength.tolist())

        if show is True or self.showplots is True:
            fig, ax = plt.subplots(2, 1)
            ax[0].scatter(g2_steps, wavelength_axis, label='Wavelength')
            ax[0].plot(g2_steps, p_g2_to_wavelength(g2_steps), label='Wavelength fit', color='tab:purple')
            residuals = wavelength_axis - p_g2_to_wavelength(g2_steps)
            ax[1].plot(g2_steps, residuals, label='Wavelength residuals', marker='o')
            ax[0].set_title('G2 Steps to Wavelength {}'.format(mode))
            ax[0].legend()
            ax[1].legend()
            plt.show()

        self.calibration_metrics['g2_to_wl_{}'.format(mode)] = fit_metrics
        self.calibrations['g2_to_wl_{}'.format(mode)] = fit_coeff_g2_to_wavelength.tolist()

        return fit_coeff_g2_to_wavelength, fit_metrics

class CameraCalibration:


    def __init__(self, dataDir):
        self.data_dict = {}  # Dictionary to hold data from all CSV files
        self.dataDir = dataDir
        self.calibrations = {}  # Dictionary to hold calibration data
        self.calibration_metrics = {}  # Dictionary to hold calibration metrics
        self.report_dict = {}  # Dictionary to hold report data
        self.showplots = False  # Flag to control whether to show plots
        self.files = [file for file in os.listdir(dataDir) if file.endswith('.csv')]


    def load_csv(self, file_path):
        """Load a CSV file."""
        try:
            data = np.loadtxt(file_path, delimiter=',')
            return data
        except Exception as e:
            print(f"Error loading CSV file {file_path}: {e}")
            return None
        
    def load_all_csv(self):
        """Load all CSV files."""

        for file in self.files:
            file_path = os.path.join(self.dataDir, file)
            self.data_dict[file] = self.load_csv(file_path)
        return self.data_dict


if __name__ == '__main__':

    dataDir = r'C:\Users\Raman\matchbook\RamanMicroscope\data\camera_calibration_data_17-04-25\processed_spectra'
    camcal = CameraCalibration(dataDir)


    # calibration, cal_data = initialise(showplots=False)
    calibration = Calibration(showplots=True)
    calibration.load_motor_recordings()
    calibration.sort_flattened_data_by_wavelength()
    calibration.assign_calibration_data()

    # coefficients = calibration.calibrate_motor_axis('g1', poly_order=1)
    # coefficients = calibration.monochromator_calibration()
    # coefficients = calibration.calibrate_motor_axis('triax')
    calibration.save_triax_calibrations()
    breakpoint()
    
    calibration.save_all_calibrations()
    
    calibration.load_motor_recordings(filename='laser_motor_recordings.json')
    calibration.sort_flattened_data_by_wavelength()
    calibration.assign_calibration_data()
    calibration.calibrate_motor_axis('l2')
    calibration.save_all_calibrations()

    breakpoint()

    # for label in calibration.laser_positions.keys():
    #     coefficients = calibration.calibrate_motor_axis(label)

    separate_g_cal = False
    if separate_g_cal:
        calibration.load_motor_recordings(filename='grating_motor_recordings.json')
        calibration.sort_flattened_data_by_wavelength()
        calibration.assign_calibration_data()
        # breakpoint()
        calibration.monochromator_positions['g4'] = [-x for x in calibration.monochromator_positions['g3']]
        calibration.monochromator_positions['g1'] = [int(round(-x/4)) for x in calibration.monochromator_positions['g3']]
        calibration.monochromator_positions['g2'] = [int(round(x/4)) for x in calibration.monochromator_positions['g3']]
        # for label in calibration.monochromator_positions.keys():
        # coefficients = calibration.calibrate_motor_axis('g1')
        for label in calibration.monochromator_positions.keys():
            coefficients = calibration.calibrate_motor_axis(label)

    
    # TRIAX cal is absolute - only needs to be saved once
    # calibration.save_triax_calibrations()
    # breakpoint()
    calibration.save_all_calibrations()
    # calibration.save_report()
    # review_report()
    # print(calibration.calibrations)

