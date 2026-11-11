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
from wavelength_calibration.line_walk import LineWalk, load_line_walk_observations, save_line_walk
from wavelength_calibration.reference_lines import (argon_mercury_lamp_lines, externally_measured_line,
                                                     mercury_lines_in_window)
from wavelength_calibration.simulated_line_lamp import (SimulatedLineLamp, default_true_model,
                                                        realistic_line_amplitudes)
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


def test_argon_mercury_table_holds_every_line_that_can_reach_the_chip():
    """The 2026-11-10 misidentifications came from lines missing from the table: all there now."""
    lines = argon_mercury_lamp_lines()
    by_label = {line.label: line for line in lines}
    for trap in ('Hg 404.657 (order 2)', 'Ar 737.212 (order 1)', 'Ar 919.464 (order 1)',
                 'Ar 840.821 (order 1)', 'Ar 750.387 (order 1)', 'Hg 407.784 (order 2)',
                 'Ar 703.025 (order 1)', 'Hg 690.746 (order 1)'):
        assert trap in by_label, f"{trap} was seen on the bench and must be in the table"
    assert by_label['Hg 404.657 (order 2)'].apparent_wavelength_nm == pytest.approx(809.314)
    assert by_label['Ar 811.531 (order 1)'].usable_as_reference
    assert 'Ar 738.398 (order 1)' in by_label, "NIST 738.3980 (the old table had 738.393)"
    assert not by_label['Ar 772.376 (order 1)'].usable_as_reference, "a blend is not a reference"
    assert not any(line.usable_as_reference for line in lines if line.element == 'Hg'), \
        "mercury sits ~0.05 nm off the argon lines on this instrument: identification only"
    assert min(line.apparent_wavelength_nm for line in lines) < 615 and \
        max(line.apparent_wavelength_nm for line in lines) > 1010, "the table spans both chip edges"


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


def test_collapse_marks_columns_with_a_saturated_pixel():
    image = np.full((40, 1024), 400.0)
    image[20, 300] = 65535  # one clipped pixel; the band mean alone would hide it
    spectrum = collapse_image_to_spectrum(image, half_height_rows=10, saturation_level=65000)
    assert spectrum[300] == 65000
    assert spectrum[299] == pytest.approx(400.0)


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


def test_model_stored_before_the_dispersion_term_loads_with_fixed_dispersion():
    stored = shipped_model().to_dict()
    del stored['nm_per_pixel_change_per_triax_step'], stored['dispersion_reference_triax_steps']
    model = WavelengthAxisModel.from_dict(stored)
    assert model.nm_per_pixel_at(90_000) == model.nm_per_pixel_at(120_000) == shipped_model().nm_per_pixel


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
    fit = fit_wavelength_axis(observations, fit_dispersion_curvature=True, fit_dispersion_change_with_triax=True)
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

    fit = fit_wavelength_axis(result.observations, fit_dispersion_curvature=True,
                              fit_dispersion_change_with_triax=True)
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
    assert stalled_record.status == 'SKIPPED' and 'skipped' in stalled_record.notes[0]


def run_argon_mercury_walk(line_amplitudes=None, random_seed=6):
    """The realistic lamp: every listed line, at a brightness from its NIST intensity."""
    true_model = default_true_model()
    catalogue = argon_mercury_lamp_lines()
    lamp = SimulatedLineLamp(
        true_model, catalogue,
        line_amplitudes=line_amplitudes or realistic_line_amplitudes(catalogue, 0.6),
        line_sigma_pixels=1.4, noise_standard_deviation=8, random_seed=random_seed)
    triax = FakeTriax()
    walk = LineWalk(triax.move_to, triax.read, lambda: lamp.spectrum(triax.read()), shipped_model(), catalogue,
                    saturation_level=65000)
    return walk, walk.run(), catalogue


def test_argon_mercury_walk_recovers_truth_with_uneven_line_strengths():
    walk, result, _catalogue = run_argon_mercury_walk()
    assert len(walk.plan_triax_positions()) < 40
    recorded_lines = {observation.line_name for observation in result.observations}
    assert not any('772.' in name for name in recorded_lines), "the unresolved 772 nm blend was used"
    assert {'Ar 800.616 (order 1)', 'Ar 801.479 (order 1)'} <= recorded_lines, "11 px pair should be resolved"
    fit = fit_wavelength_axis(result.observations, fit_dispersion_curvature=True,
                              fit_dispersion_change_with_triax=True)
    measured_steps = sorted({observation.triax_steps for observation in result.observations})
    assert largest_axis_difference_nm(fit.model, default_true_model(), measured_steps) < 0.02
    assert fit.residual_max_nm < 0.05, "a misidentified line would leave a residual of ~1 nm or more"


