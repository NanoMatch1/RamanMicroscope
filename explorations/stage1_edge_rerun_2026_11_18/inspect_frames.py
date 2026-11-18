"""List the 2026-11-18 stage 1 edge rerun frames: exposure, TRIAX, g1/g2, levels, saturation,
and where the light sits on the CCD (band centroid row, brightest columns).

Run: PYTHONPATH=.:explorations/stage1_edge_rerun_2026_11_18 .venv/bin/python \
     explorations/stage1_edge_rerun_2026_11_18/inspect_frames.py
"""
import glob
import json
import os

import numpy as np

import exploration_paths

DATA_DIRECTORY = exploration_paths.DATA_DIRECTORY
OUTPUT_PATH = os.path.join(exploration_paths.OUTPUT_DIRECTORY, 'inspect_frames.txt')
SATURATION_LEVEL = 65535

output_lines = []


def report(text=''):
    output_lines.append(text)
    print(text)


def main():
    frame_paths = sorted(glob.glob(os.path.join(DATA_DIRECTORY, 's1*', '*', '*.npz')))
    first = np.load(frame_paths[0], allow_pickle=False)
    report(f'{len(frame_paths)} frames; keys: {first.files}')
    for key in first.files:
        report(f'  {key}: {first[key].dtype} {first[key].shape}')
    metadata = json.loads(str(first['metadata']))
    report(json.dumps(metadata, indent=1, default=str)[:2500])
    report()
    report('frame'.ljust(34) + 'exp    triax   mono_wl  g1    g2    wl range       median  '
           'p99.9   max    sat   centroid_row  modified')
    for path in frame_paths:
        frame = np.load(path, allow_pickle=False)
        image = frame['image'].astype(float)
        metadata = json.loads(str(frame['metadata']))
        current = metadata.get('_current_parameters', {})
        motors = current.get('motor_positions', current.get('all_motor_positions', {})) or {}
        wavelength = frame['wavelength']
        column_profile = image.mean(axis=1)
        background = np.median(column_profile)
        above = np.clip(column_profile - background, 0, None)
        centroid_row = (np.sum(np.arange(len(above)) * above) / above.sum()
                        if above.sum() > 0 else np.nan)
        report(f'{os.path.basename(path)[:-4]:34s}{str(current.get("acquisition_time")):6s} '
               f'{str(current.get("spectrometer_steps")):7s} '
               f'{str(current.get("monochromator_wavelength", "-"))[:7]:8s} '
               f'{str(motors.get("g1", "-")):5s} {str(motors.get("g2", "-")):5s} '
               f'{wavelength[0]:6.1f}-{wavelength[-1]:6.1f}  {np.median(image):6.0f} '
               f'{np.percentile(image, 99.9):7.0f} {image.max():6.0f} '
               f'{int((image >= SATURATION_LEVEL).sum()):5d} {centroid_row:8.1f}  '
               f'{os.path.getmtime(path):.0f}')
    with open(OUTPUT_PATH, 'w') as output:
        output.write('\n'.join(output_lines) + '\n')


if __name__ == '__main__':
    main()
