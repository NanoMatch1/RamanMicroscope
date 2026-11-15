# pixisspec/simulated_picam_device.py

"""
Simulated Princeton Instruments camera device: a stand-in for pylablib's PicamCamera.

RealHardware talks to pylablib's PicamCamera object. This class offers the same calls, so
RealHardware's own code can run without a camera. It is different from SimulatedHardware,
which replaces RealHardware altogether and so cannot show faults in it.

The CCD is clocked by a background thread, as the real camera is clocked by its own
electronics. Each frame exposes for the exposure time and is then read out. Frames go into
a ring buffer whether or not anyone reads them:

    "sequence" mode   free-running, frames back to back until stopped (pylablib's default)
    "snap" mode       the requested number of frames, then the CCD stops

What a frame records is the `scene` callable, sampled at the start and at the end of its
exposure and averaged. A scene that changes during an exposure (a TRIAX move, say) therefore
gives a frame that is a mix of before and after, as on the real CCD.

Frame waiting and reading follow pylablib's frame-counter rules (ICamera.wait_for_frame,
read_newest_image, read_multiple_images, grab). Those rules are what make the stale-frame
fault reproducible here; tools/pixis_frame_freshness_check.py measures the same thing on the
real camera.

One fault of the real pairing is reproduced on purpose: with pylablib 1.4.5 and the PIXIS,
stop_acquisition() after a snap has finished by itself can raise
PicamError_AcquisitionNotInProgress, so pylablib's grab() and snap() fail some of the time
(once in two bench runs on the lab PC, 2026-11-05/06). Here it fails every time, so code
that relies on a snap fails in tests rather than intermittently on the bench. Acquire on
demand with a sequence that is stopped while still running (RealHardware.acquire_frames).

`time_scale` shortens every wait (exposure, readout, start) for simulation and tests;
reported times and settings stay in real units.

Settings behave as in Picam: a written value is held until it is committed, which pylablib
does in setup_acquisition() and start_acquisition(). The sensor is cooled instantly to the
committed set point, but no colder than `coldest_sensor_temperature_c`; below that the
status reads "Unlocked", as on the lab PIXIS (about -43 C, 2026-11-06).

The scene is the whole sensor (1024 x 1024). Each frame is the ROI cut out of it, with rows
binned on the chip by summing charge before the read, then clipped at the ADC full scale,
as on the CCD. set_roi / get_roi follow pylablib's PicamCamera (the ROI starts as the full
sensor, as on the lab camera; rows are trimmed to a whole number of bins). An exposure above
`maximum_exposure_s` is clipped without a word, as pylablib does with a value outside the
camera's range. `read_noise_counts` (default 0) is added to every output pixel after the
binning, once per read, as on the CCD; the scene supplies the light and dark signal.
"""

import collections
import threading
import time

import numpy as np

FramesStatus = collections.namedtuple('FramesStatus', ['acquired', 'unread', 'skipped', 'size'])
FrameTimings = collections.namedtuple('FrameTimings', ['exposure', 'frame_period'])
FrameInfo = collections.namedtuple(
    'FrameInfo', ['frame_index', 'timestamp_start', 'timestamp_end', 'framestamp'])
TIME_STAMP_TICKS_PER_SECOND = 1e6


class SimulatedPicamLibError(RuntimeError):
    """Stands in for pylablib's PicamLibError; `code_name` is the PicamError name."""

    def __init__(self, function_name, code_name):
        super().__init__(f"function '{function_name}' raised error {code_name}")
        self.code_name = code_name