def test_fixed_dispersion_cannot_describe_a_wide_walk():
    """
    Riley's first bench walk (2026-11-04): small rms, reduced chi^2 in the thousands.

    The dispersion falls as the grating turns; one nm_per_pixel for the whole
    690-930 nm walk leaves a systematic error that the tiny bright-line
    uncertainties turn into a huge chi^2. The cross term removes it.
    """
    _walk, result, _catalogue = run_argon_mercury_walk()
    measured_steps = sorted({observation.triax_steps for observation in result.observations})
    fixed_dispersion_fit = fit_wavelength_axis(result.observations, fit_dispersion_curvature=True)
    tracking_fit = fit_wavelength_axis(result.observations, fit_dispersion_curvature=True,
                                       fit_dispersion_change_with_triax=True)
    assert fixed_dispersion_fit.reduced_chi_squared > 50
    assert largest_axis_difference_nm(fixed_dispersion_fit.model, default_true_model(), measured_steps) > 0.1
    assert tracking_fit.reduced_chi_squared < 3
    assert tracking_fit.model.nm_per_pixel_change_per_triax_step == pytest.approx(-2.0e-8, rel=0.1)


def grating_angle_drive_true_model():
    """
    Truth for a TRIAX whose steps turn the grating ANGLE: wavelength ~ sin(angle), so
    triax_wavelength is quadratic in steps (curvature -lambda / (2 S^2), S = steps per
    radian ~ 7e5, about -7.6e-10 nm/step^2 at 800 nm), on top of the dispersion change.
    """
    quadratic_nm_per_step_squared = -7.6e-10
    centre_steps, centre_wavelength_nm, centre_slope_nm_per_step = 107_000.0, 800.0, 0.009096
    linear_nm_per_step = centre_slope_nm_per_step - 2 * quadratic_nm_per_step_squared * centre_steps
    constant_nm = (centre_wavelength_nm - quadratic_nm_per_step_squared * centre_steps ** 2
                   - linear_nm_per_step * centre_steps)
    model = default_true_model()
    model.triax_to_wavelength_coefficients = [quadratic_nm_per_step_squared, linear_nm_per_step, constant_nm]
    return model


def test_grating_angle_drive_needs_the_full_physical_model():
    true_model = grating_angle_drive_true_model()
    for pixel in (50, 900):
        steps = true_model.triax_steps_for_wavelength(842.465, at_pixel=pixel)
        assert true_model.wavelength_at(pixel, steps) == pytest.approx(842.465, abs=1e-9)

    catalogue = argon_mercury_lamp_lines()
    lamp = SimulatedLineLamp(true_model, catalogue,
                             line_amplitudes=realistic_line_amplitudes(catalogue, 0.6),
                             line_sigma_pixels=1.4, noise_standard_deviation=8, random_seed=6)
    triax = FakeTriax()
    result = LineWalk(triax.move_to, triax.read, lambda: lamp.spectrum(triax.read()), shipped_model(), catalogue,
                      saturation_level=65000).run()
    measured_steps = sorted({observation.triax_steps for observation in result.observations})
    partial_fit = fit_wavelength_axis(result.observations, fit_dispersion_curvature=True,
                                      fit_dispersion_change_with_triax=True)
    full_fit = fit_wavelength_axis(result.observations, fit_dispersion_curvature=True,
                                   fit_dispersion_change_with_triax=True, triax_polynomial_order=2)
    assert partial_fit.reduced_chi_squared > 50
    assert full_fit.reduced_chi_squared < 3
    assert largest_axis_difference_nm(full_fit.model, true_model, measured_steps) < 0.02


def test_argon_mercury_walk_skips_a_saturated_line():
    catalogue = argon_mercury_lamp_lines()
    amplitudes = [200000.0 if line.name == 'Ar 811.531' else amplitude
                  for line, amplitude in zip(catalogue, realistic_line_amplitudes(catalogue, 0.6))]
    _walk, result, _ = run_argon_mercury_walk(line_amplitudes=amplitudes)
    assert not any(o.line_name == 'Ar 811.531 (order 1)' for o in result.observations)
    all_notes = [note for record in result.position_records for note in record.notes]
    assert any('Ar 811.531' in note and 'saturated' in note for note in all_notes)
    fit = fit_wavelength_axis(result.observations, fit_dispersion_curvature=True,
                              fit_dispersion_change_with_triax=True)
    measured_steps = sorted({observation.triax_steps for observation in result.observations})
    assert largest_axis_difference_nm(fit.model, default_true_model(), measured_steps) < 0.02


