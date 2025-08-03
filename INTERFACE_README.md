# Raman Microscope Interface System - Developer Guide

This README provides a comprehensive overview of the `interface_run_me.py` file, which serves as the main entry point and central orchestrator for the Raman Microscope control system.

## Overview

The `interface_run_me.py` file implements the core `Interface` class that acts as the primary gateway between users and the complex Raman microscope hardware. It provides both Command Line Interface (CLI) and Graphical User Interface (GUI) capabilities, manages hardware initialization, handles command routing, and coordinates between multiple instrument subsystems.

## System Architecture

### Core Design Philosophy

The Interface serves as a **mediator pattern** implementation that:
- Orchestrates communication between independent hardware components
- Provides a unified command interface for both CLI and GUI interactions
- Manages hardware simulation and real hardware switching
- Handles thread safety and error management
- Maintains system state and configuration

### Key Components

1. **Hardware Instruments**: Camera, Spectrometer, Laser, Arduino Controller
2. **High-level Controllers**: Microscope (main instrument coordinator)
3. **Services**: Calibration, Acquisition Control, GUI Emitter
4. **Interface Layer**: Command parsing, routing, and execution

## Class Structure and Functions

### `Interface` Class

The main class that ties everything together. Key responsibilities include:

#### Initialization (`__init__`)
```python
def __init__(self, simulate=False, com_port='COM10', baud=9600, debug_skip=[])
```

**Purpose**: Sets up the entire microscope system with all hardware components and services.

**Key Operations**:
- Creates directory structure for data storage
- Initializes all hardware components (camera, spectrometer, laser, controller)
- Sets up the high-level Microscope coordinator
- Configures simulation vs. real hardware based on parameters
- Establishes command mapping system
- Performs integrity checks

**Hardware Initialization Order**:
1. Spectrometer (Triax)
2. Arduino Controller (motor control)
3. Camera (unless in debug_skip)
4. Laser
5. Microscope (must be last as it depends on others)

#### Command Line Interface (`cli`)
```python
@thread_locked
def cli(self)
```

**Purpose**: Provides an interactive command-line interface for microscope control.

**Features**:
- Thread-safe command execution
- Built-in commands: `exit`, `gui`, `help`, `debug`, `reinit`
- Automatic command routing through `_command_handler`
- Error handling with full stack traces
- State saving after each command

#### GUI Interface (`gui`)
```python
def gui(self)
```

**Purpose**: Launches the PyQt5-based graphical user interface.

**Implementation**: Creates a QApplication and MainWindow, providing visual control over the microscope system.

### Command Processing System

#### Command Handler (`_command_handler`)
```python
@heartbeat
def _command_handler(self, command: str)
```

**Purpose**: Central command routing system that processes all user commands.

**Command Resolution Priority**:
1. **Interface-level commands** (`triax`, `camera`, `laser`, `logger`)
2. **Instrument commands** (from dynamically generated command map)
3. **Motor commands** (individual motor movement)
4. **Direct controller commands** (passed through to Arduino)

#### Command Parser (`_command_parser`)
```python
def _command_parser(self, command: str)
```

**Purpose**: Parses user input into function name and arguments.

**Format**: Commands are space-separated with first token as function name and remaining as arguments.

### Hardware Management

#### Dynamic Command Mapping (`_generate_command_map`)
```python
def _generate_command_map(self)
```

**Purpose**: Automatically discovers and maps all available commands from instrument objects.

**How it works**: Scans all instrument attributes for objects inheriting from `Instrument` or `InstrumentBase`, then extracts their `command_functions` dictionaries to create a unified command map.

#### Hardware Connection Functions

##### Connect to Triax (`connect_to_triax`)
```python
def connect_to_triax(self)
```
**Purpose**: Switches from simulated to real TRIAX spectrometer connection.

##### Connect to Camera (`connect_to_camera`) 
```python
def connect_to_camera(self)
```
**Purpose**: Switches from simulated to real camera connection with automatic fallback.

##### Connect to Laser (`connect_to_laser`)
```python
def connect_to_laser(self)
```
**Purpose**: Switches from simulated to real laser connection.

### State Management

#### Save State (`save_state`)
```python
def save_state(self)
```
**Purpose**: Persists the current microscope state including motor positions, wavelengths, and configuration.

#### Process GUI Command (`process_gui_command`)
```python
def process_gui_command(self, command: str)
```
**Purpose**: Handles commands originating from the GUI, mirroring CLI behavior with appropriate logging.

### Utility Functions

#### Logger Level Control (`logger_level`)
```python
def logger_level(self, level)
```
**Purpose**: Dynamically adjusts logging verbosity for debugging and operation.

#### Help System (`show_help`, `generate_help`)
```python
def show_help(self)
def generate_help(self)
```
**Purpose**: Automatically generates help documentation from all available commands and their docstrings.

#### Directory Management (`_build_directories`)
```python
def _build_directories(self)
```
**Purpose**: Creates all necessary directory structures for data storage, calibration files, and temporary data.

