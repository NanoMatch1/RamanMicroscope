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

class SimulatedArduino:
    """Simulated Arduino controller for stepper motors"""
    
    def __init__(self, interface=None, com_port=None, baud=None, report=True):
        self.laser_motors = [100000, 100000, 0, 0]  # Initial values for laser motors [X, Y, Z, A]
        self.monochromator_motors = [200000, 200000, 0, 0]  # Initial values for monochromator motors [X, Y, Z, A]
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
    
    def __init__(self, interface=None, report=False):
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
    
    def acquire_one_frame(self, save_dir='data', export=True):
        """Acquire a single simulated frame"""
        width, height = self.roi[2], self.roi[3]
        data = self._generate_simulated_image(width, height)
        
        if export:
            self.export_data(data, 'test', overwrite=False, save_dir=save_dir)
        
        return data
    
    def safe_acquisition(self, target_temp=-5):
        """Simulate temperature checking and image acquisition"""
        # Randomly fluctuate temperature
        self.temperature += np.random.normal(0, 0.2)
        
        if self.temperature < target_temp:
            print(f"Temperature stable ({self.temperature:.1f}°C). Acquiring frame...")
            return self.acquire_one_frame()
        else:
            print(f"Camera too hot ({self.temperature:.1f}°C). Waiting...")
            # Cool down in simulation
            self.temperature -= 1.0
            time.sleep(0.5)  # Shorter wait for simulation
            return self.safe_acquisition(target_temp)
    
    def acquire_transient(self, save_dir='transient', export=True):
        """Acquire a single frame for transient viewing"""
        return self.acquire_one_frame(save_dir=save_dir, export=export)
    
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


# Simulated hardware factories

def get_simulated_hardware(interface, hardware_type, **kwargs):
    """Factory function to get appropriate simulated hardware"""
    hardware_classes = {
        'arduino': SimulatedArduino,
        'camera': SimulatedCamera,
        'triax': SimulatedTriax
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
    
    # Replace the hardware components
    microscope_instance.controller = sim_controller
    microscope_instance.camera = sim_camera
    microscope_instance.spectrometer = sim_triax
    
    # Update the motion control's controller reference
    microscope_instance.motion_control.controller = sim_controller
    
    # Mark as simulated
    microscope_instance.simulate = True
    
    print("Hardware components replaced with simulated versions")
    return microscope_instance