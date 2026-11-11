"""
Unit tests for the PIXIS camera layer: frame freshness, frame averaging, waiting for the
sensor temperature, the region of interest and its binning, frame timeouts that follow the
exposure, the gain, and the live viewer's ROI selection.

RealHardware's own code runs here against SimulatedPicamDevice (pixisspec/), a stand-in for
pylablib's PicamCamera whose CCD free-runs on a background thread. The scene it images is a
uniform frame whose level stands for the instrument state, so a frame's level shows which
state it was exposed in, and a frame exposed across a change comes out in between.

Run: python -m pytest test_pixis_camera.py -q
"""

import importlib.util
import json
import logging
import os
import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from acquisitioncontrol.acqcontrol import CameraScanner
from pixisspec.pixiscam import PIXISCamera
from pixisspec.pixis_hardware import RealHardware
from pixisspec.simulated_picam_device import SimulatedPicamDevice, SimulatedPicamLibError
from pixisspec.spectral_roi import (AUTOMATIC, MANUAL, SlitImageNotFound, SpectralRoi,
                                    find_slit_image)

EXPOSURE_S = 0.05
READOUT_S = 0.02
FRAME_PERIOD_S = EXPOSURE_S + READOUT_S
SCENE_LEVEL_BEFORE_MOVE = 1000
SCENE_LEVEL_AFTER_MOVE = 5000


class SceneWithLevel:
    """A uniform 100 x 1024 scene; `level` stands for where the instrument is."""

    def __init__(self, level):
        self.level = level

    def __call__(self):
        return np.full((100, 1024), self.level, dtype=float)


def frame_level(frame):
    return float(np.mean(frame))


def real_hardware_on_simulated_device(scene):
    """RealHardware, unchanged, with the simulated device in place of pylablib's PicamCamera."""
    camera_stub = SimpleNamespace(interface=None, logger=logging.getLogger('test_pixis_camera'),
                                  acqtime=EXPOSURE_S)
    hardware = RealHardware(camera_stub)
    hardware._cam = SimulatedPicamDevice(scene, exposure_s=EXPOSURE_S, readout_s=READOUT_S)
    return hardware


@pytest.fixture(params=['camera idle', 'live stream running'])
def scene_and_hardware(request):
    """RealHardware as the application leaves it: idle, or with run mode's stream left on."""
    scene = SceneWithLevel(SCENE_LEVEL_BEFORE_MOVE)
    hardware = real_hardware_on_simulated_device(scene)
    if request.param == 'live stream running':
        hardware.open_stream()
    yield scene, hardware
    hardware.close_camera()


# ----------------------------------------------------------------------
# The simulated device reproduces both grab methods
# ----------------------------------------------------------------------

def test_simulated_device_streaming_returns_a_frame_from_before_the_change():
    scene = SceneWithLevel(SCENE_LEVEL_BEFORE_MOVE)
    device = SimulatedPicamDevice(scene, exposure_s=EXPOSURE_S, readout_s=READOUT_S)
    device.start_acquisition()
    time.sleep(4 * FRAME_PERIOD_S)
    scene.level = SCENE_LEVEL_AFTER_MOVE
    device.wait_for_frame(since='lastread')
    stale_frame = device.read_newest_image()
    device.close()
    assert frame_level(stale_frame) < SCENE_LEVEL_AFTER_MOVE


def frames_from_a_sequence_started_now(device, frame_count):
    """Start a sequence, take its first frames, stop it while it runs (works on the real PIXIS)."""
    device.start_acquisition(mode='sequence', nframes=100)
    try:
        device.wait_for_frame(since='start', nframes=frame_count, timeout=5)
        return device.read_multiple_images(rng=(0, frame_count))
    finally:
        device.stop_acquisition()


def test_simulated_device_sequence_started_after_the_request_exposes_after_it():
    scene = SceneWithLevel(SCENE_LEVEL_BEFORE_MOVE)
    device = SimulatedPicamDevice(scene, exposure_s=EXPOSURE_S, readout_s=READOUT_S)
    scene.level = SCENE_LEVEL_AFTER_MOVE
    frames = frames_from_a_sequence_started_now(device, 3)
    assert [frame_level(frame) for frame in frames] == [SCENE_LEVEL_AFTER_MOVE] * 3
    assert not device.acquisition_in_progress()


