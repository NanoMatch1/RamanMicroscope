"""
PIXIS frame freshness check: does a grab return a frame exposed AFTER it was requested?

Background (2026-11-05 camera audit): the application used to open the PIXIS in
pylablib's "sequence" mode, so the CCD exposed and read out back to back into a ring buffer
all the time, and RealHardware.grab_frame() called wait_for_frame(since="lastread") and
read_newest_image(). After a pause (a TRIAX move, a motor step) unread frames had piled up,
so the wait returned at once and the newest frame in the buffer was exposed before or
during the move. Riley's line walks of 2026-11-04 show the result: lines at the previous
TRIAX position. grab_frame now acquires on demand (section 3); that streaming grab
survives only as the live view (`run`), which is what section 2 measures.

This script measures, on the real camera:
  1. the camera's timing and shutter settings as the camera opens
     (ROI, ADC speed, readout time, frame period, shutter mode, temperature);
  2. STREAMING grab, as the live view (`run`) does it and grab_frame used to: after each
     pause, was the returned frame exposed before the request, across it, or after it?
  3. ON-DEMAND grab (acquire, RealHardware.acquire_frames): start a sequence acquisition at
     the request, wait for the frames counted from its start, read them, stop it while it
     is still running. How much time does it add beyond the exposure, and when does the
     exposure start relative to the request?
  4. whether pylablib's own grab() works on this camera. It snaps, and in pylablib 1.4.5
     stop_acquisition() can raise PicamError_AcquisitionNotInProgress once a snap has
     finished by itself (once in two runs on the lab PC, 2026-11-05/06), which is why
     section 3 uses a sequence.

A frame's freshness is judged from its exposure time stamps (Picam metadata; the PIXIS
1024F has them): exposed before the request, exposure spanning it, or exposed after it.
Without time stamps the frame counter is used instead, but pylablib only counts a frame
once it polls the camera, so its count lags by 1-2 frames and it calls stale frames fresh
(lab PC, 2026-11-06: the counter said 4 of 5 fresh, the time stamps 5 of 5 stale).

Run on the lab PC with the microscope application CLOSED (the camera opens only once):
    python tools/pixis_frame_freshness_check.py
    python tools/pixis_frame_freshness_check.py --exposure-s 1.0 --repeats 8
Nothing is changed permanently: the exposure is restored, metadata is switched off again
and the camera is closed; the application re-applies its own settings when it starts.
The report goes to data/camera_checks/pixis_frame_freshness_<time>.txt (raw records in
the matching .json). Send the .txt.
"""

import argparse
import datetime
import json
import os
import sys
import time
import traceback

import numpy as np

# Same serial as RealHardware.CAMERA_SERIAL in pixisspec/pixis_hardware.py.
DEFAULT_CAMERA_SERIAL = '2712050005'
DEFAULT_REPORT_DIRECTORY = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'camera_checks')
# The application sets none of these except exposure and set point; reported as the camera opens.
TIMING_AND_SHUTTER_ATTRIBUTES = (
    'Exposure Time', 'ADC Speed', 'ADC Quality', 'ADC Analog Gain', 'Readout Time Calculation',
    'Readout Rate Calculation', 'Frames per Readout', 'Readout Count', 'Shutter Timing Mode',
    'Internal Shutter Type', 'Internal Shutter Status', 'Active Shutter', 'Clean Until Trigger',
    'Clean Before Exposure', 'Clean Cycle Count', 'Time Stamp Resolution',
    'Sensor Temperature Reading', 'Sensor Temperature Set Point', 'Sensor Temperature Status',
)
STREAMING_BUFFER_FRAMES = 100   # as RealHardware.ACQUISITION_BUFFER_FRAMES
FRESHNESS_EXPOSED_BEFORE_REQUEST = 'STALE: exposed before the request'
FRESHNESS_EXPOSURE_SPANS_REQUEST = 'STALE: exposure spans the request'
FRESHNESS_EXPOSED_AFTER_REQUEST = 'fresh: exposed after the request'


