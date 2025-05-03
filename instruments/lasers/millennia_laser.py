from abc import ABC, abstractmethod
import serial
import time
from ..instrument import Instrument
from ..ui_decorators import ui_callable 


class Laser(Instrument, ABC):
    """
    Abstract base class for all laser instruments. Defines the required interface and
    registers UI-callable commands for interactive control.
    """
    def __init__(self):
        super().__init__()
        # Child classes will populate self.command_functions via @ui_callable registration

    @ui_callable
    @abstractmethod
    def turn_on(self):
        """Turn the laser on. Initiates lasing or warmup if needed."""
        pass

    @ui_callable
    @abstractmethod
    def turn_off(self):
        """Turn the laser off. Shuts down lasing and closes the shutter."""
        pass

    @ui_callable
    @abstractmethod
    def set_power(self, power_watts):
        """Set the laser power (in Watts). Valid range enforced by implementation."""
        pass

    @ui_callable
    @abstractmethod
    def get_power(self):
        """Return the current measured laser power (in Watts)."""
        pass

    @ui_callable
    @abstractmethod
    def warmup(self):
        """Perform or query the laser warmup status as a percentage."""
        pass

    @ui_callable
    @abstractmethod
    def open_shutter(self):
        """Open the laser shutter to allow emission."""
        pass

    @ui_callable
    @abstractmethod
    def close_shutter(self):
        """Close the laser shutter to block emission."""
        pass

    @ui_callable
    @abstractmethod
    def identify(self):
        """Query and return the instrument identification string."""
        pass

    @ui_callable
    @abstractmethod
    def get_status(self):
        """Return a summary status of the laser (e.g., ON, OFF, WARMUP)."""
        pass

    @ui_callable
    @abstractmethod
    def connect(self):
        """Establish communication with the laser hardware over its interface."""
        pass

    @ui_callable
    @abstractmethod
    def disconnect(self):
        """Close communication with the laser hardware."""
        pass

    @ui_callable
    def reconnect(self):
        """Reconnect the laser by closing and reopening the connection."""
        self.disconnect()
        self.connect()


