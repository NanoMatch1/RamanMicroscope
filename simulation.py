"""
Simulation module for the Raman Microscope

This module provides simulated versions of hardware components for testing without
physical instruments. Each simulated class implements the same interface as its
real hardware counterpart, but returns simulated data.
"""

import time
import numpy as np
import serial
import os
import threading
import ctypes
from random import randint
from typing import List, Tuple, Dict, Any, Optional, Union

class SimulatedArduinoController:
    """
    Simulates the Arduino-based RamanMicroscope controller.
    Methods:
      send_command(cmd: str) -> str
        Send an envelope command (including its leading/trailing char)
        and get back exactly what the Arduino would have printed.
    """

    MODULES = ('1','2','3','4')
    MOTORS  = ('A','X','Y','Z')

    def __init__(self):
        # Initialize every motor to zero position
        self.current = {
            m: { motor: 0 for motor in self.MOTORS }
            for m in self.MODULES
        }
        # shutter and LEDs
        self.g_shutter = False
        self.led1 = False
        self.led2 = False
        # LDR reading (you can override this in tests)
        self.ldr_value = 0

    def send_command(self, cmd: str) -> str:
        """Mimic Serial.readStringUntil('\\n') + parseCommand + Serial responses."""
        cmd = cmd.strip()
        if cmd.startswith('o') and cmd.endswith('o'):
            # multi–move: o1A1000 2X2000o
            self._parse_multi_move(cmd[1:-1])
            return ''  # Arduino only prints "Moving motor…" per token, but tests usually ignore it
        elif cmd.startswith('g') and cmd.endswith('g'):
            return self._get_positions(cmd[1:-1])
        elif cmd.startswith('c') and cmd.endswith('c'):
            return self._check_moving(cmd[1:-1])
        elif cmd.startswith('s') and cmd.endswith('s'):
            return self._set_positions(cmd[1:-1])
        elif cmd.startswith('m') and cmd.endswith('m'):
            return self._hardware_command(cmd[1:-1])
        elif cmd.startswith('h') and len(cmd) == 3:
            return self._home_motor(cmd[1], cmd[2])
        elif cmd == 'imagemode':
            return self._image_mode()
        elif cmd == 'ramanmode':
            return self._raman_mode()
        else:
            return 'Unrecognized command format\n'

    # ─── motion commands ──────────────────────────────────────────────────────

    def _parse_multi_move(self, content: str):
        for token in content.split():
            if len(token) < 3:
                continue
            module, motor = token[0], token[1]
            try:
                delta = int(token[2:])
            except ValueError:
                continue
            self._move(module, motor, delta)

    def _move(self, module: str, motor: str, delta: int):
        """Relative move: stepper.move(delta)"""
        if module in self.current and motor in self.current[module]:
            self.current[module][motor] += delta

    def _get_positions(self, content: str) -> str:
        """
        g1A 2Xg  →  "1A:1000 2X:2000 \n"
        """
        out = []
        for token in content.split():
            if len(token) < 2:
                continue
            m, mt = token[0], token[1]
            if m in self.current and mt in self.current[m]:
                pos = self.current[m][mt]
                out.append(f"{m}{mt}:{pos}")
        return ' '.join(out) + '\n'

    def _check_moving(self, content: str) -> str:
        """
        c1A 2Xc →  "1A:false 2X:false \n"
        (always false here)
        """
        out = []
        for token in content.split():
            if len(token) < 2:
                continue
            m, mt = token[0], token[1]
            if m in self.current and mt in self.current[m]:
                out.append(f"{m}{mt}:false")
        return ' '.join(out) + '\n'

    def _set_positions(self, content: str) -> str:
        """
        s1A1000 3Z-500s → "Set motor 1A position to 1000\n" (last token only)
        """
        resp = ''
        for token in content.split():
            if len(token) < 3:
                continue
            m, mt = token[0], token[1]
            try:
                pos = int(token[2:])
            except ValueError:
                continue
            if m in self.current and mt in self.current[m]:
                self.current[m][mt] = pos
                resp = f"Set motor {m}{mt} position to {pos}\n"
        return resp

    # ─── hardware commands ───────────────────────────────────────────────────

    def _hardware_command(self, content: str) -> str:
        """
        m...m envelope:
          gsh on/off → Shutter
          ld0        → LDR
          led on/off → LEDs
        """
        cmd, _, arg = content.partition(' ')
        if cmd == 'gsh':
            return self._mono_shutter(arg.strip())
        elif cmd == 'ld0':
            return self._read_ldr()
        elif cmd == 'led':
            return self._toggle_led(arg.strip())
        else:
            return "Unknown hardware command.\n"

    def _mono_shutter(self, state: str) -> str:
        self.g_shutter = (state == 'on')
        return "Shutter open.\n" if self.g_shutter else "Shutter closed.\n"

    def _read_ldr(self) -> str:
        # Arduino prints 't' + summed reading; here we'll just return one value
        return f"t{self.ldr_value}\n"

    def _toggle_led(self, state: str) -> str:
        on = (state == 'on')
        self.led1 = self.led2 = on
        return "LED on\n" if on else "LED off\n"

    # ─── homing & modes ───────────────────────────────────────────────────────

    def _home_motor(self, module: str, motor: str) -> str:
        if module in self.current and motor in self.current[module]:
            self.current[module][motor] = 0
            return f"Homed motor {module}{motor} at position 0\n"
        else:
            return "Invalid motor.\n"

    def _raman_mode(self) -> str:
        # module 2, motor A  → +6000 steps
        self._move('2', 'A', +6000)
        return "Moving to Raman Mode...\n"

    def _image_mode(self) -> str:
        # module 2, motor A  → -6000 steps
        self._move('2', 'A', -100_000)
        return "Moving to Image Mode...\n"