def test_simulated_device_snap_grab_fails_as_on_the_real_camera():
    device = SimulatedPicamDevice(SceneWithLevel(SCENE_LEVEL_BEFORE_MOVE), exposure_s=EXPOSURE_S,
                                  readout_s=READOUT_S)
    with pytest.raises(SimulatedPicamLibError, match='AcquisitionNotInProgress'):
        device.grab(nframes=1)
    assert not device.acquisition_in_progress()


def test_simulated_device_frame_exposed_across_a_change_is_a_mix():
    scene = SceneWithLevel(SCENE_LEVEL_BEFORE_MOVE)
    device = SimulatedPicamDevice(scene, exposure_s=0.2, readout_s=READOUT_S)
    threading.Timer(0.1, setattr, (scene, 'level', SCENE_LEVEL_AFTER_MOVE)).start()
    mixed_frame = frames_from_a_sequence_started_now(device, 1)[0]
    assert SCENE_LEVEL_BEFORE_MOVE < frame_level(mixed_frame) < SCENE_LEVEL_AFTER_MOVE


def test_bench_freshness_check_runs_against_the_simulated_camera(tmp_path):
    """tools/pixis_frame_freshness_check.py end to end: streaming stale, on-demand fresh."""
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools',
                               'pixis_frame_freshness_check.py')
    module_spec = importlib.util.spec_from_file_location('pixis_frame_freshness_check', script_path)
    freshness_check = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(freshness_check)
    scene = SceneWithLevel(SCENE_LEVEL_BEFORE_MOVE)
    report_path = freshness_check.main(
        ['--exposure-s', str(EXPOSURE_S), '--repeats', '3', '--pause-s', '0.3',
         '--report-directory', str(tmp_path)],
        open_camera=lambda serial: SimulatedPicamDevice(scene, exposure_s=EXPOSURE_S,
                                                        readout_s=READOUT_S))
    with open(report_path.replace('.txt', '.json')) as raw_file:
        raw_results = json.load(raw_file)
    assert all(record['freshness'].startswith('STALE') for record in raw_results['streaming'])
    assert all(record['freshness_judged_by'] == 'exposure time stamps'
               and record['exposure_end_relative_to_request_s'] < 0
               for record in raw_results['streaming'])
    for frame_count in (1, 3):
        on_demand_records = raw_results[f'on_demand_{frame_count}_frames']
        assert all(record['returned_frame_indices'] == list(range(frame_count))
                   for record in on_demand_records)
        assert all(0 < record['seconds_beyond_exposure'] < 0.5 for record in on_demand_records)
    assert raw_results['pylablib_snap_grab'].startswith('pylablib grab() FAILS')


# ----------------------------------------------------------------------
# RealHardware.grab_frame: a frame requested after a move must be exposed after it
# ----------------------------------------------------------------------

def test_grab_after_a_move_returns_a_frame_exposed_after_the_move(scene_and_hardware):
    scene, hardware = scene_and_hardware
    hardware.grab_frame(timeout=5000)        # the previous point's frame
    time.sleep(4 * FRAME_PERIOD_S)           # the move: the CCD keeps exposing meanwhile
    scene.level = SCENE_LEVEL_AFTER_MOVE     # move complete
    frame = hardware.grab_frame(timeout=5000)
    assert frame_level(frame) == SCENE_LEVEL_AFTER_MOVE


def test_grab_straight_after_a_move_is_not_exposed_across_it(scene_and_hardware):
    scene, hardware = scene_and_hardware
    time.sleep(1.5 * FRAME_PERIOD_S)         # move completes part-way through an exposure
    scene.level = SCENE_LEVEL_AFTER_MOVE
    frame = hardware.grab_frame(timeout=5000)
    assert frame_level(frame) == SCENE_LEVEL_AFTER_MOVE


