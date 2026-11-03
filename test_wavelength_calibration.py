"""
Unit tests for the wavelength_calibration package (TRIAX + PIXIS wavelength axis).

The central test starts the software from a deliberately wrong calibration,
lets the line walk run against a simulated lamp that holds a separate "true"
calibration, and checks the fit recovers the truth. That is the test the old
pixel calibration could never have passed: its inputs were derived from its
own output.

    python -m pytest test_wavelength_calibration.py -q
"""

import numpy as np
import pytest

from wavelength_calibration.line_peaks import (collapse_image_to_spectrum, find_line_peaks,
                                               fit_line_peak)
from wavelength_calibration.line_walk import (LineWalk, estimate_pattern_shift, load_line_walk_observations,
                                              save_line_walk)
from wavelength_calibration.reference_lines import externally_measured_line, mercury_lines_in_window
from wavelength_calibration.simulated_line_lamp import SimulatedLineLamp, default_true_model
from wavelength_calibration.wavelength_axis_model import (CalibrationFitError, LineObservation,
                                                          WavelengthAxisModel, fit_wavelength_axis,
                                                          largest_axis_difference_nm)

SHIPPED_TRIAX_COEFFICIENTS = [0.009096028148595274, -170.88512284432366]


def shipped_model():
    """The calibration as migrated from the Tucsen era (slope OK, offset unverified)."""
    return WavelengthAxisModel(reference_pixel=50.0, triax_to_wavelength_coefficients=SHIPPED_TRIAX_COEFFICIENTS,
                               nm_per_pixel=0.07755452095074758)


class FakeTriax:
    """Absolute-position TRIAX stand-in that records every move."""

    def __init__(self, start_steps=100_000):
        self.position_steps = start_steps
        self.move_history = []

    def move_to(self, target_steps):
        self.move_history.append(int(target_steps))
        self.position_steps = int(target_steps)

    def read(self):
        return self.position_steps


# ----------------------------------------------------------------------------
# Reference lines
# ----------------------------------------------------------------------------

def test_second_order_mercury_lines_appear_at_twice_their_wavelength():
    lines = mercury_lines_in_window(800, 820, diffraction_orders=(2,))
    assert [round(line.apparent_wavelength_nm, 3) for line in lines] == [809.312, 815.566]


def test_first_order_only_window_has_no_nir_mercury_lines():
    assert mercury_lines_in_window(700, 900, diffraction_orders=(1,)) == []


# ----------------------------------------------------------------------------
# Peak finding and fitting (pixel units)
# ----------------------------------------------------------------------------

def test_fit_line_peak_recovers_subpixel_centre():
    pixels = np.arange(1024, dtype=float)
    spectrum = 400 + 5000 * np.exp(-0.5 * ((pixels - 412.37) / 1.6) ** 2)
    spectrum += np.random.default_rng(1).normal(0, 15, 1024)
    peak_fit = fit_line_peak(spectrum, approximate_pixel=410)
    assert peak_fit is not None
    assert abs(peak_fit.centre_pixel - 412.37) < 3 * peak_fit.centre_uncertainty_pixels + 0.01
    assert peak_fit.centre_uncertainty_pixels < 0.05
    assert peak_fit.signal_to_noise > 100


def test_fit_line_peak_refuses_window_clipped_by_chip_edge():
    spectrum = np.zeros(1024)
    spectrum[3] = 100
    assert fit_line_peak(spectrum, approximate_pixel=3) is None


def test_find_line_peaks_ignores_noise_only_spectrum():
    noise_only = 400 + np.random.default_rng(2).normal(0, 15, 1024)
    assert find_line_peaks(noise_only, minimum_signal_to_noise=10) == []


def test_collapse_image_follows_the_slit_image_rows():
    lamp = SimulatedLineLamp(default_true_model(), mercury_lines_in_window(800, 820, (2,)))
    triax_steps = 108_000
    image = lamp.image(triax_steps, slit_image_centre_row=70)
    spectrum = collapse_image_to_spectrum(image)
    assert spectrum.shape == (1024,)
    expected_pixel = default_true_model().pixel_of_wavelength(809.312, triax_steps)
    assert any(abs(pixel - expected_pixel) <= 1 for pixel in find_line_peaks(spectrum))


