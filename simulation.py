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

from random import randint
from typing import List, Tuple, Dict, Any, Optional, Union



class SimulatedArduinoSerial:
    """
    Simulates the Arduino-MEGA-based RamanMicroscope controller.
    Methods:
      send_command(cmd: str) -> str
        Send an envelope command (including its leading/trailing char)
        and get back exactly what the Arduino would have printed.
    """

    MODULES = ('1','2','3','4')
    MOTORS  = ('A','X','Y','Z')
    # Steps to move motor 2A (beamsplitters) into Raman mode; image mode is
    # the negation. Value taken from the firmware, which is the ground
    # truth: arduino_mega_develop.ino ramanMode() does stepperA2.move(6000)
    # and imageMode() does stepperA2.move(-6000).
    #
    # This was previously a commented-out '-100_000', which is neither the
    # right sign nor the right magnitude -- that number is the homing
    # slow-approach move elsewhere in the same firmware file, evidently
    # copied across by mistake.
    #
    # NOTE: this mirrors a LEGACY firmware path that the application never
    # exercises. The firmware brackets these commands with
    # "// Legacy mode commands", and nothing in the codebase sends the bare
    # 'ramanmode'/'imagemode' strings -- Microscope.raman_mode() moves the
    # mode motor by microscope_config.json's mode: 100000 through the o...o
    # envelope instead. detect_microscope_mode() then tests position against
    # +/-50000, which is a sentinel it writes itself, not a measurement.
    # Three numbers, one motor. See MODERNIZATION.md 2.3 -- pending a
    # hardware check on whether a limit switch is now fitted to motor 2A.
    RAMAN_MODE_STEPS = 6000

    def __init__(self, com_port=None, baud=None, report=True):
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
        self.buffer = []
        # self.in_waiting = len(self.buffer)  # Simulate serial input buffer

        print("Simulated Arduino initialized")

    @property
    def in_waiting(self) -> int:
        """Return the number of bytes in the buffer."""
        return len(self.buffer)


    def send_command(self, cmd: str) -> str:
        """
        Send an envelope command (including its leading/trailing character)
        and return exactly what the Arduino would have printed.

        This is the synchronous convenience API described in the class
        docstring. The runtime path uses write()/readline() instead, which
        models the real serial buffer; this method is for direct testing
        of the command protocol without the buffer round-trip.
        """
        return self._parse_command(cmd)

    def write(self, cmd: str) -> None:
        """Simulate sending a command to the Arduino."""
        command = cmd.decode().strip()
        response = self._parse_command(command)
        self.buffer.append(response.encode())
        self.buffer.append(b'#CF\r\n')  # Simulate end of command response
        return response
    
    def readline(self) -> str:
        """Simulate reading a line from the Arduino."""
        if self.in_waiting > 0:
            return self.buffer.pop(0)
        else:
            return ''

    def _parse_command(self, cmd: str) -> str:
        """Mimic Serial.readStringUntil('\r\n') + parseCommand + Serial responses."""
        if cmd.startswith('o') and cmd.endswith('o'):
            # multi–move: o1A1000 2X2000o
            self._parse_multi_move(cmd[1:-1])
            return ''  # Arduino only prints "Moving motor…" per token, but tests usually ignore it
        elif cmd.startswith('g') and cmd.endswith('g'):
            response = self._get_positions(cmd[1:-1])
        elif cmd.startswith('c') and cmd.endswith('c'):
            response = self._check_moving(cmd[1:-1])
        elif cmd.startswith('s') and cmd.endswith('s'):
            response = self._set_positions(cmd[1:-1])
        elif cmd.startswith('m') and cmd.endswith('m'):
            response = self._hardware_command(cmd[1:-1])
        elif cmd.startswith('h') and len(cmd) == 3:
            response = self._home_motor(cmd[1], cmd[2])
        elif cmd == 'imagemode':
            response = self._image_mode()
        elif cmd == 'ramanmode':
            response = self._raman_mode()
        else:
            response = 'Unrecognized command format'
        
        return f"{response}\r\n" # Simulate Arduino response format

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
        g1A 2Xg  →  "1A:1000 2X:2000 "
        """
        out = []
        for token in content.split():
            if len(token) < 2:
                continue
            m, mt = token[0], token[1]
            if m in self.current and mt in self.current[m]:
                pos = self.current[m][mt]
                out.append(f"{m}{mt}:{pos}")
        return ' '.join(out)

    def _check_moving(self, content: str) -> str:
        """
        c1A 2Xc →  "1A:false 2X:false "
        (always false here)
        """
        out = []
        for token in content.split():
            if len(token) < 2:
                continue
            m, mt = token[0], token[1]
            if m in self.current and mt in self.current[m]:
                out.append(f"{m}{mt}:false")
        return ' '.join(out)

    def _set_positions(self, content: str) -> str:
        """
        s1A1000 3Z-500s → "Set motor 1A position to 1000" (last token only)
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
                resp = f"Set motor {m}{mt} position to {pos}"
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
            return "Unknown hardware command."

    def _mono_shutter(self, state: str) -> str:
        self.g_shutter = (state == 'on')
        return "Shutter open." if self.g_shutter else "Shutter closed."

    def _read_ldr(self) -> str:
        # Arduino prints 't' + summed reading; here we'll just return one value
        return f"t{self.ldr_value}"

    def _toggle_led(self, state: str) -> str:
        on = (state == 'on')
        self.led1 = self.led2 = on
        return "LED on" if on else "LED off"

    # ─── homing & modes ───────────────────────────────────────────────────────

    def _home_motor(self, module: str, motor: str) -> str:
        if module in self.current and motor in self.current[module]:
            self.current[module][motor] = 0
            return f"Homed motor {module}{motor} at position 0"
        else:
            return "Invalid motor."

    def _raman_mode(self) -> str:
        # module 2, motor A  → +6000 steps
        self._move('2', 'A', self.RAMAN_MODE_STEPS)
        return "Moving to Raman Mode..."

    def _image_mode(self) -> str:
        # module 2, motor A  → -6000 steps
        self._move('2', 'A', -self.RAMAN_MODE_STEPS)
        return "Moving to Image Mode..."


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