def test_line_walk_save_and_load(tmp_path):
    lines = mercury_lines_in_window(800, 820, (2,))
    lamp = SimulatedLineLamp(default_true_model(), lines)
    triax = FakeTriax()
    walk = LineWalk(triax.move_to, triax.read, lambda: lamp.spectrum(triax.read()), shipped_model(), lines)
    result = walk.run()
    path = tmp_path / 'walk.json'
    save_line_walk(path, result, shipped_model(), description='unit test', catalogue_lines=lines)
    observations, planning_model, contents = load_line_walk_observations(path)
    assert len(observations) == len(result.observations)
    assert planning_model.nm_per_pixel == shipped_model().nm_per_pixel
    assert contents['description'] == 'unit test'
    saved_spectra = [record['spectrum'] for record in contents['position_records']]
    assert all(len(spectrum) == 1024 for spectrum in saved_spectra), "every position keeps its spectrum"
    assert saved_spectra[0] == result.position_records[0].spectrum


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
    save_line_walk(walk_path, walk.run(), shipped_model(), catalogue_lines=lines)

    master_path = tmp_path / 'master.json'
    _write_master_with_model(master_path, shipped_model())
    backup_directory = tmp_path / 'backup'
    report_directory = tmp_path / 'reports'
    common_arguments = ['fit', str(walk_path), '--curvature', '--master', str(master_path),
                        '--backup-directory', str(backup_directory), '--report-directory', str(report_directory)]

    assert main(common_arguments) == 0
    assert 'Not applied' in capsys.readouterr().out
    assert json.loads(master_path.read_text())['wavelength_axis'] == shipped_model().to_dict()
    [report_only_path] = list(report_directory.iterdir())
    assert 'status: NOT APPLIED' in report_only_path.read_text()

    assert main(common_arguments + ['--apply']) == 0
    stored = json.loads(master_path.read_text())
    applied_model = WavelengthAxisModel.from_dict(stored['wavelength_axis'])
    assert largest_axis_difference_nm(applied_model, default_true_model(), [95_000, 115_000]) < 0.03
    assert stored['polarization_calibrations'] == {'angle_to_pin': [13.333, 0.0]}
    assert len(list(backup_directory.iterdir())) == 1

    applied_report_path = report_directory / applied_model.metadata['fit_report']
    assert applied_report_path != report_only_path, "a second fit must not overwrite the first report"
    applied_report = applied_report_path.read_text()
    assert 'status: APPLIED' in applied_report and str(backup_directory) in applied_report
    assert 'residuals (measured - fitted wavelength)' in applied_report
    assert 'nm_per_pixel x (scaled steps)' in applied_report, "the dispersion term is fitted by default"


def test_command_line_fit_explains_a_single_wavelength(tmp_path, capsys):
    from wavelength_calibration.__main__ import main

    line = [externally_measured_line(800.0, 0.2)]
    lamp = SimulatedLineLamp(default_true_model(), line)
    triax = FakeTriax()
    walk = LineWalk(triax.move_to, triax.read, lambda: lamp.spectrum(triax.read()), shipped_model(), line)
    walk_path = tmp_path / 'walk.json'
    save_line_walk(walk_path, walk.run(), shipped_model(), catalogue_lines=line)
    master_path = tmp_path / 'master.json'
    _write_master_with_model(master_path, shipped_model())

    assert main(['fit', str(walk_path), '--master', str(master_path),
                 '--report-directory', str(tmp_path / 'reports')]) == 1
    assert 'two different known wavelengths' in capsys.readouterr().out


# ----------------------------------------------------------------------------
# Pattern identification, gate checks, two-stage fit, quick re-zero (2026-11-11)
# ----------------------------------------------------------------------------

import functools
import os

from wavelength_calibration.calibration_checks import (FAIL, PASS, WARN, CalibrationEvidence,
                                                       CheckLimits, check_coverage,
                                                       check_triax_shape, check_unexplained_peaks,
                                                       check_walk_data, decompose_fit_residuals,
                                                       run_checks)