class SimulatedArduino:
    """Simulated Arduino controller for stepper motors"""
    
    def __init__(self, interface=None, com_port=None, baud=None, report=True):
        self.motor_running = False
        self.shutter_status = "off"
        self.report = report
    
    def connect(self):
        """Simulate connection to Arduino"""
        print("Connected to simulated Arduino")
        return serial.Serial  # Return mock object
    
    def send_command(self, command):
        """Process commands sent to Arduino and return simulated responses"""
        if self.report:
            print(f'>UNO:{command}')
            
        cmd_parts = command.split(' ')
        cmd = cmd_parts[0].lower()
        
        # Handle different command types
        if cmd in ['apos', 'get_laser_positions']:
            positions = ','.join([f"X{self.laser_motors[0]}", 
                                 f"Y{self.laser_motors[1]}", 
                                 f"Z{self.laser_motors[2]}", 
                                 f"A{self.laser_motors[3]}"])
            return [f'S0:<P>{positions}</P>', '#CF']
        
        elif cmd in ['bpos', 'get_monochromator_positions']:
            positions = ','.join([f"X{self.monochromator_motors[0]}", 
                                 f"Y{self.monochromator_motors[1]}", 
                                 f"Z{self.monochromator_motors[2]}", 
                                 f"A{self.monochromator_motors[3]}"])
            return [f'S0:<P>{positions}</P>', '#CF']
        
        elif cmd == 'aisrun' or cmd == 'bisrun':
            return ['S0:Not running', '#CF']
            
        elif cmd == 'ld0':  # Light sensor
            return [f'S0:{randint(1000, 5000)}', '#CF']
            
        elif cmd == 'gsh':  # Shutter
            if len(cmd_parts) > 1:
                self.shutter_status = "on" if "on" in cmd_parts[1].lower() else "off"
            return [f'S0:Shutter {self.shutter_status}', '#CF']
            
        elif cmd in ['setposa', 'setposb']:
            # Set absolute position of motors
            if len(cmd_parts) > 1:
                try:
                    positions = cmd_parts[1].split(',')
                    motors = self.laser_motors if cmd == 'setposa' else self.monochromator_motors
                    
                    for i, pos in enumerate(positions[:4]):
                        if pos.strip():
                            motors[i] = int(pos)
                    
                    return ['S0:Position set', '#CF']
                except ValueError:
                    return ['F0:Invalid position values', '#CF']
            return ['F0:Missing position values', '#CF']
            
        # Motor movement commands (l1, l2, g1, g2, etc.)
        elif cmd in ['l1', 'l2', 'l3', 'l4', 'g1', 'g2', 'g3', 'g4']:
            if len(cmd_parts) > 1:
                try:
                    steps = int(cmd_parts[1])
                    motor_type = 'A' if cmd.startswith('l') else 'B'  # laser or monochromator
                    motor_index = int(cmd[1]) - 1  # Convert to 0-based index
                    
                    if motor_type == 'A':
                        self.laser_motors[motor_index] += steps
                    else:
                        self.monochromator_motors[motor_index] += steps
                        
                    return ['S0:Success', '#CF']
                except (ValueError, IndexError):
                    return ['F0:Invalid command', '#CF']

        # Default for unrecognized commands
        return ['F0:Unknown command', '#CF']
    
    def get_laser_motor_positions(self):
        """Return simulated laser motor positions"""
        return self.laser_motors
    
    def get_monochromator_motor_positions(self):
        """Return simulated monochromator motor positions"""
        return self.monochromator_motors
    
    def initialise(self):
        """Initialize the simulated Arduino"""
        self.connect()
        print("Simulated Arduino initialized")


