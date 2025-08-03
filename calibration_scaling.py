
import os
import json
import numpy as np
import argparse
import matplotlib.pyplot as plt
import datetime

from scipy.fftpack import shift

def load_calibration(file_path):
    """Load a calibration JSON file."""
    with open(file_path, 'r') as f:
        data = json.load(f)
    return data

def save_calibration(data, file_path):
    """Save calibration data to a JSON file."""
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=4)

def process_calibration(calib_data, new_microsteps, poly_order=2, wl_min=700, wl_max=900, n_points=100, key_filter=['g1', 'g2', 'g3', 'g4']):
    """
    Process a single calibration dictionary:
    1. Build a reference wavelength array.
    2. For each forward calibration (key starts with "wl_to_"):
       - Compute the original motor steps.
       - Scale them by new_microsteps/128.
       - Re-fit a forward polynomial.
       - Re-fit the inverse polynomial from the scaled motor steps.
    Returns a new calibration dictionary with updated coefficients.
    """
    # Scale factor: new microsteps divided by old microsteps (128)
    scale = new_microsteps / 128.0

    new_calib = {}
    # Create a dense reference array of wavelengths
    wavelengths = np.linspace(wl_min, wl_max, n_points)

    # Loop over calibration keys that match the forward mapping
    for key in calib_data:
        if not any(k in key for k in key_filter):
            new_calib[key] = calib_data[key]  # Leave untouched if not matched to key
            continue

        if key.startswith("wl_to_"):
            axis = key[len("wl_to_"):]  # e.g., "l3" extracted from "wl_to_l3"
            # Get original forward coefficients and build a polynomial object
            orig_fwd_coeff = calib_data[key]
            poly_fwd = np.poly1d(orig_fwd_coeff)
            
            # Generate the "old" motor steps from the reference wavelengths
            original_motor_steps = poly_fwd(wavelengths)
            # Scale motor steps to the new microsteps value
            new_motor_steps = scale * original_motor_steps

            # Re-fit the forward polynomial: wavelength → new_motor_steps
            new_fwd_coeff = np.polyfit(wavelengths, new_motor_steps, poly_order).tolist()
            # Re-fit the inverse polynomial: new_motor_steps → wavelength
            new_inv_coeff = np.polyfit(new_motor_steps, wavelengths, poly_order).tolist()



            fig, ax = plt.subplots(2, 1)
            ax[0].scatter(wavelengths, new_motor_steps, label=f'{axis} steps', color='black')
            ax[0].plot(wavelengths, new_motor_steps, label='Fit', color='tab:purple')
            ax[0].plot(wavelengths, poly_fwd(wavelengths), label='Original Fit', color='tab:orange')
            ax[0].set_xlabel('Wavelength (nm)')
            ax[0].set_ylabel('Steps')
            ax[0].set_title(f'Wavelength to {axis.upper()} Calibration')
            ax[0].legend()

            # ax[1].plot(wavelengths, residuals_fwd, label='Residuals', marker='o')
            ax[1].set_ylabel('Residuals')
            ax[1].set_xlabel('Wavelength (nm)')
            ax[1].legend()
            plt.tight_layout()
            plt.show()

            # Store the new calibrations under the same naming convention
            new_calib[f"wl_to_{axis}"] = new_fwd_coeff
            new_calib[f"{axis}_to_wl"] = new_inv_coeff

    return new_calib

