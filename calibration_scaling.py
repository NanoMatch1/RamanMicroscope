# import os
# import json
# import glob
# import numpy as np

# # Microstepping values to generate calibrations for
# MICROSTEP_VALUES = [16, 32, 64]
# REFERENCE_MICROSTEP = 128  # The current base microstepping factor
# reference_keys = ['g1', 'g2', 'g3', 'g4']  # Keys to be used for reference

# # Folder containing your calibration JSONs
# SOURCE_DIR = os.path.join(os.path.dirname(__file__), "calibration")  # Change as needed

# def wl_to_steps(coeff):
#     distr = np.arange(700, 900, 1)  # Example distribution of wavelengths
#     calib = np.poly1d(coeff)
#     steps = calib(distr)  # Apply polynomial to wavelength distribution
#     return steps


# def steps_to_wl(coeff):
#     distr = np.arange(-10000,10000, 1)  # Example distribution of steps
#     calib = np.poly1d(coeff)
#     wl = calib(distr)  # Apply polynomial to steps distribution
#     return wl


# test = wl_to_steps([0.10804683994803718, 331.8588098129754, 43950.89354704326])
# print("Steps:", test)



# # Create scaled versions
# def scale_polynomial(coeffs, scale, mode='forward'):
#     """Scales polynomial coefficients by a step factor."""
#     if mode == 'forward':  # wl_to_motor: steps increase with microstep
#         return [c * scale**i for i, c in enumerate(reversed(coeffs))][::-1]
#     elif mode == 'reverse':  # motor_to_wl: input steps are larger → divide
#         return [c / (scale**i) for i, c in enumerate(reversed(coeffs))][::-1]
#     else:
#         raise ValueError("mode must be 'forward' or 'reverse'")

# # Process each file
# json_files = [file for file in os.listdir(SOURCE_DIR) if file.endswith('.json')]


# for microstep in MICROSTEP_VALUES:
#     scale = microstep / REFERENCE_MICROSTEP
#     if not os.path.exists(os.path.join(SOURCE_DIR, f"microstep_{microstep}")):
#         os.makedirs(os.path.join(SOURCE_DIR, f"microstep_{microstep}"))
#     for file in json_files:
#         cal_dict = {}
#         filepath = os.path.join(SOURCE_DIR, file)        

#         with open(filepath, 'r') as f:
#             data = json.load(f)



#         for key, coeffs in data.items():
#             if not any(k in key for k in reference_keys):
#                 cal_dict[key] = coeffs # leave untouched if not matched to key
#                 continue
#             # Skip keys that are not in reference_keys
#             if key.startswith("wl_to_"):
#                 cal_dict[key] = scale_polynomial(coeffs, scale, mode='forward')
#                 print(f"Forward scaling for {key}: {cal_dict[key]}")
#             elif key.endswith("_to_wl"):
#                 cal_dict[key] = scale_polynomial(coeffs, scale, mode='reverse')
#                 print(f"Reverse scaling for {key}: {cal_dict[key]}")
#             else:
#                 cal_dict[key] = coeffs  # leave untouched if unknown key

#             # Save to subdirectory
#             out_dir = os.path.join(SOURCE_DIR, f"microstep_{microstep}")
#             os.makedirs(out_dir, exist_ok=True)
#             out_path = os.path.join(out_dir, file)

#             with open(out_path, 'w') as f:
#                 json.dump(cal_dict, f, indent=2)

#             # print(f"Saved scaled calibration for µstep={microstep}: {out_path}")


import os
import json
import numpy as np
import argparse
import matplotlib.pyplot as plt

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

if __name__ == "__main__":


    input_dir = os.path.join(os.path.dirname(__file__), "calibration")
    output_dir = os.path.join(os.path.dirname(__file__), "calibration", "scaled_calibrations")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)


    main(
        input_dir=input_dir,
        output_dir=output_dir,
        microsteps=32,  # Example microsteps value
        poly_order=2,
        wl_min=700.0,
        wl_max=900.0,
        n_points=100
    )