class SimulatedCamera:
    """Simulated camera for testing without hardware"""
    
    def __init__(self, interface=None, report=False, simulate=True, **kwargs):
        self.simulate = simulate
        self.report = report

        self.temperature = -5.0
        self.exposure = 500  # ms
        self.roi = (0, 0, 2048, 148)
        self.binning = 1
        self.gain = 0
        self.img_mode = 1
        self.fan_speed = 3
        self.camera_lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.is_running = False
        self.interface = interface
        self.transient_dir = interface.transientDir if interface else "transient"
    
    def initialise(self):
        """Initialize the simulated camera"""
        print("Simulated camera initialized")
        return "Simulated camera initialized"
    
    def refresh(self):
        """Refresh the simulated camera"""
        print("Refreshing simulated camera")
        return "Camera refreshed"
    
    def close_camera(self):
        """Close the simulated camera"""
        print("Simulated camera closed")
    
    def _generate_simulated_image(self, width=2048, height=148):
        """Generate a simulated spectral image with Gaussian peak"""
        img = np.zeros((height, width), dtype=np.uint16)
        
        # Create a 1D Gaussian peak profile for spectral data
        x = np.arange(width)
        center = width // 2
        sigma = width // 40  # Width of the peak
        amplitude = 40000  # Height of the peak
        
        # Calculate Gaussian with some variation based on current settings
        # Adjust position based on simulated wavelength settings
        center_shift = (self.gain - 1) * 100  # Just an example of how settings could affect output
        gaussian = amplitude * np.exp(-((x - (center + center_shift))**2) / (2 * sigma**2))
        
        # Add some noise
        noise_level = 800
        noise = np.random.normal(0, noise_level, width)
        
        # Create the spectral line
        spectral_line = gaussian + noise
        spectral_line = np.clip(spectral_line, 0, 65535).astype(np.uint16)
        
        # Fill all rows with this spectral line, with slight variations
        for i in range(height):
            row_noise = np.random.normal(0, noise_level * 0.2, width)
            img[i, :] = np.clip(spectral_line + row_noise, 0, 65535).astype(np.uint16)
        
        # For RGB simulation, expand to 3 channels
        sim_frame = np.expand_dims(img, axis=2)
        
        return sim_frame
    
    def acquire_one_frame(self, save_dir='data', export=True, **kwargs):
        """Acquire a single simulated frame"""
        width, height = self.roi[2], self.roi[3]
        data = self._generate_simulated_image(width, height)
        
        if export:
            self.export_data(data, 'test', overwrite=False, save_dir=save_dir)
        
        return data
    
    def safe_acquisition(self, target_temp=-5, **kwargs):
        """Simulate temperature checking and image acquisition"""
        # Randomly fluctuate temperature
        self.temperature += np.random.normal(0, 0.2)
        
        if self.temperature < target_temp:
            print(f"Temperature stable ({self.temperature:.1f}°C). Acquiring frame...")
            return self.acquire_one_frame(**kwargs)
        else:
            print(f"Camera too hot ({self.temperature:.1f}°C). Waiting...")
            # Cool down in simulation
            self.temperature -= 1.0
            time.sleep(0.5)  # Shorter wait for simulation
            return self.safe_acquisition(target_temp, **kwargs)
    
    def acquire_transient(self, save_dir='transient', export=True, **kwargs):
        """Acquire a single frame for transient viewing"""
        return self.acquire_one_frame(save_dir=save_dir, export=export, **kwargs)
    
    def start_continuous_acquisition(self):
        """Start continuous acquisition in a separate thread"""
        if self.is_running:
            print("Camera is already running continuous acquisition!")
            return
        
        def continuous_task():
            self.stop_flag.clear()
            
            while not self.stop_flag.is_set():
                try:
                    with self.camera_lock:
                        data = self.acquire_one_frame(export=False)
                    
                    # Save to transient directory
                    self.export_data(data, 'transient_data', save_dir=self.transient_dir, overwrite=True)
                    time.sleep(0.1)  # Simulate frame rate
                except Exception as e:
                    print(f"Acquisition error: {e}")
                    break
        
        acq_thread = threading.Thread(target=continuous_task, daemon=True)
        acq_thread.start()
        
        self.is_running = True
        print("Started continuous acquisition.")
    
    def stop_continuous_acquisition(self):
        """Stop the continuous acquisition thread"""
        print("Stopping continuous acquisition.")
        self.stop_flag.set()
        self.is_running = False
    
    def set_roi(self, roi_tuple):
        """Set the region of interest"""
        if roi_tuple == 'full':
            self.roi = (0, 0, 2048, 2048)
        elif isinstance(roi_tuple, (list, tuple)) and len(roi_tuple) == 4:
            self.roi = tuple(int(x) if isinstance(x, (int, float, str)) else x for x in roi_tuple)
        else:
            print("Invalid ROI format")
        
        print(f"ROI set to {self.roi}")
        return self.roi
    
    def set_acqtime(self, value):
        """Set the acquisition/exposure time"""
        try:
            self.exposure = float(value)
            print(f"Set exposure to {self.exposure}")
        except ValueError:
            print("Invalid exposure value")
    
    def set_hardware_binning(self, binning_level=1):
        """Set hardware binning level"""
        try:
            self.binning = int(binning_level)
            print(f"Hardware binning set to level {self.binning}")
        except ValueError:
            print("Invalid binning level")
    
    def set_image_and_gain(self, img_mode=1, gain_level=0):
        """Set image mode and gain settings"""
        self.img_mode = img_mode
        self.gain = gain_level
        print(f"Set image mode to {img_mode} and gain to {gain_level}")
    
    def set_fan_speed(self, speed=3):
        """Set the fan speed"""
        self.fan_speed = speed
        print(f"Fan speed set to {speed}")
    
    def check_camera_temperature(self, report=True):
        """Check the simulated camera temperature"""
        # Add some random fluctuation for realism
        self.temperature += np.random.normal(0, 0.1)
        
        if report:
            print(f"Camera Temperature: {self.temperature:.2f}°C")
        
        return self.temperature
    
    def export_data(self, data, filename='default', save_dir=None, overwrite=False):
        """Export simulated data to file"""
        if save_dir is None:
            save_dir = 'data'
            
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
        
        if overwrite:
            filepath = os.path.join(save_dir, f'{filename}.npy')
        else:
            # Generate a unique filename
            index = 0
            while os.path.exists(os.path.join(save_dir, f'{filename}_{index}.npy')):
                index += 1
            filepath = os.path.join(save_dir, f'{filename}_{index}.npy')
        
        np.save(filepath, data)
        if 'transient' not in save_dir:
            print(f'Data saved to {filepath}')
    
    def camera_info(self):
        """Print information about the simulated camera"""
        print("\nSimulated Camera Parameters:")
        print(f"  ROI: {self.roi}")
        print(f"  Exposure: {self.exposure} ms")
        print(f"  Temperature: {self.temperature:.2f}°C")
        print(f"  Binning Level: {self.binning}")
        print(f"  Image Mode: {self.img_mode}")
        print(f"  Gain: {self.gain}")
        print(f"  Fan Speed: {self.fan_speed}")