def test_consecutive_grabs_are_distinct_exposures(scene_and_hardware):
    scene, hardware = scene_and_hardware
    first_frame = hardware.grab_frame(timeout=5000)
    scene.level = SCENE_LEVEL_AFTER_MOVE
    second_frame = hardware.grab_frame(timeout=5000)
    assert frame_level(first_frame) == SCENE_LEVEL_BEFORE_MOVE
    assert frame_level(second_frame) == SCENE_LEVEL_AFTER_MOVE


def test_acquired_frames_all_start_after_the_request(scene_and_hardware):
    scene, hardware = scene_and_hardware
    time.sleep(2 * FRAME_PERIOD_S)
    scene.level = SCENE_LEVEL_AFTER_MOVE
    frames = hardware.acquire_frames(3, timeout=5000)
    assert [frame_level(frame) for frame in frames] == [SCENE_LEVEL_AFTER_MOVE] * 3


def test_acquiring_leaves_the_ccd_idle(scene_and_hardware):
    _, hardware = scene_and_hardware
    hardware.grab_frame(timeout=5000)
    assert not hardware._stream_open
    assert not hardware._cam.acquisition_in_progress()


# ----------------------------------------------------------------------
# Run mode: the free-running stream for live viewing
# ----------------------------------------------------------------------

def test_run_mode_returns_the_waiting_frame_at_once():
    """Live view favours speed: a frame already in the buffer comes back without waiting."""
    scene = SceneWithLevel(SCENE_LEVEL_BEFORE_MOVE)
    hardware = real_hardware_on_simulated_device(scene)
    hardware.open_stream()
    time.sleep(3 * FRAME_PERIOD_S)
    requested_at = time.perf_counter()
    frame = hardware.grab_streamed_frame(timeout=5000)
    seconds_to_return = time.perf_counter() - requested_at
    hardware.close_camera()
    assert frame is not None
    assert seconds_to_return < FRAME_PERIOD_S / 2


def test_streamed_grab_starts_the_stream_if_needed():
    hardware = real_hardware_on_simulated_device(SceneWithLevel(SCENE_LEVEL_BEFORE_MOVE))
    frame = hardware.grab_streamed_frame(timeout=5000)
    stream_was_open = hardware._stream_open
    hardware.close_camera()
    assert frame is not None and stream_was_open


@pytest.mark.parametrize('stream_running', [False, True])
def test_exposure_change_restarts_the_stream_only_if_it_was_running(stream_running):
    hardware = real_hardware_on_simulated_device(SceneWithLevel(SCENE_LEVEL_BEFORE_MOVE))
    if stream_running:
        hardware.open_stream()
    hardware.set_exposure_time(0.1)
    ccd_running_after = hardware._cam.acquisition_in_progress()
    exposure_after_s = hardware._cam.get_exposure()
    hardware.close_camera()
    assert ccd_running_after == stream_running
    assert exposure_after_s == pytest.approx(0.1)


# ----------------------------------------------------------------------
# Sensor cooling: set point committed, cooler flat out
# ----------------------------------------------------------------------

def real_hardware_opening_a_simulated_device(coldest_sensor_temperature_c):
    """RealHardware opening a simulated device whose cooler bottoms out at that temperature."""
    camera_stub = SimpleNamespace(interface=None, logger=logging.getLogger('test_pixis_camera'),
                                  acqtime=EXPOSURE_S)
    return RealHardware(camera_stub, open_device=lambda serial, logger: SimulatedPicamDevice(
        SceneWithLevel(SCENE_LEVEL_BEFORE_MOVE), exposure_s=EXPOSURE_S, readout_s=READOUT_S,
        coldest_sensor_temperature_c=coldest_sensor_temperature_c))


def test_start_up_runs_the_cooler_flat_out():
    hardware = real_hardware_opening_a_simulated_device(COLDEST_SENSOR_TEMPERATURE_C)
    hardware.initialise()
    set_point_c = hardware.get_target_temperature()
    sensor_temperature_c = hardware.get_temperature()
    status = hardware._cam.get_attribute_value('Sensor Temperature Status')
    hardware.close_camera()
    assert set_point_c == RealHardware.SENSOR_TEMPERATURE_SET_POINT_C
    assert sensor_temperature_c == COLDEST_SENSOR_TEMPERATURE_C
    assert status == 'Unlocked'


