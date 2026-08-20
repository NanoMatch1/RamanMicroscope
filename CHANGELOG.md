# Changelog

This file tracks functionally significant changes to the Raman microscope
control software. It does not track calibration data regeneration, log
churn, or other non-functional file noise — see git history for that.

## Simulation repair and test harness (2026-08-20)

Follow-up to the migration commits below. Simulate mode did not start at
all; fixed that and added the missing test coverage. All fixes verified by
reinstating each bug and confirming the corresponding test fails.

### Fixed

- `instruments/spectrometers/triax.py`: the simulate branch of
  `_send_command_to_spectrometer()` called `self.spectrometer.query()` —
  the **pyvisa** API left behind by the GPIB implementation.
  `SimulatedTriaxSerial` mirrors **pyserial** (`write`/`read`), so every
  simulated read raised `AttributeError`. Because `Triax.initialise()`
  reads the position, this aborted startup entirely: simulate mode was
  completely unusable. Same root cause as the dead `_flush_read_buffer`
  removed in `19e68df`.
- `instruments_old.py` `report_status()`: passed `{all_motors}` — a set
  literal wrapping the motor dict — to `identify_microscope_mode()`,
  raising `TypeError: unhashable type: 'dict'` on every `report` command
  that recalculated state.
- `instruments_old.py` `camera_info()`: called `self.camera.camera_info()`,
  which no camera class has ever implemented (the retired Tucsen class
  lacked it too, so `caminfo` was already broken before the migration).
  Now calls `get_camera_info()`, which `PIXISCamera` does provide.
- `instruments_old.py` `detect_microscope_mode()`: prompted via `input()`
  when the mode motor was not at exactly ±50000. In simulation the motor
  starts elsewhere, so this always prompted — during `initialise()`,
  making any headless or automated run hang on stdin. Now defaults to
  `ramanmode` when simulating; real-hardware behaviour is unchanged, since
  there the prompt is correct (the software genuinely cannot know the
  mode).
- `simulation.py`: `RAMAN_MODE_STEPS` was commented out but still
  referenced by `_raman_mode()`/`_image_mode()`, so both raised
  `AttributeError`. Restored. **Note:** its magnitude (100000) disagrees
  with `microscope_config.json` (`mode: 100000`) versus
  `detect_microscope_mode()`'s ±50000 test — only the sign is currently
  relied upon. Worth reconciling against the firmware.
- `simulation.py`: added the public `send_command()` that
  `SimulatedArduinoSerial`'s own docstring already documented but which
  did not exist, so tests no longer reach into `_parse_command()`.

### Testing

- **`test_headless_simulation.py` (new, 20 tests).** Full-workflow test
  driving the application through `Interface._command_handler` exactly as
  a CLI user would — startup, command registry, laser tuning and homing,
  spectrometer reads/moves, camera acquisition, microscope orchestration.
  Runs standalone (`python test_headless_simulation.py`) or under pytest.
  It replaces stdin with an empty stream so any prompt reached during an
  automated run fails fast instead of hanging. Includes explicit
  regression guards for each bug above. It snapshots and restores
  `tiger_step_position.json` so running the suite does not leave the
  laser's persisted position holding a simulated value.
- **`test_controller_simulated.py` (repaired, 9 tests).** Was importing
  `simulated_controller`, a module that does not exist, so the suite had
  been uncollectable — these failures predate the Tiger work. Repointed
  at `simulation.SimulatedArduinoSerial` (the class actually used at
  runtime), corrected the expected line ending to the protocol's CRLF,
  and fixed the `m...m` envelope spacing (`'m gsh on m'` → `'mgsh onm'`;
  the parser partitions on the first space, so the padded form yielded an
  empty command token). Mode-switch test now asserts a round trip rather
  than a magic step count.
- Total: **29 passing** (9 unit + 20 workflow).

### Known issues added

10. **`calibration/tiger_step_position.json` is tracked in git but is
    per-machine runtime hardware state**, exactly analogous to
    `instrument_state.json`, which is already gitignored. Pulling a
    committed value onto the lab machine would tell `TigerLaser` the
    piezomotor is somewhere it physically is not, making the next
    relative move wrong. Recommend `git rm --cached` + gitignore in the
    cleanup pass; the lab machine would keep its local copy.
11. **`interface_run_me.py` has `simulate = True` hard-coded** at the
    bottom, overriding the platform detection above it. Deliberately
    added for local testing and left uncommitted, but it must not reach
    the lab machine: it would run the microscope fully simulated with no
    hardware moving. A `--simulate` command-line flag would be a safer
    mechanism.