def open_pixis_camera(camera_serial):
    """Open the PIXIS through pylablib (imported here so the rest runs without it)."""
    from pylablib.devices import PrincetonInstruments
    print(f"Cameras found: {PrincetonInstruments.list_cameras()}")
    return PrincetonInstruments.PicamCamera(camera_serial)


def classify_freshness_by_time_stamps(exposure_start_relative_s, exposure_end_relative_s):
    """Where a frame's exposure sits relative to the request (seconds after the request)."""
    if exposure_end_relative_s <= 0:
        return FRESHNESS_EXPOSED_BEFORE_REQUEST
    if exposure_start_relative_s < 0:
        return FRESHNESS_EXPOSURE_SPANS_REQUEST
    return FRESHNESS_EXPOSED_AFTER_REQUEST


def classify_freshness_by_frame_counter(frame_index, frames_completed_at_request):
    """The same from pylablib's frame counter alone, for cameras without time stamps.

    Frames are numbered from 0 in completion order, so with N frames counted complete at the
    request, frames 0..N-1 had finished and frame N was being exposed or read out. pylablib's
    count lags the camera by 1-2 frames, so this calls stale frames fresh.
    """
    if frame_index < frames_completed_at_request:
        return FRESHNESS_EXPOSED_BEFORE_REQUEST
    if frame_index == frames_completed_at_request:
        return FRESHNESS_EXPOSURE_SPANS_REQUEST
    return FRESHNESS_EXPOSED_AFTER_REQUEST


def read_attribute_or_note(camera, attribute_name):
    """An attribute's value, or a note saying why it could not be read."""
    try:
        return camera.get_attribute_value(attribute_name, error_on_missing=False,
                                          default='(not on this camera)')
    except Exception as error:   # some attributes raise when they do not apply to the mode
        return f'(unreadable: {error})'


def enable_exposure_time_stamps(camera):
    """Switch on Picam frame metadata; returns time stamp ticks per second, or None."""
    try:
        camera.enable_metadata(True)
        if not camera.is_metadata_enabled():
            return None
        return float(camera.get_attribute_value('Time Stamp Resolution'))
    except Exception:
        return None


def describe_camera_settings(camera):
    """Device, geometry and timing as the camera opened, with pylablib's frame timing estimate."""
    settings = {}
    for label, getter in [('device', camera.get_device_info),
                          ('detector size', camera.get_detector_size),
                          ('roi (x0, x1, y0, y1, xbin, ybin)', camera.get_roi),
                          ('frame timings (exposure s, frame period s)', camera.get_frame_timings)]:
        try:
            settings[label] = getter()
        except Exception as error:
            settings[label] = f'(unreadable: {error})'
    for attribute_name in TIMING_AND_SHUTTER_ATTRIBUTES:
        settings[attribute_name] = read_attribute_or_note(camera, attribute_name)
    return settings


def seconds_after_acquisition_start(frame_info, ticks_per_second, time_stamp_field):
    """A frame's 'timestamp_start' or 'timestamp_end' in seconds; None without metadata.

    Picam time stamps count from the start of the acquisition.
    """
    if (ticks_per_second is None or frame_info is None
            or getattr(frame_info, time_stamp_field, None) is None):
        return None
    return getattr(frame_info, time_stamp_field) / ticks_per_second


