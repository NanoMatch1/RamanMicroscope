"""
PIXIS frame freshness check: does a grab return a frame exposed AFTER it was requested?

Background (2026-11-05 camera audit): the application opens the PIXIS in pylablib's
"sequence" mode, so the CCD exposes and reads out back to back into a ring buffer all the
time. RealHardware.grab_frame() then calls wait_for_frame(since="lastread") and
read_newest_image(). After a pause (a TRIAX move, a motor step) unread frames have piled
up, so the wait returns at once and the newest frame in the buffer was exposed before or
during the move. Riley's line walks of 2026-11-04 show the result: lines at the previous
TRIAX position.

This script measures, on the real camera:
  1. the camera's timing and shutter settings as the application leaves them
     (ROI, ADC speed, readout time, frame period, shutter mode);
  2. STREAMING grab, exactly as the application does it now: after each pause, is the
     returned frame one that finished before the request, one that was already exposing
     at the request, or one that started after it?
  3. ON-DEMAND grab (the proposed "acquire"): start a sequence acquisition at the request,
     wait for the frames counted from its start, read them, stop it while it is still
     running. How much time does it add beyond the exposure, and when does the exposure
     start relative to the request?
  4. whether pylablib's own grab() works on this camera. It snaps, and in pylablib 1.4.5
     stop_acquisition() raises PicamError_AcquisitionNotInProgress once a snap has finished
     by itself (found on the lab PC 2026-11-05), which is why section 3 uses a sequence.

A frame's freshness is judged two ways. The frame counter needs no camera support: frame
k is the (k+1)th frame to complete, so a returned index below the count completed at the
request finished before it, and an index equal to that count was mid-exposure at the
request. Exposure-start time stamps (Picam metadata, if this camera supports them) give
the same answer in seconds.

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
DEFAULT_REPORT_DIRECTORY = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                        'data', 'camera_checks')
# The application never sets these, so they are reported as the camera opens.
TIMING_AND_SHUTTER_ATTRIBUTES = (
    'Exposure Time', 'ADC Speed', 'ADC Quality', 'ADC Analog Gain', 'Readout Time Calculation',
    'Readout Rate Calculation', 'Frames per Readout', 'Readout Count', 'Shutter Timing Mode',
    'Internal Shutter Type', 'Internal Shutter Status', 'Active Shutter', 'Clean Until Trigger',
    'Clean Before Exposure', 'Clean Cycle Count', 'Time Stamp Resolution',
    'Sensor Temperature Reading', 'Sensor Temperature Status',
)
STREAMING_BUFFER_FRAMES = 100   # pylablib's default, what RealHardware.open_stream gets
FRESHNESS_FINISHED_BEFORE_REQUEST = 'STALE: finished before the request'
FRESHNESS_EXPOSING_AT_REQUEST = 'STALE: already exposing at the request'
FRESHNESS_STARTED_AFTER_REQUEST = 'fresh: started after the request'


def open_pixis_camera(camera_serial):
    """Open the PIXIS through pylablib (imported here so the rest of the script runs without it)."""
    from pylablib.devices import PrincetonInstruments
    print(f"Cameras found: {PrincetonInstruments.list_cameras()}")
    return PrincetonInstruments.PicamCamera(camera_serial)


def classify_frame_freshness(frame_index, frames_completed_at_request):
    """Where a returned frame sits relative to the request, from the frame counter alone.

    Frames are numbered from 0 in completion order, so with N frames complete at the request,
    frames 0..N-1 had finished, frame N was being exposed or read out, and N+1 onwards started later.
    """
    if frame_index < frames_completed_at_request:
        return FRESHNESS_FINISHED_BEFORE_REQUEST
    if frame_index == frames_completed_at_request:
        return FRESHNESS_EXPOSING_AT_REQUEST
    return FRESHNESS_STARTED_AFTER_REQUEST


def read_attribute_or_note(camera, attribute_name):
    """An attribute's value, or a note saying why it could not be read."""
    try:
        return camera.get_attribute_value(attribute_name, error_on_missing=False, default='(not on this camera)')
    except Exception as error:   # some attributes raise when they do not apply to the current mode
        return f'(unreadable: {error})'


def enable_exposure_time_stamps(camera):
    """Switch on Picam frame metadata; returns the time stamp resolution in ticks per second, or None."""
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
    for label, getter in [('device', camera.get_device_info), ('detector size', camera.get_detector_size),
                          ('roi (x0, x1, y0, y1, xbin, ybin)', camera.get_roi),
                          ('frame timings (exposure s, frame period s)', camera.get_frame_timings)]:
        try:
            settings[label] = getter()
        except Exception as error:
            settings[label] = f'(unreadable: {error})'
    for attribute_name in TIMING_AND_SHUTTER_ATTRIBUTES:
        settings[attribute_name] = read_attribute_or_note(camera, attribute_name)
    return settings


def exposure_start_seconds_after_acquisition_start(frame_info, ticks_per_second):
    """Picam time stamps count from the start of the acquisition; None without metadata."""
    if ticks_per_second is None or frame_info is None or getattr(frame_info, 'timestamp_start', None) is None:
        return None
    return frame_info.timestamp_start / ticks_per_second


