"""
Unit tests for filter_calibration: the stage 1 edge (g1) calibration.

Most tests build a session on disk without the application: the run files are "played" by a
small interpreter (play_run_file) that keeps track of the motor counts, the TRIAX and the slit
the way the application does, writes a run log in the application's format, and saves each
frame from a SimulatedStage1Bench. The analysis must then recover the bench's true calibration.
The full workflow through the application (the real runfile command in simulate mode) is in
test_headless_simulation.py.

Run: python -m pytest test_filter_calibration.py -q
"""

import json
import os
import shutil
import tempfile

import numpy as np
import pytest

from filter_calibration import frame_names, run_files
from filter_calibration.__main__ import main as filter_calibration_main
from filter_calibration.analysis import analyse_session
from filter_calibration.axis_reference import measure_axis_reference
from filter_calibration.calibration_checks import run_edge_checks
from filter_calibration.edge_fit import analyse_edge_frame
from filter_calibration.session import read_session
from filter_calibration.simulated_bench import ARGON_MERCURY, HALOGEN, SimulatedStage1Bench
from wavelength_calibration.calibration_checks import FAIL, WARN

MASTER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'calibration',
                           'master_calibration_microsteps_32.json')
CHIP_PLACEMENT = run_files.ChipPlacement(target_pixel=100, nm_per_pixel=0.0774)
IMAGE_HEIGHT = 200
SMALL_BENCH = dict(band_row=120.0, argon_rows=(40, 180))


def load_master():
    with open(MASTER_PATH) as master_file:
        return json.load(master_file)


def frame_axis_nm(st_wavelength_nm, columns=1024):
    """The axis 'st X' gives: X on the target pixel, nm_per_pixel per column."""
    return st_wavelength_nm + (np.arange(columns) - CHIP_PLACEMENT.target_pixel) * \
        CHIP_PLACEMENT.nm_per_pixel


class RunFilePlayer:
    """Plays run file lines as the application would, for the commands the run files use."""

    def __init__(self, bench, data_directory, log_directory, master, slit_width_um=500):
        self.bench, self.data_directory, self.log_directory = bench, data_directory, log_directory
        self.master = master
        self.motor_counts = {'g1': 0, 'g2': 0}
        self.st_wavelength_nm = 800.0
        self.slit_width_um = slit_width_um
        self.pending_name = None
        self.clock = 0

    def triax_steps(self):
        return int(round(self.st_wavelength_nm * 128))

    def play(self, lines, log_name):
        log_path = os.path.join(self.log_directory, log_name)
        with open(log_path, 'w') as log:
            log.write(f'# run file: {log_name}\n')
            for line in lines:
                if not line.strip() or line.startswith('#'):
                    continue
                result = self._run(line.strip())
                self.clock += 1
                log.write(f'2026-12-01T10:{self.clock // 60:02d}:{self.clock % 60:02d}\t{line}\t'
                          f'{result}\n')
        return log_path

    def _run(self, line):
        command, _, argument = line.partition(' ')
        if command == 'st':
            self.st_wavelength_nm = float(argument)
            return True
        if command == 'sg':
            for motor in ('g1', 'g2'):
                self.motor_counts[motor] = int(round(np.polyval(
                    self.master[f'manual_{motor}'][f'wl_to_{motor}'], float(argument))))
            return True
        if command in ('g1', 'g2'):
            self.motor_counts[command] += int(argument)
            return None
        if command == 'rg':
            return self.triax_steps()
        if command == 'ren':
            return self.slit_width_um
        if command == 'allmotors':
            return dict(self.motor_counts)
        if command == 'filename':
            self.pending_name = argument
            return None
        if command == 'acquire':
            self._save_frame()
            return None
        return True                 # acqtime, nframe

    def _save_frame(self):
        name = self.pending_name
        folder = os.path.join(self.data_directory, name)
        os.makedirs(folder, exist_ok=True)
        index = len(os.listdir(folder))
        axis = frame_axis_nm(self.st_wavelength_nm)
        image = self.bench.image(self.motor_counts['g1'], axis, self.triax_steps(),
                                 image_height=IMAGE_HEIGHT)
        metadata = {'_current_parameters': {'acquisition_time': 1.0, 'filename': name}}
        np.savez_compressed(os.path.join(folder, f'{name}_{index:06d}.npz'), image=image,
                            wavelength=axis, metadata=json.dumps(metadata))


