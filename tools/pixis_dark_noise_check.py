"""
PIXIS dark noise check: read noise against dark current, to choose the frame length.

A long point can be one long frame or several shorter ones (`nframe`). Several frames let a
cosmic ray spoil one frame instead of the point, but each frame adds the read noise once:

    noise^2 per frame (counts^2) = read^2 + dark rate x t / K     (K = electrons per count)

So frames cost little once the dark noise of each frame clearly exceeds the read noise. This
script measures both, with the light blocked, at a few exposures:

  1. the whole sensor, every row read out: per pixel, the bias (shortest exposure), the dark
     signal and its rate, the read noise, a conversion-gain estimate from how the noise grows
     with the dark signal, hot pixels, and the frame length at which read noise is
     `--read-fraction` (default 10 %) of the noise in a frame;
  2. the data ROI with its rows binned on the chip, measured directly (read noise enters once
     per column, the dark current of every ROI row adds up), against the same rows binned in
     software (each row read out, so read noise enters once per row);
  3. both again at each ADC speed in `--adc-speeds` (the PIXIS 1024F has 0.1 and 2 MHz; the
     slower one reads more quietly).

Noise comes from the difference of two frames taken one after the other, so fixed patterns
(bias structure, hot pixels) cancel; a robust spread (median absolute deviation) keeps cosmic
rays out of it. The dark frames must be dark: the PIXIS has no shutter, so block the light
(cap the camera or close the spectrograph entrance, lamps and laser off). The report says so
if rows or columns stand out the way light would.

Run on the lab PC with the microscope application CLOSED (the camera opens only once):
    python tools/pixis_dark_noise_check.py
    python tools/pixis_dark_noise_check.py --exposures 0.01 1 10 60 300 --adc-speeds 0.1 2
    python tools/pixis_dark_noise_check.py --roi-rows 791 812
The data ROI defaults to the one stored in microscope_config.json ('camera_roi'). The duration
is printed at the start (about 2 x the sum of the exposures per measurement). Nothing is changed
permanently: exposure, ROI and ADC speed are restored and the camera closed. The report goes to
data/camera_checks/pixis_dark_noise_<time>.txt (raw numbers in the matching .json). Send the .txt.
"""

import argparse
import datetime
import json
import os
import sys
import traceback

import numpy as np

REPOSITORY_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Same serial as RealHardware.CAMERA_SERIAL in pixisspec/pixis_hardware.py.
DEFAULT_CAMERA_SERIAL = '2712050005'
DEFAULT_REPORT_DIRECTORY = os.path.join(REPOSITORY_ROOT, 'data', 'camera_checks')
DEFAULT_CONFIG_PATH = os.path.join(REPOSITORY_ROOT, 'microscope_config.json')
DEFAULT_EXPOSURES_S = (0.01, 1.0, 10.0, 60.0, 300.0)
ACQUISITION_BUFFER_FRAMES = 100  # as RealHardware.ACQUISITION_BUFFER_FRAMES
FRAME_TIMEOUT_MARGIN_S = 60.0
LIGHT_SUSPECT_SIGMA = 5.0        # a row or column this many noise sigmas above the rest
HOT_PIXEL_SIGMA = 10.0


def open_pixis_camera(camera_serial):
    """Open the PIXIS through pylablib (imported here so the rest runs without it)."""
    from pylablib.devices import PrincetonInstruments
    print(f"Cameras found: {PrincetonInstruments.list_cameras()}")
    return PrincetonInstruments.PicamCamera(camera_serial)


# ----------------------------------------------------------------------
# Analysis (pure)
# ----------------------------------------------------------------------

def robust_standard_deviation(values):
    values = np.asarray(values, dtype=float).ravel()
    return 1.4826 * float(np.median(np.abs(values - np.median(values))))


def pair_noise_counts(first_frame, second_frame):
    """Noise of one frame (counts rms per pixel) from the difference of two, in which fixed
    patterns cancel."""
    difference = np.asarray(first_frame, dtype=float) - np.asarray(second_frame, dtype=float)
    return robust_standard_deviation(difference) / np.sqrt(2.0)


