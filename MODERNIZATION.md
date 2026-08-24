# Modernization Backlog

Work items to bring this codebase up to current engineering standards.
The code predates the disciplines now applied across the other instrument
projects, so this is a deliberate, prioritised catch-up list rather than a
bug list — for bugs and migration history see `CHANGELOG.md`.

Every item below was verified against the source; file:line references are
given so each can be picked up cold. Nothing here is urgent-broken: the
system runs. These are the things that make it expensive to change safely.

**How to use this:** work top-down within a tier. Tier 1 items are
prerequisites — they make the rest cheaper and safer to do. Tier 3 items
are worth doing but can wait indefinitely without cost compounding.

---

## Tier 1 — Do these first (they unblock everything else)

### 1.1 `instruments_old.py` is the live core, not legacy — ✅ DONE (Gate 3)

Renamed to `microscope.py`; the single import in `interface_run_me.py:8`
was updated. The dead `acquisitioncontrol_old.py` (833 lines, zero
importers) was deleted, along with the never-instantiated `Camera` and
`Spectrometer` stub classes that sat at the bottom of the file, and the
now-unused `serial` / `abstractmethod` imports they required.

Remaining: the file is still 2826 lines. See 1.2.

### 1.2 Break up the monoliths

| File | Lines | Contains |
|---|---:|---|
| `microscope.py` | 2825 | `Microscope`, `MotionControl`, `Instrument` ABC, 4 decorators |
| `calibration_manual.py` | 1909 | manual calibration workflows |
| `calibration_auto.py` | 1381 | automated calibration workflows |
| `acquisitioncontrol/pyqtGUI.py` | 1174 | the entire PyQt GUI |

`Microscope` alone mixes motion control, wavelength coordination,
acquisition orchestration, calibration workflows, state persistence and
status reporting. Suggested split:

- `motion_control.py` — `MotionControl` (already a clean separable class)
- `microscope.py` — coordination only
- `microscope_state.py` — save/load/report
- `instrument_base.py` — the ABC (see 1.3)

**Do this incrementally**, one class out at a time, with the headless test
suite green after each move. The suite exists now precisely to make this
safe.

### 1.3 Two different `Instrument` base classes with the same name

- `instruments/instrument_base.py:Instrument` — used by `TigerLaser`,
  `Triax`, `PIXISCamera`
- `microscope.py:525:Instrument` — used by `Microscope`

`interface_run_me.py:426` has to `isinstance`-check against **both** to
build the command map, importing one as `InstrumentBase` to disambiguate.
This works but is a trap: a new instrument inheriting the "wrong" one still
appears to function until something checks its type.

Collapse to one ABC in `instruments/instrument_base.py`. Low risk — the
two implementations are near-identical; the registry contract
(`_integrity_checker`) is the part that matters and it is duplicated.

### 1.4 Hardware ports are hard-coded, defeating the DI design

The architecture is otherwise good dependency injection — hardware objects
are constructed in `interface_run_me.py` and passed in. But the ports are
baked into the classes:

- `instruments/lasers/tiger_laser.py:75` — `PORT = 'COM17'` (class constant)
- `instruments/spectrometers/triax.py:16` — `self.port = 'COM16'`
- `controller.py:6` — `com_port='COM10'` default
- `instruments/lasers/millennia_laser.py:109` — `port='COM13'`

Consequence: the same code cannot run on a second machine, or against a
device that enumerated on a different port, without editing source. This is
the pattern already solved in the TDS_app controllers package — a JSON
instrument-connection config, ports injected at construction.

**Recommended:** `instrument_config.json` (gitignored, with a committed
`.example`), read by `Interface`, ports passed to each constructor. This
also fixes the `simulate=True` hazard in 1.5.

### 1.5 `simulate` is a hard-coded override, not a flag

