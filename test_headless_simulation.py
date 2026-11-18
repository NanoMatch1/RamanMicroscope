"""
Headless full-workflow test for the Raman microscope control software.

This is the "form 2" test described in the project testing philosophy: it
drives the whole application in simulate mode exactly as a user would from
the CLI — through `Interface._command_handler` — and asserts on outcomes.
It complements `test_controller_simulated.py`, which unit-tests the
simulated Arduino protocol in isolation.

No hardware, no GUI, and no stdin are required. stdin is deliberately
replaced with an empty stream, so any code path that tries to prompt the
operator raises EOFError immediately instead of hanging forever. That is a
feature: an interactive prompt reached during automated startup is a bug,
and this test is designed to surface it loudly.

Run it either way:

    python test_headless_simulation.py        # standalone, no pytest needed
    python -m pytest test_headless_simulation.py -q

Note: acquisition tests write .npz frames into `data/` using the filename
prefix `headless_test`, so their output is easy to identify and delete.
"""

import io
import os
import sys
import atexit
import json
import shutil
import contextlib
import time

import numpy as np

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)

# Any prompt reached during an automated run should fail fast, not block.
sys.stdin = io.StringIO()

from interface_run_me import Interface
from pixisspec.pixis_hardware import RealHardware
from pixisspec.simulated_picam_device import SimulatedPicamDevice


# ----------------------------------------------------------------------------
# Shared interface
# ----------------------------------------------------------------------------
# PIXISCamera enforces a singleton guard, so exactly one Interface may exist
# per process. It is built once, lazily, and shared by every test.

_interface = None


def _preserve_laser_step_position(interface):
    """
    Snapshot the persisted piezomotor position and restore it on exit.

    tiger_step_position.json is the only record of where the Tiger's
    piezomotor physically is, and TigerLaser rewrites it after every move.
    These tests move the laser, so without this the file would be left
    holding a simulated position. That matters because the file is
    currently tracked in git: committing a test-mutated value would tell
    the lab machine the laser sits at a wavelength it is not actually at,
    and the next relative move would be wrong.
    """
    path = interface.laser._step_state_path
    if not os.path.exists(path):
        return

    backup = path + '.testbackup'
    shutil.copyfile(path, backup)

    def restore():
        try:
            shutil.move(backup, path)
        except Exception:
            pass

    atexit.register(restore)


def get_interface():
    """Build (once) and return the simulate-mode Interface under test."""
    global _interface
    if _interface is None:
        with contextlib.redirect_stdout(io.StringIO()):
            _interface = Interface(
                simulate=True, com_port='COM10', debug_skip=[]
            )
        _preserve_laser_step_position(_interface)
    return _interface


def run_command(command):
    """
    Send one command through the real CLI command handler, exactly as
    Interface.cli() does, with the chatty logging suppressed.

    Raises AssertionError if the handler reports an error, so that a
    swallowed exception surfaces as a test failure rather than passing
    silently — the handler catches everything and returns an error string.
    """
    with contextlib.redirect_stdout(io.StringIO()):
        result = get_interface()._command_handler(command)

    text = str(result)
    assert 'Error' not in text and 'Traceback' not in text, (
        f"command {command!r} reported an error:\n{text}"
    )
    return result


# ----------------------------------------------------------------------------
# Startup and command registry
# ----------------------------------------------------------------------------

def test_startup_completes_without_prompting():
    """
    The whole instrument stack must initialise headlessly.

    stdin is an empty stream, so if any initialise() path prompts the
    operator this raises EOFError instead of hanging.
    """
    interface = get_interface()
    assert interface.simulate is True
    assert interface.microscope is not None
    assert interface.microscope.microscope_mode in ('ramanmode', 'imagemode')


def test_command_registry_is_populated():
    """
    Every instrument's @ui_callable methods should be flattened into one
    command map. This is the registry contract that lets the CLI and GUI
    dispatch by name.
    """
    command_map = get_interface().command_map

    # A representative command from each hardware module must be present.
    for command in ['gotowavelength', 'wavelength', 'laserhome',   # laser
                    'rg', 'ren', 'mg',                             # spectrometer
                    'acquire', 'acqtime', 'caminfo',               # camera
                    'report', 'wai', 'ramanshift']:                # microscope
        assert command in command_map, f"{command!r} missing from command map"


def test_integrity_checker_agrees_with_registry():
    """
    Instrument._integrity_checker() asserts @ui_callable methods and
    command_functions entries are in exact correspondence. It runs during
    construction, so reaching this point means it passed for every
    instrument; re-run it explicitly to guard against later mutation.
    """
    interface = get_interface()
    for instrument in [interface.laser, interface.spectrometer,
                       interface.microscope]:
        with contextlib.redirect_stdout(io.StringIO()):
            instrument._integrity_checker()


def test_command_reference_is_up_to_date():
    """docs/command_reference.md is generated from the command docstrings. A changed docstring
    or command without regenerating the file fails here."""
    sys.path.insert(0, os.path.join(REPO_DIR, 'tools'))  # tools/ is not a package
    import build_command_reference
    generated = build_command_reference.reference_for_interface(get_interface(), 'this test')
    with open(build_command_reference.COMMAND_REFERENCE_PATH) as file:
        committed = file.read()
    assert (build_command_reference.without_build_stamp(committed)
            == build_command_reference.without_build_stamp(generated)), (
        "docs/command_reference.md is out of date: run "
        "'PYTHONPATH=. python tools/build_command_reference.py' and commit the result")


def test_command_reference_shows_which_of_two_same_named_commands_runs():
    """The generator flags a name registered twice, says which method runs, marks the other as
    unreachable, and lists commands without a docstring."""
    sys.path.insert(0, os.path.join(REPO_DIR, 'tools'))  # tools/ is not a package
    import build_command_reference as reference

    def set_wavelength(wavelength):
        """Set every grating to a wavelength."""

    def relative_move(steps):
        """Move the grating by a number of steps."""

    def undocumented():
        pass

    sources = reference.CommandSources(
        registrations=[reference.CommandRegistration('Microscope', 'sg', set_wavelength),
                       reference.CommandRegistration('TRIAX', 'sg', relative_move),
                       reference.CommandRegistration('TRIAX', 'mg', relative_move),
                       reference.CommandRegistration('TRIAX', 'nodoc', undocumented)],
        dispatched={'sg': set_wavelength, 'mg': relative_move, 'nodoc': undocumented},
        motor_groups={}, subsystems=[('Gratings', 'How the gratings move.')])
    markdown = reference.command_reference_markdown(sources, 'a test')
    assert '### `sg`, `mg`' in markdown, "aliases of one method are listed together"
    assert '**Not reachable as `sg`**' in markdown
    clash_row = next(line for line in markdown.split('\n') if line.startswith('| `sg`'))
    assert clash_row.endswith('`test_command_reference_shows_which_of_two_same_named_commands_runs.'
                              '<locals>.set_wavelength` |')
    assert markdown.rstrip().endswith('`nodoc`')
    assert '## How it works: Gratings' in markdown