class SimulatedPicamDevice:
    """A free-running CCD with pylablib's PicamCamera interface, driven by a scene callable."""

    def __init__(self, scene, exposure_s=0.05, readout_s=0.02, acquisition_start_delay_s=0.005,
                 default_buffer_frames=100, time_scale=1.0, coldest_sensor_temperature_c=-45.0,
                 initial_set_point_c=-70.0, sensor_size=(1024, 1024), maximum_exposure_s=None,
                 read_noise_counts=0.0, random_seed=None):
        self.scene = scene
        self.exposure_s = float(exposure_s)
        self.readout_s = float(readout_s)
        self.acquisition_start_delay_s = acquisition_start_delay_s
        self.time_scale = float(time_scale)
        self.coldest_sensor_temperature_c = float(coldest_sensor_temperature_c)
        self.committed_set_point_c = float(initial_set_point_c)
        self.acquisition_mode = 'sequence'
        self.buffer_frames = default_buffer_frames
        self.sensor_width, self.sensor_height = sensor_size
        self.maximum_exposure_s = maximum_exposure_s
        self.read_noise_counts = float(read_noise_counts)
        self.random_generator = np.random.default_rng(random_seed)
        self.attributes = {'Sensor Temperature Set Point': float(initial_set_point_c),
                           'ADC Analog Gain': 'High', 'ADC Speed': 2.0,
                           'ROIs': [(0, self.sensor_width, 1, 0, self.sensor_height, 1)],
                           'Time Stamp Resolution': TIME_STAMP_TICKS_PER_SECOND}
        self.frame_buffer = {}
        self.frame_exposure_times = {}
        self.frames_acquired = 0
        self.last_read_frame = 0
        self.last_wait_frame = 0
        self.acquisition_started_at = None
        self.ccd_thread = None
        self.stop_event = threading.Event()
        self.frames_changed = threading.Condition()
        self.is_open = True

    # ------------------------------------------------------------------
    # Acquisition control
    # ------------------------------------------------------------------

    def setup_acquisition(self, mode='sequence', nframes=100):
        """Acquisition mode ('sequence' or 'snap') and ring buffer size, as PicamCamera."""
        if mode not in ('sequence', 'snap'):
            raise ValueError(f"unknown acquisition mode {mode!r}")
        self.stop_acquisition()
        self.acquisition_mode = mode
        self.buffer_frames = int(nframes)
        self._commit_settings()

    def _commit_settings(self):
        """Picam_CommitParameters: written settings reach the camera (here, the set point)."""
        self.committed_set_point_c = float(self.attributes['Sensor Temperature Set Point'])

    def clear_acquisition(self):
        self.stop_acquisition()

    def start_acquisition(self, mode=None, nframes=None):
        """Start the CCD; with `mode`/`nframes` given, set them up first (as pylablib does)."""
        self.stop_acquisition()
        if mode is not None or nframes is not None:
            self.setup_acquisition(mode or self.acquisition_mode, nframes or self.buffer_frames)
        self._commit_settings()   # pylablib commits on every start
        with self.frames_changed:
            self.frame_buffer.clear()
            self.frame_exposure_times.clear()
            self.frames_acquired = 0
            self.last_read_frame = 0
            self.last_wait_frame = 0
        self.stop_event.clear()
        time.sleep(self.acquisition_start_delay_s * self.time_scale)
        self.acquisition_started_at = time.perf_counter()
        self.ccd_thread = threading.Thread(target=self._run_ccd, name='SimulatedPicamCCD',
                                           daemon=True)
        self.ccd_thread.start()

    def stop_acquisition(self):
        """Stop the CCD; frames already in the buffer are dropped at the next start.

        Raises, as pylablib 1.4.5 does on the real PIXIS, if a snap had already finished by itself.
        """
        snap_finished_by_itself = (self.acquisition_in_progress()
                                   and self.acquisition_mode == 'snap'
                                   and self.frames_acquired >= self.buffer_frames)
        self.stop_event.set()
        if self.ccd_thread is not None and self.ccd_thread is not threading.current_thread():
            self.ccd_thread.join()
        self.ccd_thread = None
        self.acquisition_started_at = None
        if snap_finished_by_itself:
            raise SimulatedPicamLibError('Picam_WaitForAcquisitionUpdate',
                                         'PicamError_AcquisitionNotInProgress')

    def acquisition_in_progress(self):
        return self.acquisition_started_at is not None

    def _run_ccd(self):
        """Expose, read out, store; back to back until stopped or the snap count is reached."""
        frame_index = 0
        while not self.stop_event.is_set():
            if self.acquisition_mode == 'snap' and frame_index >= self.buffer_frames:
                return
            exposure_started_at = time.perf_counter()
            scene_at_exposure_start = np.asarray(self.scene(), dtype=float)
            if self.stop_event.wait(self.exposure_s * self.time_scale):
                return
            scene_at_exposure_end = np.asarray(self.scene(), dtype=float)
            exposure_ended_at = time.perf_counter()
            if self.stop_event.wait(self.readout_s * self.time_scale):
                return
            mean_scene = (scene_at_exposure_start + scene_at_exposure_end) / 2
            frame = np.clip(self._read_out_roi(mean_scene), 0, 65535).astype(np.uint16)
            with self.frames_changed:
                self.frame_buffer[frame_index % self.buffer_frames] = frame
                self.frame_exposure_times[frame_index % self.buffer_frames] = (
                    exposure_started_at - self.acquisition_started_at,
                    exposure_ended_at - self.acquisition_started_at)
                self.frames_acquired = frame_index + 1
                self.frames_changed.notify_all()
            frame_index += 1

    def _read_out_roi(self, sensor_image):
        """The ROI of a full-sensor image, rows and columns binned by summing (on-chip)."""
        hstart, hend, vstart, vend, hbin, vbin = self.get_roi()
        region = sensor_image[vstart:vend, hstart:hend]
        rows, columns = region.shape[0] // vbin, region.shape[1] // hbin
        region = region[:rows * vbin, :columns * hbin]
        binned = region.reshape(rows, vbin, columns, hbin).sum(axis=(1, 3))
        if self.read_noise_counts:
            binned = binned + self.random_generator.normal(0.0, self.read_noise_counts,
                                                           binned.shape)
        return binned

    # ------------------------------------------------------------------
    # Frame counter, waiting and reading (pylablib ICamera rules)
    # ------------------------------------------------------------------

    def get_frames_status(self):
        with self.frames_changed:
            oldest_in_buffer = max(0, self.frames_acquired - self.buffer_frames)
            skipped = max(0, oldest_in_buffer - self.last_read_frame)
            unread = self.frames_acquired - max(self.last_read_frame, oldest_in_buffer)
            return FramesStatus(self.frames_acquired, unread, skipped, self.buffer_frames)

    def wait_for_frame(self, since='lastread', nframes=1, timeout=20.0, error_on_stopped=False):
        """Wait until `nframes` frames have completed since the reference point (as pylablib)."""
        if not self.acquisition_in_progress():
            if error_on_stopped:
                raise RuntimeError("waiting for a frame while acquisition is stopped")
            return False
        deadline = None if timeout is None else time.perf_counter() + timeout
        with self.frames_changed:
            reference_frame = {'lastread': self.last_read_frame, 'lastwait': self.last_wait_frame,
                               'now': self.frames_acquired, 'start': 0}[since]
            while self.frames_acquired < reference_frame + nframes:
                remaining_s = None if deadline is None else deadline - time.perf_counter()
                if remaining_s is not None and remaining_s <= 0:
                    raise TimeoutError("simulated PIXIS: timed out waiting for a frame")
                self.frames_changed.wait(remaining_s)
            self.last_wait_frame = self.frames_acquired
        return True

    def get_new_images_range(self):
        """(first, last) unread frames still in the buffer, last exclusive; None if none."""
        with self.frames_changed:
            first = max(self.last_read_frame, self.frames_acquired - self.buffer_frames)
            return (first, self.frames_acquired) if self.frames_acquired > first else None

    def read_multiple_images(self, rng=None, peek=False, return_info=False, return_rng=False):
        """Frames in `rng` (default: all unread); marks them read unless `peek`."""
        with self.frames_changed:
            if rng is None:
                rng = self.get_new_images_range() or (self.frames_acquired, self.frames_acquired)
            first = max(rng[0], self.frames_acquired - self.buffer_frames)
            last = min(rng[1], self.frames_acquired)
            frame_indices = range(first, max(first, last))
            frames = [self.frame_buffer[index % self.buffer_frames].copy()
                      for index in frame_indices]
            infos = [FrameInfo(index, *self._time_stamp_ticks(index), index + 1)
                     for index in frame_indices]
            if not peek:
                self.last_read_frame = max(self.last_read_frame, last)
        result = (frames,)
        if return_info:
            result += (infos,)
        if return_rng:
            result += ((first, max(first, last)),)
        return result[0] if len(result) == 1 else result

    def _time_stamp_ticks(self, frame_index):
        """Exposure start and end of a buffered frame, in ticks from the acquisition start."""
        exposure_times = self.frame_exposure_times[frame_index % self.buffer_frames]
        return tuple(round(seconds * TIME_STAMP_TICKS_PER_SECOND) for seconds in exposure_times)

    def read_newest_image(self, peek=False, return_info=False):
        """The newest unread frame (older unread frames are skipped), or None."""
        new_frames_range = self.get_new_images_range()
        if new_frames_range is None:
            return None
        newest_frame_range = (new_frames_range[1] - 1, new_frames_range[1])
        if return_info:
            frames, infos = self.read_multiple_images(rng=newest_frame_range, peek=peek,
                                                      return_info=True)
            return frames[0], infos[0]
        return self.read_multiple_images(rng=newest_frame_range, peek=peek)[0]

    def grab(self, nframes=1, frame_timeout=5.0, missing_frame='skip', return_info=False,
             buff_size=None):
        """Snap `nframes`: start, wait for each, read, stop (pylablib ICamera.grab)."""
        self.start_acquisition(mode='snap', nframes=nframes)
        frames, infos = [], []
        try:
            while len(frames) < nframes:
                self.wait_for_frame(timeout=frame_timeout)
                new_frames, new_infos = self.read_multiple_images(return_info=True)
                frames += new_frames
                infos += new_infos
        finally:
            self.stop_acquisition()
        return (frames, infos) if return_info else frames

    def snap(self, timeout=5.0, return_info=False):
        result = self.grab(frame_timeout=timeout, return_info=return_info)
        return (result[0][0], result[1][0]) if return_info else result[0]

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def get_attribute_value(self, name, error_on_missing=True, default=None, enum_as_str=True):
        if name == 'Exposure Time':
            return self.exposure_s * 1e3   # Picam uses milliseconds
        if name == 'Readout Time Calculation':
            return self.readout_s * 1e3    # milliseconds, as Picam
        if name == 'Sensor Temperature Reading':
            return max(self.committed_set_point_c, self.coldest_sensor_temperature_c)
        if name == 'Sensor Temperature Status':
            return ('Locked' if self.committed_set_point_c >= self.coldest_sensor_temperature_c
                    else 'Unlocked')
        if name not in self.attributes and error_on_missing:
            raise KeyError(f"simulated PIXIS has no attribute {name!r}")
        return self.attributes.get(name, default)

    def set_attribute_value(self, name, value, truncate=True, error_on_missing=True):
        if name == 'Exposure Time':
            exposure_s = float(value) / 1e3
            if self.maximum_exposure_s is not None:
                exposure_s = min(exposure_s, self.maximum_exposure_s)
            self.exposure_s = exposure_s
        else:
            self.attributes[name] = value

    def get_exposure(self):
        return self.exposure_s

    def set_exposure(self, exposure_s):
        self.exposure_s = float(exposure_s)
        return self.exposure_s

    def get_frame_timings(self):
        return FrameTimings(self.exposure_s, self.exposure_s + self.readout_s)

    def enable_metadata(self, enable=True):
        """Exposure time stamps are always recorded here; kept for interface parity."""

    def is_metadata_enabled(self):
        return True

    def get_device_info(self):
        return ('Simulated', 'PIXIS: 1024F (simulated)', '0000000000', 'none')

    def get_detector_size(self):
        """(width, height), as pylablib."""
        return (self.sensor_width, self.sensor_height)

    def get_roi(self):
        x_start, width, x_binning, y_start, height, y_binning = self.attributes['ROIs'][0]
        return x_start, x_start + width, y_start, y_start + height, x_binning, y_binning

    def set_roi(self, hstart=0, hend=None, vstart=0, vend=None, hbin=1, vbin=1):
        """As pylablib: stops the acquisition, keeps the ROI on the sensor, trims each axis to a
        whole number of bins, and returns what was set."""
        self.stop_acquisition()
        hend = self.sensor_width if hend is None else hend
        vend = self.sensor_height if vend is None else vend
        hstart, hend = max(0, int(hstart)), min(self.sensor_width, int(hend))
        vstart, vend = max(0, int(vstart)), min(self.sensor_height, int(vend))
        hbin = max(1, min(int(hbin), hend - hstart))
        vbin = max(1, min(int(vbin), vend - vstart))
        hend = hstart + (hend - hstart) // hbin * hbin
        vend = vstart + (vend - vstart) // vbin * vbin
        self.attributes['ROIs'] = [(hstart, hend - hstart, hbin, vstart, vend - vstart, vbin)]
        return self.get_roi()

    def close(self):
        self.stop_acquisition()
        self.is_open = False