`interface_run_me.py:530` currently carries `simulate = True  # Force
simulation mode for testing purposes`, which overrides the platform
detection above it. **This is deliberately uncommitted** (it would run the
lab microscope fully simulated with no hardware moving), but the underlying
problem is that there is no supported way to ask for simulation.

Replace the whole `if "Users\\Sam" in os.getcwd()` heuristic block
(`interface_run_me.py:523-528` — hostname-sniffing to guess intent) with an
explicit `argparse` flag: `python interface_run_me.py --simulate`.

### 1.6 The Arduino firmware is no longer in the repo

`arduino_mega_develop/arduino_mega_develop.ino` (574 lines) was deleted in
`a6d9efa`. It is recoverable from `2f3aacc` but is currently absent from
the working tree, and no `.ino` exists anywhere on disk.

This matters more than it looks: the firmware is the **ground truth for the
motor command protocol** that `controller.py` speaks and `simulation.py`
imitates. Without it there is no way to:

- verify the simulator matches the real device,
- reconcile the `RAMAN_MODE_STEPS` disagreement (see 2.3),
- reflash or modify the controller.

**✅ DONE (Gate 3):** restored from `2f3aacc` to
`arduino_mega_develop/arduino_mega_develop.ino`. It immediately paid for
itself by settling the `RAMAN_MODE_STEPS` question in 2.3.

Remaining: if the firmware is also maintained elsewhere, record which copy
is authoritative in `README.md`, so the two cannot silently diverge.

---

## Tier 2 — Correctness and maintainability

### 2.1 Interactive `input()` calls inside library code

Blocking prompts buried in instrument logic make automation and testing
impossible, and hang unattended runs:

- `microscope.py:1146` — `raman_mode()` "already in Raman mode, continue? (y/n)"
- `microscope.py:1160` — `image_mode()` same
- `microscope.py:1556` — inside a calibration loop
- `microscope.py:1617` — `autocal` "Continue? (y/n)"
- `microscope.py:2660` — `laser_safety_check()`

(`detect_microscope_mode()` at `microscope.py:1111` was the worst case — it fired during
`initialise()` — and is already fixed for simulation in `57cacf2`.)

**Pattern to adopt:** library code should never prompt. Take a
`confirm: Callable[[str], bool]` or a `force: bool` parameter, defaulting
to non-interactive; let the CLI layer supply the prompt. This is the same
separation the GUI already needs, since none of these prompts can work from
`process_gui_command()` either.

### 2.2 Cross-object private state access

`Microscope` writes directly into `AcquisitionControl`'s private dict:

- `microscope.py:794, 795, 2677` — `self.interface.acq_ctrl._current_parameters[...] = ...`

This is the coupling that makes `Microscope` hard to test in isolation. Give
`AcquisitionControl` an explicit setter, or have it observe the microscope
rather than be written into.

The general form of this issue: components reach each other through
`self.interface.<anything>`, so `Interface` is effectively a service locator
and every component transitively depends on all others. Passing the specific
collaborators each class needs (as is already done for `Microscope`'s
constructor) is the fix.

### 2.3 Magic numbers and unreconciled physical constants

**Partly resolved in Gate 3** once the firmware (1.6) was restored to act
as ground truth. `arduino_mega_develop.ino:246-254` is definitive:

```c
void ramanMode() { stepperA2.move(6000);  }   // +6000
void imageMode() { stepperA2.move(-6000); }   // -6000
```

`simulation.py` had `RAMAN_MODE_STEPS = -100_000` — wrong in **both sign
and magnitude**. That number is the homing slow-approach move from
elsewhere in the same firmware file (`:335`), evidently copied across by
mistake. Corrected to `6000`, and `test_controller_simulated.py` now
asserts the firmware value explicitly rather than a round trip.

#### TODO — resolve mode switching (needs hardware check with the student)

Traced end to end. **The ±6000 firmware path is dead code as far as the
application is concerned**, so the disagreement is less alarming than it
first looked — but it should still be cleaned up, and there may be a
better mechanism available now.