from wavelength_calibration.line_identification import (IDENTIFIED, NOT_IDENTIFIED,
                                                        merge_coincident_lines)
from wavelength_calibration.line_peaks import find_and_fit_peaks
from wavelength_calibration.wavelength_axis_model import CALIBRATED_RANGE_KEY
from wavelength_calibration.line_walk import identify_saved_walk, load_line_walk
from wavelength_calibration.fit_plots import plot_wavelength_axis_fit
from wavelength_calibration.promotion import (FitOptions, WalkFitOutcome,
                                              fit_and_check_line_walk_files)
from wavelength_calibration.provenance import software_version
from wavelength_calibration.reference_lines import ReferenceLine
from wavelength_calibration.simulated_line_lamp import periodic_triax_drive_error
from wavelength_calibration.triax_zero import position_table, run_triax_zero, zero_evidence

REPLAY_FIXTURE = os.path.join(os.path.dirname(__file__), 'test_fixtures',
                              'linewalk_20261110_161055_arhg_replay.json')


def realistic_lamp(true_model=None, drive_error=None, extra_lines=(), extra_amplitudes=(),
                   random_seed=3):
    """Every table line at a NIST-based brightness, and an optional TRIAX drive error."""
    catalogue = argon_mercury_lamp_lines()
    return SimulatedLineLamp(
        true_model or default_true_model(), list(catalogue) + list(extra_lines),
        line_amplitudes=realistic_line_amplitudes(catalogue, 0.6) + list(extra_amplitudes),
        line_sigma_pixels=1.2, noise_standard_deviation=8, random_seed=random_seed,
        triax_drive_error_nm=drive_error)


def walk_with(lamp, samples_per_line=6, prior=None):
    triax = FakeTriax()
    walk = LineWalk(triax.move_to, triax.read, lambda: lamp.spectrum(triax.read()),
                    prior or shipped_model(), argon_mercury_lamp_lines(),
                    samples_per_line=samples_per_line, saturation_level=65000)
    return walk.run()


@functools.lru_cache(maxsize=None)
def walk_with_drive_error():
    """A realistic walk with a measured-size TRIAX drive error, shared by several tests (~20 s)."""
    lamp = realistic_lamp(drive_error=periodic_triax_drive_error())
    return lamp, walk_with(lamp)


def evidence_for(identification, **fields):
    """CalibrationEvidence for one simulated walk."""
    return CalibrationEvidence(kind='fit', walk_labels=['simulated'],
                               identifications=[identification], instruments=[{}],
                               frame_conditions=[[]], format_versions=[2], **fields)


def test_identification_puts_every_line_where_the_truth_has_it():
    """
    The 2026-11-10 failure, in the simulator: weak neighbours present, the prior calibration
    ~2.7 nm off with an error that changes along the walk, a TRIAX drive error. Every recorded line
    must be the right line.
    """
    lamp, result = walk_with_drive_error()
    assert len(result.observations) > 100
    assert result.identification.ambiguity_ratio < 0.7
    for observation in result.observations:
        drive_error = lamp.triax_drive_error_nm(observation.triax_steps)
        true_pixel = lamp.true_model.pixel_of_wavelength(
            observation.apparent_wavelength_nm - drive_error, observation.triax_steps)
        assert abs(observation.centre_pixel - true_pixel) < 0.3, f"{observation.line_name} is wrong"


def test_unlisted_strong_line_is_reported_with_its_wavelength():
    """A strong line missing from the table must be named in the gate report by wavelength."""
    unlisted = ReferenceLine(name='X 845.700', wavelength_nm=845.700)
    lamp = realistic_lamp(extra_lines=[unlisted], extra_amplitudes=[30000.0])
    result = walk_with(lamp, samples_per_line=3)
    check = check_unexplained_peaks(evidence_for(result.identification), CheckLimits())
    assert check.verdict == WARN
    assert any('845.7' in detail for detail in check.details), check.details
    assert all(observation.line_name != 'X 845.700' for observation in result.observations)


def test_coincident_lines_merge_into_the_dominant_line_or_a_blend():
    merged_lines = merge_coincident_lines(argon_mercury_lamp_lines(), 0.2, 0.003)
    merged = {line.name: line for line in merged_lines}
    assert merged['Ar 706.722'].usable_as_reference, "the 100x weaker Ar 706.874 cannot move it"
    assert 'Ar 706.874' not in merged
    blend = [line for name, line in merged.items() if '772.376' in name]
    assert len(blend) == 1 and not blend[0].usable_as_reference, "772.376 + 772.421 is one blend"