@pytest.fixture
def workspace():
    directory = tempfile.mkdtemp(prefix='filter_calibration_test_')
    paths = {name: os.path.join(directory, name) for name in ('data', 'logs', 'reports',
                                                              'calibration')}
    for path in paths.values():
        os.makedirs(path)
    yield paths
    shutil.rmtree(directory, ignore_errors=True)


def play_session(workspace, bench, centres=(760, 800, 840), with_axis_references=True,
                 with_steps=True, with_repeatability=True):
    """Play a small session; returns the run log paths."""
    master = load_master()
    player = RunFilePlayer(bench, workspace['data'], workspace['logs'], master)
    grating_pair_at = lambda centre: run_files.GratingPair(
        run_files.g2_steps_per_g1_step(master, centre))
    logs = [player.play(run_files.edge_walk_lines(centres, CHIP_PLACEMENT, grating_pair_at,
                                                  exposure_seconds=1.0), 'walk.txt')]
    if with_steps:
        logs.append(player.play(run_files.single_step_lines(
            800, CHIP_PLACEMENT, grating_pair_at(800), half_range_steps=4, reverse_steps=2),
            'steps.txt'))
    if with_repeatability:
        logs.append(player.play(run_files.repeatability_lines(800, CHIP_PLACEMENT, cycles=1),
                                'repeatability.txt'))
    if with_axis_references:
        bench.lamp, player.slit_width_um = ARGON_MERCURY, 50
        logs.append(player.play(run_files.axis_reference_lines(centres, CHIP_PLACEMENT),
                                'axis.txt'))
        bench.lamp, player.slit_width_um = HALOGEN, 500
    return logs


def analyse(workspace, logs):
    return analyse_session(read_session(logs, workspace['data']), load_master())


def verdicts(check_results):
    return {result.name: result.verdict for result in check_results}


# ---------------------------------------------------------------------------- frame names

def test_every_name_the_run_files_write_parses_back():
    master = load_master()
    pair_at = lambda centre: run_files.GratingPair(run_files.g2_steps_per_g1_step(master, centre))
    all_lines = (run_files.edge_walk_lines([720, 800], CHIP_PLACEMENT, pair_at)
                 + run_files.single_step_lines(800, CHIP_PLACEMENT, pair_at(800))
                 + run_files.repeatability_lines(800, CHIP_PLACEMENT)
                 + run_files.axis_reference_lines([720, 800], CHIP_PLACEMENT))
    names = [line.split()[1] for line in all_lines if line.startswith('filename ')]
    parsed = [frame_names.parse_frame_name(name) for name in names]
    assert None not in parsed
    kinds = {frame_name.kind for frame_name in parsed}
    assert kinds == {frame_names.EDGE_WALK, frame_names.SINGLE_STEP, frame_names.REPEATABILITY,
                     frame_names.AXIS_REFERENCE}
    walk = [frame_name for frame_name in parsed if frame_name.kind == frame_names.EDGE_WALK]
    assert sorted({frame_name.g1_offset_steps for frame_name in walk}) == \
        [-150, -20, -10, 0, 10, 20, 150]
    visits = {frame_name.visit_kind for frame_name in parsed
              if frame_name.kind == frame_names.REPEATABILITY}
    assert visits == {'start', 'still', 'triax', 'gratings'}