What actually happens:

| Path | Steps | Reached by |
|---|---|---|
| `Microscope.raman_mode()` / `image_mode()` (`microscope.py:1146,1160`) | **±100000** | **This is the live path.** Sends the envelope `o2A±100000o`, then polls `c2Ac`. Verified on the wire. |
| Firmware `ramanMode()` / `imageMode()` (`.ino:246-254`) | ±6000 | **Nothing in the application.** Only by typing the bare word `ramanmode` at the Arduino serial console. |
| `detect_microscope_mode()` (`microscope.py:1092-1095`) | ±50000 | A **software sentinel it writes itself** — not a physical position at all. |

Evidence the ±6000 path is vestigial:

- `ramanmode` / `imagemode` are registered as *Microscope* commands
  (`microscope.py:655-656`), so typing them in the CLI calls the Python
  methods and never falls through to `controller.send_command()`.
- Nothing anywhere sends those strings to the controller — the only
  callers are `test_controller_simulated.py`.
- The firmware itself brackets them with the comment
  `// Legacy mode commands` (`.ino:564`).

Samuel's recollection matches the live path: **100000 steps** were needed
to move between Raman and image mode; the ±6000 in the firmware was a
workaround from an early input-only test and was never updated.

**To resolve:**

1. **Confirm with the student** whether a limit switch has since been
   fitted to the mode motor (2A). If so, mode switching should home
   against it rather than open-loop stepping a magic number — which is
   the real fix, since an open-loop ±100000 silently mis-positions if a
   step is ever lost.
2. Note the firmware currently has only **one shared** limit input,
   `homingLimitPin = 13` (`.ino:82`, active-low `INPUT_PULLUP`), used by
   `homeMotor()` for whichever motor is being homed — there are no
   per-motor endstops. Leveraging a switch for mode position therefore
   needs either a dedicated pin for 2A, or that shared pin wired to 2A
   only (which would preclude homing the other axes). The `h2A` command
   already exists and would work if 2A is the wired axis.
3. Once decided: delete the dead firmware `ramanMode()`/`imageMode()` and
   the simulator's `_raman_mode()`/`_image_mode()` mirror of them, or
   make them agree with the live path. Do not leave three different
   numbers describing one motor.
4. Replace the ±50000 sentinel with a real position query, or state
   plainly in the code that it is a flag, not a measurement.

Others:

- `instruments/spectrometers/triax.py:158` — `steps_correction=1910`, an
  undocumented empirical fudge (was 200 pre-migration; the ~10x change
  presumably tracks the 2048→1024 sensor swap but this is not recorded).
- `calibration.py:189` — `array_length=1024` hard-coded; should come from
  the camera object, so a future sensor swap cannot desynchronise the
  wavelength axis from the frame.

**Recommended:** single source of truth per constant, in config, with the
derivation documented.

### 2.4 Silent exception swallowing

- `instruments/lasers/tiger_laser.py:842-843` — `except Exception: pass` in
  `__del__`
- `interface_run_me.py:320-322` — `except Exception: pass` around camera
  shutdown

More broadly, `Interface._command_handler` catches every exception and
returns it as a **formatted string**. Callers cannot distinguish success
from failure without string-matching (the headless test has to do exactly
this, `test_headless_simulation.py:76`). Errors are also not routed to the
error log in that path.

This directly undercuts the **active diagnostics** requirement: a 6-hour
scan can currently accumulate failures that are logged as INFO-level strings
and never surfaced. Consider a `CommandResult` dataclass
(`ok: bool, value, error`) instead of stringly-typed returns.

### 2.5 Naming that fails the searchability test

- `Triax.go_to_position()` (`triax.py:217`) sends `F0`, a **relative** move.
  `sg 105500` shifts by 105500 steps rather than moving to that position.
  Rename to `move_grating_relative` (which already exists as a separate
  command mapping to the same underlying call).