def ccd_shape_error_nm(model, true_model, steps_values):
    """Largest error of the CCD axis shape (wavelength relative to the chip centre)."""
    errors = []
    for steps in steps_values:
        model_shape = model.wavelength_axis(steps, 1024) - model.wavelength_at(512, steps)
        true_shape = true_model.wavelength_axis(steps, 1024) - true_model.wavelength_at(512, steps)
        errors.append(float(np.max(np.abs(model_shape - true_shape))))
    return max(errors)


def test_two_stage_fit_keeps_the_ccd_axis_through_a_triax_drive_error():
    """In a joint fit the drive error bends the CCD terms; with a free offset per frame it can't."""
    lamp, result = walk_with_drive_error()
    steps = sorted({observation.triax_steps for observation in result.observations})
    fit_settings = dict(triax_polynomial_order=2, fit_dispersion_curvature=True,
                        fit_dispersion_change_with_triax=True)
    joint = fit_wavelength_axis(result.observations, **fit_settings)
    two_stage = fit_wavelength_axis(result.observations, separate_triax_from_ccd=True,
                                    **fit_settings)
    two_stage_error = ccd_shape_error_nm(two_stage.model, lamp.true_model, steps)
    assert two_stage_error < 0.005
    assert ccd_shape_error_nm(joint.model, lamp.true_model, steps) > 2 * two_stage_error


def test_triax_shape_gate_names_the_polynomial_order_the_data_needs():
    """A TRIAX that is cubic in steps, fitted as quadratic: the gate must say 'triaxorder=3'."""
    true_model = default_true_model()
    cubic_nm_per_step_cubed = 4e-14  # ~0.4 nm over the walk, the size measured on 2026-11-10
    linear, constant = true_model.triax_to_wavelength_coefficients
    cubic_term = cubic_nm_per_step_cubed * np.poly1d([1.0, -104_000.0]) ** 3
    true_model.triax_to_wavelength_coefficients = list(np.poly1d([linear, constant]) + cubic_term)
    result = walk_with(realistic_lamp(true_model=true_model), samples_per_line=3)
    fit = fit_wavelength_axis(result.observations, triax_polynomial_order=2,
                              fit_dispersion_curvature=True, fit_dispersion_change_with_triax=True,
                              separate_triax_from_ccd=True)
    evidence = evidence_for(result.identification, fit=fit, current_model=true_model,
                            fit_options={'triax_polynomial_order': 2})
    check = check_triax_shape(evidence, CheckLimits())
    assert check.verdict in (WARN, FAIL)
    assert any('triaxorder=3' in action for action in check.what_to_try), check.what_to_try


def test_walk_recorded_in_simulate_mode_fails_a_real_calibration():
    evidence = CalibrationEvidence(kind='fit', walk_labels=['linewalk_sim.json'],
                                   identifications=[], instruments=[{'simulate': True}],
                                   frame_conditions=[[]], format_versions=[2])
    assert check_walk_data(evidence, CheckLimits()).verdict == FAIL
    evidence.running_in_simulate_mode = True
    assert check_walk_data(evidence, CheckLimits()).verdict == PASS


def test_walks_with_different_triax_zeros_share_the_shape_and_take_the_latest_zero(tmp_path):
    """The TRIAX counter moves 100 steps between walks: one shape fit, the later zero, a WARN."""
    paths = []
    for name, counter_error_steps in (('linewalk_1.json', 0), ('linewalk_2.json', 100)):
        lamp = realistic_lamp(random_seed=len(paths) + 1)
        lamp.triax_counter_error_steps = counter_error_steps
        path = tmp_path / name
        save_line_walk(path, walk_with(lamp, samples_per_line=3), shipped_model(),
                       reference_kind='arhg', instrument={'simulate': True})
        paths.append(str(path))
    outcome = fit_and_check_line_walk_files(
        paths, shipped_model(), FitOptions(curvature=True, triax_polynomial_order=2),
        running_in_simulate_mode=True)
    agreement = [result for result in outcome.check_results if result.name == 'walk agreement'][0]
    assert agreement.verdict == WARN
    assert any('zero moved' in cause for cause in agreement.likely_causes)
    nm_per_step = abs(outcome.fit.model.nm_per_triax_step(104_000))
    step_shift = abs(outcome.fit.group_offsets_nm['linewalk_1.json']) / nm_per_step
    assert step_shift == pytest.approx(100, abs=2)
    truth = realistic_lamp().true_model
    for steps in (95_000, 110_000):
        assert outcome.fit.model.wavelength_at(512, steps) == pytest.approx(
            truth.wavelength_at(512, steps + 100), abs=0.02), "the model follows the latest walk"