class SimulatedTriax:
    """Simulated TRIAX spectrometer"""
    
    def __init__(self, interface=None):
        self.spectrometer_position = 380000  # Initial value
    
    def initialise(self):
        """Initialize the simulated spectrometer"""
        print("Simulated TRIAX spectrometer initialized")
        return self.spectrometer_position
    
    def get_spectrometer_position(self):
        """Get the current position of the simulated spectrometer"""
        return self.spectrometer_position
    
    def get_triax_steps(self):
        """Get the current steps of the simulated spectrometer"""
        return self.spectrometer_position
    
    def go_to_wavelength(self, wavelength):
        """Move the simulated spectrometer to a specific wavelength"""
        try:
            wavelength = float(wavelength)
            # Simple linear relationship between wavelength and steps for simulation
            # In reality this would use a calibration function
            self.spectrometer_position = int(380000 + (wavelength - 700) * 100)
            print(f"Simulated TRIAX moved to {wavelength} nm (position: {self.spectrometer_position})")
            return "S0"
        except ValueError:
            print("Invalid wavelength value")
            return "F0"
    
    def go_to_position(self, position):
        """Move the simulated spectrometer to a specific position"""
        try:
            self.spectrometer_position = int(position)
            print(f"Moved to position {self.spectrometer_position}")
            return "OK"
        except ValueError:
            print("Invalid position value")
            return "Error"
    
    def send_command(self, command):
        """Process commands sent to the spectrometer"""
        cmd_parts = command.split(' ')
        cmd = cmd_parts[0].lower()
        
        if cmd in ['rg', 'read_grating', 'get_grating_steps']:
            return f'F{self.spectrometer_position}'
        
        elif cmd in ['mg', 'move_grating']:
            if len(cmd_parts) > 1:
                try:
                    steps = int(cmd_parts[1])
                    self.spectrometer_position += steps
                    return 'o'  # Success response
                except ValueError:
                    return 'Error: Invalid step value'
        
        # Other commands can be handled similarly
        return 'o'  # Default success response