def measure_streaming_grabs(camera, pause_s, repeats, frame_timeout_s, ticks_per_second, clock=time.perf_counter):
    """Free-running acquisition grabbed the way RealHardware.grab_frame does it, after each pause."""
    camera.setup_acquisition(mode='sequence', nframes=STREAMING_BUFFER_FRAMES)
    camera.start_acquisition()
    acquisition_started_at = clock()   # Picam_StartAcquisition is the last call in start_acquisition
    records = []
    try:
        for repeat_index in range(repeats):
            time.sleep(pause_s)   # stands in for a TRIAX move: frames keep arriving meanwhile
            request_time = clock()
            frames_status = camera.get_frames_status()
            # As RealHardware.grab_frame: wait_for_frame(since="lastread") then read the newest frame.
            camera.wait_for_frame(since='lastread', timeout=frame_timeout_s)
            new_frames_range = camera.get_new_images_range()
            newest_frame_index = new_frames_range[1] - 1
            frames, frame_infos = camera.read_multiple_images(rng=(newest_frame_index, newest_frame_index + 1),
                                                              return_info=True)
            returned_time = clock()
            exposure_start = exposure_start_seconds_after_acquisition_start(frame_infos[0], ticks_per_second)
            records.append({
                'repeat': repeat_index,
                'frames_completed_at_request': int(frames_status.acquired),
                'unread_frames_at_request': int(frames_status.unread),
                'returned_frame_index': int(newest_frame_index),
                'freshness': classify_frame_freshness(newest_frame_index, frames_status.acquired),
                'seconds_from_request_to_return': returned_time - request_time,
                'exposure_start_relative_to_request_s': (None if exposure_start is None else
                                                         acquisition_started_at + exposure_start - request_time),
                'frame_mean_counts': float(np.mean(frames[0])),
            })
    finally:
        camera.stop_acquisition()
    return records


def grab_on_demand(camera, frame_count, frame_timeout_s):
    """Start a sequence acquisition now, read the first `frame_count` frames, stop it while it still runs.

    Every frame starts after the call. A snap would stop by itself, and pylablib 1.4.5 then
    raises from stop_acquisition() on Picam cameras; stopping a running sequence works.
    """
    camera.start_acquisition(mode='sequence', nframes=STREAMING_BUFFER_FRAMES)
    try:
        camera.wait_for_frame(since='start', nframes=frame_count, timeout=frame_timeout_s * frame_count)
        return camera.read_multiple_images(rng=(0, frame_count), return_info=True)
    finally:
        camera.stop_acquisition()


def check_pylablib_snap_grab(camera, frame_timeout_s):
    """Does pylablib's grab() (snap mode) complete on this camera? Returns a one-line verdict."""
    try:
        camera.grab(nframes=1, frame_timeout=frame_timeout_s)
        return "pylablib grab() works on this camera"
    except Exception as error:
        try:
            camera.stop_acquisition()
        except Exception:
            pass
        return f"pylablib grab() FAILS: {type(error).__name__}: {error}"


def measure_on_demand_grabs(camera, pause_s, repeats, frames_per_grab, exposure_s, frame_timeout_s,
                            ticks_per_second, clock=time.perf_counter):
    """grab_on_demand after each pause: time beyond the exposure, and when the exposures start."""
    records = []
    for repeat_index in range(repeats):
        time.sleep(pause_s)
        request_time = clock()
        frames, frame_infos = grab_on_demand(camera, frames_per_grab, frame_timeout_s)
        returned_time = clock()
        exposure_starts = [exposure_start_seconds_after_acquisition_start(frame_info, ticks_per_second)
                           for frame_info in frame_infos]
        seconds_from_request_to_return = returned_time - request_time
        records.append({
            'repeat': repeat_index,
            'frames_per_grab': frames_per_grab,
            'returned_frame_indices': [int(getattr(frame_info, 'frame_index', -1)) for frame_info in frame_infos],
            'seconds_from_request_to_return': seconds_from_request_to_return,
            'seconds_beyond_exposure': seconds_from_request_to_return - frames_per_grab * exposure_s,
            # Measured from the acquisition start, which is after the request, so never stale.
            'exposure_starts_after_acquisition_start_s': exposure_starts,
            'frame_mean_counts': [float(np.mean(frame)) for frame in frames],
        })
    return records


def summarise_streaming(records):
    """Counts of each freshness class, and the time stamps when there are any."""
    lines = []
    for freshness in (FRESHNESS_FINISHED_BEFORE_REQUEST, FRESHNESS_EXPOSING_AT_REQUEST,
                      FRESHNESS_STARTED_AFTER_REQUEST):
        count = sum(record['freshness'] == freshness for record in records)
        lines.append(f"  {freshness}: {count} of {len(records)}")
    exposure_starts = [record['exposure_start_relative_to_request_s'] for record in records
                       if record['exposure_start_relative_to_request_s'] is not None]
    if exposure_starts:
        lines.append(f"  exposure start relative to the request (negative = before): "
                     f"{', '.join(f'{value:+.3f}' for value in exposure_starts)} s")
    else:
        lines.append("  no exposure time stamps (camera has no metadata support); frame counter only")
    lines.append(f"  request to return: {np.mean([record['seconds_from_request_to_return'] for record in records]):.3f} s mean")
    return lines