# ----------------------------------------------------------------------------
# Model algebra
# ----------------------------------------------------------------------------

def test_model_inverse_round_trips_exactly():
    model = default_true_model()
    for wavelength_nm in (750.0, 809.312, 871.666):
        for pixel in (50, 512, 1000):
            steps = model.triax_steps_for_wavelength(wavelength_nm, at_pixel=pixel)
            assert model.wavelength_at(pixel, steps) == pytest.approx(wavelength_nm, abs=1e-9)
            assert model.pixel_of_wavelength(wavelength_nm, steps) == pytest.approx(pixel, abs=1e-6)


def test_wavelength_axis_has_unit_pixel_spacing():
    """Regression guard: the old axis used np.linspace with endpoint=True, stretching it by 1/1023."""
    model = shipped_model()
    axis = model.wavelength_axis(triax_steps=106_000, number_of_pixels=1024)
    assert np.allclose(np.diff(axis), model.nm_per_pixel)
    assert axis[50] == pytest.approx(model.triax_wavelength(106_000))


def test_model_dictionary_round_trip():
    model = default_true_model()
    restored = WavelengthAxisModel.from_dict(model.to_dict())
    assert largest_axis_difference_nm(model, restored, [100_000, 110_000]) == 0.0


# ----------------------------------------------------------------------------
# Fit
# ----------------------------------------------------------------------------

def synthetic_observations(true_model, wavelengths_nm, pixels, pixel_noise=0.0, seed=0):
    random_generator = np.random.default_rng(seed)
    observations = []
    for wavelength_nm in wavelengths_nm:
        for pixel in pixels:
            steps = int(round(true_model.triax_steps_for_wavelength(wavelength_nm, at_pixel=pixel)))
            centre = true_model.pixel_of_wavelength(wavelength_nm, steps) + random_generator.normal(0, pixel_noise)
            observations.append(LineObservation(f'{wavelength_nm}', wavelength_nm, 0.002, steps, centre,
                                                max(pixel_noise, 0.01)))
    return observations


def test_fit_recovers_true_model_from_two_lines():
    true_model = WavelengthAxisModel(50.0, [0.0091, -172.0], nm_per_pixel=0.0772)
    observations = synthetic_observations(true_model, [809.312, 815.566], range(100, 1000, 150), pixel_noise=0.05)
    fit = fit_wavelength_axis(observations, reference_pixel=50.0)
    assert fit.model.nm_per_pixel == pytest.approx(0.0772, rel=1e-3)
    assert largest_axis_difference_nm(fit.model, true_model, [104_000, 108_000]) < 0.02
    assert fit.residual_rms_nm < 0.01


def test_fit_refuses_a_single_wavelength_and_explains_why():
    true_model = default_true_model()
    observations = synthetic_observations(true_model, [809.312], range(100, 1000, 150))
    with pytest.raises(CalibrationFitError, match='two different known wavelengths'):
        fit_wavelength_axis(observations)


def test_fit_refuses_a_single_triax_position():
    observations = [LineObservation('a', 809.312, 0.002, 107_000, 300.0, 0.05),
                    LineObservation('b', 815.566, 0.002, 107_000, 381.0, 0.05),
                    LineObservation('c', 815.566, 0.002, 107_000, 381.1, 0.05)]
    with pytest.raises(CalibrationFitError, match='two TRIAX positions'):
        fit_wavelength_axis(observations)


def test_fit_with_curvature_recovers_curvature():
    true_model = default_true_model()
    observations = synthetic_observations(true_model, [730.03, 809.312, 815.566, 871.666],
                                          range(60, 1000, 60), pixel_noise=0.02)
    fit = fit_wavelength_axis(observations, fit_dispersion_curvature=True)
    assert fit.model.nm_per_pixel_squared == pytest.approx(true_model.nm_per_pixel_squared, rel=0.1)
    assert largest_axis_difference_nm(fit.model, true_model, [95_000, 115_000]) < 0.01