def measure_streaming_grabs(camera, pause_s, repeats, frame_timeout_s, ticks_per_second,
                            clock=time.perf_counter):
    """Free-running acquisition grabbed as the live view does it, after each pause."""
    camera.setup_acquisition(mode='sequence', nframes=STREAMING_BUFFER_FRAMES)
    camera.start_acquisition()
    acquisition_started_at = clock()   # Picam_StartAcquisition is start_acquisition's last call
    records = []
    try:
        for repeat_index in range(repeats):
            time.sleep(pause_s)   # stands in for a TRIAX move: frames keep arriving meanwhile
            request_time = clock()
            frames_status = camera.get_frames_status()
            # As RealHardware.grab_streamed_frame: wait_for_frame(since="lastread"), newest frame.
            camera.wait_for_frame(since='lastread', timeout=frame_timeout_s)
            newest_frame_index = camera.get_new_images_range()[1] - 1
            frames, frame_infos = camera.read_multiple_images(
                rng=(newest_frame_index, newest_frame_index + 1), return_info=True)
            returned_time = clock()
            freshness_by_frame_counter = classify_freshness_by_frame_counter(
                newest_frame_index, frames_status.acquired)
            record = {
                'repeat': repeat_index,
                'frames_completed_at_request': int(frames_status.acquired),
                'unread_frames_at_request': int(frames_status.unread),
                'returned_frame_index': int(newest_frame_index),
                'freshness_by_frame_counter': freshness_by_frame_counter,
                'freshness_judged_by': 'frame counter',
                'freshness': freshness_by_frame_counter,
                'seconds_from_request_to_return': returned_time - request_time,
                'exposure_start_relative_to_request_s': None,
                'exposure_end_relative_to_request_s': None,
                'frame_mean_counts': float(np.mean(frames[0])),
            }
            exposure_start = seconds_after_acquisition_start(frame_infos[0], ticks_per_second,
                                                             'timestamp_start')
            exposure_end = seconds_after_acquisition_start(frame_infos[0], ticks_per_second,
                                                           'timestamp_end')
            if exposure_start is not None and exposure_end is not None:
                start_relative_s = acquisition_started_at + exposure_start - request_time
                end_relative_s = acquisition_started_at + exposure_end - request_time
                record['exposure_start_relative_to_request_s'] = start_relative_s
                record['exposure_end_relative_to_request_s'] = end_relative_s
                record['freshness_judged_by'] = 'exposure time stamps'
                record['freshness'] = classify_freshness_by_time_stamps(start_relative_s,
                                                                        end_relative_s)
            records.append(record)
    finally:
        camera.stop_acquisition()
    return records


def grab_on_demand(camera, frame_count, frame_timeout_s):
    """Start a sequence now, read its first `frame_count` frames, stop it while it still runs.

    Every frame starts after the call. This is RealHardware.acquire_frames. A snap would stop
    by itself, and pylablib 1.4.5 can then raise from stop_acquisition() on Picam cameras.
    """
    camera.start_acquisition(mode='sequence', nframes=STREAMING_BUFFER_FRAMES)
    try:
        camera.wait_for_frame(since='start', nframes=frame_count,
                              timeout=frame_timeout_s * frame_count)
        return camera.read_multiple_images(rng=(0, frame_count), return_info=True)
    finally:
        camera.stop_acquisition()


def check_pylablib_snap_grab(camera, frame_timeout_s):
    """Does pylablib's grab() (snap mode) complete on this camera? Returns a one-line verdict."""
    try:
        camera.grab(nframes=1, frame_timeout=frame_timeout_s)
        return "pylablib grab() works on this camera (this time; it has failed intermittently)"
    except Exception as error:
        try:
            camera.stop_acquisition()
        except Exception:
            pass
        return f"pylablib grab() FAILS: {type(error).__name__}: {error}"


def measure_on_demand_grabs(camera, pause_s, repeats, frames_per_grab, exposure_s,
                            frame_timeout_s, ticks_per_second, clock=time.perf_counter):
    """grab_on_demand after each pause: time beyond the exposure, and when exposures start."""
    records = []
    for repeat_index in range(repeats):
        time.sleep(pause_s)
        request_time = clock()
        frames, frame_infos = grab_on_demand(camera, frames_per_grab, frame_timeout_s)
        returned_time = clock()
        seconds_from_request_to_return = returned_time - request_time
        records.append({
            'repeat': repeat_index,
            'frames_per_grab': frames_per_grab,
            'returned_frame_indices': [int(getattr(frame_info, 'frame_index', -1))
                                       for frame_info in frame_infos],
            'seconds_from_request_to_return': seconds_from_request_to_return,
            'seconds_beyond_exposure': (seconds_from_request_to_return
                                        - frames_per_grab * exposure_s),
            # From the acquisition start, which is after the request, so never stale.
            'exposure_starts_after_acquisition_start_s': [
                seconds_after_acquisition_start(frame_info, ticks_per_second, 'timestamp_start')
                for frame_info in frame_infos],
            'frame_mean_counts': [float(np.mean(frame)) for frame in frames],
        })
    return records