def test_set_point_reaches_the_camera_without_an_acquisition():
    """Picam holds written settings until committed; the set point must not wait for one."""
    hardware = real_hardware_opening_a_simulated_device(COLDEST_SENSOR_TEMPERATURE_C)
    hardware.open_camera()
    hardware.set_target_temperature(-20.0)
    sensor_temperature_c = hardware.get_temperature()
    hardware.close_camera()
    assert sensor_temperature_c == -20.0


def test_set_point_change_keeps_a_running_stream_running():
    hardware = real_hardware_opening_a_simulated_device(COLDEST_SENSOR_TEMPERATURE_C)
    hardware.open_camera()
    hardware.open_stream()
    hardware.set_target_temperature(-25.0)
    still_streaming = hardware._stream_open and hardware._cam.acquisition_in_progress()
    hardware.close_camera()
    assert still_streaming


# ----------------------------------------------------------------------
# Frame averaging: n frames, equal weight
# ----------------------------------------------------------------------

def camera_scanner_with_frames(frames):
    """CameraScanner whose camera hands out `frames` in order."""
    remaining_frames = list(frames)
    camera_stub = SimpleNamespace(stop_flag=threading.Event(),
                                  grab_frame_safe=lambda timeout=None: remaining_frames.pop(0))
    camera_stub.stop_flag.set()
    interface_stub = SimpleNamespace(microscope=SimpleNamespace(), camera=camera_stub,
                                     logger=logging.getLogger('test_pixis_camera'))
    acquisition_control_stub = SimpleNamespace(interface=interface_stub,
                                               general_parameters={'n_frames': len(frames)})
    return CameraScanner(acquisition_control_stub)


def test_averaged_frames_are_weighted_equally():
    frames = [np.full((100, 1024), level, dtype=np.uint16) for level in (0, 100, 200, 300)]
    averaged_frame = camera_scanner_with_frames(frames)._acquire_once()
    assert frame_level(averaged_frame) == pytest.approx(150.0)


# ----------------------------------------------------------------------
# Waiting for the sensor temperature must give up, not hang a scan
# ----------------------------------------------------------------------

COLDEST_SENSOR_TEMPERATURE_C = -43.0   # the lab PIXIS, cooler flat out (2026-11-06)


def camera_with_temperatures(sensor_temperatures_c):
    """Stub PIXISCamera: the sensor reads the given temperatures in turn (the last one repeats)."""
    remaining_temperatures = list(sensor_temperatures_c)
    frames_taken = []

    def read_sensor_temperature():
        if len(remaining_temperatures) > 1:
            return remaining_temperatures.pop(0)
        return remaining_temperatures[0]

    def grab_frame(timeout=None):
        frames_taken.append(np.zeros((100, 1024)))
        return frames_taken[-1]

    camera_stub = SimpleNamespace(
        hardware=SimpleNamespace(get_temperature=read_sensor_temperature),
        grab_frame=grab_frame, _publish_temperature=lambda sensor_temperature_c: None,
        logger=logging.getLogger('test_pixis_camera'))
    return camera_stub, frames_taken


@pytest.fixture
def fast_temperature_polling(monkeypatch):
    monkeypatch.setattr('pixisspec.pixiscam.TEMPERATURE_POLL_INTERVAL_S', 0.01)


def test_grab_frame_safe_takes_a_frame_with_the_cooler_flat_out(fast_temperature_polling):
    """Unlocked at its coldest, well below the -30 C limit: no waiting."""
    camera_stub, frames_taken = camera_with_temperatures([COLDEST_SENSOR_TEMPERATURE_C])
    frame = PIXISCamera.grab_frame_safe(camera_stub, timeout=1000)
    assert frame is not None and len(frames_taken) == 1