class SimulatedInstrument:
    """Base class for all simulated instruments"""
    
    def __init__(self, interface=None):
        self.interface = interface
        self.simulate = True
        self.command_functions = {}
        
    def initialise(self):
        """Initialize the simulated instrument"""
        print(f"Initialized simulated {self.__class__.__name__}")
        return f"Simulated {self.__class__.__name__} initialized"


class SimulatedMonochromator(SimulatedInstrument):
    """Simulated monochromator class"""
    
    def __init__(self, interface=None, simulate=True):
        super().__init__(interface)
        self.simulate = simulate
        self.wavelength = 700.0  # nm
        self.grating_position = 1  # Current grating position
        
        self.command_functions = {
            'set_wavelength': self.set_wavelength,
            'get_wavelength': self.get_wavelength
        }
    
    def set_wavelength(self, wavelength):
        """Set the monochromator to a specific wavelength"""
        try:
            self.wavelength = float(wavelength)
            print(f"Monochromator set to {self.wavelength} nm (simulated)")
            return f"Wavelength set to {self.wavelength} nm"
        except Exception as e:
            print(f"Error setting wavelength: {e}")
            return "Error setting wavelength"
    
    def get_wavelength(self):
        """Get the current wavelength of the monochromator"""
        print(f"Current monochromator wavelength: {self.wavelength} nm (simulated)")
        return self.wavelength


class SimulatedLaser(SimulatedInstrument):
    """Simulated laser class"""
    
    def __init__(self, interface=None, simulate=True):
        super().__init__(interface)
        self.simulate = simulate
        self.power = 50.0  # Power in percent
        self.wavelength = 785.0  # nm
        self.is_on = False
        
        self.command_functions = {
            'set_power': self.set_power,
            'get_power': self.get_power,
            'turn_on': self.turn_on,
            'turn_off': self.turn_off
        }
    
    def initialise(self):
        """Initialize the laser"""
        print("Simulated laser initialized")
        self.is_on = False
        self.power = 50.0
        return "Simulated laser initialized"
    
    def set_power(self, power):
        """Set the laser power"""
        try:
            self.power = float(power)
            if self.power < 0:
                self.power = 0
            elif self.power > 100:
                self.power = 100
                
            print(f"Laser power set to {self.power}% (simulated)")
            return f"Power set to {self.power}%"
        except Exception as e:
            print(f"Error setting power: {e}")
            return "Error setting power"
    
    def get_power(self):
        """Get the current laser power"""
        print(f"Current laser power: {self.power}% (simulated)")
        return self.power
    
    def turn_on(self):
        """Turn the laser on"""
        self.is_on = True
        print("Laser turned on (simulated)")
        return "Laser turned on"
    
    def turn_off(self):
        """Turn the laser off"""
        self.is_on = False
        print("Laser turned off (simulated)")
        return "Laser turned off"