def test_external_spectrometer_points_are_down_weighted():
    """
    Tiger + spare spectrometer: a large reference uncertainty must give a reduced chi^2 near 1, not >>1.

    All points of one Tiger wavelength share that wavelength's measurement error, so there are only a
    few effective degrees of freedom and chi^2 varies a lot between draws: test the median of several.
    The truth is linear on purpose; a curved truth fitted with a linear model adds a systematic residual.
    """
    true_model = WavelengthAxisModel(50.0, [0.0091, -172.0], nm_per_pixel=0.0772)
    reduced_chi_squared_values = []
    for seed in range(8):
        random_generator = np.random.default_rng(seed)
        observations = []
        for tiger_true_nm in (780.0, 800.0, 820.0, 840.0):
            line = externally_measured_line(tiger_true_nm + random_generator.normal(0, 0.2), uncertainty_nm=0.2)
            for pixel in (100, 400, 700, 950):
                steps = int(round(true_model.triax_steps_for_wavelength(tiger_true_nm, at_pixel=pixel)))
                observations.append(LineObservation('tiger', line.apparent_wavelength_nm, 0.2, steps,
                                                    true_model.pixel_of_wavelength(tiger_true_nm, steps), 0.02))
        reduced_chi_squared_values.append(fit_wavelength_axis(observations).reduced_chi_squared)
    assert np.median(reduced_chi_squared_values) < 1.5


# ----------------------------------------------------------------------------
# Line walk
# ----------------------------------------------------------------------------

def test_pattern_shift_matches_both_lines():
    assert estimate_pattern_shift([280, 360], [300, 380], match_tolerance_pixels=5,
                                  largest_shift_pixels=60) == pytest.approx(-20)


def test_pattern_shift_none_when_nothing_detected():
    assert estimate_pattern_shift([], [300], 5, 60) is None


def test_line_walk_moves_in_one_direction_only():
    lines = mercury_lines_in_window(800, 820, (2,))
    lamp = SimulatedLineLamp(default_true_model(), lines)
    triax = FakeTriax()
    walk = LineWalk(triax.move_to, triax.read, lambda: lamp.spectrum(triax.read()), shipped_model(), lines)
    walk.run()
    assert triax.move_history == sorted(triax.move_history)


def test_line_walk_and_fit_recover_truth_from_wrong_starting_calibration():
    """The end-to-end check: the software starts ~2 nm off and must find the simulator's truth."""
    true_model = default_true_model()
    starting_model = shipped_model()
    lines = mercury_lines_in_window(700, 900, diffraction_orders=(2,))
    lamp = SimulatedLineLamp(true_model, lines, random_seed=4)
    triax = FakeTriax()

    starting_error_nm = largest_axis_difference_nm(starting_model, true_model, [100_000, 110_000])
    assert starting_error_nm > 1.0

    walk = LineWalk(triax.move_to, triax.read, lambda: lamp.spectrum(triax.read()), starting_model, lines)
    result = walk.run()
    assert len(result.observations) >= 20

    fit = fit_wavelength_axis(result.observations, fit_dispersion_curvature=True)
    assert largest_axis_difference_nm(fit.model, true_model, [95_000, 115_000]) < 0.02
    assert fit.reduced_chi_squared < 3


