# CLAUDE.md - Guidelines for the RamanMicroscope Project

## Running Commands
- Run the interface: `python interface_run_me.py`
- Run the data viewer: `python data_viewer_run_me.py`
- Calibration: `python calibration.py`, `python calibration_manual.py`, or `python calibration_auto.py`

## Testing
Both suites must pass before a change is considered complete.
- Unit (Arduino protocol): `python -m pytest test_controller_simulated.py -q`
- Full headless workflow: `python -m pytest test_headless_simulation.py -q`
  (also runs standalone without pytest: `python test_headless_simulation.py`)
- Everything: `python -m pytest test_controller_simulated.py test_headless_simulation.py -q`

The headless suite drives the whole application in simulate mode through
the real command handler, with stdin replaced by an empty stream so any
interactive prompt fails fast instead of hanging. Never add a bare
`input()` to library code — see MODERNIZATION.md 2.1.

## Code Style Guidelines
- **Language**: Python 3.x
- **Formatting**: 4-space indentation, max line length 100 characters
- **Imports**: Group standard library, third-party, and local imports in that order
- **Naming**:
  - Classes: PascalCase (e.g., `PIXISCamera`, `TigerLaser`, `Microscope`)
  - Functions/variables: snake_case (e.g., `get_laser_motor_positions`)
  - Constants: UPPERCASE (e.g., `RAMAN_MODE_STEPS`, `STEP_MAX`)
- **Documentation**: Use docstrings for all functions and classes
- **Error Handling**: Use try/except blocks for hardware interactions, log errors
- **Types**: Consider adding type hints to function signatures
- **Simulation**: Use `@simulate` decorator for hardware-free testing

## Repository Structure
- Root contains main modules and entry points
- `microscope.py` holds the `Microscope` orchestration class — the functional
  core of the system. (Was `instruments_old.py`; renamed because the name
  wrongly implied it was legacy.)
- `/instruments/` hardware classes: `lasers/` (Tiger), `spectrometers/` (TRIAX)
- `/pixisspec/` Princeton Instruments PIXIS camera interface (replaced the
  Tucsen camera and its `/instruments/cameras/` tree)
- `/acquisitioncontrol/` acquisition orchestration and the PyQt5 GUI
- `/calibration/` stores calibration data files
- `/tools/` standalone diagnostic and calibration scripts, not imported by
  the application — see `tools/README.md`
- `/arduino_mega_develop/` controller firmware — the ground truth for the
  motor command protocol
- `MODERNIZATION.md` tracks known technical debt and standards work
- `CHANGELOG.md` tracks functionally significant changes

## Arduino Communication Architecture
- **Motor Label Translation**:
  - `Microscope.action_groups` organizes motors by functional groups (laser_wavelength, monochromator_wavelength, polarization)
  - Maps human-readable labels ('l1', 'g1', etc.) to Arduino motor IDs ('1X', '2Y', etc.)
  - Creates a flattened `motor_map` for direct lookup of any motor by label

- **MotionControl Integration**:
  - `MotionControl` class receives `motor_map` at initialization
  - Handles translation between human-readable labels and Arduino motor IDs
  - Functions like `get_laser_motor_positions()` pass specific action groups to MotionControl
  - Motor movement is initiated by `MotionControl.move_motors`, which accepts a dictionary of motor labels and steps regardless of action group, enabling any combination of motors to be moved in a single command

- **Arduino Motor ID Format**:
  - Motor IDs follow format: [module number][motor letter]
  - Module numbers (1-4) correspond to motor controller groups
  - Motor letters (A, X, Y, Z) identify specific motors within groups

## Compatibility & Development
- **Current Working Architecture**: The current version is the working architecture with no backward compatibility requirements
- **Recent Improvements**: Modern communication protocol with Arduino featuring envelope formats (o...o, g...g, c...c, s...s)
- **Dictionary-based Positions**: Motor positions stored as dictionaries mapping motor labels to positions, rather than fixed-length lists

## Error Handling Requirements
- **Robust Operation**: Code should continue running despite minor issues
- **Clear Error Reporting**: Errors must be caught and reported with detailed information including:
  - Function or class where error occurred
  - Descriptive messages to aid debugging
  - Current state information when relevant
- **Future Error Logging**: Consider implementing a dedicated error logging and reporting class to monitor errors and their occurrences
- **Validation Patterns**: Implement thorough validation for commands, positions, and responses with appropriate feedback