def test_help_is_an_application_command():
    """'help' goes through the command handler like any other command."""
    assert 'help' in get_interface().interface_commands
    assert run_command('help') is None


# ----------------------------------------------------------------------------
# Tiger laser
# ----------------------------------------------------------------------------

def test_laser_wavelength_round_trip():
    """Commanding a wavelength should land within one calibration step."""
    run_command('gotowavelength 800')
    reported = run_command('wavelength')
    assert abs(float(reported) - 800.0) < 0.5, (
        f"laser reported {reported} nm after commanding 800 nm"
    )


def test_laser_rejects_out_of_range_wavelength():
    """
    The Tiger calibration covers 765.546-840.035 nm. Anything outside must
    be refused rather than silently clamped, since clamping would move the
    laser somewhere the operator did not ask for.
    """
    assert run_command('gotowavelength 700') is False
    assert run_command('gotowavelength 900') is False


def test_laser_relative_steps_are_symmetric():
    """A step up followed by an equal step down returns to the start."""
    laser = get_interface().laser
    start = laser.step_offset

    run_command('stepup 100')
    assert laser.step_offset == start + 100

    run_command('stepdown 100')
    assert laser.step_offset == start


def test_laser_home_resets_to_calibrated_home():
    """
    Homing drives the motor past the hard stop but must reset the logical
    position to exactly STEP_MAX, otherwise the calibration is offset by
    the overshoot.
    """
    interface = get_interface()
    _, step_max = interface.laser.calibration.get_step_range()

    run_command('laserhome')
    assert interface.laser.step_offset == step_max

    homed_wavelength = float(run_command('wavelength'))
    assert abs(homed_wavelength - 765.546) < 0.01


def test_laser_step_position_persists_to_disk():
    """
    Step position is the only record of where the piezomotor is, so it must
    survive a restart. Verify the on-disk file tracks the in-memory value.
    """
    import json

    interface = get_interface()
    run_command('gotowavelength 790')

    with open(interface.laser._step_state_path, 'r') as handle:
        saved = json.load(handle)

    assert int(saved['step_offset']) == interface.laser.step_offset


# ----------------------------------------------------------------------------
# TRIAX spectrometer
# ----------------------------------------------------------------------------

def test_spectrometer_reports_position():
    """
    Regression guard: the simulate path used to call query(), a pyvisa API
    left behind by the GPIB implementation, which does not exist on
    SimulatedTriaxSerial and raised AttributeError on every read.
    """
    position = run_command('rg')
    assert isinstance(position, int)
    assert position > 0


def test_spectrometer_relative_move_changes_position():
    """'mg' issues a relative TRIAX grating move; position must track it."""
    before = run_command('rg')
    run_command('mg 500')
    after = run_command('rg')
    assert after == before + 500


def test_sg_sets_the_grating_wavelength_not_a_triax_move():
    """'sg' sets every tunable-filter grating to a wavelength. The TRIAX once registered 'sg' as a
    relative move too, and the registry gave it the name, so 'sg 800' moved the TRIAX 800 steps."""
    interface = get_interface()
    assert interface.command_map['sg'][1] == interface.microscope.go_to_grating_wavelength
    triax_steps_before = run_command('rg')
    run_command('sg 800')
    assert run_command('rg') == triax_steps_before


def test_spectrometer_always_arrives_at_a_position_from_below():
    """The calibration measured every TRIAX position going up, so a move down must overshoot
    by APPROACH_STEPS and come back up; a move up goes straight there."""
    spectrometer = get_interface().spectrometer
    simulated_serial = spectrometer.spectrometer
    grating_moves = []
    original_write = simulated_serial.write

    def recording_write(command):
        if command.startswith('F0,'):
            grating_moves.append(int(command.split(',')[1]))
        original_write(command)

    simulated_serial.write = recording_write
    try:
        start = run_command('rg')
        with contextlib.redirect_stdout(io.StringIO()):
            assert spectrometer.go_to_steps(start - 5000) == 'S0'
        assert grating_moves == [-5000 - spectrometer.APPROACH_STEPS, spectrometer.APPROACH_STEPS]
        assert run_command('rg') == start - 5000
        grating_moves.clear()
        with contextlib.redirect_stdout(io.StringIO()):
            assert spectrometer.go_to_steps(start) == 'S0'
        assert grating_moves == [5000]
        assert run_command('rg') == start
    finally:
        simulated_serial.write = original_write


def test_spectrometer_slit_is_readable():
    """Entrance slit width should read back as an integer."""
    assert isinstance(run_command('ren'), int)


# ----------------------------------------------------------------------------
# PIXIS camera
# ----------------------------------------------------------------------------

def test_camera_frame_matches_pixis_sensor_width():
    """
    Regression guard for the Tucsen -> PIXIS swap: the sensor is 1024 px
    wide, not the 2048 the Tucsen provided. A mismatch here means the
    wavelength axis and the frame would disagree.
    """
    with contextlib.redirect_stdout(io.StringIO()):
        frame = get_interface().camera.grab_frame()

    assert frame is not None, "simulated camera returned no frame"
    assert np.shape(frame)[1] == 1024, f"unexpected frame shape {np.shape(frame)}"


def test_wavelength_axis_matches_frame_width():
    """The wavelength axis must be one entry per detector column."""
    interface = get_interface()
    run_command('wavelengthaxis')
    assert len(interface.microscope.wavelength_axis) == 1024


def test_camera_exposure_time_is_in_seconds():
    """
    acquisition_time is in SECONDS throughout the codebase; the camera
    layer converts to milliseconds internally. Guards the 1000x overrun
    that the old millisecond default caused.
    """
    interface = get_interface()
    run_command('acqtime 0.5')
    assert abs(interface.camera.acqtime - 0.5) < 1e-9
    assert abs(
        interface.acq_ctrl.general_parameters['acquisition_time'] - 0.5
    ) < 1e-9