def test_every_run_file_logs_the_slit_width_before_its_first_frame():
    for lines in (run_files.edge_walk_lines([800], CHIP_PLACEMENT, lambda centre:
                                            run_files.GratingPair(-1.0)),
                  run_files.axis_reference_lines([800], CHIP_PLACEMENT)):
        assert lines.index('ren') < lines.index('acquire')


# ---------------------------------------------------------------------------- one frame

def test_edge_fit_finds_the_simulated_edge_on_the_frame_axis():
    bench = SimulatedStage1Bench(**SMALL_BENCH)
    axis = frame_axis_nm(768.0)
    triax_steps = 98304
    image = bench.image(5, axis, triax_steps, image_height=IMAGE_HEIGHT)
    closed = bench.image(-150, axis, triax_steps, image_height=IMAGE_HEIGHT)
    result = analyse_edge_frame(image, axis, closed)
    expected_on_axis = bench.true_edge_nm(5) + bench.axis_error_nm(triax_steps)
    assert result.band_found
    assert result.edge.edge_nm == pytest.approx(expected_on_axis, abs=0.02)
    assert result.edge.width_nm == pytest.approx(bench.edge_width_nm, abs=0.1)
    assert result.band_row_at_centre == pytest.approx(bench.band_row, abs=3)


def test_axis_reference_measures_the_axis_error():
    bench = SimulatedStage1Bench(lamp=ARGON_MERCURY, **SMALL_BENCH)
    axis = frame_axis_nm(768.0)
    reference = measure_axis_reference(bench.image(0, axis, 98304, image_height=IMAGE_HEIGHT),
                                       axis, band_row=120.0)
    assert reference.correction_nm == pytest.approx(-bench.axis_error_nm(98304), abs=0.01)
    assert len(reference.lines_used) >= 5 and reference.spread_nm < 0.01


def test_axis_reference_does_not_take_a_brighter_neighbour_for_a_line():
    """800.616 and 801.479 nm are 0.86 nm apart: with the axis 0.9 nm off, the brightest pixel
    near where 800.616 should be is 801.479's. The two-pass search must still pair them right."""
    bench = SimulatedStage1Bench(lamp=ARGON_MERCURY, axis_error_nm=lambda steps: 0.9,
                                 **SMALL_BENCH)
    axis = frame_axis_nm(768.0)
    reference = measure_axis_reference(bench.image(0, axis, 0, image_height=IMAGE_HEIGHT), axis,
                                       band_row=120.0)
    assert reference.correction_nm == pytest.approx(-0.9, abs=0.01)
    assert reference.spread_nm < 0.01


# ---------------------------------------------------------------------------- session

def test_session_takes_the_newest_frames_when_older_ones_share_a_name(workspace):
    bench = SimulatedStage1Bench(**SMALL_BENCH)
    logs = play_session(workspace, bench, centres=(800,), with_axis_references=False,
                        with_steps=False, with_repeatability=False)
    old_folder = os.path.join(workspace['data'], 's1edge_t800_g1p000')
    shutil.copy(os.path.join(old_folder, 's1edge_t800_g1p000_000000.npz'),
                os.path.join(old_folder, 's1edge_t800_g1p000_000001.npz'))
    found = read_session(logs, workspace['data'])
    record = next(record for record in found.records if record.name == 's1edge_t800_g1p000')
    assert record.frame_path.endswith('_000001.npz')
    assert found.older_frames_present == ['s1edge_t800_g1p000']
    assert record.slit_width_um == 500 and record.triax_steps is not None
    assert record.g1_count is not None


# ---------------------------------------------------------------------------- the analysis