def mean_seconds_from_request_to_return(records):
    return np.mean([record['seconds_from_request_to_return'] for record in records])


def summarise_streaming(records):
    """Counts of each freshness class, and the time stamps when there are any."""
    lines = [f"  judged by: {records[0]['freshness_judged_by']}"]
    for freshness in (FRESHNESS_EXPOSED_BEFORE_REQUEST, FRESHNESS_EXPOSURE_SPANS_REQUEST,
                      FRESHNESS_EXPOSED_AFTER_REQUEST):
        count = sum(record['freshness'] == freshness for record in records)
        lines.append(f"  {freshness}: {count} of {len(records)}")
    exposure_starts = [record['exposure_start_relative_to_request_s'] for record in records
                       if record['exposure_start_relative_to_request_s'] is not None]
    if exposure_starts:
        lines.append(f"  exposure start relative to the request (negative = before): "
                     f"{', '.join(f'{value:+.3f}' for value in exposure_starts)} s")
    else:
        lines.append("  no exposure time stamps (camera has no metadata support); frame "
                     "counter only, which lags the camera and undercounts stale frames")
    lines.append(f"  request to return: {mean_seconds_from_request_to_return(records):.3f} s mean")
    return lines


def summarise_on_demand(records):
    """Time added beyond the exposure, and when the exposure started after the acquisition."""
    seconds_beyond_exposure = [record['seconds_beyond_exposure'] for record in records]
    lines = [f"  frames per grab: {records[0]['frames_per_grab']}",
             f"  request to return: {mean_seconds_from_request_to_return(records):.3f} s mean",
             f"  time beyond the exposure (start, cleaning, readout, stop): "
             f"{np.mean(seconds_beyond_exposure):.3f} s mean, "
             f"{np.min(seconds_beyond_exposure):.3f}-{np.max(seconds_beyond_exposure):.3f} s range"]
    first_exposure_starts = [record['exposure_starts_after_acquisition_start_s'][0]
                             for record in records
                             if record['exposure_starts_after_acquisition_start_s'][0] is not None]
    if first_exposure_starts:
        lines.append(f"  first exposure starts {np.mean(first_exposure_starts):.3f} s after the "
                     "acquisition start (always after the request)")
    return lines


def write_report(report_directory, report_lines, raw_results):
    """Save the text report and the raw records side by side; returns the text report path."""
    os.makedirs(report_directory, exist_ok=True)
    timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    report_path = os.path.join(report_directory, f'pixis_frame_freshness_{timestamp}.txt')
    with open(report_path, 'w') as report_file:
        report_file.write('\n'.join(report_lines) + '\n')
    with open(report_path.replace('.txt', '.json'), 'w') as raw_file:
        json.dump(raw_results, raw_file, indent=2, default=str)
    return report_path


def run_section(measurement, summarise, raw_results, result_name, camera):
    """Run one measurement; on failure report the error and stop the camera, then carry on."""
    try:
        records = measurement()
    except Exception:
        raw_results[result_name] = traceback.format_exc()
        try:
            camera.stop_acquisition()
        except Exception:
            pass
        traceback_lines = ['    ' + line for line in traceback.format_exc().splitlines()]
        return ['  FAILED:'] + traceback_lines + ['']
    raw_results[result_name] = records
    return summarise(records) + ['']