def test_camera_reports_temperature_and_info():
    """
    Regression guard: camera_info() called a method name that no camera
    class actually implemented, so 'caminfo' raised AttributeError.
    """
    temperature = run_command('temp')
    assert isinstance(temperature, float)

    info = run_command('caminfo')
    assert isinstance(info, dict) and info, "caminfo returned no data"


def test_single_frame_acquisition_completes():
    """Acquire one frame end to end through the acquisition control layer."""
    run_command('filename headless_test')
    run_command('nframe 1')
    run_command('acqtime 0.1')
    run_command('acquire')


def test_simulate_mode_runs_the_real_camera_driver():
    """Simulate mode runs RealHardware itself, on a simulated Picam device, not a stand-in."""
    camera = get_interface().camera
    assert isinstance(camera.hardware, RealHardware)
    assert isinstance(camera.hardware._cam, SimulatedPicamDevice)


def test_run_gives_live_frames_and_acquire_stops_it():
    """`run` streams frames for live viewing; an acquisition stops it, then takes its own frame."""
    interface = get_interface()
    camera = interface.camera
    live_frames = []
    record_live_frame = lambda image_data, wavelengths: live_frames.append(image_data)
    original_callback = camera.save_transient_spectrum_cb
    camera.save_transient_spectrum_cb = record_live_frame
    try:
        run_command('nframe 1')
        run_command('acqtime 0.1')
        run_command('run')
        deadline = time.monotonic() + 5
        while len(live_frames) < 3 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert len(live_frames) >= 3, "run produced no live frames"
        assert camera.is_running and camera.hardware._stream_open

        with contextlib.redirect_stdout(io.StringIO()):
            frame = camera.grab_frame()
        assert frame is not None
        assert not camera.is_running and not camera.hardware._stream_open
        assert camera.acquisition_thread is None
    finally:
        run_command('stop')
        camera.save_transient_spectrum_cb = original_callback


# ----------------------------------------------------------------------------
# Microscope orchestration
# ----------------------------------------------------------------------------

def test_report_status_runs_with_recalculation():
    """
    Regression guard: report_status() wrapped its motor dict in a set
    literal before passing it on, raising 'unhashable type: dict' on every
    call that recalculated state.
    """
    run_command('report')


def test_stage_moves_update_reported_position():
    """Relative stage moves must be reflected in the reported position."""
    microscope = get_interface().microscope
    before = dict(microscope.stage_positions_microns)

    run_command('x 10')

    after = microscope.stage_positions_microns
    assert after['x'] != before['x'], "x stage position did not change"


def test_where_am_i_reports_without_error():
    """The status summary must survive an empty laser action group."""
    run_command('wai')


def test_laser_action_group_is_empty_but_safe():
    """
    The Tiger has no Arduino-driven axes, so its action group is empty by
    design. Position queries must return an empty dict rather than raising
    or issuing a malformed controller command.
    """
    interface = get_interface()
    assert interface.microscope.action_groups['laser_wavelength'] == {}
    assert run_command('laserpos') == {}


# ----------------------------------------------------------------------------
# Wavelength axis calibration (TRIAX + PIXIS line walk)
# ----------------------------------------------------------------------------

def _largest_difference_from_simulated_truth_nm(model, triax_steps_values):
    from wavelength_calibration.simulated_line_lamp import default_true_model
    from wavelength_calibration.wavelength_axis_model import largest_axis_difference_nm
    return largest_axis_difference_nm(model, default_true_model(), triax_steps_values)


def test_wavelength_axis_line_walk_recovers_simulated_truth():
    """
    The full operator workflow: 'speccal arhg', 'speccalfit curvature', 'speccalapply curvature'.

    In simulate mode the camera images a mercury lamp whose true calibration
    lives in the simulator and starts ~2 nm away from the shipped one. The
    procedure must find the truth, and applying it must change the live
    wavelength axis. The master file is a temporary copy, restored after.
    """
    import tempfile
    from wavelength_calibration.wavelength_axis_model import WavelengthAxisModel

    microscope = get_interface().microscope
    original_master_path = microscope.master_calibration_path
    original_backup_directory = microscope.calibration_backup_directory
    original_report_directory = microscope.calibration_fit_report_directory
    original_model_dict = microscope.calibration_service.wavelength_axis_model.to_dict()

    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary_master_path = os.path.join(temporary_directory, 'master.json')
        shutil.copyfile(original_master_path, temporary_master_path)
        microscope.master_calibration_path = temporary_master_path
        microscope.calibration_backup_directory = os.path.join(temporary_directory, 'backup')
        microscope.calibration_fit_report_directory = os.path.join(temporary_directory, 'reports')
        original_line_walk_directory = microscope.line_walk_directory
        microscope.line_walk_directory = os.path.join(temporary_directory, 'walks')
        try:
            run_command('speccalreset')
            line_walk_path = run_command('speccal arhg')
            assert os.path.exists(line_walk_path)

            fit = run_command('speccalfit curvature')
            measured_triax_steps = sorted({o.triax_steps for o in fit.observations})
            assert len(fit.observations) >= 20
            assert _largest_difference_from_simulated_truth_nm(fit.model, measured_triax_steps) < 0.03

            starting_error_nm = _largest_difference_from_simulated_truth_nm(
                WavelengthAxisModel.from_dict(original_model_dict), measured_triax_steps)
            assert starting_error_nm > 1.0
            report_names = sorted(os.listdir(microscope.calibration_fit_report_directory))
            assert len(report_names) == 2, "speccalfit saves a report and, by default, its plot"
            assert run_command('speccalfit nonsense') is None, "an unknown option must refuse, not fit"

            run_command('speccalapply curvature')
            applied_model = microscope.calibration_service.wavelength_axis_model
            assert _largest_difference_from_simulated_truth_nm(applied_model, measured_triax_steps) < 0.03
            with open(temporary_master_path) as file:
                stored_metadata = json.load(file)['wavelength_axis']['metadata']
            assert stored_metadata['verified_against_external_reference']
            with open(os.path.join(microscope.calibration_fit_report_directory,
                                   stored_metadata['fit_report'])) as file:
                assert 'status: APPLIED' in file.read()
            assert os.listdir(microscope.calibration_backup_directory)

            run_command('wavelengthaxis')
            steps = microscope.spectrometer_position
            assert microscope.wavelength_axis[50] == applied_model.triax_wavelength(steps)
        finally:
            microscope.master_calibration_path = original_master_path
            microscope.calibration_backup_directory = original_backup_directory
            microscope.calibration_fit_report_directory = original_report_directory
            microscope.line_walk_directory = original_line_walk_directory
            microscope.calibration_service._load_wavelength_axis_model(original_model_dict)
            microscope.generate_wavelength_axis()
            run_command('speccalreset')
            if 'line_walk_path' in locals() and os.path.exists(line_walk_path):
                os.remove(line_walk_path)