def fit_noise_model(exposures_s, dark_levels_counts, noise_counts):
    """
    Straight lines through the measurements: dark level = bias + rate x t, and
    noise^2 = read^2 + (dark level - bias) / K. Returns a dict; K (electrons per count) is None
    when the dark signal is too small to show its shot noise.
    """
    exposures_s = np.asarray(exposures_s, dtype=float)
    dark_levels_counts = np.asarray(dark_levels_counts, dtype=float)
    variances = np.asarray(noise_counts, dtype=float) ** 2
    dark_rate, bias = np.polyfit(exposures_s, dark_levels_counts, 1)
    dark_signal = dark_levels_counts - bias
    if np.ptp(dark_signal) > 0:
        variance_per_dark_count, read_variance = np.polyfit(dark_signal, variances, 1)
    else:
        variance_per_dark_count, read_variance = 0.0, float(np.mean(variances))
    read_variance = max(float(read_variance), float(np.min(variances)) * 0.5)
    electrons_per_count = (1.0 / variance_per_dark_count) if variance_per_dark_count > 0 else None
    # Variance the dark current adds per second, in counts^2.
    dark_variance_rate = max(float(variance_per_dark_count * dark_rate), 0.0)
    return {'bias_counts': float(bias), 'dark_rate_counts_per_s': float(dark_rate),
            'read_noise_counts': float(np.sqrt(read_variance)),
            'electrons_per_count_estimate': electrons_per_count,
            'dark_variance_rate_counts2_per_s': dark_variance_rate}


def frame_length_for_read_fraction(read_noise_counts, dark_variance_rate_counts2_per_s,
                                   read_fraction=0.1):
    """Exposure (s) at which read noise variance is `read_fraction` of the frame's dark variance;
    None if the dark current adds no measurable noise."""
    if dark_variance_rate_counts2_per_s <= 0:
        return None
    return read_noise_counts ** 2 / (read_fraction * dark_variance_rate_counts2_per_s)


def light_suspects(dark_frame_minus_bias, pixel_noise_counts):
    """Rows or columns that stand out as light would (a slit image, a spectrum); [] if none."""
    suspects = []
    for axis_name, axis in (('rows', 1), ('columns', 0)):
        profile = np.median(dark_frame_minus_bias, axis=axis)
        lines_averaged = dark_frame_minus_bias.shape[axis]
        threshold = LIGHT_SUSPECT_SIGMA * pixel_noise_counts / np.sqrt(max(lines_averaged, 1))
        bright = np.flatnonzero(profile - np.median(profile) > max(threshold, 1.0))
        if bright.size:
            suspects.append(f"{bright.size} {axis_name} brighter than the rest "
                            f"(e.g. {axis_name[:-1]} {int(bright[np.argmax(profile[bright])])}, "
                            f"+{float(np.max(profile[bright]) - np.median(profile)):.1f} counts)")
    return suspects


def hot_pixel_fraction(dark_frame_minus_bias, pixel_noise_counts):
    excess = dark_frame_minus_bias - np.median(dark_frame_minus_bias)
    return float(np.mean(excess > HOT_PIXEL_SIGMA * max(pixel_noise_counts, 1e-9)))


# ----------------------------------------------------------------------
# Measurement
# ----------------------------------------------------------------------

def acquire_frame_pair(camera, exposure_s):
    """Two frames one after the other, exposed after the call (as RealHardware.acquire_frames)."""
    camera.set_exposure(exposure_s)
    camera.start_acquisition(mode='sequence', nframes=ACQUISITION_BUFFER_FRAMES)
    try:
        camera.wait_for_frame(since='start', nframes=2,
                              timeout=2 * (exposure_s + FRAME_TIMEOUT_MARGIN_S))
        frames = camera.read_multiple_images(rng=(0, 2))
    finally:
        camera.stop_acquisition()
    return [np.asarray(frame, dtype=float) for frame in frames]


def read_sensor_temperature(camera):
    try:
        return float(camera.get_attribute_value('Sensor Temperature Reading'))
    except Exception:
        return None


def measure_dark_series(camera, exposures_s, label):
    """Frame pairs at each exposure on the ROI set now: level, noise and the frames' mean."""
    records, mean_frames = [], {}
    for exposure_s in exposures_s:
        print(f"  {label}: exposure {exposure_s:g} s ...")
        first_frame, second_frame = acquire_frame_pair(camera, exposure_s)
        mean_frames[exposure_s] = (first_frame + second_frame) / 2
        records.append({'exposure_s': float(camera.get_exposure()),
                        'sensor_temperature_c': read_sensor_temperature(camera),
                        'frame_shape': list(first_frame.shape),
                        'dark_level_counts': float(np.median(mean_frames[exposure_s])),
                        'noise_counts': pair_noise_counts(first_frame, second_frame)})
    return records, mean_frames


