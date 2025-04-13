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

        self.command_functions = {
            'laseron': self.turn_on,
            'laseroff': self.turn_off,
            'setpower': self.set_power,
            'getpower': self.get_power,
            'warmup': self.get_warmup_status,
            'openshutter': self.open_shutter,
            'closeshutter': self.close_shutter,
            'identify': self.identify
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
        if warmup == "100%":
            response = self.send_command('ON')
            return response
        else:
            warmup = self.send_command('ON')
            print("In standby mode. Beginning warmup: {warmup}")
            return warmup

    @ui_callable
    def turn_off(self):
        response = self.send_command('OFF')
        return response

    @ui_callable
    def set_power(self, power_watts):
        response = self.send_command(f'P:{power_watts:.2f}')
        return response

    @ui_callable
    def get_power(self):
        response = self.send_command('?P')
        return response

    @ui_callable
    def get_warmup_status(self):
        response = self.send_command('?WARMUP%')
        return response

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
        if command in assess_commands:
            result = assess_commands[command]()
            print(f"Result: {result}")
        else:
            print(f"Unknown command: {command}")
    except Exception as e:
        print(f"Error: {e}")
        time.sleep(1)