def test_fit_plot_is_saved_for_a_fit_and_skipped_without_one(tmp_path):
    """speccalfit plot: a PNG of the fit and its residuals; nothing drawn when there is no fit."""
    walk_path = tmp_path / 'linewalk_plot.json'
    save_line_walk(walk_path, walk_with(realistic_lamp(), samples_per_line=3), shipped_model(),
                   reference_kind='arhg', instrument={'simulate': True})
    outcome = fit_and_check_line_walk_files(
        [str(walk_path)], shipped_model(), FitOptions(curvature=True, triax_polynomial_order=2),
        running_in_simulate_mode=True)
    plot_path = tmp_path / 'fit.png'
    assert plot_wavelength_axis_fit(outcome, str(plot_path), title='test') == str(plot_path)
    assert plot_path.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n'
    no_fit = WalkFitOutcome(fit=None, evidence=outcome.evidence, check_results=[])
    assert plot_wavelength_axis_fit(no_fit, str(tmp_path / 'none.png')) is None
    assert not (tmp_path / 'none.png').exists()


@functools.lru_cache(maxsize=None)
def calibrated_model_with_drive_error():
    """A model fitted (two-stage, with its TRIAX position table) from the drive-error walk."""
    import tempfile
    _lamp, result = walk_with_drive_error()
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, 'linewalk_calibration.json')
        save_line_walk(path, result, shipped_model(), reference_kind='arhg',
                       instrument={'simulate': True})
        outcome = fit_and_check_line_walk_files(
            [path], shipped_model(), FitOptions(curvature=True, triax_polynomial_order=2),
            running_in_simulate_mode=True)
    return outcome.fit.model


def run_zero_on(lamp, model):
    triax = FakeTriax()
    return run_triax_zero(triax.move_to, triax.read, lambda: lamp.spectrum(triax.read()), model,
                          argon_mercury_lamp_lines(), saturation_level=65000)


def test_rezero_recovers_a_shifted_step_count():
    """The TRIAX counter loses 137 steps: speccalzero must find 137, and the model fit the lamp."""
    model = calibrated_model_with_drive_error()
    assert model.metadata['triax_position_offsets_nm'], "the fit stores the TRIAX position table"
    lamp = realistic_lamp(drive_error=periodic_triax_drive_error())
    lamp.triax_counter_error_steps = 137
    zero_run = run_zero_on(lamp, model)
    assert zero_run.measurement.step_offset == pytest.approx(137, abs=1.5)
    assert zero_run.passes == 2, "a large shift is re-measured at the corrected positions"
    results = run_checks(zero_evidence(zero_run, model, running_in_simulate_mode=True))
    assert not any(result.verdict == FAIL for result in results), \
        [result.summary for result in results if result.verdict == FAIL]
    corrected = zero_run.measurement.corrected_model(model)
    assert corrected.triax_step_offset == pytest.approx(model.triax_step_offset + 137, abs=1.5)
    # After the re-zero each frame is off the polynomial by exactly what the calibration walk
    # measured at the same drive position (the drive pattern the polynomial cannot follow).
    table = position_table(model)
    for observation in zero_run.walk_result.observations:
        drive = observation.triax_steps + corrected.triax_step_offset
        stored_drive = min(table, key=lambda steps: abs(steps - drive))
        assert abs(stored_drive - drive) < 5
        residual = observation.apparent_wavelength_nm - corrected.wavelength_at(
            observation.centre_pixel, observation.triax_steps)
        assert residual == pytest.approx(table[stored_drive], abs=0.02)


def test_rezero_refuses_when_more_than_the_zero_changed():
    """If the TRIAX scale changed, the frames disagree on the shift and the gate says: full walk."""
    model = calibrated_model_with_drive_error()
    changed_truth = default_true_model()
    slope, constant = changed_truth.triax_to_wavelength_coefficients
    changed_truth.triax_to_wavelength_coefficients = [slope * 1.002,
                                                      constant - 0.002 * slope * 104_000]
    lamp = realistic_lamp(true_model=changed_truth, drive_error=periodic_triax_drive_error())
    zero_run = run_zero_on(lamp, model)
    results = run_checks(zero_evidence(zero_run, model, running_in_simulate_mode=True))
    consistency = [result for result in results if result.name == 'zero consistency'][0]
    assert consistency.verdict == FAIL
    assert any('speccal' in action for action in consistency.what_to_try)