def test_spectrometer_wavelength_lands_on_target_pixel():
    """'st' must put the requested wavelength on spectrometer_target_pixel, within one TRIAX step."""
    microscope = get_interface().microscope
    target_pixel = microscope.config['spectrometer_target_pixel']
    run_command('st 800')
    nm_per_triax_step = microscope.calibration_service.wavelength_axis_model.triax_to_wavelength_coefficients[0]
    assert abs(microscope.wavelength_axis[target_pixel] - 800.0) <= nm_per_triax_step


@contextlib.contextmanager
def temporary_calibration_files(microscope):
    """Master file, backups, reports and walks in a temporary directory; model in use restored."""
    import tempfile
    redirected = ('master_calibration_path', 'calibration_backup_directory',
                  'calibration_fit_report_directory', 'line_walk_directory')
    saved = {name: getattr(microscope, name) for name in redirected}
    original_model_dict = microscope.calibration_service.wavelength_axis_model.to_dict()
    with tempfile.TemporaryDirectory() as temporary_directory:
        microscope.master_calibration_path = os.path.join(temporary_directory, 'master.json')
        shutil.copyfile(saved['master_calibration_path'], microscope.master_calibration_path)
        microscope.calibration_backup_directory = os.path.join(temporary_directory, 'backup')
        microscope.calibration_fit_report_directory = os.path.join(temporary_directory, 'reports')
        microscope.line_walk_directory = os.path.join(temporary_directory, 'walks')
        try:
            run_command('speccalreset')
            yield temporary_directory
        finally:
            for name, value in saved.items():
                setattr(microscope, name, value)
            microscope.calibration_service._load_wavelength_axis_model(original_model_dict)
            microscope.generate_wavelength_axis()
            run_command('speccalreset')


def test_speccalzero_restores_the_axis_after_lost_steps():
    """
    Calibrate, then the TRIAX counter slips by 120 steps (simulated lost steps). 'speccalzero check'
    measures the shift without changing anything; 'speccalzero' stores it, and the axis matches the
    lamp again.
    """
    microscope = get_interface().microscope
    with temporary_calibration_files(microscope):
        run_command('speccal arhg')
        assert run_command('speccalapply curvature triaxquadratic') is not None
        calibrated = microscope.calibration_service.wavelength_axis_model
        assert calibrated.metadata['triax_position_offsets_nm'], "applied model has the TRIAX table"
        lamp = microscope.simulated_line_lamp
        lamp.triax_counter_error_steps = 120
        try:
            measurement = run_command('speccalzero check')
            assert abs(measurement.step_offset - 120) <= 2
            assert microscope.calibration_service.wavelength_axis_model.triax_step_offset == \
                calibrated.triax_step_offset, "check must not change the calibration"
            run_command('speccalzero')
            rezeroed = microscope.calibration_service.wavelength_axis_model
            assert abs(rezeroed.triax_step_offset - (calibrated.triax_step_offset + 120)) <= 2
            for steps in (95_000, 110_000):
                true_wavelength = lamp.true_model.wavelength_at(512, steps + 120)
                assert abs(rezeroed.wavelength_at(512, steps) - true_wavelength) < 0.03
            reports = os.listdir(microscope.calibration_fit_report_directory)
            assert sum(name.startswith('triax_zero_') for name in reports) == 2
        finally:
            lamp.triax_counter_error_steps = 0


def test_speccal_samples_and_speccalfit_plot():
    """'speccal arhg samples=N' sets the walk density; 'speccalfit' saves a PNG beside the report
    unless 'noplots' is given; a bad samples value refuses instead of walking."""
    microscope = get_interface().microscope
    with temporary_calibration_files(microscope):
        assert run_command('speccal arhg samples=1') is None
        assert run_command('speccal arhg samples=many') is None
        line_walk_path = run_command('speccal arhg samples=4')
        with open(line_walk_path) as file:
            assert '4 samples per line' in json.load(file)['description']
        assert run_command('speccalfit curvature triaxquadratic') is not None
        report_files = sorted(os.listdir(microscope.calibration_fit_report_directory))
        assert len(report_files) == 2, report_files
        report_name, plot_name = sorted(report_files, key=lambda name: name.endswith('.png'))
        assert plot_name == os.path.splitext(report_name)[0] + '.png'
        assert run_command('speccalfit curvature triaxquadratic noplots') is not None
        report_files_after = os.listdir(microscope.calibration_fit_report_directory)
        assert sum(name.endswith('.png') for name in report_files_after) == 1, report_files_after
        assert sum(name.endswith('.txt') for name in report_files_after) == 2, report_files_after


def test_speccal_repeat_walks_the_same_positions_and_the_report_tabulates_each_walk():
    """'speccal arhg repeat=2' runs two walks planned from one calibration, so they visit the same
    TRIAX steps; 'speccalfit' tabulates each walk's offset at each position. A bad repeat value
    refuses instead of walking."""
    microscope = get_interface().microscope
    with temporary_calibration_files(microscope):
        assert run_command('speccal arhg repeat=0') is None
        assert run_command('speccal arhg repeat=twice') is None
        line_walk_paths = run_command('speccal arhg samples=3 repeat=2')
        assert len(line_walk_paths) == 2 and len(set(line_walk_paths)) == 2
        requested_steps_by_walk, descriptions = [], []
        for line_walk_path in line_walk_paths:
            with open(line_walk_path) as file:
                walk = json.load(file)
            requested_steps_by_walk.append([record['requested_steps']
                                            for record in walk['position_records']])
            descriptions.append(walk['description'])
        assert requested_steps_by_walk[0] == requested_steps_by_walk[1]
        assert 'walk 1 of 2' in descriptions[0] and 'walk 2 of 2' in descriptions[1]
        assert microscope.line_walk_session_files == line_walk_paths
        assert run_command('speccalfit curvature triaxquadratic noplots') is not None
        report_name, = os.listdir(microscope.calibration_fit_report_directory)
        with open(os.path.join(microscope.calibration_fit_report_directory, report_name)) as file:
            report = file.read()
        table = report.split('TRIAX frame offsets by walk and position')[1].split('\n\n')[0]
        assert 'walk 1' in table and 'walk 2' in table
        for line_walk_path in line_walk_paths:
            assert os.path.basename(line_walk_path) in table


