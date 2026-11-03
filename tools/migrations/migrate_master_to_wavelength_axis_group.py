"""
One-off migration (2026-11-03): replace the master file's `camera_calibrations`
and `triax_calibrations` groups with a single `wavelength_axis` group.

Behaviour is preserved: same TRIAX slope and offset, same nm per pixel, same
reference pixel (50). Dropped: the TRIAX quadratic term (-7.4e-22 nm/step^2,
under 1e-11 nm anywhere in range) and the separately fitted inverses, which
are now computed exactly from the forward model. The axis also loses the
1/1023 linspace stretch (wavelength_calibration.wavelength_axis_model).

Run once from the repository root:
    python tools/migrations/migrate_master_to_wavelength_axis_group.py
"""

import json
import os
import shutil
import datetime

REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
MASTER_PATH = os.path.join(REPOSITORY_ROOT, 'calibration', 'master_calibration_microsteps_32.json')
BACKUP_DIRECTORY = os.path.join(REPOSITORY_ROOT, 'calibration', 'backup')


def migrate(master):
    if 'wavelength_axis' in master:
        raise SystemExit('Master file already has a wavelength_axis group; nothing to do.')
    camera_group = master.pop('camera_calibrations')
    triax_group = master.pop('triax_calibrations')

    pixel_to_wavelength_slope, _ = camera_group['pixel_to_wl']
    _, triax_slope, triax_intercept = triax_group['triax_to_wl']
    master['wavelength_axis'] = {
        'reference_pixel': 50.0,
        'triax_to_wavelength_coefficients': [triax_slope, triax_intercept],
        'nm_per_pixel': pixel_to_wavelength_slope,
        'nm_per_pixel_squared': 0.0,
        'metadata': {
            'migrated_on': datetime.date.today().isoformat(),
            'verified_against_external_reference': False,
            'provenance': (
                'Migrated from camera_calibrations (PIXIS slope, set via tools/Calibrationgenerator.py, '
                'which is circular) and triax_calibrations (2025-07-31). The slope matches the pixel '
                'pitch; the offset was never measured on the PIXIS. Replace with a line walk '
                '(docs/calibration.md section 3).'),
        },
    }
    return master


if __name__ == '__main__':
    with open(MASTER_PATH) as file:
        master = json.load(file)
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    backup_path = os.path.join(BACKUP_DIRECTORY, f'master_calibration_microsteps_32.bak-{timestamp}.json')
    shutil.copyfile(MASTER_PATH, backup_path)
    with open(MASTER_PATH, 'w') as file:
        json.dump(migrate(master), file, indent=4)
    print(f'Migrated {MASTER_PATH}\nBackup:  {backup_path}')