def test_replay_of_the_2026_11_10_bench_walk_finds_the_right_lines():
    """
    Riley's walk of 2026-11-10 16:10 (spectra kept as a fixture). The first walk code recorded the
    weak Hg 404.657 (2nd order) peak at pixel ~903.5 as Ar 811.531; the real Ar 810.369 / 811.531
    pair is at ~916.6 / ~931.7. Re-identified from the spectra, every frame with lines must be
    identified, those three peaks must get their real names, and each frame's lines must agree to
    < 0.01 nm.
    """
    saved_walk = load_line_walk(REPLAY_FIXTURE)
    identification = identify_saved_walk(saved_walk)
    frames_with_lines = [frame for frame in identification.frames if frame.strong_peaks]
    identified = sum(frame.status == IDENTIFIED for frame in frames_with_lines)
    assert identified >= len(frames_with_lines) - 1
    assert len(identification.observations) >= 120
    frame = [frame for frame in identification.frames if frame.triax_steps == 100279][0]

    def name_of_peak_near(pixel):
        assignment = min(frame.assignments,
                         key=lambda assignment: abs(assignment.peak.centre_pixel - pixel))
        assert abs(assignment.peak.centre_pixel - pixel) < 1.0
        return assignment.line.label

    assert name_of_peak_near(903.5) == 'Hg 404.657 (order 2)'
    assert name_of_peak_near(916.6) == 'Ar 810.369 (order 1)'
    assert name_of_peak_near(931.7) == 'Ar 811.531 (order 1)'
    old_record = [o for o in saved_walk.stored_observations if o.triax_steps == 100279][0]
    assert old_record.line_name == 'Ar 811.531 (order 1)', "the old identification is kept"
    assert abs(old_record.centre_pixel - 903.5) < 1
    fit = fit_wavelength_axis(identification.observations, triax_polynomial_order=3,
                              fit_dispersion_curvature=True, fit_dispersion_change_with_triax=True,
                              separate_triax_from_ccd=True)
    assert decompose_fit_residuals(fit).within_frame_rms_nm < 0.01


def test_saved_walk_records_conditions_and_is_reidentified_from_its_spectra(tmp_path):
    lines = mercury_lines_in_window(700, 900, (2,))
    lamp = SimulatedLineLamp(default_true_model(), lines, random_seed=4)
    triax = FakeTriax()
    walk = LineWalk(triax.move_to, triax.read, lambda: lamp.spectrum(triax.read()), shipped_model(),
                    lines, read_frame_conditions=lambda: {'sensor_temperature_c': -43.0})
    result = walk.run()
    path = tmp_path / 'walk.json'
    save_line_walk(path, result, shipped_model(), catalogue_lines=lines,
                   instrument={'simulate': True, 'camera': {'exposure_s': 1.0}})
    saved_walk = load_line_walk(path)
    assert saved_walk.format_version == 2 and saved_walk.recorded_in_simulate_mode is True
    assert saved_walk.reference_kind == 'catalogue'
    recorded = [record for record in saved_walk.contents['position_records'] if record['spectrum']]
    assert all(record['conditions'] == {'sensor_temperature_c': -43.0} and record['recorded_at']
               for record in recorded)
    assert all(record['status'] for record in recorded), "each position says if it was identified"
    assert len(identify_saved_walk(saved_walk).observations) == len(result.observations)


def test_triax_step_offset_shifts_the_model_in_steps_only():
    base = default_true_model()
    shifted = WavelengthAxisModel.from_dict({**base.to_dict(), 'triax_step_offset': 250.0})
    for pixel in (0, 512, 1000):
        expected = base.wavelength_at(pixel, 100_250)
        assert shifted.wavelength_at(pixel, 100_000) == pytest.approx(expected, abs=1e-9)
    steps = shifted.triax_steps_for_wavelength(812.0, at_pixel=300)
    assert shifted.wavelength_at(300, steps) == pytest.approx(812.0, abs=1e-9)


def test_software_version_is_unknown_outside_a_clone(tmp_path):
    version = software_version(tmp_path)
    assert version['commit'] == 'unknown' and version['branch'] == 'unknown'