- `"enterance"` — misspelling of "entrance", **32 occurrences** across the
  codebase including public method names (`read_enterance_slit`,
  `move_enterance_slit`, `enterance_slit_width`). Searching for the correct
  spelling finds nothing.
- Non-descriptive file names: `Lasercomstesttiger.py`,
  `Calibrationgenerator.py`, `Lasercalbration.py` (also misspelled),
  `sdk check.py` (space in filename), `cal1.csv`, `calitest.csv`.

### 2.6 Two GUI frameworks

`acquisitioncontrol/acqgui.py` is **tkinter**; `acquisitioncontrol/pyqtGUI.py`
is **PyQt5**. The tkinter one is imported unconditionally in
`acquisitioncontrol/__init__.py:2`, so it is a hard dependency of the
package even though the running application uses PyQt.

Only `acquisitioncontrol/simulation.py:119` uses it. Either drop it or make
the import lazy.

---

## Tier 3 — Polish, do when convenient

### 3.1 Packaging and dependencies

- ~~`MULETA_Raman_Microscope.egg-info/` is tracked~~ — ✅ DONE (Gate 3):
  untracked and gitignored.
- No `pyproject.toml`; `setup.py` is 253 bytes and does not declare
  dependencies, so `requirements.txt` and packaging metadata can drift.
- `pytest` is not in `requirements.txt` despite two pytest suites. Add a
  `requirements-dev.txt`.
- `gpib-ctypes` and `PyVISA-py` remain in `requirements.txt` but nothing
  imports pyvisa or GPIB since the TRIAX moved to RS-232 — leftover from
  the migration.

### 3.2 Type hints and docstring consistency

Type hints are essentially absent outside `tiger_calibration.py` (which is
the best-documented module in the repo and a good template). Docstrings
exist widely but vary between `'''` and `"""` and rarely document
parameters or return types. `CLAUDE.md` already asks for type hints —
adopt them on new/touched code rather than in a sweep.

### 3.3 Test coverage gaps

Current state: 29 tests (9 protocol unit + 20 headless workflow, added
`57cacf2`). Untested:

- `Calibration` service — the polynomial fits and `wl_to_steps`/`steps_to_wl`
  round-trips. Pure functions, trivially testable, and the highest-value
  target since a calibration error silently corrupts every measurement.
- `TigerCalibration` — interpolation and clamping edges are pure functions
  with no hardware dependency.
- `datafit/` — fitting functions, entirely pure.
- `AcquisitionControl` scan-sequence generation.
- The PyQt GUI (`pytest-qt` would be needed).

### 3.4 Documentation

- ~~`changes.txt` (72 KB) raw pasted `git diff`~~ — ✅ DONE (Gate 3): deleted,
  superseded by real git history plus `CHANGELOG.md`.
- `refactor_history.md` describes the March 2025 protocol rewrite; fold its
  still-relevant "Architecture Notes" into `README.md` and retire the rest.
- `README.md` describes the architecture well but predates the
  Tiger/PIXIS/RS-232 changes — it still implies the laser is stepper-driven.
- No documented startup procedure for the lab machine (which COM ports,
  what order to power on, how to verify).

### 3.5 Runtime state tracked in git — ✅ DONE (Gate 3)

All untracked via `git rm --cached` (local copies retained, so the lab
machine keeps its real values) and added to `.gitignore`:

- `calibration/tiger_step_position.json` — **the laser's physical
  position**, and the highest-risk of the group: a committed value tells
  `TigerLaser` the piezomotor is somewhere it is not, making the next
  relative move wrong.
- `instrument_errors.log`, `viewer_settings.json`
- `MULETA_Raman_Microscope.egg-info/`
- `motor_tests.json` moved to `tools/` with the data it belongs to
- `delme.py` deleted (it was listed in `.gitignore` but tracked anyway —
  gitignore does not untrack already-tracked files)

`.gitignore` also regained `.venv/` and gained `.vs/`.