def summarise_on_demand(records):
    """Time added beyond the exposure, and when the exposure started after the acquisition did."""
    seconds_beyond_exposure = [record['seconds_beyond_exposure'] for record in records]
    lines = [f"  frames per grab: {records[0]['frames_per_grab']}",
             f"  request to return: {np.mean([record['seconds_from_request_to_return'] for record in records]):.3f} s mean",
             f"  time beyond the exposure (start, cleaning, readout, stop): {np.mean(seconds_beyond_exposure):.3f} s mean, "
             f"{np.min(seconds_beyond_exposure):.3f}-{np.max(seconds_beyond_exposure):.3f} s range"]
    first_exposure_starts = [record['exposure_starts_after_acquisition_start_s'][0] for record in records
                             if record['exposure_starts_after_acquisition_start_s'][0] is not None]
    if first_exposure_starts:
        lines.append(f"  first exposure starts {np.mean(first_exposure_starts):.3f} s after the acquisition start "
                     "(always after the request)")
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
    """Run one measurement; on failure report the error and stop the camera, so later sections still run."""
    try:
        records = measurement()
    except Exception:
        raw_results[result_name] = traceback.format_exc()
        try:
            camera.stop_acquisition()
        except Exception:
            pass
        return ['  FAILED:'] + ['    ' + line for line in traceback.format_exc().splitlines()] + ['']
    raw_results[result_name] = records
    return summarise(records) + ['']


def run_check(camera, exposure_s, repeats, pause_s, frames_per_grab, report_directory):
    """All four sections on an open camera; restores the exposure and metadata setting afterwards.

    The report is written even if a section fails, with the error in its place."""
    original_exposure_s = camera.get_exposure()
    report_lines = [f"PIXIS frame freshness check, {datetime.datetime.now().isoformat(timespec='seconds')}",
                    f"exposure {exposure_s} s, {repeats} repeats per method"]
    raw_results = {'exposure_s': exposure_s, 'repeats': repeats, 'pause_s': pause_s}
    try:
        settings = describe_camera_settings(camera)   # before any change: what the application gets
        camera.set_exposure(exposure_s)
        ticks_per_second = enable_exposure_time_stamps(camera)
        exposure_s_set, frame_period_s = camera.get_frame_timings()
        frame_timeout_s = 2 * frame_period_s + 10.0
        pause_s = max(pause_s, 3 * frame_period_s)   # long enough for several frames to pile up
        raw_results['pause_s'] = pause_s
        raw_results['settings'] = settings
        report_lines += [f"{pause_s:.2f} s pause before each grab (stands in for a move)", '']
        report_lines += ['1. Camera settings as opened (the application does not change these)']
        report_lines += [f"  {name}: {value}" for name, value in settings.items()]
        report_lines += [f"  after setting the exposure: exposure {exposure_s_set:.3f} s, "
                         f"frame period {frame_period_s:.3f} s, so readout ~{frame_period_s - exposure_s_set:.3f} s",
                         f"  exposure time stamps: {'yes' if ticks_per_second else 'NOT available'}", '']

        print("Measuring streaming grabs (the application's current method)...")
        report_lines += ['2. STREAMING grab (current: free-running + wait_for_frame + read_newest_image)']
        report_lines += run_section(lambda: measure_streaming_grabs(camera, pause_s, repeats, frame_timeout_s,
                                                                    ticks_per_second),
                                    summarise_streaming, raw_results, 'streaming', camera)

        for grab_frame_count in sorted({1, frames_per_grab}):
            print(f"Measuring on-demand grabs of {grab_frame_count} frame(s) (proposed acquire)...")
            report_lines += [f'3. ON-DEMAND grab (proposed: start, wait, read, stop), {grab_frame_count} frame(s)']
            report_lines += run_section(lambda: measure_on_demand_grabs(camera, pause_s, repeats, grab_frame_count,
                                                                        exposure_s_set, frame_timeout_s,
                                                                        ticks_per_second),
                                        summarise_on_demand, raw_results, f'on_demand_{grab_frame_count}_frames',
                                        camera)

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
    """Command line entry; `open_camera` is injectable so the script can be exercised without hardware."""
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--serial', default=DEFAULT_CAMERA_SERIAL, help='PIXIS serial number')
    parser.add_argument('--exposure-s', type=float, default=0.5, help='exposure time in seconds (default 0.5)')
    parser.add_argument('--repeats', type=int, default=5, help='grabs per method (default 5)')
    parser.add_argument('--pause-s', type=float, default=3.0,
                        help='pause before each grab, standing in for a move (default 3, at least 3 frame periods)')
    parser.add_argument('--frames-per-grab', type=int, default=3,
                        help='also time on-demand grabs of this many frames, as used for averaging (default 3)')
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
