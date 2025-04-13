import serial
import time

def ui_callable(func):
    """Decorator to mark functions as callable from the UI."""
    def wrapper(*args, **kwargs):
        return func(*args, **kwargs)
    return wrapper


class Instrument:
    """Base class for instruments."""
    def __init__(self):
        pass

    def connect(self):
        raise NotImplementedError("Connect method must be implemented.")

    def disconnect(self):
        raise NotImplementedError("Disconnect method must be implemented.")

class MillenniaLaser(Instrument):
    def __init__(self, interface, port='COM13', baudrate=9600, simulate=False):
        super().__init__()
        self.interface = interface
        self.port = port
        self.baudrate = baudrate
        self.simulate = simulate
        self.ser = None
        self.status = "OFF"

        self.command_functions = {
            'laseron': self.turn_on,
            'laseroff': self.turn_off,
            'setpower': self.set_power,
            'getpower': self.get_power,
            'warmup': self.get_warmup_status,
            'openshutter': self.open_shutter,
            'closeshutter': self.close_shutter,
            'identify': self.identify,
            'getdiode': self.get_diode_status,
            'enable': self.enable_laser,
            'status': self.get_status,
            'shutterstatus': self.get_shutter_status,
            'getpowerset' : self.get_power_setpoint,
        }

        self.connect()

    def connect(self):
        if self.simulate:
            print("Simulated connection.")
            return

        self.ser = serial.Serial(
            port=self.port,
            baudrate=self.baudrate,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            bytesize=serial.EIGHTBITS,
            timeout=1
        )

        if not self.ser.is_open:
            self.ser.open()

        time.sleep(2)
        print(f"Connected to laser on port {self.port}")

    @ui_callable
    def get_status(self):
        print("Laser Status: {}".format(self.status))
        return self.status

    @ui_callable
    def get_shutter_status(self):
        '''Returns the current status of the shutter. This is a simple command to check if the shutter is open or closed.'''
        response = self.send_command('?SHUTTER')
        if response == "1":
            print("Shutter is OPEN.")
        elif response == "0":
            print("Shutter is CLOSED.")
        else:
            print("Unknown shutter status.")
        return response

    @ui_callable
    def laser_diagnosis(self):
        '''Runs through a series of checks to determine the status of the laser. This includes checking the power setpoint, actual power, and diode status.'''
        print("Running laser diagnostics...")

        def check_status():

            diode_power = self.get_diode_status()
            diode_power = [float(x[:-2]) for x in diode_power]
            power_setpoint = self.get_power_setpoint()
            power_actual = self.get_power()
            warmup = self.get_warmup_status()

            print("Current status: {}".format(self.status))
            print("Warmup: {}".format(warmup))
            print("Power setpoint: {}, Power actual: {}".format(power_setpoint, power_actual))
            print("Diode power: {}".format(diode_power))
            return diode_power, power_setpoint, power_actual, warmup
        
        def cycle_power_setpoint():
            if power_actual < power_setpoint*0.8:
                print("Power not yet stabilised.")
            print("Cycling setpoint...")

            self.set_power(0.05)
            time.sleep(2)
            self.set_power(power_setpoint)
            time.sleep(5)
            power_actual = self.get_power()

            if power_actual < power_setpoint*0.8:
                print("Power not stabilised after cycling setpoint. Inspect laser manually.")
                return False
            else:
                print("Power stabilised after cycling setpoint.")
                self.status = "ON"
                print("Laser is ON at {}.".format(power_setpoint))
                return True

        diode_power, power_setpoint, power_actual, warmup = check_status()
        if warmup != 100:
            print("Laser is warming up. Please wait.")
            return False
        
        cycle_power_setpoint()

        print("Laser diagnostics complete. All checks passed. If any issues persist, please inspect the laser manually.")
        print("Remember to cycle the shutter - it sometimes gets stuck.")

    @ui_callable
    def cycle_shutter(self):
        '''Cycles the shutter to ensure it is functioning properly. This is a simple command to open and close the shutter.'''
        self.close_shutter()
        time.sleep(1)
        self.open_shutter()
        print("Shutter cycled.")
        return True

    @ui_callable
    def enable_laser(self):
        '''Handles the turning on of the laser, from warmup to on state. The final step is to open the shutter.'''

        warmup = self.get_warmup_status()
        power = self.get_power()
        
        if power >= 3.5:
            print("Laser is already ON at {} watts. Change power with 'setpower' command.".format(power))
            return True

        if self.status == "ON":
            power = self.get_power()
            print("Laser is ON at {} watts. Ramping to 4.0 Watts".format(power))
            self.close_shutter()
            self.set_power(4.0)
            print("Laser is now ON at 4.0 watts. Open the shutter to pump the tunable cavity (NIR laser).")
            return True
        
        elif warmup == 100:
            response = self.send_command('ON')
            self.set_power(0.05)
            self.status = "ON"
            print("Laser is now ON in low-power mode (not lasing). Return in 2 minutes to increase power.")
            return True
        
        elif 0 < warmup < 100:
            self.status = "WARMUP"
            print("Laser is warming up at {}%. Please wait...".format(warmup))
            return False

        elif warmup == 0:
            print(f"In standby mode. Beginning warmup: {warmup}")
            self.send_command('ON')
            self.status = "WARMUP"
            return False
        
    def disconnect(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("Serial connection closed.")

    def send_command(self, command):
        if self.simulate:
            print(f"Simulated command sent: {command}")
            return "SIMULATED RESPONSE"

        full_command = command.strip() + '\r\n'
        self.ser.write(full_command.encode('ascii'))
        time.sleep(0.2)
        response = self.ser.read_all().decode('ascii').strip()
        return response

    @ui_callable
    def turn_on(self):
        warmup = self.get_warmup_status()
        if warmup == 100:
            response = self.send_command('ON')
            self.status = "ON"
            print("Laser is now ON.")
            return True
        else:
            warmup = self.send_command('ON')
            self.status = "WARMUP"
            print("In standby mode. Beginning warmup: {warmup}")
            return False
        
    @ui_callable
    def get_diode_status(self):
        response_1 = self.send_command('?C1')
        print(f"Diode 1 status: {response_1}")
        response_2 = self.send_command('?C2')
        print(f"Diode 2 status: {response_2}")
        return (response_1, response_2)

    @ui_callable
    def turn_off(self):
        response = self.send_command('OFF')
        return response

    @ui_callable
    def set_power(self, power_watts):
        try:
            power_watts = round(float(power_watts), 2)
        except ValueError:
            raise ValueError("Power must be a numeric value.")

        if power_watts < 0 or power_watts > 6:
            raise ValueError("Power must be between 0 and 6 Watts.")
        
        response = self.send_command('P:{}'.format(power_watts))
        return response

    @ui_callable
    def get_power(self):
        response = self.send_command('?P')
        return float(response[:-1])
    
    @ui_callable
    def get_power_setpoint(self):
        response = self.send_command('?PSET')
        print(f"Power setpoint: {response}")
        return float(response[:-1])

    @ui_callable
    def get_warmup_status(self):
        response = self.send_command('?WARMUP%')
        return float(response[:-1])

    @ui_callable
    def open_shutter(self):
        response = self.send_command('SHUTTER:1')
        return response

    @ui_callable
    def close_shutter(self):
        response = self.send_command('SHUTTER:0')
        return response

    @ui_callable
    def identify(self):
        response = self.send_command('?IDN')
        return response

    def __str__(self):
        return f"MillenniaLaser(port={self.port})"

    def __call__(self, command: str, *args, **kwargs):
        if command not in self.command_functions:
            raise ValueError(f"Unknown laser command: '{command}'")
        return self.command_functions[command](*args, **kwargs)

    def __del__(self):
        self.disconnect()


laser = MillenniaLaser(interface=None, simulate=False)

assess_commands = {key: func for key, func in laser.command_functions.items()}

while True:
    try:
        command = input("Enter command (or 'exit' to quit): ").strip()
        if command.lower() == 'exit':   
            break
        command = command.strip()
        coms = command.split(' ')
        if coms[0] in assess_commands:
            if len(coms) > 1:
                command = coms[0]
                args = coms[1:]
                result = assess_commands[command](*args)
            else:
                result = assess_commands[command]()
            print(f"Result: {result}")
        else:
            print(f"Unknown command: {command}")
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(1)