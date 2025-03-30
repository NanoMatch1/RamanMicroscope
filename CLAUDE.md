# CLAUDE.md - Guidelines for the RamanMicroscope Project

## Running Commands
- Run the interface: `python interface_run_me.py`
- Run the data viewer: `python data_viewer_run_me.py`
- Run the camera tester: `python camera_tester_v3_run_me.py`
- Calibration: `python calibration.py`, `python calibration_manual.py`, or `python calibration_auto.py`

## Code Style Guidelines
- **Language**: Python 3.x
- **Formatting**: 4-space indentation, max line length 100 characters
- **Imports**: Group standard library, third-party, and local imports in that order
- **Naming**:
  - Classes: PascalCase (e.g., `TucamCamera`, `Microscope`)
  - Functions/variables: snake_case (e.g., `get_laser_motor_positions`)
  - Constants: UPPERCASE (e.g., `TUCAMRET`, `TUFRM_FORMATS`)
- **Documentation**: Use docstrings for all functions and classes
- **Error Handling**: Use try/except blocks for hardware interactions, log errors
- **Types**: Consider adding type hints to function signatures
- **Simulation**: Use `@simulate` decorator for hardware-free testing

## Repository Structure
- Root contains main modules and entry points
- `/tucsen/` contains camera interface code
- `/calibrations/` stores calibration data files