def test_line_walk_skips_a_position_the_triax_did_not_reach():
    """A timed-out TRIAX move must not produce observations (the grating may still be moving)."""
    lines = mercury_lines_in_window(800, 820, (2,))
    lamp = SimulatedLineLamp(default_true_model(), lines)
    triax = FakeTriax()
    planned_positions = LineWalk(None, None, None, shipped_model(), lines).plan_triax_positions()
    stuck_target = planned_positions[3]

    def move_that_stalls_once(target_steps):
        triax.move_to(target_steps - 40 if target_steps == stuck_target else target_steps)

    acquisition_positions = []

    def acquire():
        acquisition_positions.append(triax.read())
        return lamp.spectrum(triax.read())

    result = LineWalk(move_that_stalls_once, triax.read, acquire, shipped_model(), lines).run()
    assert stuck_target - 40 not in acquisition_positions
    assert all(observation.triax_steps != stuck_target - 40 for observation in result.observations)
    stalled_record = [record for record in result.position_records if record.requested_steps == stuck_target][0]
    assert 'skipped' in stalled_record.notes[0]


def test_line_walk_save_and_load(tmp_path):
    lines = mercury_lines_in_window(800, 820, (2,))
    lamp = SimulatedLineLamp(default_true_model(), lines)
    triax = FakeTriax()
    walk = LineWalk(triax.move_to, triax.read, lambda: lamp.spectrum(triax.read()), shipped_model(), lines)
    result = walk.run()
    path = tmp_path / 'walk.json'
    save_line_walk(path, result, shipped_model(), description='unit test')
    observations, planning_model, contents = load_line_walk_observations(path)
    assert len(observations) == len(result.observations)
    assert planning_model.nm_per_pixel == shipped_model().nm_per_pixel
    assert contents['description'] == 'unit test'


# ----------------------------------------------------------------------------
# Command line: python -m wavelength_calibration fit
# ----------------------------------------------------------------------------

def _write_master_with_model(path, model):
    import json
    with open(path, 'w') as file:
        json.dump({'polarization_calibrations': {'angle_to_pin': [13.333, 0.0]}, 'wavelength_axis': model.to_dict()},
                  file)


def test_command_line_fit_reports_without_writing_then_applies(tmp_path, capsys):
    import json
    from wavelength_calibration.__main__ import main

    lines = mercury_lines_in_window(700, 900, diffraction_orders=(2,))
    lamp = SimulatedLineLamp(default_true_model(), lines, random_seed=5)
    triax = FakeTriax()
    walk = LineWalk(triax.move_to, triax.read, lambda: lamp.spectrum(triax.read()), shipped_model(), lines)
    walk_path = tmp_path / 'walk.json'
    save_line_walk(walk_path, walk.run(), shipped_model())

    master_path = tmp_path / 'master.json'
    _write_master_with_model(master_path, shipped_model())
    backup_directory = tmp_path / 'backup'
    common_arguments = ['fit', str(walk_path), '--curvature', '--master', str(master_path),
                        '--backup-directory', str(backup_directory)]

    assert main(common_arguments) == 0
    assert 'Not applied' in capsys.readouterr().out
    assert json.loads(master_path.read_text())['wavelength_axis'] == shipped_model().to_dict()

    assert main(common_arguments + ['--apply']) == 0
    stored = json.loads(master_path.read_text())
    applied_model = WavelengthAxisModel.from_dict(stored['wavelength_axis'])
    assert largest_axis_difference_nm(applied_model, default_true_model(), [95_000, 115_000]) < 0.03
    assert stored['polarization_calibrations'] == {'angle_to_pin': [13.333, 0.0]}
    assert len(list(backup_directory.iterdir())) == 1


def test_command_line_fit_explains_a_single_wavelength(tmp_path, capsys):
    from wavelength_calibration.__main__ import main

    line = [externally_measured_line(800.0, 0.2)]
    lamp = SimulatedLineLamp(default_true_model(), line)
    triax = FakeTriax()
    walk = LineWalk(triax.move_to, triax.read, lambda: lamp.spectrum(triax.read()), shipped_model(), line)
    walk_path = tmp_path / 'walk.json'
    save_line_walk(walk_path, walk.run(), shipped_model())
    master_path = tmp_path / 'master.json'
    _write_master_with_model(master_path, shipped_model())

    assert main(['fit', str(walk_path), '--master', str(master_path)]) == 1
    assert 'two different known wavelengths' in capsys.readouterr().out