**Created Directories**:
- `data/` - Main data storage
- `data/transient_data/` - Temporary acquisition data  
- `autocalibration/` - Automatic calibration files
- `calibration/` - Manual calibration data
- `calibration/motor_recordings/` - Motor position recordings

#### Batch Processing (`run_batch`)
```python
def run_batch(self, commands)
```
**Purpose**: Executes a list of commands sequentially, useful for initialization scripts and automated procedures.

## Thread Safety

The system implements thread safety through:

### `thread_locked` Decorator
```python
def thread_locked(method)
```
**Purpose**: Ensures thread-safe execution of critical methods using non-blocking locks.

**Behavior**: 
- Attempts to acquire lock without blocking
- Returns error message if lock is unavailable
- Automatically releases lock after execution
- Provides full error tracing on exceptions

## Simulation and Debug Features

### Debug Skip System
The `debug_skip` parameter allows selective simulation of hardware components:
- `'camera'` - Use simulated camera
- `'TRIAX'` - Use simulated spectrometer  
- `'UNO'` - Use simulated Arduino controller
- `'laser'` - Use simulated laser

### Hardware Detection
Automatic simulation detection based on:
- Username detection (`"Users\\Sam"` triggers simulation)
- Platform detection (Linux triggers simulation)
- Manual override through parameters

## Integration Points

### Microscope Integration
The Interface creates and coordinates with a high-level `Microscope` object that provides:
- Calibrated wavelength control
- Motor coordination
- Data acquisition
- State management

### Acquisition Control Integration  
Links with `AcquisitionControl` for:
- Scan parameter management
- Data collection coordination
- GUI parameter synchronization

### Calibration Service Integration
Connects with `Calibration` service for:
- Wavelength-to-motor-step conversions
- Live calibration corrections
- Reference calibration procedures

## Development Guidelines

### Adding New Commands

1. **Instrument-level commands**: Add to the appropriate instrument's `command_functions` dictionary
2. **Interface-level commands**: Add to `self.interface_commands` in `__init__`
3. **Ensure proper docstrings**: Used by help system
4. **Consider thread safety**: Use `@thread_locked` for critical operations

### Adding New Hardware

1. **Create instrument class** inheriting from `InstrumentBase`
2. **Add to Interface `__init__`** method
3. **Include in hardware initialization sequence**
4. **Add simulation fallback** if needed
5. **Update command mapping** (automatic if using `command_functions`)

### Error Handling Best Practices

1. **Use try/except blocks** around hardware operations
2. **Provide meaningful error messages** with context
3. **Include stack traces** for debugging
4. **Implement graceful fallbacks** where possible
5. **Log all errors** appropriately

### Configuration Management

- **Hardware settings**: Stored in `microscope_config.json`
- **Calibration data**: Stored in `calibration/` directory
- **Motor positions**: Persisted in instrument state
- **Acquisition parameters**: Managed by AcquisitionControl

## Usage Examples

### Basic Startup
```python
# Create interface in simulation mode
interface = Interface(simulate=True, debug_skip=['camera'])

# Run startup commands
interface.run_batch(['sl 800', 'report'])

# Start CLI
interface.cli()
```

### Adding Custom Commands
```python
# In instrument class
class MyInstrument(InstrumentBase):
    def __init__(self):
        super().__init__()
        self.command_functions = {
            'mycommand': self.my_function
        }
    
    def my_function(self, arg1, arg2):
        """My custom function documentation"""
        # Implementation here
        pass
```

### Hardware Connection Control
```python
# Switch from simulation to real hardware
interface.process_gui_command('triax')  # Connect to real spectrometer
interface.process_gui_command('camera') # Connect to real camera
interface.process_gui_command('laser')  # Connect to real laser
```

## Common Patterns

### Command Flow
1. User input → `cli()` or `process_gui_command()`
2. Command parsing → `_command_parser()`
3. Command routing → `_command_handler()`
4. Execution → Appropriate instrument method
5. State saving → `save_state()`
6. Response logging

### Error Recovery
1. Hardware errors → Simulation fallback
2. Command errors → Error logging + continue
3. Critical errors → Full stack trace + safe exit

### State Synchronization
1. Motor movements → Update calibrated wavelengths
2. Wavelength changes → Update motor positions  
3. GUI changes → Update acquisition parameters
4. All changes → Persist to configuration files

## Debugging and Maintenance

### Logging Control
- Use `logger 10` for debug level logging
- Use `logger 20` for info level logging
- Use `logger 30` for warning level logging

### Common Debug Commands
- `debug` - Enter Python debugger
- `help` - Show all available commands
- `report` - Display current system status
- `wai` - "Where am I" - show current positions

### Hardware Troubleshooting
- Check connection strings and COM ports
- Verify hardware power and connections
- Use simulation mode to isolate software issues
- Check log files for error details

This interface system provides a robust, extensible foundation for controlling the complex Raman microscope hardware while maintaining ease of use and development flexibility.