def test_simulated_session_recovers_the_true_calibration(workspace):
    bench = SimulatedStage1Bench(**SMALL_BENCH)
    session_analysis = analyse(workspace, play_session(workspace, bench))
    fit = session_analysis.calibration
    for count in fit.x_values:
        assert fit(count) == pytest.approx(bench.true_edge_nm(count), abs=0.03)
    assert fit.residual_rms < 0.02
    proposed = session_analysis.proposed
    for wavelength in (770, 800, 830):
        count = np.polyval(proposed.wl_to_g1, wavelength)
        assert bench.true_edge_nm(count) == pytest.approx(wavelength, abs=0.05)
    for summary in session_analysis.centres:
        assert summary.slope_nm_per_step == pytest.approx(
            np.polyval(np.polyder(bench.true_g1_to_edge_nm), summary.master_count), abs=0.005)
        assert abs(summary.band_rows_per_g1_step) < 0.1
    assert abs(session_analysis.single_steps.offset_from_walk_nm) < 0.03
    assert session_analysis.repeatability.spread_nm('triax') < 0.03
    assert FAIL not in verdicts(run_edge_checks(session_analysis)).values()


def test_without_axis_references_the_edges_are_off_by_the_axis_error_and_it_warns(workspace):
    bench = SimulatedStage1Bench(axis_error_nm=lambda steps: 0.4, **SMALL_BENCH)
    session_analysis = analyse(workspace, play_session(workspace, bench,
                                                       with_axis_references=False))
    fit = session_analysis.calibration
    assert np.mean([fit(count) - bench.true_edge_nm(count) for count in fit.x_values]) == \
        pytest.approx(0.4, abs=0.03)
    assert verdicts(run_edge_checks(session_analysis))['axis references'] == WARN


def test_an_edge_that_does_not_move_with_g1_fails(workspace):
    """The intermediate slit left in: the edge on the CCD is that slit's, fixed (2026-11-17)."""
    bench = SimulatedStage1Bench(true_g1_to_edge_nm=(0.0, -0.01, 803.0), **SMALL_BENCH)
    session_analysis = analyse(workspace, play_session(workspace, bench, centres=(800,),
                                                       with_steps=False,
                                                       with_repeatability=False))
    assert verdicts(run_edge_checks(session_analysis))['edge moves with g1'] == FAIL


def test_a_grating_that_does_not_return_shows_in_the_repeatability_gate(workspace):
    """The edge jumps 0.5 nm after the gratings' second excursion: only 'gratings' spreads."""
    bench = SimulatedStage1Bench(**SMALL_BENCH)
    logs = play_session(workspace, bench, centres=(760, 800, 840), with_axis_references=False,
                        with_steps=False, with_repeatability=False)
    master = load_master()
    player = RunFilePlayer(bench, workspace['data'], workspace['logs'], master)
    lines = run_files.repeatability_lines(800, CHIP_PLACEMENT, cycles=2)
    jump_at = max(index for index, line in enumerate(lines) if line == 'sg 920')
    original = bench.true_g1_to_edge_nm
    logs.append(player.play(lines[:jump_at], 'repeatability_a.txt'))
    bench.true_g1_to_edge_nm = (original[0], original[1], original[2] + 0.5)
    logs.append(player.play(lines[jump_at:], 'repeatability_b.txt'))
    session_analysis = analyse(workspace, logs)
    repeatability = session_analysis.repeatability
    assert repeatability.spread_nm('gratings') == pytest.approx(0.5, abs=0.05)
    assert repeatability.spread_nm('triax') < 0.03
    assert verdicts(run_edge_checks(session_analysis))['repeatability'] == WARN


# ---------------------------------------------------------------------------- command line