def main(input_dir, output_dir, microsteps, poly_order=2, wl_min=400, wl_max=800, n_points=100):
    """
    For all JSON calibration files in input_dir:
       - Process and scale the calibration using process_calibration.
       - Save each updated calibration in an output folder labelled with the microsteps value.
       - Build a master calibration dictionary that aggregates the new calibrations from each file.
       - Save the master calibration file.
    """
    # Create an output folder for the individual scaled calibration files.
    output_folder = os.path.join(output_dir, f"microsteps_{microsteps}")
    os.makedirs(output_folder, exist_ok=True)

    master_calibration = {}

    # Process each JSON file in the input directory
    for file_name in os.listdir(input_dir):
        if file_name.endswith('.json'):
            file_path = os.path.join(input_dir, file_name)
            calib_data = load_calibration(file_path)
            new_calib = process_calibration(calib_data, microsteps, poly_order, wl_min, wl_max, n_points)
            
            # Save the new calibration in the output folder
            out_file_path = os.path.join(output_folder, file_name)
            save_calibration(new_calib, out_file_path)
            
            # Add to the master calibration dictionary
            master_calibration[file_name] = new_calib

    # Save the master calibration file in the designated output directory
    master_file_name = f"master_calibration_microsteps_{microsteps}.json"
    master_file_path = os.path.join(output_dir, master_file_name)
    save_calibration(master_calibration, master_file_path)
    print(f"Processed calibrations saved in {output_folder}")
    print(f"Master calibration file saved as {master_file_path}")

import numpy as np
import json
import matplotlib.pyplot as plt
import shutil
import os

class CalibrationEdit:
    """
    Class to handle calibration edits, specifically shifting the triax axis
    calibration by a constant number of motor steps.
    """
    calibration_labels = {
        'triax': ['wl_to_triax', 'triax_to_wl'],
        'l1': ['wl_to_l1', 'l1_to_wl'],
        'l2': ['wl_to_l2', 'l2_to_wl'],
        'l3': ['wl_to_l3', 'l3_to_wl'],
        'g1': ['wl_to_g1', 'g1_to_wl'],
        'g2': ['wl_to_g2', 'g2_to_wl'],
        'g3': ['wl_to_g3', 'g3_to_wl'],
        'g4': ['wl_to_g4', 'g4_to_wl'],
    }

    calibration_map = {
        'triax_calibrations': 'triax'
    }

    def __init__(self, master_calib_path = None):
        if master_calib_path is None:
            self.calibration_dir = os.path.join(os.path.dirname(__file__), 'calibration')
            self.master_calib_path = os.path.join(self.calibration_dir, 'master_calibration_microsteps_32.json')
        else:
            self.master_calib_path = master_calib_path
            if not os.path.exists(self.master_calib_path):
                raise FileNotFoundError(f"Master calibration file not found at {self.master_calib_path}")
            self.calibration_dir = os.path.dirname(self.master_calib_path)

        self.backup_dir = os.path.join(self.calibration_dir, 'backup')
        if not os.path.exists(self.backup_dir):
            os.makedirs(self.backup_dir)

        self.master_calibration = self.load_master_calibration()
        
    def load_master_calibration(self):
        """Load the master calibration JSON file."""
        with open(self.master_calib_path, 'r') as f:
            self.master_calibration = json.load(f)
        return self.master_calibration

    def shift_calibration(self, calibration_type, shift,
                                wl_min=700, wl_max=900, n_points=200,
                                poly_order=2, make_backup=True, overwrite_cal=True):
        """
        Reads in the 'master' calibration JSON, applies a constant motor-step shift
        to the triax-axis calibration, re-fits forward & inverse polynomials,
        and overwrites the master file (optionally keeping a timestamped backup).

        Parameters
        ----------
        new_calibration_path : str
            Path to the new calibration JSON file.
        calibration_type : str
            Type of calibration to shift (e.g., 'triax').
        shift_steps : float
            The number of motor steps to subtract from the original forward mapping.
        wl_min, wl_max : float
            Wavelength range (nm) over which to sample & re-fit.
        n_points : int
            Number of points for the dense sampling grid.
        poly_order : int
            Order of the polynomial to fit (typically 2 or 3).
        make_backup : bool
            If True, copy the original file to
            master_calib_path + '.bak-<timestamp>' before overwriting.

        Returns
        -------
        new_calib : dict
            The updated calibration dict with keys
            "wl_to_triax" and "triax_to_wl".
        """

        # Backup original file
        if make_backup:
            base, ext = os.path.splitext(self.master_calib_path)
            backup_path = os.path.join(self.backup_dir, f"{base}.bak-{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}")
            shutil.copy2(self.master_calib_path, backup_path)
            print(f"Backup saved to {backup_path}")



        # Sample wavelengths
        wavelengths = np.linspace(wl_min, wl_max, n_points)
        calibration_keys = self.master_calibration[calibration_type]

        # Original forward poly: wavelength → steps
        if calibration_type not in self.calibration_map:
            raise KeyError(f"Calibration type '{calibration_type}' not found in calibration map.")

        calibration_label = self.calibration_map.get(calibration_type, calibration_type)

        forward_key = f"wl_to_{calibration_label}"
        inverse_key = f"{calibration_label}_to_wl"
        p_fwd_orig = np.poly1d(calibration_keys[forward_key])
        steps_orig = p_fwd_orig(wavelengths)

        difference = p_fwd_orig(761.14) - p_fwd_orig(761.14 - 2)
        print(f"Difference at 761.14 nm: {difference} steps")
        shift_steps = difference
        breakpoint()
        # Apply constant shift
        steps_shifted = steps_orig + shift_steps

        # Re‑fit forward (wavelength → shifted steps)
        new_fwd_coeff = np.polyfit(wavelengths, steps_shifted, poly_order).tolist()

        # Re‑fit inverse (shifted steps → wavelength)
        new_inv_coeff = np.polyfit(steps_shifted, wavelengths, poly_order).tolist()

        # (Optional) Plot for quick sanity check
        plt.figure(figsize=(8,4))
        plt.plot(wavelengths, steps_orig, 'r--', label="Original")
        plt.plot(wavelengths, steps_shifted, 'b-', label="Shifted")
        plt.xlabel("Wavelength (nm)")
        plt.ylabel("Triax Steps")
        plt.title("Calibration Shift")
        plt.legend()
        plt.tight_layout()
        plt.show()

        # Update and overwrite
        self.master_calibration[forward_key] = new_fwd_coeff
        self.master_calibration[inverse_key] = new_inv_coeff

        if overwrite_cal is True:
            with open(self.master_calib_path, 'w') as f:
                json.dump(self.master_calibration, f, indent=4)

            print(f"Master calibration updated in {self.master_calib_path}")
            return self.master_calibration

        breakpoint()





