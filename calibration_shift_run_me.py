import numpy as np
import json
import matplotlib.pyplot as plt
import shutil
import os
import datetime

class CalibrationEdit:
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

    def __init__(self, master_calib_path=None):
        if master_calib_path is None:
            self.calibration_dir = os.path.join(os.path.dirname(__file__), 'calibration')
            self.master_calib_path = os.path.join(self.calibration_dir, 'master_calibration_microsteps_32.json')
        else:
            self.master_calib_path = master_calib_path
            if not os.path.exists(self.master_calib_path):
                raise FileNotFoundError(f"Master calibration file not found at {self.master_calib_path}")
            self.calibration_dir = os.path.dirname(self.master_calib_path)

        self.backup_dir = os.path.join(self.calibration_dir, 'backup')
        os.makedirs(self.backup_dir, exist_ok=True)

        self.master_calibration = self.load_master_calibration()

    def load_master_calibration(self):
        with open(self.master_calib_path, 'r') as f:
            return json.load(f)

    def shift_calibration(self, calibration_type, shift,
                          wl_min=700, wl_max=900, n_points=200,
                          poly_order=2, make_backup=True, overwrite_cal=True,
                          reference_nm=800):
        if calibration_type not in self.calibration_map:
            raise KeyError(f"Calibration type '{calibration_type}' not found in calibration map.")
        
        # Backup
        if make_backup:
            base = os.path.splitext(os.path.basename(self.master_calib_path))[0]
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_path = os.path.join(self.backup_dir, f"{base}.bak-{timestamp}.json")
            shutil.copy2(self.master_calib_path, backup_path)
            print(f"Backup saved to {backup_path}")

        label = self.calibration_map[calibration_type]
        forward_key = f"wl_to_{label}"
        inverse_key = f"{label}_to_wl"

        p_fwd = np.poly1d(self.master_calibration[calibration_type][forward_key])

        if isinstance(shift, tuple):
            units, value = shift
            if units == 'nm':
                wl1 = reference_nm
                wl2 = reference_nm + value
                steps1 = p_fwd(wl1)
                steps2 = p_fwd(wl2)
                shift_steps = steps2 - steps1
                print(f"Shift of {value} nm at {reference_nm} nm → {shift_steps:.3f} steps")
            elif units == 'steps':
                shift_steps = value
            else:
                raise ValueError("Shift must be a tuple like ('nm', Δnm) or ('steps', Δsteps)")
        else:
            raise ValueError("Shift must be provided as a tuple (units, value)")

        wavelengths = np.linspace(wl_min, wl_max, n_points)
        original_steps = p_fwd(wavelengths)
        shifted_steps = original_steps + shift_steps

        new_fwd = np.polyfit(wavelengths, shifted_steps, poly_order).tolist()
        new_inv = np.polyfit(shifted_steps, wavelengths, poly_order).tolist()

        self.master_calibration[calibration_type][forward_key] = new_fwd
        self.master_calibration[calibration_type][inverse_key] = new_inv

        # Plot
        plt.figure()
        plt.plot(wavelengths, original_steps, 'r--', label='Original')
        plt.plot(wavelengths, shifted_steps, 'b-', label='Shifted')
        plt.xlabel('Wavelength (nm)')
        plt.ylabel('Steps')
        plt.title(f'Calibration Shift ({shift[0]} = {shift[1]})')
        plt.legend()
        plt.tight_layout()
        plt.show()

        if overwrite_cal:
            with open(self.master_calib_path, 'w') as f:
                json.dump(self.master_calibration, f, indent=4)
            print(f"Calibration updated: {self.master_calib_path}")

        return self.master_calibration

if __name__ == "__main__":
    cal = CalibrationEdit()
    cal.shift_calibration(
        'triax_calibrations',
        shift=('nm', 2.1),  # shift by -2 nm at 800 nm
        wl_min=650,
        wl_max=1100,
        n_points=200,
        poly_order=2,
        overwrite_cal=True,
        make_backup=True
    )
