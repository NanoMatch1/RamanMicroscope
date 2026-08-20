"""
pixel_to_wl_calibration.py
──────────────────────────
Fit a new pixel_to_wl and wl_to_pixel calibration from measured
(pixel, true_wavelength) pairs and update master_calibration_microsteps_32.json.

Usage
-----
1. Run `sl <wavelength>` at two or more known wavelengths.
2. Record the `Peak pixel` and `Live-cal λ` values from the [POST-FIT] line.
3. Enter them in MEASUREMENTS below.
4. Run this script.
"""

import os
import json
import shutil
import datetime
import numpy as np
import matplotlib.pyplot as plt

# ── 1. Enter your measurements here ───────────────────────────────────────────
# Format: (peak_pixel, true_wavelength_nm)
# true_wavelength_nm should come from your wavemeter / live-cal λ

MEASUREMENTS = [
    (310.26, 788.415),   # e.g. (312.4, 785.000)
    (106.21, 772.59),   # e.g. (687.1, 810.000)
    # add more rows here if you have them
]

# ── 2. Path to master calibration file ────────────────────────────────────────
SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
CAL_DIR      = os.path.join(SCRIPT_DIR, 'calibration')
MASTER_FILE  = os.path.join(CAL_DIR, 'master_calibration_microsteps_32.json')
BACKUP_DIR   = os.path.join(CAL_DIR, 'backup')

# ── 3. Fit ────────────────────────────────────────────────────────────────────

def fit_calibration(measurements, poly_order=1):
    data       = np.array(measurements, dtype=float)
    pixels     = data[:, 0]
    wavelengths = data[:, 1]

    # pixel → wavelength
    coeff_p2w  = np.polyfit(pixels, wavelengths, poly_order)
    poly_p2w   = np.poly1d(coeff_p2w)

    # wavelength → pixel
    coeff_w2p  = np.polyfit(wavelengths, pixels, poly_order)
    poly_w2p   = np.poly1d(coeff_w2p)

    # residuals
    pred_wl    = poly_p2w(pixels)
    residuals  = wavelengths - pred_wl
    rmse       = np.sqrt(np.mean(residuals ** 2))

    return coeff_p2w, coeff_w2p, poly_p2w, poly_w2p, residuals, rmse


def plot_fit(measurements, poly_p2w, residuals):
    data        = np.array(measurements, dtype=float)
    pixels      = data[:, 0]
    wavelengths = data[:, 1]

    pixel_range = np.linspace(0, 1023, 1024)

    fig, ax = plt.subplots(2, 1, figsize=(8, 6))

    ax[0].scatter(pixels, wavelengths, color='black', zorder=5, label='Measured')
    ax[0].plot(pixel_range, poly_p2w(pixel_range), color='tab:blue', label='Fit')
    ax[0].set_xlabel('Pixel')
    ax[0].set_ylabel('Wavelength (nm)')
    ax[0].set_title('Pixel → Wavelength Calibration')
    ax[0].legend()

    ax[1].scatter(pixels, residuals, color='tab:red', zorder=5)
    ax[1].axhline(0, color='black', linewidth=0.8)
    ax[1].set_xlabel('Pixel')
    ax[1].set_ylabel('Residual (nm)')
    ax[1].set_title(f'Residuals  (RMSE = {np.sqrt(np.mean(residuals**2)):.4f} nm)')

    plt.tight_layout()
    plt.show()


def update_master(master_file, backup_dir, coeff_p2w, coeff_w2p):
    # Backup
    os.makedirs(backup_dir, exist_ok=True)
    timestamp   = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(
        backup_dir,
        f"master_calibration_microsteps_32.bak-{timestamp}.json"
    )
    shutil.copy2(master_file, backup_path)
    print(f"Backup saved to {backup_path}")

    # Load
    with open(master_file, 'r') as f:
        master = json.load(f)

    # Update
    master['camera_calibrations']['pixel_to_wl'] = coeff_p2w.tolist()
    master['camera_calibrations']['wl_to_pixel']  = coeff_w2p.tolist()

    # Save
    with open(master_file, 'w') as f:
        json.dump(master, f, indent=4)

    print(f"Master calibration updated: {master_file}")
    print(f"  pixel_to_wl: {coeff_p2w.tolist()}")
    print(f"  wl_to_pixel: {coeff_w2p.tolist()}")


# ── 4. Main ───────────────────────────────────────────────────────────────────

if __name__ == '__main__':

    if len(MEASUREMENTS) < 2:
        raise ValueError("Need at least 2 measurements. Add more to MEASUREMENTS.")

    coeff_p2w, coeff_w2p, poly_p2w, poly_w2p, residuals, rmse = fit_calibration(
        MEASUREMENTS, poly_order=1
    )

    print("\n── Fit Results ──────────────────────────────────────────")
    print(f"  pixel_to_wl coefficients : {coeff_p2w.tolist()}")
    print(f"  wl_to_pixel  coefficients : {coeff_w2p.tolist()}")
    print(f"  RMSE                      : {rmse:.4f} nm")
    print(f"  Residuals per point       :")
    data = np.array(MEASUREMENTS, dtype=float)
    for i, (pix, wl) in enumerate(MEASUREMENTS):
        print(f"    pixel {pix:.1f}  true {wl:.3f} nm  "
              f"fit {poly_p2w(pix):.3f} nm  "
              f"residual {residuals[i]:+.4f} nm")

    plot_fit(MEASUREMENTS, poly_p2w, residuals)

    confirm = input("\nWrite new coefficients to master calibration file? (yes/no): ")
    if confirm.strip().lower() == 'yes':
        update_master(MASTER_FILE, BACKUP_DIR, coeff_p2w, coeff_w2p)
    else:
        print("Calibration not saved. Re-run and enter 'yes' to save.")