def test_a_bump_on_a_bright_line_wing_is_not_fitted_as_a_satellite():
    """
    2026-11-11 (RAM-F2): a small bump on a broad line's wing became a candidate, its fit window
    shrank to 3 px, and the Gaussian climbed the bright line to the window edge: a false peak
    2-3 px from every bright line. Riley's counts around Ar 811.531 (walk 14:24, TRIAX 100858)
    reproduce it; only the line itself may be reported.
    """
    riley_counts_823_to_839 = [391, 393, 463, 487, 465, 602, 1045, 1529, 1639, 1494, 1307, 1045,
                               775, 610, 512, 435, 391]
    spectrum = 391.0 + np.random.default_rng(4).normal(0.0, 5.0, 1024)
    spectrum[823:840] = riley_counts_823_to_839
    without_check = find_and_fit_peaks(spectrum, maximum_centre_shift_pixels=np.inf)
    assert len(without_check) == 2, "the test spectrum must reproduce the artefact"
    peaks = find_and_fit_peaks(spectrum)
    assert len(peaks) == 1
    assert peaks[0].centre_pixel == pytest.approx(831.4, abs=0.1)


def test_frames_beyond_the_walk_trend_are_identified_from_their_neighbours():
    """
    2026-11-11 (RAM-F2): the TRIAX bent away from the walk's smooth trend at its ends (0.5-1.7 nm
    in the last frames), so those frames failed. Identified outward from their neighbours, every
    frame with lines must be identified, with the right lines.
    """
    def drive_bending_at_the_walk_ends(triax_steps):
        return 1.7 * ((np.asarray(triax_steps, dtype=float) - 104_000.0) / 17_000.0) ** 8

    lamp = realistic_lamp(drive_error=drive_bending_at_the_walk_ends)
    result = walk_with(lamp)
    frames_with_lines = [frame for frame in result.identification.frames
                         if frame.status != 'NO LINES']
    assert all(frame.identified for frame in frames_with_lines), \
        [frame.summary() for frame in frames_with_lines if not frame.identified]
    assert any('neighbouring frames' in ' '.join(frame.reasons) for frame in frames_with_lines), \
        "the walk ends must need the outward pass, or the test does not test it"
    for observation in result.observations:
        true_pixel = lamp.true_model.pixel_of_wavelength(
            observation.apparent_wavelength_nm - lamp.triax_drive_error_nm(observation.triax_steps),
            observation.triax_steps)
        assert abs(observation.centre_pixel - true_pixel) < 0.3, f"{observation.line_name} is wrong"


def test_fitted_range_is_stored_and_an_unfitted_walk_end_is_reported(tmp_path):
    """The model knows the TRIAX range it was fitted over; frames past it make coverage WARN."""
    walk_path = tmp_path / 'linewalk_range.json'
    save_line_walk(walk_path, walk_with(realistic_lamp(), samples_per_line=3), shipped_model(),
                   reference_kind='arhg', instrument={'simulate': True})
    outcome = fit_and_check_line_walk_files(
        [str(walk_path)], shipped_model(), FitOptions(curvature=True, triax_polynomial_order=2),
        running_in_simulate_mode=True)
    model = outcome.fit.model
    first_steps, last_steps = model.metadata[CALIBRATED_RANGE_KEY]
    assert model.steps_outside_calibrated_range((first_steps + last_steps) / 2) == 0.0
    assert model.steps_outside_calibrated_range(last_steps + 500) == pytest.approx(500)
    assert model.steps_outside_calibrated_range(first_steps - 200) == pytest.approx(200)
    coverage = [result for result in outcome.check_results if result.name == 'coverage'][0]
    assert coverage.verdict == PASS, coverage.details

    identification = outcome.evidence.identifications[0]
    last_frame = max(identification.identified_frames, key=lambda frame: frame.triax_steps)
    last_frame.status = NOT_IDENTIFIED  # as if the walk's last frame had failed
    kept = [observation for observation in outcome.fit.observations
            if observation.triax_steps != last_frame.triax_steps]
    fit_without_end = fit_wavelength_axis(kept, triax_polynomial_order=2,
                                          fit_dispersion_curvature=True,
                                          separate_triax_from_ccd=True)
    coverage = check_coverage(evidence_for(identification, fit=fit_without_end), CheckLimits())
    assert coverage.verdict == WARN
    assert 'extrapolated' in coverage.summary
    assert any(str(last_frame.triax_steps) in detail for detail in coverage.details)