def test_grab_frame_safe_waits_for_the_sensor_to_cool(fast_temperature_polling):
    camera_stub, frames_taken = camera_with_temperatures([20.0, -10.0, -29.5, -31.0])
    frame = PIXISCamera.grab_frame_safe(camera_stub, timeout=1000, temperature_wait_timeout_s=5)
    assert frame is not None and len(frames_taken) == 1


def test_grab_frame_safe_gives_up_when_the_temperature_cannot_be_read(fast_temperature_polling):
    camera_stub, frames_taken = camera_with_temperatures([None])
    results = []
    grab_thread = threading.Thread(daemon=True, target=lambda: results.append(
        PIXISCamera.grab_frame_safe(camera_stub, timeout=1000, temperature_wait_timeout_s=0.5)))
    grab_thread.start()
    grab_thread.join(timeout=5)
    assert not grab_thread.is_alive(), "grab_frame_safe is still waiting for a readable temperature"
    assert results == [None] and frames_taken == []


# ----------------------------------------------------------------------
# Region of interest and binning (pixisspec/spectral_roi.py)
# ----------------------------------------------------------------------

def test_spectral_roi_rows_binning_and_round_trip():
    roi = SpectralRoi(790, 830)
    assert roi.camera_roi() == (0, 1024, 790, 830, 1, 1), "columns are never binned"
    on_chip = roi.with_rows_binned_on_chip('all')
    assert on_chip.binned_on_chip and on_chip.camera_roi()[-1] == 40
    moved = on_chip.with_rows(700, 720)
    assert moved.binned_on_chip and moved.rows_binned_on_chip == 20, "on-chip stays on-chip"
    assert SpectralRoi.from_dict(moved.as_dict()) == moved
    with pytest.raises(ValueError):
        SpectralRoi(800, 1100)
    with pytest.raises(ValueError):
        SpectralRoi(800, 810, rows_binned_on_chip=11)


def slit_image_frame(centre_row=800.0, tilt_rows_per_1000_columns=0.0, line_columns=(150, 480, 900),
                     half_height_rows=6.0, seed=1):
    """A full-sensor frame of three lamp lines on a tilted slit image, with read noise."""
    rows = np.arange(1024, dtype=float)[:, None]
    columns = np.arange(1024, dtype=float)[None, :]
    slit_rows = centre_row + tilt_rows_per_1000_columns / 1000 * (columns - 512)
    lines = sum(np.exp(-0.5 * ((columns - column) / 1.5) ** 2) for column in line_columns)
    frame = 400 + 20000 * lines * np.exp(-0.5 * ((rows - slit_rows) / half_height_rows) ** 2)
    return frame + np.random.default_rng(seed).normal(0, 10, frame.shape)


def test_slit_image_is_found_with_its_tilt_and_gives_an_automatic_roi():
    slit_image = find_slit_image(slit_image_frame(centre_row=800, tilt_rows_per_1000_columns=8))
    assert abs(slit_image.peak_row - 800) <= 1
    assert slit_image.tilt_rows_per_1000_columns == pytest.approx(8, abs=1.5)
    roi = slit_image.roi(margin_rows=3)
    assert roi.source == AUTOMATIC and roi.rows_binned_on_chip == 1
    assert roi.first_row <= 800 - 6 - 4 and roi.last_row >= 800 + 6 + 4, roi.describe()
    assert roi.row_count < 60, "the ROI follows the slit image, not the whole sensor"


def test_no_slit_image_on_a_dark_frame():
    dark = 400 + np.random.default_rng(2).normal(0, 10, (1024, 1024))
    with pytest.raises(SlitImageNotFound):
        find_slit_image(dark)