def summarise_series(records, model, read_fraction, unit):
    header = f"  {'exposure s':>10} {'sensor C':>8} {'level':>9} {'dark':>8} {'noise':>7}"
    lines = [f"{header}  ({unit})"]
    for record in records:
        temperature = record['sensor_temperature_c']
        lines.append(f"  {record['exposure_s']:>10.3f} "
                     f"{temperature if temperature is not None else float('nan'):>8.1f} "
                     f"{record['dark_level_counts']:>9.1f} "
                     f"{record['dark_level_counts'] - model['bias_counts']:>8.1f} "
                     f"{record['noise_counts']:>7.2f}")
    gain = model['electrons_per_count_estimate']
    gain_text = (f'{gain:.2f} electrons per count' if gain
                 else 'not measurable (too little dark signal)')
    frame_length = frame_length_for_read_fraction(model['read_noise_counts'],
                                                  model['dark_variance_rate_counts2_per_s'],
                                                  read_fraction)
    lines += [f"  read noise {model['read_noise_counts']:.2f} counts rms; dark "
              f"{model['dark_rate_counts_per_s'] * 60:.2f} counts per minute; bias "
              f"{model['bias_counts']:.1f} counts",
              f"  conversion gain estimate: {gain_text}"]
    if frame_length is None:
        lines.append("  the dark current adds no measurable noise over these exposures: read "
                     "noise dominates, so fewer, longer frames are quieter")
    else:
        lines.append(f"  read noise is {read_fraction:.0%} of the noise variance in a frame of "
                     f"{frame_length:.0f} s: a long point split into frames at least that long "
                     "gains little noise from the extra reads")
    return lines


def run_check(camera, exposures_s, adc_speeds_mhz, data_roi_rows, read_fraction,
              report_directory):
    """Every measurement on an open camera; restores exposure, ROI and ADC speed afterwards."""
    started = datetime.datetime.now().isoformat(timespec='seconds')
    original_exposure_s = camera.get_exposure()
    original_roi = camera.get_roi()
    original_adc_speed = _read_attribute(camera, 'ADC Speed')
    width, height = camera.get_detector_size()
    report = [f"PIXIS dark noise check, {started}",
              f"exposures {', '.join(f'{value:g}' for value in exposures_s)} s; ADC speeds "
              f"{', '.join(f'{value:g}' for value in adc_speeds_mhz)} MHz; data ROI rows "
              f"{'%d..%d' % data_roi_rows if data_roi_rows else 'none given'}; gain "
              f"{_read_attribute(camera, 'ADC Analog Gain')}", '']
    raw = {'started': started, 'exposures_s': list(exposures_s),
           'adc_speeds_mhz': list(adc_speeds_mhz), 'data_roi_rows': data_roi_rows,
           'read_fraction': read_fraction, 'measurements': {}}
    try:
        for adc_speed_mhz in adc_speeds_mhz:
            camera.set_attribute_value('ADC Speed', adc_speed_mhz)
            adc_label = f"ADC {_read_attribute(camera, 'ADC Speed')} MHz"
            report.append(f"=== {adc_label} ===")

            camera.set_roi(0, width, 0, height, 1, 1)
            records, mean_frames = measure_dark_series(camera, exposures_s,
                                                       f"{adc_label}, full sensor")
            model = fit_noise_model([r['exposure_s'] for r in records],
                                    [r['dark_level_counts'] for r in records],
                                    [r['noise_counts'] for r in records])
            longest = max(mean_frames)
            dark_minus_bias = mean_frames[longest] - mean_frames[min(mean_frames)]
            suspects = light_suspects(dark_minus_bias, records[-1]['noise_counts'])
            hot_fraction = hot_pixel_fraction(dark_minus_bias, records[-1]['noise_counts'])
            raw['measurements'][f'{adc_label}, full sensor'] = {
                'records': records, 'model': model, 'light_suspects': suspects,
                'hot_pixel_fraction': hot_fraction}
            report += ["1. Whole sensor, every row read out (per pixel)",
                       *summarise_series(records, model, read_fraction, 'counts per pixel'),
                       f"  hot pixels (> {HOT_PIXEL_SIGMA:.0f} sigma at {longest:g} s): "
                       f"{hot_fraction:.3%}",
                       "  light: " + ('; '.join(suspects) + ' -- IS THE LIGHT BLOCKED?'
                                      if suspects else 'none seen (the frames are dark)'), '']

            if data_roi_rows:
                first_row, last_row = data_roi_rows
                row_count = last_row - first_row + 1
                camera.set_roi(0, width, first_row, last_row + 1, 1, row_count)
                on_chip_records, _ = measure_dark_series(camera, exposures_s,
                                                         f"{adc_label}, ROI on-chip")
                on_chip_model = fit_noise_model([r['exposure_s'] for r in on_chip_records],
                                                [r['dark_level_counts'] for r in on_chip_records],
                                                [r['noise_counts'] for r in on_chip_records])
                software_read_noise = model['read_noise_counts'] * np.sqrt(row_count)
                raw['measurements'][f'{adc_label}, ROI on-chip'] = {
                    'records': on_chip_records, 'model': on_chip_model,
                    'roi_rows': [first_row, last_row]}
                report += [f"2. Data ROI, rows {first_row}..{last_row} ({row_count} rows) summed "
                           "on the chip (per spectrum point)",
                           *summarise_series(on_chip_records, on_chip_model, read_fraction,
                                             'counts per column'),
                           f"  the same rows binned in software (each read out): read noise "
                           f"{software_read_noise:.2f} counts per spectrum point (from section "
                           f"1), against {on_chip_model['read_noise_counts']:.2f} on the chip", '']
    except Exception:
        report += ['(check stopped early)', traceback.format_exc()]
    finally:
        try:
            camera.set_roi(*_roi_arguments(original_roi))
            camera.set_exposure(original_exposure_s)
            if original_adc_speed is not None:
                camera.set_attribute_value('ADC Speed', original_adc_speed)
        except Exception as error:
            report.append(f'(restoring settings failed: {error})')
    report_path = write_report(report_directory, report, raw)
    print('\n'.join(report))
    print(f"Report saved to {report_path}")
    return report_path