12. **`simulation.py:SimulatedArduinoController` is dead code.** The
    runtime path uses `SimulatedArduinoSerial`; this second class is
    unused, implements an older non-envelope protocol, and its
    `__init__` never creates the `laser_motors`/`monochromator_motors`
    attributes its own methods reference. Deletion candidate.
13. **`Triax.go_to_position()` is misleadingly named** — it sends `F0`,
    a *relative* grating move, so `sg 105500` shifts by 105500 steps
    rather than moving to that position. The simulator faithfully
    reproduces this. Pre-existing, but worth renaming.

## [Unreleased] — Tsunami → Tiger laser migration (2026-08-20)

Untracked working-tree edits made in the Melbourne lab to connect a new
Tiger Ti:Sapphire laser in place of the retired Tsunami. Captured here
before the first commit of this work. Reviewed and summarised by Claude
at Samuel's request; not yet split into individual commits.

### Laser: Tsunami → Tiger

- Added `instruments/lasers/tiger_laser.py` (`TigerLaser`) — RS-232 control
  (COM17, 9600 baud) of the Tiger's 1DBuP piezomotor tuning controller.
  Unlike the Tsunami, the Tiger is **not** stepper-motor tuned: it has no
  remote on/off, no power control, and no shutter command. Those
  `Microscope`-facing methods (`turn_on`, `turn_off`, `set_power`,
  `cycle_shutter`, ...) are now no-op stubs that log a warning and return a
  safe default so the rest of the call chain doesn't break.
- Added `instruments/lasers/tiger_calibration.py` (`TigerCalibration`) —
  step↔wavelength conversion. Deliberately switched from a 39-point cubic
  spline (which had ~10 nm systematic error from Runge's-phenomenon
  oscillation between poorly-verified points) to **linear interpolation
  over 6 verified measurement points**, range 765.546–840.035 nm
  (steps 2453–5400). More points can be added as they're measured.
- `microscope_config.json`: `action_groups.laser_wavelength` emptied
  (was `{l1, l2, l3}` → Arduino motor IDs) and the corresponding `l1/l2/l3`
  entries removed from `ldr_scan_dict`. The laser no longer has
  Arduino-driven axes.
- `instruments_old.py` (`Microscope`): `go_to_laser_wavelength` now
  delegates directly to `TigerLaser.go_to_wavelength()` instead of
  computing stepper-motor target positions via
  `calibration_service.wl_to_steps()`. The `@apply_pseudocal_forwards`
  decorator (a stepper-motor pseudo-calibration correction) was removed
  from this path accordingly.
  - `current_laser_wavenumber`, `report_laser_wavelength`,
    `current_monochromator_wavenumber` are now hardcoded to return `0.0`
    ("disabled — tuned via piezomotor"). **See Known Issues.**
  - The old `calculate_laser_wavelength` (which actually computed
    *grating* wavelengths from motor steps — a pre-existing naming bug)
    was renamed to `calculate_grating_wavelength`. A new
    `calculate_laser_wavelength` was added that is a no-op for the Tiger.
  - `MotionControl.get_motor_positions` now returns `{}` immediately for
    an empty motor dict, and `_parse_motor_positions` now tolerates empty/
    malformed controller responses instead of raising — both needed
    because the laser motor group is now empty.
  - `live_laser_calibration` decorator gained detailed post-fit logging
    (TRIAX/centre-pixel/Tiger-estimate/live-cal wavelengths) and is now
    also applied to `go_to_wavelength_all`.
  - `live_calibration_laser`: entrance slit width during auto laser-line
    detection changed from 5 → 7.

### Spectrometer: TRIAX moved from GPIB to RS-232

Not part of the laser swap, but bundled into the same uncommitted diff —
**flagging separately since it changes physical connectivity of a
different instrument.**

- `instruments/spectrometers/triax.py`: dropped `pyvisa`/GPIB
  (`GPIB0::1::INSTR`) entirely in favour of raw RS-232 (COM16, 4800 baud).
  Added a from-scratch "intelligent mode" handshake
  (`_enter_intelligent_mode`, `_is_initialised`, `_run_initialisation`)
  matching the TRIAX serial protocol (byte 248 to enter intelligent mode,
  `H0` to probe init state, space-triggered autobaud/init sequence, up to
  120 s).
- `go_to_wavelength`: the artificial `steps_correction` fudge factor
  (pushes the laser line to a known pixel) changed from 200 → 1910 —
  consistent with the camera swap below, but a large jump worth
  double-checking physically.

### Camera: Tucsen → Princeton Instruments PIXIS

Also not part of the laser swap, also bundled into the same diff.