def test_roi_rows_are_read_out_and_binned_on_the_chip():
    """The simulated CCD reads only the ROI rows; on-chip binning sums them (clipped at the ADC
    full scale); a row count that is not a whole number of bins is trimmed, as pylablib does."""
    def two_row_values():
        image = np.full((1024, 1024), 100.0)
        image[800:810] = 1000.0
        return image
    hardware = real_hardware_on_simulated_device(two_row_values)
    try:
        assert hardware.set_roi_and_binning(0, 1024, 795, 815, 1, 1) == (0, 1024, 795, 815, 1, 1)
        frame = hardware.grab_frame()
        assert frame.shape == (20, 1024)
        assert hardware.set_roi_and_binning(0, 1024, 795, 815, 1, 20) == (0, 1024, 795, 815, 1, 20)
        frame = hardware.grab_frame()
        assert frame.shape == (1, 1024)
        assert frame[0, 0] == 10 * 100 + 10 * 1000, "charge of all ROI rows summed"
        assert hardware.set_roi_and_binning(0, 1024, 795, 815, 1, 3)[3] == 813, "trimmed to bins"
    finally:
        hardware.close_camera()


def test_frames_wait_at_least_the_exposure():
    """A caller's short timeout must not cut off a long exposure (2026-11 port issue)."""
    hardware = real_hardware_on_simulated_device(SceneWithLevel(SCENE_LEVEL_BEFORE_MOVE))
    try:
        assert hardware.set_exposure_time(120.0)
        expected_timeout_s = 120.0 + hardware.FRAME_TIMEOUT_MARGIN_S
        assert hardware.frame_timeout_s(10000) == pytest.approx(expected_timeout_s)
        assert hardware.set_exposure_time(EXPOSURE_S)
        assert hardware.grab_frame(timeout=1) is not None, "a 1 ms caller timeout still waits"
    finally:
        hardware.close_camera()


def test_an_exposure_the_camera_clips_is_reported():
    hardware = real_hardware_on_simulated_device(SceneWithLevel(SCENE_LEVEL_BEFORE_MOVE))
    hardware._cam.maximum_exposure_s = 100.0
    try:
        assert hardware.set_exposure_time(60.0) is True
        assert hardware.set_exposure_time(300.0) is False
    finally:
        hardware.close_camera()


def test_adc_gain_is_set_by_name():
    hardware = real_hardware_on_simulated_device(SceneWithLevel(SCENE_LEVEL_BEFORE_MOVE))
    try:
        assert hardware.set_adc_gain('Medium') is True
        assert hardware.readout_settings()['adc_analog_gain'] == 'Medium'
    finally:
        hardware.close_camera()


# ----------------------------------------------------------------------
# Live viewer: the selected rows become the camera ROI
# ----------------------------------------------------------------------

@pytest.fixture(scope='module')
def qt_application():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PyQt5.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def live_viewer_with_roi(spectral_roi, sent_commands):
    from acquisitioncontrol.pyqtGUI import LiveDataViewer
    camera = SimpleNamespace(spectral_roi=spectral_roi)
    interface = SimpleNamespace(logger=logging.getLogger('test_live_viewer'), camera=camera,
                                microscope=SimpleNamespace(wavelength_axis=np.arange(1024.0)))
    return LiveDataViewer(interface, send_command=sent_commands.append)


def test_live_viewer_selection_sets_the_camera_roi_in_sensor_rows(qt_application, tmp_path,
                                                                 monkeypatch):
    monkeypatch.chdir(tmp_path)
    sent_commands = []
    viewer = live_viewer_with_roi(SpectralRoi(780, 820, source=MANUAL), sent_commands)
    viewer.update_data(np.zeros((40, 1024)))
    viewer.region_changed.emit(5, 15)  # frame rows 5..14 selected
    viewer.btn_use_selection_as_roi.click()
    assert sent_commands == ['roi 785 794']
    viewer.combo_binning.activated[str].emit('On-chip binning')
    assert sent_commands[-1] == 'roi binning onchip'


def test_live_viewer_cannot_select_rows_of_an_on_chip_binned_frame(qt_application, tmp_path,
                                                                   monkeypatch):
    monkeypatch.chdir(tmp_path)
    sent_commands = []
    viewer = live_viewer_with_roi(SpectralRoi(780, 820).with_rows_binned_on_chip('all'),
                                  sent_commands)
    viewer.update_data(np.zeros((1, 1024)))
    assert not viewer.btn_use_selection_as_roi.isEnabled()
    viewer._on_use_selection_as_roi()
    assert sent_commands == []

