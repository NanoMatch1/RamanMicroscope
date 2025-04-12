import os
import sys
import numpy as np
import csv
import json
import scipy.optimize as opt
import matplotlib.pyplot as plt
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'analysis-spectroscopy','analysis_spectroscopy'))

from analysis_spectroscopy import dataset_analysis as asp


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



calibration_records = {
    'date': '2024-08-27'
    ,

    'manual_measurements': {
        'nm_per_laser_step': 0.0158,
        'lamba_change_for_400_steps': 6.32,
        'nm_per_pixel': 4/400, # retrieved from recent calibration sweep
        # nm_per_step = 0
        'triax_steps': 410000,
        'nm_per_triax_step': 0.00110267
    },

    'eept': {
        'headers': {
            'L1': 0,
            'L2': 1,
            'NIU': 2,
            'NIU': 3,
            'G1': 4,
            'G2': 5,
            'NIU': 6,
            'NIU': 7,
            'triax_steps': 8,
            'pixels': 9
        },
        'data':
            "['X-473', 'Y212', 'Z0', 'A0']:['X58', 'Y45', 'Z0', 'A0']:380000,518\n['X-973', 'Y424', 'Z0', 'A0']:['X112', 'Y90', 'Z0', 'A0']:385000,390\n['X-1473', 'Y636', 'Z0', 'A0']:['X184', 'Y170', 'Z0', 'A0']:390000,263\n['X-2473', 'Y1058', 'Z0', 'A0']:['X350', 'Y359', 'Z0', 'A0']:395000,645\n['X-3473', 'Y1479', 'Z0', 'A0']:['X508', 'Y587', 'Z0', 'A0']:405000,414\n['X-4473', 'Y1897', 'Z0', 'A0']:['X619', 'Y698', 'Z0', 'A0']:415000,152\n['X-5473', 'Y2327', 'Z0', 'A0']:['X770', 'Y851', 'Z0', 'A0']:420000,542\n['X-6473', 'Y2735', 'Z0', 'A0']:['X917', 'Y970', 'Z0', 'A0']:430000,300\n['X-7473', 'Y3149', 'Z0', 'A0']:['X1023', 'Y1064', 'Z0', 'A0']:435000,668\n['X-8473', 'Y3572', 'Z0', 'A0']:['X1163', 'Y1181', 'Z0', 'A0']:445000,436\n['X27', 'Y1', 'Z0', 'A0']:['X-28', 'Y-28', 'Z0', 'A0']:375000,646\n['X1027', 'Y-413', 'Z0', 'A0']:['X-198', 'Y-224', 'Z0', 'A0']:370000,274\n['X2027', 'Y-846', 'Z0', 'A0']:['X-323', 'Y-343', 'Z0', 'A0']:360000,489\n['X3027', 'Y-1262', 'Z0', 'A0']:['X-468', 'Y-455', 'Z0', 'A0']:355000,140\n['X4027', 'Y-1687', 'Z0', 'A0']:['X-603', 'Y-566', 'Z0', 'A0']:345000,367\n#['X5027', 'Y-2186', 'Z0', 'A0']:['X-693', 'Y-650', 'Z0', 'A0']:335000,589\n#['X6027', 'Y-2609', 'Z0', 'A0']:['X-848', 'Y-782', 'Z0', 'A0']:330000,242\n#['X7027', 'Y-3045', 'Z0', 'A0']:['X-963', 'Y-888', 'Z0', 'A0']:320000,473\n#['X-473', 'Y168', 'Z0', 'A0']:['X62', 'Y50', 'Z0', 'A0']:380000,515"
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

def lin_sin_modulation_fit(x, a1, a0, A, B, C, D):
    # Polynomial part
    poly = a1 * x + a0
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

@dataclass
class Peak:
    '''Dataclass for peak data.'''
    peak_type: str
    pos: float
    amp: float
    fwhm: float
    eta: float = 0

    def __repr__(self):
        return f'Peak D-Class(pos={round(self.pos, 2)}, amp={round(self.amp, 2)}, fwhm={round(self.fwhm, 2)}, eta={round(self.eta, 2)})'
    

class AutoCalibration:

    def __init__(self, showplots=True, exclude=[], **kwargs):
        self.linked_motor_scalars = {
            'g2': ('g1', -1),
            'g3': ('g1', -0.25),
            'g4': ('g1', 0.25),
        }

        self.excluded = exclude
        self.data_mask_dict = {'l1': (710, 880), 'l2': (710, 880), 'l3':(710,880), 'g1': (710, 880), 'g2': (710, 880), 'g3': (710, 880), 'g4': (710, 880)}
        self.motor_calibrations = {
            'l1': (self.l1_to_wavelength, self.wavelength_to_l1),
            'l2': (self.l2_to_wavelength, self.wavelength_to_l2),
            'l3': (self.l2_to_wavelength, self.wavelength_to_l2),
            'g1': (self.g1_to_wavelength, self.wavelength_to_g1),
            'g2': (self.g2_to_wavelength, self.wavelength_to_g2),
            'g3': (self.g2_to_wavelength, self.wavelength_to_g2),
            'g4': (self.g2_to_wavelength, self.wavelength_to_g2),
        } # dict of possible motor calibrations and their methods. Update here as new autocals are created
        self.scriptDir = os.path.dirname(__file__)
        self.showplots = showplots
        self.calibration_metrics = {}
        self.calibrations = {}
        self.report_dict = {'initial': {}, 'subtractive': {}, 'additive': {}}
        self.autocal_dict = self.collect_autocalibration_files()
        self.kwargs = kwargs

    def collect_autocalibration_files(self):
        '''Collect all calibration files from the calibration directory and sorts into the latest for each type.'''
    
        autocal_dict = {}
        files = [f for f in os.listdir(os.path.join(self.scriptDir, 'autocalibration')) if f.endswith('.json')]

        assert len(files) > 0, 'No calibration files found in the autocalibration directory.'
        for motor_type in self.motor_calibrations:
            autocal_dict[motor_type] = [f for f in files if motor_type in f]
        
        for motor_type, file_list in autocal_dict.items():
            if len(file_list) == 0:
                autocal_dict[motor_type] = None
                continue
            
            file_list.sort(key=lambda x: int(x.split('_')[1]))
            latest_cal = file_list[-1]
            autocal_dict[motor_type] = latest_cal
        
        return autocal_dict
    
    def autocalibrate_motor_axis(self, motor_label, poly_order=2, manual=False, load=False, show=False, linked=True, **kwargs):
        """Automatically calibrate a motor axis based on peak fitting of a spectral dataset."""
        file = self.autocal_dict.get(motor_label)
        if file is None:
            print(f"No calibration file found for {motor_label}.")
            return

        print(f"Calibrating motor: {motor_label}")
        print(f"Using file: {file}")

        if load:
            filename = f'peakfit_autocal_{motor_label}'
            dataSet = asp.DataSet(dataDir)
            dataSet.load_database(filename)
        else:
            dataSet = self._extract_peak_positions(file, motor_label, manual=manual, **kwargs)

        calibration_result = self._generate_motor_calibration(
            motor_label, dataSet, poly_order=poly_order, show=show
        )

        if linked:
            self._propagate_linked_calibrations(motor_label, calibration_result)

        return calibration_result
    
    def _propagate_linked_calibrations(self, source_label, source_calibration):
        """Propagate calibration from one motor to others using predefined scalar relations."""
        for target_label, (base_label, scalar) in self.linked_motor_scalars.items():
            if base_label != source_label:
                continue  # Only apply if the calibration was for the linked base motor

            print(f"Propagating calibration to {target_label} using scalar {scalar}")

            # Scale forward poly: wavelength → steps
            source_fwd_coeff = source_calibration['forward']['coeff']
            scaled_fwd_coeff = np.array(source_fwd_coeff) * scalar
            poly_fwd = np.poly1d(scaled_fwd_coeff)

            # Compute inverse by fitting wavelength vs predicted steps again
            wavelengths = np.array(self.wavelength_axis)
            steps_scaled = poly_fwd(wavelengths)
            coeff_inv = np.polyfit(steps_scaled, wavelengths, len(scaled_fwd_coeff)-1)
            poly_inv = np.poly1d(coeff_inv)

            pred_steps = poly_fwd(wavelengths)
            pred_wavelengths = poly_inv(pred_steps)

            metrics_fwd = self.calculate_fit_metrics(pred_steps, pred_steps)  # Fit is exact by construction
            metrics_inv = self.calculate_fit_metrics(wavelengths, pred_wavelengths)

            # Store results
            self.calibrations[f'wl_to_{target_label}'] = scaled_fwd_coeff.tolist()
            self.calibrations[f'{target_label}_to_wl'] = coeff_inv.tolist()
            self.calibration_metrics[f'wl_to_{target_label}'] = metrics_fwd
            self.calibration_metrics[f'{target_label}_to_wl'] = metrics_inv

            self.save_calibration(f'autocal_{target_label}')

            print(f"Saved propagated calibration for {target_label}")

    
    def _extract_peak_positions(self, file, motor_label, manual=False, **kwargs):
        smoothing = self.kwargs.get('smoothing', 3)
        dataSet = asp.DataSet(dataDir, fileList=[file])
        data_mask = kwargs.get('data_mask', self.data_mask_dict.get(motor_label))

        fileObj = dataSet.dataDict.get(file)
        dataSet.dataDict = fileObj.data
        dataSet.dataDict = mask_data(dataSet.dataDict, data_mask)

        for cal_obj in dataSet.dataDict.values():
            cal_obj._minimise_data()
            cal_obj._apply_smoothing(window_length=smoothing)

        peakfit_config = {
            'peak_list': [],
            'peak_type': 'voigt_pseudo',
            'peak_sign': 'positive',
            'threshold': 0.01,
            'peak_detect': 'all',
            'copy_peaks': False,
            'show_ui': manual,
        }

        dataSet._peakfit(peakfitting_info=peakfit_config)
        dataSet.save_database(tagList='', seriesName=f'peakfit_autocal_{motor_label}')
        return dataSet

    def _generate_motor_calibration(self, motor_label, dataSet, poly_order=2, show=False):
        peak_positions = []

        for wavelength, peakdict in dataSet.peakfitDict.items():
            peaks = [Peak(*p) for p in peakdict.get('peaks', [])]
            if not peaks:
                continue
            peaks.sort(key=lambda p: p.amp)
            peak = peaks[-1]
            peak_positions.append((float(wavelength), float(peak.pos)))

        if not peak_positions:
            raise RuntimeError(f"No peaks found for calibration of {motor_label}.")

        peak_positions.sort()
        data = np.array(peak_positions)
        wavelengths = data[:, 0]
        self.wavelength_axis = wavelengths # needed for linked calibrations
        steps = data[:, 1]

        # Forward calibration: wavelength → motor steps
        coeff_fwd = np.polyfit(wavelengths, steps, poly_order)
        poly_fwd = np.poly1d(coeff_fwd)
        pred_steps = poly_fwd(wavelengths)
        residuals_fwd = steps - pred_steps
        metrics_fwd = self.calculate_fit_metrics(steps, pred_steps)

        # Inverse calibration: motor steps → wavelength
        coeff_inv = np.polyfit(steps, wavelengths, poly_order)
        poly_inv = np.poly1d(coeff_inv)
        pred_wl = poly_inv(steps)
        residuals_inv = wavelengths - pred_wl
        metrics_inv = self.calculate_fit_metrics(wavelengths, pred_wl)

        # Store calibration
        self.calibrations[f'wl_to_{motor_label}'] = coeff_fwd.tolist()
        self.calibrations[f'{motor_label}_to_wl'] = coeff_inv.tolist()
        self.calibration_metrics[f'wl_to_{motor_label}'] = metrics_fwd
        self.calibration_metrics[f'{motor_label}_to_wl'] = metrics_inv

        if show or getattr(self, 'showplots', False):
            fig, ax = plt.subplots(2, 1)
            ax[0].scatter(wavelengths, steps, color='black', label='Measured')
            ax[0].plot(wavelengths, pred_steps, color='tab:blue', label='Fit')
            ax[0].set_title(f'Auto Calibration: Wavelength to {motor_label.upper()}')
            ax[0].set_ylabel('Motor Steps')
            ax[0].legend()

            ax[1].plot(wavelengths, residuals_fwd, marker='o', label='Residuals')
            ax[1].set_xlabel('Wavelength (nm)')
            ax[1].set_ylabel('Residuals (steps)')
            ax[1].legend()
            plt.tight_layout()
            plt.show()

        self.save_calibration(f'autocal_{motor_label}')

        return {
            'forward': {
                'coeff': coeff_fwd,
                'metrics': metrics_fwd,
                'poly': poly_fwd,
            },
            'inverse': {
                'coeff': coeff_inv,
                'metrics': metrics_inv,
                'poly': poly_inv,
            }
        }

    
    def autocalibrate_all(self, manual=False):
        for motor_type, file in self.autocal_dict.items():
            if file is None or motor_type in self.excluded:
                continue
            dataSet = self.peakfit_autocal(file, motor_type, manual=manual)
            self.generate_autocal(motor_type, dataSet=dataSet)
    
    def autocalibrate_single(self, motor_type, manual=False, load=False, **kwargs):
        file = self.autocal_dict.get(motor_type)
        if file is None:
            print(f'No calibration file found for {motor_type}.')
            return
        print("Calibrating motor type: {}".format(motor_type))
        print(file)
        if load is True:
            filename = 'peakfit_autocal_{}'.format(motor_type)
            dataSet = asp.DataSet(dataDir)
            dataSet.load_database(filename)
        else:
            dataSet = self.peakfit_autocal(file, motor_type, manual=manual, **kwargs)
        self.generate_autocal(motor_type, dataSet=dataSet, **kwargs)


    def peakfit_autocal(self, file, motor_type, manual=False, **kwargs):
        smoothing = self.kwargs.get('smoothing', 3)
        dataSet = asp.DataSet(dataDir, fileList=[file])
        data_mask = self.data_mask_dict[motor_type]

        fileObj = dataSet.dataDict.get(file)
        # note: DataSet class is designed to work on a set of files, but the calibration dataset contains one file with a set of data. The following line is a workaround to access the data.
        dataSet.dataDict = fileObj.data
        dataSet.dataDict = mask_data(dataSet.dataDict, data_mask) # mask data to select only the wavelengths of interest. Ranges specified in the data_mask_dict

        for cal_obj in dataSet.dataDict.values():
            # cal_obj._invert_data()
            cal_obj._minimise_data()
            cal_obj._apply_smoothing(window_length=smoothing)
            # cal_obj._plot_individual()
        dataSet.plot_current()
        
        peakfitting_info = {
            'peak_list': [],
            'peak_type': 'voigt_pseudo',
            'peak_sign': 'positive',
            'threshold': 0.01, # percentage of max intensity;
            'peak_detect': 'all',
            'copy_peaks': False,
            'show_ui': manual,
        } 
        dataSet._peakfit(peakfitting_info=peakfitting_info)
        # dataSet.plot_peaks()
        dataSet.save_database(tagList='', seriesName='peakfit_autocal_{}'.format(motor_type))
        return dataSet

    def generate_autocal(self, motor_type, dataSet=None, poly_order=1):
        key_index = {
            'pos': 1,
            'amp': 2,
            'fwhm': 3,
        }
        if dataSet is None:
            calibration_name = input('Enter the filename of the calibration data to load: ')
            dataSet = asp.DataSet(dataDir)
            dataSet.load_database(calibration_name)
        # dataSet.plot_peaks()
        dataSet.plot_current()

        calibration_peaks = {}

        for wave, peakdict in dataSet.peakfitDict.items():
            peak_list = []
            peaks = peakdict['peaks']
            if len(peaks) == 0:
                continue
            for peak in peaks:
                peak_list.append(Peak(*peak))
            if len(peak_list) > 1: # if there are multiple peaks, sort by amplitude and take the largest one
                peak_list.sort(key=lambda x: x.amp)
            peak = peak_list[-1]
            calibration_peaks[wave] = peak
            print(peak_list)

        for key, value in calibration_peaks.items():
            print(key, value)

        data = [(key, value.pos) for key, value in calibration_peaks.items()]
        data.sort(key=lambda x: x[0])
        data = np.array(data).astype(float)

        self.data_array = data
        self.wavelength_axis = data[:, 0]

        fit, fitmetrics1 = self.motor_calibrations[motor_type][0](mode='subtractive', show=True, model='poly', poly_order=poly_order)
        print(fit)
        print(fitmetrics1)
        fit, fitmetrics2 = self.motor_calibrations[motor_type][1](mode='subtractive', show=True, model='poly', poly_order=poly_order)
        print(fit)
        print(fitmetrics2)
        self.save_calibration('autocal_{}'.format(motor_type))
            

    
    def calculate_fit_metrics(self, actual, model):
        # Fit quality metrics
        r2 = r_squared(actual, model)
        rmse_val = rmse(actual, model)
        mae_val = mae(actual, model)
        residuals = actual - model
        res_std = residual_std(residuals)

        return FitMetrics(r2, rmse_val, mae_val, res_std)

    def save_report(self):
        # unpack report_dict into dict for json serialization
        newDict = {x: y for x, y in self.report_dict.items()}
        for mode, data in self.report_dict.items():
            for key, value in data.items():
                newDict[mode][key] = (value[0].__dict__, value[1])

        with open(os.path.join(os.path.dirname(__file__), 'calibration_report.json'), 'w') as f:
            json.dump(newDict, f)
    

    def save_calibration(self, filename):
        self.calibrationDir = os.path.join(os.path.dirname(__file__), 'calibration')
        with open(os.path.join(self.calibrationDir, '{}_autocal.json'.format(filename)), 'w') as f:
            json.dump(self.calibrations, f)

        print("Calibration complete: Successfully saved calibration data to '{}_autocal.json' file.".format(filename))

    def wavelength_to_l1(self, poly_order=1, mode=None, show=False, model='poly'):
        pass

    def l1_to_wavelength(self, poly_order=1, mode=None, show=False, model='poly'):
        pass

    def wavelength_to_l2(self, poly_order=2, mode=None, model='poly', show=False):
        '''Calibration for using laser wavelength to calculate L2 steps.'''

        assert mode in ['subtractive', 'additive'], 'Invalid mode. Must be either "subtractive" or "additive".'

        # if mode == 'subtractive':
        #     wavelength_axis = self.laser_wavelength_axis
        #     print('using laser wavelength axis')
        # elif mode == 'additive':
        #     wavelength_axis = self.grating_wavelength_axis
        #     print('using grating wavelength axis')

        wavelength_axis = self.wavelength_axis
        l2_steps = self.data_array[:, 1]

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
        
    def l2_to_wavelength(self, poly_order=2, mode=None, model='poly', show=False):
        '''Reverse calibration for calculating laser wavelength from L2 steps.'''

        assert mode in ['subtractive', 'additive'], 'Invalid mode. Must be either "subtractive" or "additive".'

        # if mode == 'subtractive':
        #     wavelength_axis = self.laser_wavelength_axis
        #     print('using laser wavelength axis')
        # elif mode == 'additive':
        #     wavelength_axis = self.grating_wavelength_axis
        #     print('using grating wavelength axis')

        wavelength_axis = self.wavelength_axis
        l2_steps = self.data_array[:, 1]

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

    def wavelength_to_g1(self, poly_order=1, mode=None, show=False, model='poly'):
        '''Calibration for using laser wavelength to calculate G1 steps.'''

        wavelength_axis = self.wavelength_axis
        g1_steps = self.data_array[:, 1]

        assert mode in ['subtractive', 'additive'], 'Invalid mode. Must be either "subtractive" or "additive".'

        initial_guess = [8.196252645921234, -800, -54.08824066045618, 0.02544855329855095, 20.71117654365508, 0]

        if model == 'linsin':
            print('Fitting with linsin')
            # initial_guess = [-5, 5000, 200, 0.05, 0, 100]
            # fit_coeff_wavelength_to_g1 = poly_sin_modulation_fit(wavelength_axis, *initial_guess)
            fit_coeff_wavelength_to_g1, pcov = opt.curve_fit(lin_sin_modulation_fit, wavelength_axis, g1_steps, p0=initial_guess)
            p_wavelength_to_g1 = lambda x: lin_sin_modulation_fit(x, *fit_coeff_wavelength_to_g1)
        elif model == 'polysin':
            print('Fitting with polysin')
            initial_guess = [0.01, -5, 5000, 200, 0.05, 0, 100]
            # fit_coeff_wavelength_to_g1 = poly_sin_modulation_fit(wavelength_axis, *initial_guess)
            fit_coeff_wavelength_to_g1, pcov = opt.curve_fit(poly_sin_modulation_fit, wavelength_axis, g1_steps, p0=initial_guess)
            p_wavelength_to_g1 = lambda x: poly_sin_modulation_fit(x, *fit_coeff_wavelength_to_g1)
        else:
            print("Fitting with polynomial of order {}".format(poly_order))
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
        
    def g1_to_wavelength(self, poly_order=1, mode=None, model='poly', show=False):
        '''Reverse calibration for calculating laser wavelength from G1 steps.'''

        assert mode in ['subtractive', 'additive'], 'Invalid mode. Must be either "subtractive" or "additive".'

        wavelength_axis = self.wavelength_axis
        g1_steps = self.data_array[:, 1]

        initial_guess  = [0, 0.1, 800, 1, 0.005, 0, 0]

        if model == 'linsin':
            print('Fitting with linsin')
            initial_guess = [0.18298010826338804, -169155.69463447115, -64.6001908392166, 0.001218420554789506, 0.136231899401439, 0]
            # fit_coeff_g1_to_wavelength = poly_sin_modulation_fit(g1_steps, *initial_guess)
            fit_coeff_g1_to_wavelength, pcov = opt.curve_fit(lin_sin_modulation_fit, g1_steps, wavelength_axis, p0=initial_guess)
            p_g1_to_wavelength = lambda x: lin_sin_modulation_fit(x, *fit_coeff_g1_to_wavelength)

        elif model == 'polysin':
            print('Fitting with polysin')
            # initial_guess = [0.01, 800, -1.53840861,  0.00463291, -1.04822887, -0.2]
            # fit_coeff_g1_to_wavelength = poly_sin_modulation_fit(g1_steps, *initial_guess)
            fit_coeff_g1_to_wavelength, pcov = opt.curve_fit(poly_sin_modulation_fit, g1_steps, wavelength_axis, p0=initial_guess)
            p_g1_to_wavelength = lambda x: poly_sin_modulation_fit(x, *fit_coeff_g1_to_wavelength)
        else:
            print("Fitting with polynomial of order {}".format(poly_order))
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
    
    def wavelength_to_g2(self, poly_order=1, mode=None, show=False, model='poly'):
        '''Calibration for using laser wavelength to calculate G1 steps.'''

        wavelength_axis = self.wavelength_axis
        g2_steps = self.data_array[:, 1]

        assert mode in ['subtractive', 'additive'], 'Invalid mode. Must be either "subtractive" or "additive".'

        initial_guess = [8.196252645921234, -800, -54.08824066045618, 0.02544855329855095, 20.71117654365508, 0]

        if model == 'linsin':
            print('Fitting with linsin')
            # initial_guess = [-5, 5000, 200, 0.05, 0, 100]
            # fit_coeff_wavelength_to_g2 = poly_sin_modulation_fit(wavelength_axis, *initial_guess)
            fit_coeff_wavelength_to_g2, pcov = opt.curve_fit(lin_sin_modulation_fit, wavelength_axis, g2_steps, p0=initial_guess)
            p_wavelength_to_g2 = lambda x: lin_sin_modulation_fit(x, *fit_coeff_wavelength_to_g2)
        elif model == 'polysin':
            print('Fitting with polysin')
            initial_guess = [0.01, -5, 5000, 200, 0.05, 0, 100]
            # fit_coeff_wavelength_to_g2 = poly_sin_modulation_fit(wavelength_axis, *initial_guess)
            fit_coeff_wavelength_to_g2, pcov = opt.curve_fit(poly_sin_modulation_fit, wavelength_axis, g2_steps, p0=initial_guess)
            p_wavelength_to_g2 = lambda x: poly_sin_modulation_fit(x, *fit_coeff_wavelength_to_g2)
        else:
            print("Fitting with polynomial of order {}".format(poly_order))
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
            ax[0].set_title('Wavelength to G2 Steps')
            ax[0].legend()
            ax[1].legend()
            plt.show()

        self.calibration_metrics['wl_to_g2_{}'.format(mode)] = fit_metrics
        self.calibrations['wl_to_g2_{}'.format(mode)] = fit_coeff_wavelength_to_g2.tolist()

        return fit_coeff_wavelength_to_g2, fit_metrics


    def g2_to_wavelength(self, poly_order=1, mode=None, model='poly', show=False):
        '''Reverse calibration for calculating laser wavelength from G2 steps.'''

        assert mode in ['subtractive', 'additive'], 'Invalid mode. Must be either "subtractive" or "additive".'

        wavelength_axis = self.wavelength_axis
        g2_steps = self.data_array[:, 1]

        initial_guess  = [0, 0.1, 800, 1, 0.005, 0, 0]

        if model == 'linsin':
            print('Fitting with linsin')
            initial_guess = [0.18298010826338804, -169155.69463447115, -64.6001908392166, 0.001218420554789506, 0.136231899401439, 0]
            # fit_coeff_g2_to_wavelength = poly_sin_modulation_fit(g2_steps, *initial_guess)
            fit_coeff_g2_to_wavelength, pcov = opt.curve_fit(lin_sin_modulation_fit, g2_steps, wavelength_axis, p0=initial_guess)
            p_g2_to_wavelength = lambda x: lin_sin_modulation_fit(x, *fit_coeff_g2_to_wavelength)

        elif model == 'polysin':
            print('Fitting with polysin')
            # initial_guess = [0.01, 800, -1.53840861,  0.00463291, -1.04822887, -0.2]
            # fit_coeff_g2_to_wavelength = poly_sin_modulation_fit(g2_steps, *initial_guess)
            fit_coeff_g2_to_wavelength, pcov = opt.curve_fit(poly_sin_modulation_fit, g2_steps, wavelength_axis, p0=initial_guess)
            p_g2_to_wavelength = lambda x: poly_sin_modulation_fit(x, *fit_coeff_g2_to_wavelength)
        else:
            print("Fitting with polynomial of order {}".format(poly_order))
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
            ax[0].set_title('G2 Steps to Wavelength')
            ax[0].legend()
            ax[1].legend()
            plt.show()

        self.calibration_metrics['g2_to_wl_{}'.format(mode)] = fit_metrics
        self.calibrations['g2_to_wl_{}'.format(mode)] = fit_coeff_g2_to_wavelength.tolist()
        
        return fit_coeff_g2_to_wavelength, fit_metrics




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
    

    def __init__(self, calibration_dict:dict, showplots=False):
        # self.data = data
        self.scriptDir = os.path.dirname(__file__)
        self.dataDir = os.path.join(os.path.dirname(__file__), 'laser_calibration')
        self.files = [f for f in os.listdir(self.dataDir) if f.endswith('.txt')]
        self.showplots = showplots
        self.calibration_metrics = {}
        self.calibrations = {}
        self.report_dict = {'initial': {}, 'subtractive': {}, 'additive': {}}
        self.autocal_dict = self.collect_autocalibration_files()
        self.process_calibration_data(calibration_dict)

    def process_calibration_data(self, calibration_dict):
        data_array = [[key, peak.pos] for key, peak in calibration_dict.items()]
        data_array.sort(key=lambda x: x[0])
        data_array = np.array(data_array).astype(float)

        self.wavelength_axis = data_array[:, 0]
        self.data_array = data_array
        # print('data_array')
        # breakpoint()

    def calculate_fit_metrics(self, actual, model):
        # Fit quality metrics
        r2 = r_squared(actual, model)
        rmse_val = rmse(actual, model)
        mae_val = mae(actual, model)
        residuals = actual - model
        res_std = residual_std(residuals)

        return FitMetrics(r2, rmse_val, mae_val, res_std)

    def save_report(self):
        # unpack report_dict into dict for json serialization
        newDict = {x: y for x, y in self.report_dict.items()}
        for mode, data in self.report_dict.items():
            for key, value in data.items():
                newDict[mode][key] = (value[0].__dict__, value[1])

        with open(os.path.join(os.path.dirname(__file__), 'calibration_report.json'), 'w') as f:
            json.dump(newDict, f)
    

    def save_calibration(self, filename):
        with open(os.path.join(os.path.dirname(__file__), '{}_autocal.json'.format(filename)), 'w') as f:
            json.dump(self.calibrations, f)

        print("Calibration complete: Successfully saved calibration data to 'calibrations.json' file.")

    def wavelength_to_g1(self, poly_order=1, mode=None, show=False, model='poly'):
        '''Calibration for using laser wavelength to calculate G1 steps.'''

        wavelength_axis = self.wavelength_axis
        g1_steps = self.data_array[:, 1]

        assert mode in ['subtractive', 'additive'], 'Invalid mode. Must be either "subtractive" or "additive".'

        # if mode == 'subtractive':
        #     wavelength_axis = self.laser_wavelength_axis
        #     print('using laser wavelength axis')
        # elif mode == 'additive':
        #     wavelength_axis = self.grating_wavelength_axis
        #     print('using grating wavelength axis')

        initial_guess = [8.196252645921234, -800, -54.08824066045618, 0.02544855329855095, 20.71117654365508, 0]

        if model == 'linsin':
            print('Fitting with linsin')
            # initial_guess = [-5, 5000, 200, 0.05, 0, 100]
            # fit_coeff_wavelength_to_g1 = poly_sin_modulation_fit(wavelength_axis, *initial_guess)
            fit_coeff_wavelength_to_g1, pcov = opt.curve_fit(lin_sin_modulation_fit, wavelength_axis, g1_steps, p0=initial_guess)
            p_wavelength_to_g1 = lambda x: lin_sin_modulation_fit(x, *fit_coeff_wavelength_to_g1)
        elif model == 'polysin':
            print('Fitting with polysin')
            initial_guess = [0.01, -5, 5000, 200, 0.05, 0, 100]
            # fit_coeff_wavelength_to_g1 = poly_sin_modulation_fit(wavelength_axis, *initial_guess)
            fit_coeff_wavelength_to_g1, pcov = opt.curve_fit(poly_sin_modulation_fit, wavelength_axis, g1_steps, p0=initial_guess)
            p_wavelength_to_g1 = lambda x: poly_sin_modulation_fit(x, *fit_coeff_wavelength_to_g1)
        else:
            print("Fitting with polynomial of order {}".format(poly_order))
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
        
    def g1_to_wavelength(self, poly_order=1, mode=None, model='poly', show=False):
        '''Reverse calibration for calculating laser wavelength from G1 steps.'''

        assert mode in ['subtractive', 'additive'], 'Invalid mode. Must be either "subtractive" or "additive".'

        # if mode == 'subtractive':
        #     wavelength_axis = self.laser_wavelength_axis
        #     print('using laser wavelength axis')
        # elif mode == 'additive':
        #     wavelength_axis = self.grating_wavelength_axis
        #     print('using grating wavelength axis')

        wavelength_axis = self.wavelength_axis
        g1_steps = self.data_array[:, 1]

        initial_guess  = [0, 0.1, 800, 1, 0.005, 0, 0]
        # fig, ax  = plt.subplots(2, 1)
        # # ax[0].plot(g1_steps, wavelength_axis)
        # # ax[0].plot(g1_steps, lin_sin_modulation_fit(g1_steps, *initial_guess))
        # ax[0].plot(g1_steps, simple_sin_fit(g1_steps, *initial_guess[2:]))
        # residual = wavelength_axis - lin_sin_modulation_fit(g1_steps, *initial_guess)
        # ax[1].plot(g1_steps, residual)
        # plt.show()

        if model == 'linsin':
            print('Fitting with linsin')
            initial_guess = [0.18298010826338804, -169155.69463447115, -64.6001908392166, 0.001218420554789506, 0.136231899401439, 0]
            # fit_coeff_g1_to_wavelength = poly_sin_modulation_fit(g1_steps, *initial_guess)
            fit_coeff_g1_to_wavelength, pcov = opt.curve_fit(lin_sin_modulation_fit, g1_steps, wavelength_axis, p0=initial_guess)
            p_g1_to_wavelength = lambda x: lin_sin_modulation_fit(x, *fit_coeff_g1_to_wavelength)

        elif model == 'polysin':
            print('Fitting with polysin')
            # initial_guess = [0.01, 800, -1.53840861,  0.00463291, -1.04822887, -0.2]
            # fit_coeff_g1_to_wavelength = poly_sin_modulation_fit(g1_steps, *initial_guess)
            fit_coeff_g1_to_wavelength, pcov = opt.curve_fit(poly_sin_modulation_fit, g1_steps, wavelength_axis, p0=initial_guess)
            p_g1_to_wavelength = lambda x: poly_sin_modulation_fit(x, *fit_coeff_g1_to_wavelength)
        else:
            print("Fitting with polynomial of order {}".format(poly_order))
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

    def wavelength_to_g1_test(self, poly_order=1, mode=None, show=False, model='poly'):
        '''Calibration for using laser wavelength to calculate G1 steps.'''

        wavelength_axis = self.wavelength_axis
        g1_steps = self.data_array[:, 1]

        assert mode in ['subtractive', 'additive'], 'Invalid mode. Must be either "subtractive" or "additive".'

        # if mode == 'subtractive':
        #     wavelength_axis = self.laser_wavelength_axis
        #     print('using laser wavelength axis')
        # elif mode == 'additive':
        #     wavelength_axis = self.grating_wavelength_axis
        #     print('using grating wavelength axis')

        initial_guess = [8.196252645921234, -800, -54.08824066045618, 0.02544855329855095, 20.71117654365508, 0]


        print("Fitting with polynomial of order {}".format(1))
        fit_coeff_wavelength_to_g1 = np.polyfit(wavelength_axis, g1_steps, 1)       
        p_wavelength_to_g1 = np.poly1d(fit_coeff_wavelength_to_g1)

        y_pred = p_wavelength_to_g1(wavelength_axis)
        residuals = g1_steps - y_pred
        fit_metrics = self.calculate_fit_metrics(g1_steps, y_pred)
        self.report_dict[mode]['wl_to_g1_{}'.format(mode)] = (fit_metrics, fit_coeff_wavelength_to_g1.tolist())
        print(fit_metrics)
        print("Fitting residuals with sin function")
        #
        resid_fit, pcov = opt.curve_fit(simple_sin_fit, wavelength_axis, residuals, p0=initial_guess[2:])
        p_resid = lambda x: simple_sin_fit(x, *resid_fit)
        y_pred_resid = p_resid(wavelength_axis)
        residuals = g1_steps - y_pred_resid

        # Fit quality metrics
        fit_metrics = self.calculate_fit_metrics(residuals, y_pred_resid)
        self.report_dict[mode]['wl_to_g1_resid_{}'.format(mode)] = (fit_metrics, resid_fit.tolist())
        print(fit_metrics)

        # plt.plot(wavelength_axis, residuals)

        # Fit quality metrics

        if show is True or self.showplots is True:
            fig, ax = plt.subplots(2, 1)
            ax[0].scatter(wavelength_axis, g1_steps, label='G1 Steps')
            ax[0].plot(wavelength_axis, p_wavelength_to_g1(wavelength_axis), label='G1 Steps fit', color='tab:purple')
            residuals = g1_steps - p_wavelength_to_g1(wavelength_axis)
            ax[1].plot(wavelength_axis, residuals, label='G1 Steps residuals', marker='o')
            ax[1].plot(wavelength_axis, p_resid(residuals), label='Residuals fit', color='tab:orange', marker='o')
            ax[1].plot(wavelength_axis, y_pred_resid, label='Residuals fit', color='tab:orange', marker='o')
            ax[0].set_title('Wavelength to G1 Steps')
            ax[0].legend()
            ax[1].legend()
            plt.show()

        self.calibration_metrics['wl_to_g1_{}'.format(mode)] = fit_metrics
        self.calibrations['wl_to_g1_{}'.format(mode)] = fit_coeff_wavelength_to_g1.tolist()

        return fit_coeff_wavelength_to_g1, fit_metrics
        


def sort_by_key(value):
    return int(value.split('_')[1])

def get_latest_calibration_file(dataDir):
    fileList = [file for file in os.listdir(os.path.join(os.path.dirname(__file__), 'autocalibration')) if file.endswith('.json')]
    fileList = [f.split('.')[0] for f in fileList]
    sorted_files = sorted(fileList, key=lambda x: int(x.split('_')[1]))
    return sorted_files[-1]+'.json'


class Peaks:

    def __init__(self, peak_type, position, amplitude, fwhm, eta=None):
        self.peak_type = peak_type
        self.pos = position
        self.amp = amplitude
        self.fwhm = fwhm
        self.eta = eta

    def __repr__(self):
        return f'Peak Object(pos={round(self.pos, 2)}, amp={round(self.amp, 2)}, fwhm={round(self.fwhm, 2)})'

def mask_data(dataDict, range:tuple):
    newData = {}
    for wavelength, data in dataDict.items():
        if wavelength >= range[0] and wavelength <= range[1]:
            newData[wavelength] = data
    
    return newData
    

# def peakfit_autocal(scriptDir, dataDir, calibration_name):
#     working_calibration_file = get_latest_calibration_file(dataDir)
#     dataSet = asp.DataSet(dataDir, fileList=[working_calibration_file])

#     fileObj = dataSet.dataDict.get(working_calibration_file)
#     dataSet.dataDict = fileObj.data
#     dataSet.dataDict = mask_data(dataSet.dataDict, (710, 880))
    

#     for cal_obj in dataSet.dataDict.values():
#         # cal_obj._invert_data()
#         cal_obj._minimise_data()
#         cal_obj._apply_smoothing(window_length=7)
#         # cal_obj._plot_individual()
    
#     dataSet.plot_current()


#     # dataSet.minimise_all()
#     # dataSet.baseline_all(show=False, lam=100, p=0.01)

#     peakfitting_info = {
#         'peak_list': [],
#         'peak_type': 'voigt_pseudo',
#         'peak_sign': 'positive',
#         'threshold': 0.01, # percentage of max intensity
#         'peak_detect': 'all',
#         'copy_peaks': False,
#     } 
#     dataSet._peakfit(peakfitting_info=peakfitting_info)
#     dataSet.save_database(tagList='', seriesName=calibration_name)

# def generate_autocal(scriptDir, dataDir, calibration_name):
#     key_index = {
#         'pos': 1,
#         'amp': 2,
#         'fwhm': 3,
#     }
#     dataSet = asp.DataSet(dataDir)
#     dataSet.load_database(calibration_name)
#     # dataSet.plot_peaks()
#     # dataSet.plot_current()

#     calibration_peaks = {}

#     for wave, peakdict in dataSet.peakfitDict.items():
#         peak_list = []
#         peaks = peakdict['peaks']
#         if len(peaks) == 0:
#             continue
#         # print(wave, peaks)
#         for peak in peaks:
#             # breakpoint()
#             peak_list.append(Peak(*peak))
#         if len(peak_list) > 1:
#             peak_list.sort(key=lambda x: x.amp)
#         peak = peak_list[0]
#         calibration_peaks[wave] = peak

#     for key, value in calibration_peaks.items():
#         print(key, value)
#     # breakpoint()
#     calibration = Calibration(calibration_peaks, showplots=True)
#     fit, fitmetrics1 = calibration.wavelength_to_g1(mode='subtractive', show=True, model='poly', poly_order=1)
#     print(fit)
#     print(fitmetrics1)
#     fit, fitmetrics2 = calibration.g1_to_wavelength(mode='subtractive', show=True, model='poly', poly_order=1)
#     print(fit)
#     print(fitmetrics2)
#     # fit, fitmetrics3 = calibration.wavelength_to_g1_test(mode='subtractive', show=True, poly_order=1)
#     # print(fit)
#     # print(fitmetrics3)
#     breakpoint()
#     calibration.save_calibration(calibration_name)
#     breakpoint()
        


# series name - name of file
calibration_name = 'autocal_2'
scriptDir = os.path.dirname(__file__)
dataDir = os.path.join(scriptDir, 'autocalibration')

autocal = AutoCalibration(showplots=True, smoothing=1)
# autocal.autocalibrate_all(manual=False)
autocal.autocalibrate_motor_axis('g1', manual=True, poly_order=2, load=False, linked=True, data_mask=(750,850)) # linked applies scalar calculation of g2-4 from g1 
breakpoint()

# TODO: create unit tests, create metric for quality assessment at a glance

# OLD
# peakfit_autocal(scriptDir, dataDir, calibration_name)
# generate_autocal(scriptDir, dataDir, calibration_name)