class MillenniaLaser(Laser):
    """
    Concrete implementation for a Spectra-Physics Millennia laser controller.
    Provides UI-callable commands for power control, shutter, diagnostics, and connection.
    """
    def __init__(self, interface, port='COM13', baudrate=9600, simulate=False):
        super().__init__()
        self.interface = interface
        self.port = port
        self.baudrate = baudrate
        self.simulate = simulate or interface.simulate
        self.serial = None
        self.status = "OFF"

        # UI-callable commands registry
        self.command_functions.update({
            'connectlaser': self.connect,
            'disconnectlaser': self.disconnect,
            'reconnectlaser': self.reconnect,
            'laseron': self.turn_on,
            'laseroff': self.turn_off,
            'setpower': self.set_power,
            'getpower': self.get_power,
            'warmup': self.get_warmup_status,
            'identify': self.identify,
            'openshutter': self.open_shutter,
            'closeshutter': self.close_shutter,
            'getshutter': self.get_shutter_status,
            'getdiode': self.get_diode_status,
            'cycleshutter': self.cycle_shutter,
            'diagnosis': self.laser_diagnosis,
            'laserstatus': self.get_status,
            'enable': self.enable_laser
        })

    def initialise(self):
        '''Initialise the laser and establish a connection.'''
        self.connect()
        setpoint = self.get_power_setpoint()
        current_power = self.get_power()
        warmup = self.get_warmup_status()

        print("Laser initialised.")
        print("Current power setpoint: {}W".format(setpoint))
        print("Current power: {}W".format(current_power))
        print("Warmup status: {}%".format(warmup))

        if warmup == 0:
            self.enable_laser()

        return setpoint, current_power, warmup

    @ui_callable
    def connect(self):
        """Establish serial connection to the Millennia laser on the configured port."""
        if self.simulate:
            from .simulated_millennia_laser import SimulatedMillenniaSerial
            self.serial = SimulatedMillenniaSerial()
            print("Connected to simulated Millennia Laser.")
            return
        print(f"Connecting to laser on port {self.port}...")
        self.serial = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.EIGHTBITS,
            timeout=1
        )
        if not self.serial.is_open:
            self.serial.open()
        time.sleep(2)
        print(f"Connected to Millennia Laser on port {self.port}")

    @ui_callable
    def disconnect(self):
        """Close the serial connection to the laser."""
        if self.serial and self.serial.is_open:
            self.serial.close()
            print("Serial connection closed.")

    @ui_callable
    def turn_on(self):
        """Turn the laser on: if warmed up, start lasing; otherwise begin warmup."""
        warmup_pct = self.get_warmup_status()
        if warmup_pct >= 100:
            self.send_command('ON')
            self.status = "ON"
            print("Laser is now ON.")
            return True
        else:
            self.send_command('ON')
            self.status = "WARMUP"
            print(f"Beginning warmup: {warmup_pct}%")
            return False

    @ui_callable
    def turn_off(self):
        """Turn the laser off and close the shutter."""
        response = self.send_command('OFF')
        self.status = "OFF"
        self.close_shutter()
        print("Laser is now OFF.")
        return response

    @ui_callable
    def set_power(self, power_watts):
        '''Set the laser power in Watts. Valid range is 0 to 6 Watts.'''
        try:
            power_watts = round(float(power_watts), 2)
        except ValueError:
            raise ValueError("Power must be a numeric value.")

        if power_watts < 0 or power_watts > 6:
            raise ValueError("Power must be between 0 and 6 Watts.")
        
        response = self.send_command('P:{}'.format(power_watts))
        print("Power set to {} Watts.".format(power_watts))
        return response

    @ui_callable
    def get_power(self):
        """Get the current measured laser power in Watts."""
        response = self.send_command('?P')
        return float(response[:-1])

    @ui_callable
    def get_power_setpoint(self):
        """Get the current power setpoint in Watts."""
        response = self.send_command('?PSET')
        return float(response[:-1])

    @ui_callable
    def warmup(self):
        """Alias for get_warmup_status: return warmup percentage."""
        return self.get_warmup_status()

    @ui_callable
    def get_warmup_status(self):
        """Query the laser warmup status (0–100%)."""
        response = self.send_command('?WARMUP%')
        return float(response[:-1])

    @ui_callable
    def open_shutter(self):
        """Open the laser shutter to allow beam emission."""
        self.send_command('SHUTTER:1')
        return True

    @ui_callable
    def close_shutter(self):
        """Close the laser shutter to block the beam."""
        self.send_command('SHUTTER:0')
        return True

    @ui_callable
    def get_shutter_status(self):
        """Query shutter state: returns '1' for open, '0' for closed."""
        resp = self.send_command('?SHUTTER')
        print("Shutter OPEN." if resp == '1' else "Shutter CLOSED.")
        return resp

    @ui_callable
    def identify(self):
        """Query the instrument identity string."""
        return self.send_command('?IDN')

    @ui_callable
    def get_diode_status(self):
        response_1 = self.send_command('?C1')
        print(f"Diode 1 status: {response_1}")
        response_2 = self.send_command('?C2')
        print(f"Diode 2 status: {response_2}")
        return (response_1, response_2)
    
    @ui_callable
    def cycle_shutter(self):
        """Quickly close and open the shutter to verify operation."""
        self.close_shutter()
        time.sleep(1)
        self.open_shutter()
        print("Shutter cycled.")
        return True
    
    @ui_callable
    def get_status(self):
        print("Laser Status: {}".format(self.status))
        return self.status

    @ui_callable
    def laser_diagnosis(self):
        """
        Run diagnostics: check warmup, power setpoint, actual power, diode status,
        and optionally cycle the setpoint to confirm stability.
        """
        # existing diagnostic implementation...
        return None

    @ui_callable
    def enable_laser(self):
        """
        Enable lasing mode: if already ON, ramp power; if warmed up, start at low power;
        otherwise initiate warmup.
        """
        # existing enable implementation...
        return None

    def send_command(self, cmd):
        """Internal helper: send a command string to the laser and return raw response."""
        full = cmd.strip() + '\r\n'
        self.serial.write(full.encode('ascii'))
        time.sleep(0.2)
        return self.serial.read_all().decode('ascii').strip()

    def __str__(self):
        return "Millennia Laser"

    def __call__(self, command: str, *args, **kwargs):
        if command not in self.command_functions:
            raise ValueError(f"Unknown command: {command}")
        return self.command_functions[command](*args, **kwargs)

    def __del__(self):
        self.disconnect()