def test_fit_command_writes_a_report_and_applies_only_when_asked(workspace):
    bench = SimulatedStage1Bench(**SMALL_BENCH)
    logs = play_session(workspace, bench)
    master_copy = os.path.join(workspace['calibration'], 'master.json')
    shutil.copy(MASTER_PATH, master_copy)
    common = logs + ['--data-directory', workspace['data'], '--master', master_copy,
                     '--report-directory', workspace['reports'],
                     '--backup-directory', os.path.join(workspace['calibration'], 'backup')]

    assert filter_calibration_main(['fit'] + common) == 0
    with open(master_copy) as master_file:
        assert json.load(master_file) == load_master(), "nothing written without --apply"
    report_directory = os.path.join(workspace['reports'], os.listdir(workspace['reports'])[0])
    assert {'report.txt', 'results.json', 'g1_calibration.png', 'edge_fits.png',
            'steps_and_repeatability.png', 'widths_and_band.png'} <= \
        set(os.listdir(report_directory))
    with open(os.path.join(report_directory, 'results.json')) as results_file:
        results = json.load(results_file)
    assert len(results['provenance']['frames']) == len(results['frames'])
    assert all(len(digest) == 64 for digest in results['provenance']['frames'].values())
    assert results['provenance']['software']['commit']

    shutil.rmtree(workspace['reports'])
    os.makedirs(workspace['reports'])
    assert filter_calibration_main(['fit'] + common + ['--apply', '--no-plots']) == 0
    with open(master_copy) as master_file:
        applied = json.load(master_file)
    report_directory = os.path.join(workspace['reports'], os.listdir(workspace['reports'])[0])
    with open(os.path.join(report_directory, 'results.json')) as results_file:
        rerun = json.load(results_file)
    assert rerun['calibration_fit']['coefficients'] == results['calibration_fit']['coefficients'], \
        "the same files give the same fit"
    assert applied['manual_g1']['wl_to_g1'] == rerun['proposed_master_entries']['wl_to_g1']
    assert applied['manual_g2']['wl_to_g2'] == rerun['proposed_master_entries']['wl_to_g2']
    assert applied['wavelength_axis'] == load_master()['wavelength_axis']
    assert len(os.listdir(os.path.join(workspace['calibration'], 'backup'))) == 1
    with open(os.path.join(workspace['calibration'],
                           'stage1_edge_calibration_history.json')) as history_file:
        history = json.load(history_file)
    assert len(history) == 1 and history[0]['report_directory'] == report_directory


def test_apply_is_refused_when_a_gate_fails(workspace):
    bench = SimulatedStage1Bench(true_g1_to_edge_nm=(0.0, -0.01, 803.0), **SMALL_BENCH)
    logs = play_session(workspace, bench, centres=(800,), with_steps=False,
                        with_repeatability=False)
    master_copy = os.path.join(workspace['calibration'], 'master.json')
    shutil.copy(MASTER_PATH, master_copy)
    filter_calibration_main(['fit'] + logs + [
        '--data-directory', workspace['data'], '--master', master_copy, '--report-directory',
        workspace['reports'], '--backup-directory', os.path.join(workspace['calibration'], 'b'),
        '--apply', '--no-plots'])
    with open(master_copy) as master_file:
        assert json.load(master_file) == load_master()
    assert not os.path.exists(os.path.join(workspace['calibration'], 'b'))


def test_fit_command_expands_wildcards_itself(workspace):
    """The Windows command prompt passes 'stage1_*.txt' through unexpanded."""
    from filter_calibration.__main__ import expand_run_log_arguments
    for name in ('stage1_edge_walk_20261201_1.txt', 'stage1_axis_references_20261201_2.txt',
                 'stage1_edge_walk_20261130_1.txt'):
        open(os.path.join(workspace['logs'], name), 'w').close()
    pattern = os.path.join(workspace['logs'], 'stage1_*_20261201_*.txt')
    assert [os.path.basename(path) for path in expand_run_log_arguments([pattern])] == \
        ['stage1_axis_references_20261201_2.txt', 'stage1_edge_walk_20261201_1.txt']


def test_plan_command_writes_the_four_run_files(workspace):
    assert filter_calibration_main(['plan', '--output-directory', workspace['logs'],
                                    '--exposure', '15', '--axis-exposure', '15']) == 0
    assert sorted(os.listdir(workspace['logs'])) == sorted(run_files.RUN_FILE_NAMES.values())