- Added `pixisspec/pixiscam.py` (`PIXISCamera`) and
  `pixisspec/pixis_hardware.py`, built via `pylablib` as a drop-in
  replacement for the old `TucsenCamera` (deleted, along with all of
  `instruments/cameras/`, including the Tucsen SDK DLLs).
  `PIXISCamera` has a class-level singleton guard (`_instance_active`).
- Sensor width changed 2048 → 1024 px. Propagated to
  `calibration.py:generate_wavelength_axis` (default `array_length`) and
  `data_viewer_run_me.py`'s placeholder array shape.
- Exposure time convention (seconds in, converted to ms internally) is
  explicitly documented and consistent between `pixiscam.py` and
  `pixis_hardware.py`.

### Bug fix worth calling out: acquisition_time unit mismatch

`acquisitioncontrol/acqcontrol.py`: `general_parameters['acquisition_time']`
default changed from `1000.0` to `1.0`, with a comment explaining the old
value was a leftover millisecond convention being passed to a
seconds-expecting `set_exposure_time`, causing a **1000× exposure
overrun**. This looks like a genuine, previously-live bug that the student
caught and fixed. See Known Issues for a related loose end.

### Known Issues / follow-ups (found during this review, not yet fixed)

1. **Missing dependency: `pylablib`.** `pixis_hardware.py` does
   `from pylablib.devices import PrincetonInstruments` at module level,
   and `pixiscam.py` imports it unconditionally, and `interface_run_me.py`
   imports `pixiscam` unconditionally. `pylablib` is not in
   `requirements.txt`. **A clean environment (`pip install -r
   requirements.txt`) cannot start the application at all, even in
   `simulate=True` mode.** Highest-priority fix.
2. **Laser/monochromator wavenumber reporting is silently zeroed.**
   `current_laser_wavenumber`, `report_laser_wavelength`,
   `current_monochromator_wavenumber` always return `0.0`. Concretely:
   - The GUI's laser-wavelength label (`pyqtGUI.py`) will always show
     "0.00 nm".
   - `Microscope.report_status()` logs `'laser wavenumber': 0.0` and
     `'monochromator wavenumber': 0.0` on every status report.
   - `Microscope.laser_safety_check()` compares
     `current_laser_wavenumber` against `current_monochromator_wavenumber`
     — with both pinned at 0.0 this condition is trivially always true.
     Currently **no code path calls `laser_safety_check()`**, so this is
     dormant rather than actively wrong, but it should either be wired up
     correctly (using `TigerLaser.get_estimated_wavelength()`) or removed.
3. **Stale local config will silently set a 100 s exposure.**
   `acquisitioncontrol/acquisition_config.json` (gitignored, machine-local)
   still has `"acquisition_time": 100.0` from before the ms→s fix above.
   On next GUI launch this loads as **100 seconds**, not the old 100 ms.
   Needs a manual reset/edit on the lab machine.
4. **Orphaned reference to removed import.**
   `triax.py:_flush_read_buffer` still references
   `pyvisa.errors.VisaIOError`, but `import pyvisa` was replaced with
   `import serial` elsewhere in the same file. Nothing currently calls
   this method (leftover from the GPIB implementation), so it's dead
   code rather than an active crash — candidate for deletion.
5. **`requirements.txt` gained `gpib-ctypes` and `PyVISA-py`** even though
   neither `triax.py` nor `tiger_laser.py` use PyVISA/GPIB anymore (both
   now use raw `pyserial`). Looks like leftover exploration debris from
   before the RS-232 rewrite.
6. **`PIXISCamera` singleton guard is only released reliably via
   `__del__`.** `close_camera()` does not clear `_instance_active`; the
   one call site that reconnects (`Interface.connect_to_camera`) works
   around this by manually resetting the private class attribute rather
   than the class managing its own lifecycle.
7. **Dead scaffolding in `instruments_old.py`.** A new `Instrument(ABC)`
   base class is now defined locally in `instruments_old.py` (the old
   `from instruments.instrument_base import Instrument` was removed),
   separate from `instruments.instrument_base.Instrument`
   (`InstrumentBase` in `interface_run_me.py`). `Microscope` extends the
   local one; `TigerLaser`/`Triax`/`PIXISCamera` extend the package one.
   Two new stub classes, `Camera` and `Spectrometer`, were also added at
   the bottom of `instruments_old.py` and are never instantiated anywhere.
8. **Docstring/implementation mismatch.** `TigerLaser`'s class docstring
   states the calibrated range is "765.546 – 847.876 nm (steps
   1500 – 5400)"; the actual `TigerCalibration` data caps out at
   840.035 nm / step 2453. The docstring predates the switch to the
   6-point verified dataset.
9. **`.gitignore` lost its `.venv/` entry.** No `.venv/` currently exists
   in the working tree, so this hasn't bitten yet, but it should probably
   be restored before the first commit.