def run_check(camera, exposure_s, repeats, pause_s, frames_per_grab, report_directory):
    """All four sections on an open camera; restores exposure and metadata afterwards.

    The report is written even if a section fails, with the error in its place."""
    original_exposure_s = camera.get_exposure()
    started = datetime.datetime.now().isoformat(timespec='seconds')
    report_lines = [f"PIXIS frame freshness check, {started}",
                    f"exposure {exposure_s} s, {repeats} repeats per method"]
    raw_results = {'exposure_s': exposure_s, 'repeats': repeats, 'pause_s': pause_s}
    try:
        settings = describe_camera_settings(camera)   # before any change
        camera.set_exposure(exposure_s)
        ticks_per_second = enable_exposure_time_stamps(camera)
        exposure_s_set, frame_period_s = camera.get_frame_timings()
        frame_timeout_s = 2 * frame_period_s + 10.0
        pause_s = max(pause_s, 3 * frame_period_s)   # long enough for frames to pile up
        raw_results['pause_s'] = pause_s
        raw_results['settings'] = settings
        report_lines += [f"{pause_s:.2f} s pause before each grab (stands in for a move)", '']
        report_lines += ['1. Camera settings as opened '
                         '(the application sets only exposure and set point)']
        report_lines += [f"  {name}: {value}" for name, value in settings.items()]
        report_lines += [f"  after setting the exposure: exposure {exposure_s_set:.3f} s, "
                         f"frame period {frame_period_s:.3f} s, "
                         f"so readout ~{frame_period_s - exposure_s_set:.3f} s",
                         f"  exposure time stamps: "
                         f"{'yes' if ticks_per_second else 'NOT available'}", '']

        print("Measuring streaming grabs (run mode, and the old grab_frame)...")
        report_lines += ['2. STREAMING grab (run mode and the old grab_frame: '
                         'free-running + wait_for_frame + read_newest_image)']
        report_lines += run_section(
            lambda: measure_streaming_grabs(camera, pause_s, repeats, frame_timeout_s,
                                            ticks_per_second),
            summarise_streaming, raw_results, 'streaming', camera)

        for grab_frame_count in sorted({1, frames_per_grab}):
            print(f"Measuring on-demand grabs of {grab_frame_count} frame(s) (acquire)...")
            report_lines += [f'3. ON-DEMAND grab (acquire: start, wait, read, stop), '
                             f'{grab_frame_count} frame(s)']
            report_lines += run_section(
                lambda: measure_on_demand_grabs(camera, pause_s, repeats, grab_frame_count,
                                                exposure_s_set, frame_timeout_s,
                                                ticks_per_second),
                summarise_on_demand, raw_results, f'on_demand_{grab_frame_count}_frames', camera)

        print("Checking pylablib's own grab() (snap mode)...")
        snap_verdict = check_pylablib_snap_grab(camera, frame_timeout_s)
        raw_results['pylablib_snap_grab'] = snap_verdict
        report_lines += ["4. pylablib grab() in snap mode", f"  {snap_verdict}", '']
    except Exception:
        report_lines += ['(check stopped early)', traceback.format_exc()]
    finally:
        try:
            camera.stop_acquisition()
            camera.enable_metadata(False)
            camera.set_exposure(original_exposure_s)
        except Exception as error:
            report_lines.append(f'(restoring settings failed: {error})')
    report_path = write_report(report_directory, report_lines, raw_results)
    print('\n'.join(report_lines))
    print(f"Report saved to {report_path}")
    return report_path


def main(argument_list=None, open_camera=open_pixis_camera):
    """Command line entry; `open_camera` is injectable so the script runs without hardware."""
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--serial', default=DEFAULT_CAMERA_SERIAL, help='PIXIS serial number')
    parser.add_argument('--exposure-s', type=float, default=0.5,
                        help='exposure time in seconds (default 0.5)')
    parser.add_argument('--repeats', type=int, default=5, help='grabs per method (default 5)')
    parser.add_argument('--pause-s', type=float, default=3.0,
                        help='pause before each grab, standing in for a move '
                             '(default 3, at least 3 frame periods)')
    parser.add_argument('--frames-per-grab', type=int, default=3,
                        help='also time on-demand grabs of this many frames, as used for '
                             'averaging (default 3)')
    parser.add_argument('--report-directory', default=DEFAULT_REPORT_DIRECTORY)
    arguments = parser.parse_args(argument_list)

    camera = open_camera(arguments.serial)
    try:
        return run_check(camera, arguments.exposure_s, arguments.repeats, arguments.pause_s,
                         arguments.frames_per_grab, arguments.report_directory)
    finally:
        camera.close()


if __name__ == '__main__':
    sys.exit(0 if main() else 1)