if __name__ == "__main__":


    # input_dir = os.path.join(os.path.dirname(__file__), "calibration")
    # output_dir = os.path.join(os.path.dirname(__file__), "calibration", "scaled_calibrations")
    # if not os.path.exists(output_dir):
        # os.makedirs(output_dir)



    # new_calibration_path = r'C:\Users\Sam\matchbook\ramanproject\RamanMicroscope\calibration\modifications\Spectrometer Calibration.csv'
    # new_data = []
    # with open(new_calibration_path, 'r') as f:
    #     newline = f.read().replace('\r\n', '\n')
    #     new_data = newline.split('\n')
    # new_data = [line.split(',') for line in new_data if line.strip()]
    # new_data_array = np.array(new_data[1:], dtype=float)
    # new_data_dict = {
    #     new_data[0][0]: new_data_array[:, 0],
    #     new_data[0][1]: new_data_array[:, 1],
    #     new_data[0][2]: new_data_array[:, 2],
    # }

    # diff = new_data_array[:, 0] - new_data_array[:, 1]
    # print("Difference between Oceanoptics and Spectrometer:", diff)

    # plt.scatter(new_data_dict['Oceanoptics'], new_data_dict['Spectrometer'])
    # plt.show()
    # breakpoint()


    

    cal = CalibrationEdit()
    # Example usage of shift_master_calibration
    shift_steps = 1000  # Example shift value

    cal.shift_calibration(
        'triax_calibrations',
        shift=('nm', -2),
        wl_min=650,
        wl_max=1100,
        n_points=200,
        poly_order=2,
        overwrite_cal=False,
        make_backup=False
    )

    # main(
    #     input_dir=input_dir,
    #     output_dir=output_dir,
    #     microsteps=32,  # Example microsteps value
    #     poly_order=2,
    #     wl_min=700.0,
    #     wl_max=900.0,
    #     n_points=100
    # )