class SimulatedStageControl(SimulatedInstrument):
    """Simulated stage control for microscope"""
    
    def __init__(self, interface=None, simulate=True):
        super().__init__(interface)
        self.simulate = simulate
        self.position = {"x": 0.0, "y": 0.0, "z": 0.0}  # mm
        self.speed = 1.0  # mm/s
        
        self.command_functions = {
            'move': self.move_stage,
            'home': self.home_stage,
            'get_position': self.get_position
        }
    
    def move_stage(self, axis=None, distance=None):
        """Move the stage by a specified distance"""
        if axis is None or distance is None:
            print("Missing axis or distance parameters")
            return "Error: Missing parameters"
            
        try:
            axis = axis.lower()
            distance = float(distance)
            
            if axis not in self.position:
                print(f"Unknown axis: {axis}")
                return f"Error: Unknown axis {axis}"
                
            # Simulate movement time
            time.sleep(abs(distance) / self.speed)
            
            self.position[axis] += distance
            print(f"Moved {axis}-axis by {distance} mm to {self.position[axis]} mm (simulated)")
            return f"Moved to {self.position[axis]} mm"
        except Exception as e:
            print(f"Movement error: {e}")
            return f"Error: {e}"
    
    def home_stage(self, axis=None):
        """Home the stage (move to origin)"""
        if axis is None:
            # Home all axes
            time.sleep(sum(abs(pos) for pos in self.position.values()) / self.speed)
            self.position = {"x": 0.0, "y": 0.0, "z": 0.0}
            print("All axes homed (simulated)")
            return "All axes homed"
        else:
            # Home specific axis
            try:
                axis = axis.lower()
                if axis not in self.position:
                    print(f"Unknown axis: {axis}")
                    return f"Error: Unknown axis {axis}"
                
                time.sleep(abs(self.position[axis]) / self.speed)
                self.position[axis] = 0.0
                print(f"{axis}-axis homed (simulated)")
                return f"{axis}-axis homed"
            except Exception as e:
                print(f"Homing error: {e}")
                return f"Error: {e}"
    
    def get_position(self, axis=None):
        """Get the current position of the stage"""
        if axis is None:
            # Return all positions
            print(f"Current position: X={self.position['x']}, Y={self.position['y']}, Z={self.position['z']} mm (simulated)")
            return self.position
        else:
            # Return specific axis position
            try:
                axis = axis.lower()
                if axis not in self.position:
                    print(f"Unknown axis: {axis}")
                    return None
                    
                print(f"Current {axis}-axis position: {self.position[axis]} mm (simulated)")
                return self.position[axis]
            except Exception:
                return None


# Simulated hardware factories

def get_simulated_hardware(interface, hardware_type, **kwargs):
    """Factory function to get appropriate simulated hardware"""
    hardware_classes = {
        'arduino': SimulatedArduino,
        'camera': SimulatedCamera,
        'triax': SimulatedTriax,
        'laser': SimulatedLaser,
        'monochromator': SimulatedMonochromator,
        'stage': SimulatedStageControl
    }
    
    if hardware_type.lower() not in hardware_classes:
        raise ValueError(f"Unknown hardware type: {hardware_type}")
    
    return hardware_classes[hardware_type.lower()](interface, **kwargs)


# Helper function to dynamically replace real hardware with simulated hardware
def inject_simulated_hardware(microscope_instance):
    """
    Replace real hardware components with simulated versions in an existing
    microscope instance.
    """
    # Create simulated hardware instances
    sim_controller = SimulatedArduino(microscope_instance.interface)
    sim_camera = SimulatedCamera(microscope_instance.interface)
    sim_triax = SimulatedTriax(microscope_instance.interface)
    sim_laser = SimulatedLaser(microscope_instance.interface)
    sim_monochromator = SimulatedMonochromator(microscope_instance.interface)
    sim_stage = SimulatedStageControl(microscope_instance.interface)
    
    # Replace the hardware components
    microscope_instance.controller = sim_controller
    microscope_instance.camera = sim_camera
    microscope_instance.spectrometer = sim_triax
    microscope_instance.laser = sim_laser
    microscope_instance.monochromator = sim_monochromator
    microscope_instance.stage = sim_stage
    
    # Update the motion control's controller reference
    microscope_instance.motion_control.controller = sim_controller
    
    # Mark as simulated
    microscope_instance.simulate = True
    
    print("Hardware components replaced with simulated versions")
    return microscope_instance