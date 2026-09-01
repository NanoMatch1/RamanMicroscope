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
import shutil
import contextlib

import numpy as np

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
if REPO_DIR not in sys.path:
    sys.path.insert(0, REPO_DIR)

# Any prompt reached during an automated run should fail fast, not block.
sys.stdin = io.StringIO()

from interface_run_me import Interface


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

    Returns the command's value. Raises AssertionError if the handler
    reports a failure, so that a caught exception surfaces as a test
    failure rather than passing silently.
    """
    result = run_command_raw(command)
    assert result.ok, f"command {command!r} failed:\n{result.text}"
    return result.value


def run_command_raw(command):
    """Send one command and return the full CommandResult, pass or fail."""
    with contextlib.redirect_stdout(io.StringIO()):
        return get_interface()._command_handler(command)


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
                    'rg', 'ren', 'sg',                             # spectrometer
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


# ----------------------------------------------------------------------------
# Command results
# ----------------------------------------------------------------------------

def test_failed_command_returns_structured_failure():
    """
    A command that raises must come back as ok=False with the error and a
    traceback, not as a formatted string and not as a raised exception.
    Callers (CLI, GUI, remote clients) rely on the flag, never on text.
    """
    # A missing required argument raises TypeError before any method body
    # runs, so this does not depend on how one instrument validates input.
    result = run_command_raw('gotowavelength')
    assert result.ok is False
    assert result.value is None
    assert 'TypeError' in result.error
    assert result.traceback and 'Traceback' in result.traceback
    assert result.command == 'gotowavelength'


def test_empty_command_is_a_successful_no_op():
    """An empty line must not be forwarded to the Arduino as a raw command."""
    result = run_command_raw('')
    assert result.ok is True
    assert result.value is None


def test_successful_command_carries_its_value():
    """The value a method returns is the value on the result, untouched."""
    result = run_command_raw('rg')
    assert result.ok is True
    assert isinstance(result.value, int)
    assert result.error is None and result.traceback is None


# ----------------------------------------------------------------------------
# Reporting channel
# ----------------------------------------------------------------------------

# Commands whose output an operator reads. Every one used to print() to the
# terminal, which no console but the launching terminal could see.
REPORTING_COMMANDS = [
    'wai', 'report', 'stagepos', 'allmotors', 'laserpos', 'monopos',
    'rg', 'ren', 'wavelength', 'temp', 'caminfo',
    'x 10', 'x -10', 'stepup 10', 'stepdown 10',
    'acqtime 0.5', 'nframe 1', 'filename headless_test',
    'acqtime notanumber', 'nframe notanumber',   # the warning paths too
]


def test_commands_report_through_the_logger_not_stdout():
    """
    Nothing a command says may go to stdout. The logger is the one
    reporting channel every client shares (CLI, Qt console, remote
    clients); print() reaches only the terminal the process was started
    from, so anything printed is invisible to everyone else.
    """
    captured = io.StringIO()
    with contextlib.redirect_stdout(captured):
        for command in REPORTING_COMMANDS:
            get_interface()._command_handler(command)

    assert captured.getvalue() == '', (
        "commands wrote to stdout instead of the logger:\n" + captured.getvalue()
    )


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
    """'sg' issues a relative grating move; position must track it."""
    before = run_command('rg')
    run_command('sg 500')
    after = run_command('rg')
    assert after == before + 500


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