def _roi_arguments(roi):
    """pylablib get_roi() (hstart, hend, vstart, vend, hbin, vbin) as set_roi's arguments."""
    return tuple(int(value) for value in roi)


def _read_attribute(camera, name):
    try:
        return camera.get_attribute_value(name)
    except Exception:
        return None


def write_report(report_directory, report_lines, raw_results):
    os.makedirs(report_directory, exist_ok=True)
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    report_path = os.path.join(report_directory, f'pixis_dark_noise_{timestamp}.txt')
    with open(report_path, 'w') as report_file:
        report_file.write('\n'.join(report_lines) + '\n')
    with open(report_path.replace('.txt', '.json'), 'w') as raw_file:
        json.dump(raw_results, raw_file, indent=2, default=str)
    return report_path


def stored_roi_rows(config_path):
    """(first, last) rows, both included, of the ROI stored in the application's config; or None."""
    try:
        with open(config_path) as config_file:
            stored = json.load(config_file).get('camera_roi')
        return (int(stored['first_row']), int(stored['last_row']) - 1) if stored else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def main(argument_list=None, open_camera=open_pixis_camera):
    """Command line entry; `open_camera` is injectable so the script runs without hardware."""
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--serial', default=DEFAULT_CAMERA_SERIAL, help='PIXIS serial number')
    parser.add_argument('--exposures', type=float, nargs='+', default=list(DEFAULT_EXPOSURES_S),
                        help='exposures in seconds (default 0.01 1 10 60 300)')
    parser.add_argument('--adc-speeds', type=float, nargs='+', default=None,
                        help='ADC speeds in MHz to measure (default: the current one only; '
                             'the PIXIS 1024F has 0.1 and 2)')
    parser.add_argument('--roi-rows', type=int, nargs=2, default=None,
                        metavar=('FIRST', 'LAST'),
                        help='data ROI rows, both included (default: the ROI stored in '
                             'microscope_config.json; none: the on-chip section is skipped)')
    parser.add_argument('--read-fraction', type=float, default=0.1,
                        help='read noise share of the frame noise variance used for the '
                             'frame-length advice (default 0.1)')
    parser.add_argument('--config', default=DEFAULT_CONFIG_PATH)
    parser.add_argument('--report-directory', default=DEFAULT_REPORT_DIRECTORY)
    arguments = parser.parse_args(argument_list)

    data_roi_rows = tuple(arguments.roi_rows) if arguments.roi_rows \
        else stored_roi_rows(arguments.config)
    camera = open_camera(arguments.serial)
    try:
        current_adc_speed_mhz = float(_read_attribute(camera, 'ADC Speed') or 2.0)
        adc_speeds_mhz = arguments.adc_speeds or [current_adc_speed_mhz]
        measurements = len(adc_speeds_mhz) * (2 if data_roi_rows else 1)
        print(f"About {measurements * 2 * sum(arguments.exposures) / 60:.0f} minutes of exposure. "
              "Keep the light blocked throughout.")
        return run_check(camera, arguments.exposures, adc_speeds_mhz, data_roi_rows,
                         arguments.read_fraction, arguments.report_directory)
    finally:
        camera.close()


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