def test_speccal_repeat_keeps_the_walks_saved_before_one_fails():
    """If a walk of 'speccal repeat=N' fails, the walks already saved are kept and returned, and
    the remaining walks are not started."""
    microscope = get_interface().microscope
    original_run_one_line_walk = microscope._run_one_line_walk
    walks_started = []

    def second_walk_fails(*arguments, **keyword_arguments):
        walks_started.append(len(walks_started) + 1)
        if len(walks_started) == 2:
            raise RuntimeError('simulated camera timeout')
        return original_run_one_line_walk(*arguments, **keyword_arguments)

    with temporary_calibration_files(microscope):
        microscope._run_one_line_walk = second_walk_fails
        try:
            line_walk_paths = run_command('speccal arhg samples=3 repeat=3')
        finally:
            del microscope._run_one_line_walk
        assert walks_started == [1, 2]
        assert len(line_walk_paths) == 1 and os.path.exists(line_walk_paths[0])


def test_applied_axis_warns_outside_its_fitted_triax_range():
    """An applied calibration records the TRIAX range it was fitted over and the frame shape the
    camera returned; the application warns when the TRIAX goes beyond that range."""
    microscope = get_interface().microscope
    with temporary_calibration_files(microscope):
        line_walk_path = run_command('speccal arhg samples=4')
        with open(line_walk_path) as file:
            first_frame_conditions = json.load(file)['position_records'][0]['conditions']
        assert first_frame_conditions['frame_shape'][-1] == len(microscope.wavelength_axis)
        assert run_command('speccalapply curvature triaxquadratic') is not None
        model = microscope.calibration_service.wavelength_axis_model
        first_steps, last_steps = model.metadata['calibrated_triax_drive_steps']
        microscope._extrapolation_warned_at = None
        microscope.calculate_spectrometer_wavelength(steps=(first_steps + last_steps) // 2)
        assert microscope._extrapolation_warned_at is None, "no warning inside the range"
        microscope.calculate_spectrometer_wavelength(steps=last_steps + 3000)
        assert microscope._extrapolation_warned_at == last_steps + 3000
        microscope.calculate_spectrometer_wavelength()


@contextlib.contextmanager
def temporary_camera_roi_config(microscope):
    """Config file and data directory in a temporary directory; full-sensor ROI afterwards."""
    import tempfile
    from pixisspec.spectral_roi import SpectralRoi
    saved_config_path, saved_data_directory = microscope.config_path, microscope.dataDir
    with tempfile.TemporaryDirectory() as temporary_directory:
        microscope.config_path = os.path.join(temporary_directory, 'microscope_config.json')
        shutil.copyfile(saved_config_path, microscope.config_path)
        microscope.dataDir = temporary_directory
        os.makedirs(os.path.join(temporary_directory, 'transient_data'))
        try:
            yield temporary_directory
        finally:
            microscope.config_path, microscope.dataDir = saved_config_path, saved_data_directory
            microscope.config.pop('camera_roi', None)
            microscope.camera.set_spectral_roi(SpectralRoi.full_sensor())
            microscope._roi_warned_for = None


def test_camera_roi_automatic_manual_binning_stored_and_recorded():
    """
    'roi auto' finds the simulated slit image (rows ~800) and reads only its rows; 'roi <first>
    <last>' sets rows by hand; 'roi binning onchip' gives one-row frames; the ROI is stored in
    the config and set again at start-up, and every saved file records the camera readout.
    """
    from wavelength_calibration.reference_lines import argon_mercury_lamp_lines
    microscope = get_interface().microscope
    camera = microscope.camera
    with temporary_camera_roi_config(microscope) as temporary_directory:
        run_command('acqtime 0.1')
        run_command('nframe 1')
        assert run_command('roi auto') is None, "no light on the slit: nothing to find"
        microscope._install_simulated_line_lamp(argon_mercury_lamp_lines())
        try:
            automatic = run_command('roi auto')
        finally:
            camera.simulated_scene.override_scene = None
        assert automatic.source == 'automatic'
        assert automatic.first_row < 800 < automatic.last_row and automatic.row_count < 80
        assert camera.grab_frame().shape == (automatic.row_count, 1024)

        manual = run_command('roi 790 810')
        assert (manual.first_row, manual.last_row, manual.source) == (790, 811, 'manual')
        with open(microscope.config_path) as file:
            assert json.load(file)['camera_roi']['first_row'] == 790

        on_chip = run_command('roi binning onchip')
        assert on_chip.binned_on_chip and camera.grab_frame().shape == (1, 1024)
        assert run_command('setbin 0') is None, "zero rows per bin must refuse"
        assert run_command('setbin 7').rows_binned_on_chip == 7
        assert run_command('setbin 1').rows_binned_on_chip == 1
        assert run_command('setgain medium') is True

        run_command('roi full')
        assert camera.spectral_roi.row_count == 1024
        microscope.config['camera_roi'] = manual.as_dict()
        assert microscope.apply_stored_camera_roi() == manual, "start-up sets the stored ROI"

        run_command('filename headless_roi_test')
        run_command('acquire')
        [saved_name] = os.listdir(os.path.join(temporary_directory, 'headless_roi_test'))
        with np.load(os.path.join(temporary_directory, 'headless_roi_test', saved_name)) as saved:
            metadata = json.loads(str(saved['metadata']))
            assert saved['image'].shape == (21, 1024)
        readout = metadata['camera']
        assert readout['spectral_roi']['first_row'] == 790
        assert readout['camera_roi_hstart_hend_vstart_vend_hbin_vbin'] == [0, 1024, 790, 811, 1, 1]
        assert readout['adc_analog_gain'] == 'Medium'


def test_line_walk_moves_an_roi_that_misses_the_slit_image():
    """A lamp walk checks the slit image first: an ROI that misses it is replaced by an
    automatic one, and the walk records where the slit image was."""
    microscope = get_interface().microscope
    with temporary_camera_roi_config(microscope), temporary_calibration_files(microscope):
        run_command('roi 100 120')
        line_walk_path = run_command('speccal arhg samples=3')
        roi_used = microscope.camera.spectral_roi
        assert roi_used.source == 'automatic' and roi_used.first_row < 800 < roi_used.last_row
        with open(line_walk_path) as file:
            slit_image = json.load(file)['instrument']['slit_image']
        assert abs(slit_image['peak_row'] - 800) <= 2


def test_data_without_a_manual_roi_is_flagged_once():
    microscope = get_interface().microscope
    with temporary_camera_roi_config(microscope):
        run_command('filename headless_roi_test')
        run_command('acqtime 0.1')
        run_command('acquire')
        assert microscope._roi_warned_for == microscope.camera.spectral_roi
        run_command('roi 790 810')
        microscope._roi_warned_for = None
        run_command('acquire')
        assert microscope._roi_warned_for is None, "a manual ROI raises no warning"


def test_speccalapply_refuses_when_a_gate_fails():
    """A walk recorded in simulate mode must not become a real calibration: refuse, and say why."""
    microscope = get_interface().microscope
    with temporary_calibration_files(microscope):
        run_command('speccal arhg')
        with open(microscope.master_calibration_path) as file:
            master_before = file.read()
        microscope.simulate = False  # as if a real session had picked up a simulated walk
        try:
            assert run_command('speccalapply curvature triaxquadratic noplots') is None
        finally:
            microscope.simulate = True
        with open(microscope.master_calibration_path) as file:
            assert file.read() == master_before, "the master file must not change"
        [report_name] = os.listdir(microscope.calibration_fit_report_directory)
        with open(os.path.join(microscope.calibration_fit_report_directory, report_name)) as file:
            report = file.read()
        assert 'NOT APPLIED: a gate check failed' in report and '[FAIL] walk data' in report
        assert 'SIMULATE mode' in report


def test_wavelength_axis_fit_refuses_without_line_walks():
    """speccalfit with no walks this session reports the problem instead of raising."""
    run_command('speccalreset')
    assert run_command('speccalfit') is None


def test_speccalexport_writes_observed_vs_expected_csv():
    """'speccalexport' after a walk writes a CSV whose observed values track the expected ones."""
    import csv
    import tempfile
    microscope = get_interface().microscope
    original_directory = microscope.calibration_fit_report_directory
    original_line_walk_directory = microscope.line_walk_directory
    with tempfile.TemporaryDirectory() as temporary_directory:
        microscope.calibration_fit_report_directory = temporary_directory
        microscope.line_walk_directory = os.path.join(temporary_directory, 'walks')
        try:
            run_command('speccalreset')
            run_command('speccal arhg')
            export_path = run_command('speccalexport')
            with open(export_path, newline='') as file:
                rows = list(csv.DictReader(file))
        finally:
            microscope.calibration_fit_report_directory = original_directory
            microscope.line_walk_directory = original_line_walk_directory
            run_command('speccalreset')
    assert len(rows) >= 20
    assert {'line_name', 'expected_nm', 'observed_nm', 'error_nm'} <= set(rows[0])
    assert all(abs(float(row['error_nm'])) < 5.0 for row in rows)


def test_external_reference_line_walk_needs_wavelength_and_uncertainty():
    """'speccal external' without numbers must refuse, not walk with a made-up wavelength."""
    assert run_command('speccal external') is None


# ----------------------------------------------------------------------------
# Run files ('runfile')
# ----------------------------------------------------------------------------

import tempfile

import command_file
from filter_calibration import run_files as stage1_run_files
from filter_calibration.analysis import analyse_session
from filter_calibration.calibration_checks import run_edge_checks
from filter_calibration.session import read_session
from filter_calibration.simulated_bench import (ARGON_MERCURY, HALOGEN,
                                                SimulatedStage1Bench)


def _write_run_file(lines):
    """A run file in a temporary directory (lower-case path: typed commands are lower-cased)."""
    directory = tempfile.mkdtemp(prefix='headless_runfile_').lower()
    path = os.path.join(directory, 'test_run.txt')
    with open(path, 'w') as run_file:
        run_file.write('\n'.join(lines) + '\n')
    atexit.register(shutil.rmtree, directory, True)
    return path


def _g1_steps():
    return get_interface().microscope.get_all_motor_positions()['g1']


def _g2_steps():
    return get_interface().microscope.get_all_motor_positions()['g2']


def _remove_run_logs_after_tests():
    log_directory = os.path.join(get_interface().dataDir, 'runfile_logs')
    logs_before = set(os.listdir(log_directory)) if os.path.isdir(log_directory) else set()

    def remove_new_logs():
        if os.path.isdir(log_directory):
            for name in set(os.listdir(log_directory)) - logs_before:
                os.remove(os.path.join(log_directory, name))
    atexit.register(remove_new_logs)


def test_run_file_lines_skip_blanks_and_comments_and_keep_line_numbers():
    lines = command_file.read_command_lines('# header\n\ng1 10\n  acquire  \n# end\n')
    assert [(line.line_number, line.command) for line in lines] == [(3, 'g1 10'), (4, 'acquire')]


def test_run_file_checker_follows_the_cli_lookup_order():
    """A motor label that a command shares runs as the command ('triax' connects), so it is not
    checked as a jog; a plain motor label needs one whole number of steps."""
    command_lines = command_file.read_command_lines(
        'triax\ng1 10\ng1 ten\ng1\ng4 1 2\nfocus_up 3\nrunfile other.txt\n')
    invalid = command_file.find_invalid_lines(command_lines, {'triax', 'runfile'},
                                              {'triax', 'g1', 'g4'})
    assert [command_line.line_number for command_line, _ in invalid] == [3, 4, 5, 6, 7]


def test_runfile_refuses_a_file_with_a_bad_line_and_moves_nothing():
    """The whole file is checked first: a typo must not reach the controller, and the good lines
    before it must not run either."""
    _remove_run_logs_after_tests()
    run_file_path = _write_run_file(['g1 10', 'acquier', 'g1 x'])
    g1_before = _g1_steps()
    with contextlib.redirect_stdout(io.StringIO()):
        result = get_interface()._command_handler(f'runfile {run_file_path}')
    assert 'was not run' in result and 'line 2' in result and 'line 3' in result
    assert _g1_steps() == g1_before


def test_runfile_runs_jogs_in_order_and_logs_every_command():
    _remove_run_logs_after_tests()
    run_file_path = _write_run_file(['# jog test', 'g1 -30', '', 'g1 10', 'allmotors', 'g1 5'])
    g1_before = _g1_steps()
    result = run_command(f'runfile {run_file_path}')
    assert 'Ran all 4 commands' in result
    assert _g1_steps() == g1_before - 15
    log_directory = os.path.join(get_interface().dataDir, 'runfile_logs')
    newest_log = max((os.path.join(log_directory, name) for name in os.listdir(log_directory)),
                     key=os.path.getmtime)
    with open(newest_log) as run_log:
        logged_commands = [line.split('\t')[1] for line in run_log if not line.startswith('#')]
    assert logged_commands == ['g1 -30', 'g1 10', 'allmotors', 'g1 5']


def test_runfile_stops_at_the_first_command_that_fails():
    """'filename' without a name raises; the jog after it must not run."""
    _remove_run_logs_after_tests()
    run_file_path = _write_run_file(['g1 2', 'filename', 'g1 7'])
    g1_before = _g1_steps()
    with contextlib.redirect_stdout(io.StringIO()):
        result = get_interface()._command_handler(f'runfile {run_file_path}')
    assert 'run stopped at line 2' in result
    assert _g1_steps() == g1_before + 2


def test_runfile_stops_when_a_frame_cannot_be_acquired():
    """A failed acquisition (e.g. an early, unexposed frame, #31) saves nothing and stops the
    run at that line, instead of the run carrying on past a missing frame."""
    _remove_run_logs_after_tests()
    acquisition = get_interface().acq_ctrl
    run_file_path = _write_run_file(['filename headless_failed_frame_test', 'acquire', 'g1 3'])
    g1_before = _g1_steps()
    acquire_one_frame = acquisition._acquire_one_frame
    acquisition._acquire_one_frame = lambda: None
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            result = get_interface()._command_handler(f'runfile {run_file_path}')
    finally:
        acquisition._acquire_one_frame = acquire_one_frame
    assert 'run stopped at line 2' in result
    assert _g1_steps() == g1_before
    assert not os.path.exists(os.path.join(get_interface().dataDir, 'headless_failed_frame_test'))


def test_stage1_edge_walk_run_file_runs_end_to_end():
    """A generated edge walk (one centre, small offsets) passes the checker and runs in simulate
    mode: every frame is saved under its position name and g1 ends where the plan says."""
    _remove_run_logs_after_tests()
    chip_placement = stage1_run_files.chip_placement_from_files()
    pair = stage1_run_files.grating_pair_from_calibration(800)
    lines = stage1_run_files.edge_walk_lines([800], chip_placement, lambda centre: pair,
                                             edge_offsets_steps=(-1, 0, 1),
                                             exposure_seconds=0.1)
    run_file_path = _write_run_file(lines)
    data_directory = get_interface().dataDir
    expected_names = ['s1edge_t800_g1m001', 's1edge_t800_g1p000', 's1edge_t800_g1p001',
                      's1edge_t800_g1p150', 's1edge_t800_g1m150']
    for name in expected_names:
        atexit.register(shutil.rmtree, os.path.join(data_directory, name), True)
    run_command('sg 800')
    g1_at_centre, g2_at_centre = _g1_steps(), _g2_steps()
    result = run_command(f'runfile {run_file_path}')
    assert 'Ran all' in result
    for name in expected_names:
        assert os.path.exists(os.path.join(data_directory, name, f'{name}_000000.npz')), name
    final_offset = -stage1_run_files.EDGE_FREE_OFFSET_STEPS
    assert _g1_steps() == g1_at_centre + final_offset
    assert _g2_steps() == g2_at_centre + pair.g2_offset(final_offset), "g2 follows g1"


def test_stage1_run_files_approach_every_frame_from_below():
    """Each edge-walk frame (other than the edge-free ones) and each single step on the way up is
    reached by a positive g1 move, as the bench procedure needs for repeatable positions."""
    chip_placement = stage1_run_files.ChipPlacement(target_pixel=100, nm_per_pixel=0.08)
    pair = stage1_run_files.GratingPair(g2_steps_per_g1_step=-0.97)
    for lines in (stage1_run_files.edge_walk_lines([760, 800], chip_placement,
                                                   lambda centre: pair),
                  stage1_run_files.single_step_lines(800, chip_placement, pair,
                                                     reverse_steps=0)):
        last_move = None
        for line in lines:
            if line.startswith('g1 '):
                last_move = int(line.split()[1])
            if line.startswith('filename') and not line.endswith(('p150', 'm150')):
                assert last_move > 0, line
    assert chip_placement.st_wavelength_for_chip_centre(800) == 800 - 412 * 0.08


def test_stage1_run_files_keep_g2_matched_to_g1_at_every_frame():
    """g1 moved alone turns the beam leaving stage 1 and loses the light (2026-11-17), so at
    every frame g2 sits at round(ratio * g1 offset), including the edge-free frames."""
    chip_placement = stage1_run_files.ChipPlacement(target_pixel=100, nm_per_pixel=0.08)
    pair = stage1_run_files.GratingPair(g2_steps_per_g1_step=-0.97)
    for lines in (stage1_run_files.edge_walk_lines([800], chip_placement,
                                                   lambda centre: pair),
                  stage1_run_files.single_step_lines(800, chip_placement, pair)):
        g1_offset = g2_offset = frames = 0
        for line in lines:
            if line.startswith('sg '):
                g1_offset = g2_offset = 0
            elif line.startswith('g1 '):
                g1_offset += int(line.split()[1])
            elif line.startswith('g2 '):
                g2_offset += int(line.split()[1])
            elif line == 'acquire':
                frames += 1
                assert g2_offset == pair.g2_offset(g1_offset), (g1_offset, g2_offset)
        assert frames > 0
    ratio_at_800 = stage1_run_files.grating_pair_from_calibration(800).g2_steps_per_g1_step
    assert -1.1 < ratio_at_800 < -0.8, "the master calibration turns g2 against g1, about 1:1"


def test_stage1_repeatability_run_file_moves_one_thing_per_frame():
    """Between frames only the TRIAX ('st') or only the gratings ('sg') move, or nothing, and
    each move returns to the centre: a change in the edge then says which one did not return."""
    chip_placement = stage1_run_files.ChipPlacement(target_pixel=100, nm_per_pixel=0.08)
    lines = stage1_run_files.repeatability_lines(800, chip_placement, cycles=2)
    centre_st_line = f'st {chip_placement.st_wavelength_for_chip_centre(800):.1f}'
    moves_since_frame, kinds_moved = [], []
    for line in lines:
        if line.startswith(('st ', 'sg ', 'g1 ', 'g2 ')):
            moves_since_frame.append(line)
        elif line == 'acquire':
            kinds = {move.split()[0] for move in moves_since_frame}
            kinds_moved.append(kinds)
            if 'st' in kinds and 'sg' not in kinds:
                assert moves_since_frame[-1] == centre_st_line, moves_since_frame
            elif kinds == {'sg'}:
                assert moves_since_frame[-1] == 'sg 800', moves_since_frame
            moves_since_frame = []
    assert kinds_moved[0] == {'st', 'sg'}, "the start frame puts everything at the centre"
    assert kinds_moved[1:] == 2 * [set(), {'st'}, {'st'}, {'sg'}, {'sg'}]


def test_stage1_repeatability_run_file_runs_end_to_end():
    """One cycle passes the checker and runs in simulate mode, saving every frame by name and
    leaving the gratings where 'sg 800' puts them."""
    _remove_run_logs_after_tests()
    chip_placement = stage1_run_files.chip_placement_from_files()
    lines = stage1_run_files.repeatability_lines(800, chip_placement, cycles=1,
                                                 exposure_seconds=0.1)
    run_file_path = _write_run_file(lines)
    data_directory = get_interface().dataDir
    expected_names = [line.split()[1] for line in lines if line.startswith('filename ')]
    assert len(expected_names) == 6
    for name in expected_names:
        atexit.register(shutil.rmtree, os.path.join(data_directory, name), True)
    run_command('sg 800')
    g1_at_centre, g2_at_centre = _g1_steps(), _g2_steps()
    run_command('sg 760')
    result = run_command(f'runfile {run_file_path}')
    assert 'Ran all' in result
    for name in expected_names:
        assert os.path.exists(os.path.join(data_directory, name, f'{name}_000000.npz')), name
    assert (_g1_steps(), _g2_steps()) == (g1_at_centre, g2_at_centre)


def test_stage1_edge_calibration_workflow_recovers_the_simulated_bench():
    """The g1 calibration as it is run on the bench: the package's run files, run by 'runfile'
    in simulate mode against a simulated stage 1 bench (halogen with the slit at 500 um, then
    Ar-Hg with it closed to 50 um), then analysed from the run logs and the saved frames. The
    analysis must find the bench's true calibration, with each centre's axis error corrected
    by its Ar-Hg frame, and no gate may fail."""
    _remove_run_logs_after_tests()
    interface = get_interface()
    microscope = interface.microscope
    scene = microscope.camera.simulated_scene
    data_directory = interface.dataDir
    log_directory = os.path.join(data_directory, 'runfile_logs')
    logs_before = set(os.listdir(log_directory)) if os.path.isdir(log_directory) else set()
    bench = SimulatedStage1Bench(band_row=500.0)

    chip_placement = stage1_run_files.chip_placement_from_files()
    pair_at = stage1_run_files.grating_pair_from_calibration
    centres = [780, 820]
    halogen_runs = [
        stage1_run_files.edge_walk_lines(centres, chip_placement, pair_at,
                                         edge_offsets_steps=(-10, 0, 10), exposure_seconds=0.1),
        stage1_run_files.single_step_lines(780, chip_placement, pair_at(780), half_range_steps=3,
                                           reverse_steps=1, exposure_seconds=0.1),
        stage1_run_files.repeatability_lines(780, chip_placement, cycles=1, exposure_seconds=0.1)]
    axis_run = stage1_run_files.axis_reference_lines(centres, chip_placement, exposure_seconds=0.1)
    for lines in halogen_runs + [axis_run]:
        for name in [line.split()[1] for line in lines if line.startswith('filename ')]:
            atexit.register(shutil.rmtree, os.path.join(data_directory, name), True)

    scene.override_scene = lambda: bench.image(
        microscope.get_all_motor_positions(report=False)['g1'], microscope.wavelength_axis,
        interface.spectrometer.get_triax_steps(), image_height=scene.height)
    try:
        slit_width = run_command('ren')
        run_command(f'men {500 - slit_width}')
        for lines in halogen_runs:
            assert 'Ran all' in run_command(f'runfile {_write_run_file(lines)}')
        bench.lamp = ARGON_MERCURY
        run_command('men -450')
        assert 'Ran all' in run_command(f'runfile {_write_run_file(axis_run)}')
    finally:
        bench.lamp = HALOGEN
        scene.override_scene = None
        run_command(f'men {slit_width - run_command("ren")}')

    run_logs = [os.path.join(log_directory, name)
                for name in sorted(set(os.listdir(log_directory)) - logs_before)]
    assert len(run_logs) == 4
    with open(microscope.master_calibration_path) as master_file:
        master = json.load(master_file)
    found = read_session(run_logs, data_directory)
    assert not found.missing_frames
    session_analysis = analyse_session(found, master)

    fit = session_analysis.calibration
    for count in fit.x_values:
        assert abs(fit(count) - bench.true_edge_nm(count)) < 0.05, count
    for summary in session_analysis.centres:
        assert abs(summary.axis_correction_nm + bench.axis_error_nm(summary.triax_steps)) < 0.02
    assert abs(session_analysis.single_steps.offset_from_walk_nm) < 0.05
    assert session_analysis.repeatability.spread_nm('triax') < 0.05
    results = {result.name: result.verdict for result in run_edge_checks(session_analysis)}
    assert 'FAIL' not in results.values(), results


def test_saved_frame_records_the_wavelength_the_gratings_are_at():
    """The frame's monochromator wavelength comes from the motor positions when it is saved,
    not from a value only some commands refresh: after 'sg 720' it is 720, not stale (#32)."""
    name = 'headless_stale_wavelength_test'
    atexit.register(shutil.rmtree, os.path.join(get_interface().dataDir, name), True)
    run_command('sg 800')
    run_command('sm 800')
    run_command('sg 720')
    run_command(f'filename {name}')
    run_command('acqtime 0.01')
    run_command('acquire')
    saved_path = os.path.join(get_interface().dataDir, name, f'{name}_000000.npz')
    with np.load(saved_path) as saved:
        metadata = json.loads(str(saved['metadata']))
    assert abs(metadata['_current_parameters']['monochromator_wavelength'] - 720) < 1.0


# ----------------------------------------------------------------------------
# Standalone runner
# ----------------------------------------------------------------------------

def main():
    """Run every test in this module and report pass/fail counts."""
    tests = [
        (name, obj) for name, obj in sorted(globals().items())
        if name.startswith('test_') and callable(obj)
    ]

    passed, failures = 0, []
    for name, test in tests:
        try:
            test()
            passed += 1
            print(f"[ PASS ] {name}")
        except Exception as exc:
            failures.append((name, exc))
            print(f"[ FAIL ] {name}: {type(exc).__name__}: {exc}")

    print(f"\n{passed}/{len(tests)} passed")
    if failures:
        print(f"{len(failures)} failed:")
        for name, exc in failures:
            print(f"  - {name}: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
