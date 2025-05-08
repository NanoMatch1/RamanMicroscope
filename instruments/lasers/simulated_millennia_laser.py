class SimulatedMillenniaSerial:
    """
    Simulated serial interface for MillenniaLaser; parses commands and returns mock responses.
    """
    def __init__(self):
        self.power_setpoint = 0.0
        self.actual_power = 0.0
        self.warmup_pct = 100.0
        self.shutter_open = False
        # self.diode1_current = 25.36  # default simulated current
        # self.diode2_current = 25.12
        self.is_open = True
        self._last_response = b""

        self.command_map = {
            'ON': self.turn_on,
            'OFF': self.turn_off,
            'P:': self.set_power,
            '?P': self.get_power,
            '?PSET': self.get_power_setpoint,
            '?WARMUP%': self.get_warmup_pct,
            'SHUTTER:1': self.open_shutter,
            'SHUTTER:0': self.close_shutter,
            '?SHUTTER': self.get_shutter_status,
            '?IDN': self.get_idn,
            '?C1': self.get_diode1_current,
            '?C2': self.get_diode2_current,
        }

    def open(self):
        self.is_open = True

    def close(self):
        self.is_open = False

    def set_power(self, power: float):
        try:
            power = float(power)
        except ValueError:
            raise ValueError("Power must be a float.")
        
        if 0 <= power <= 6:
            self.power_setpoint = float(power)
            self.actual_power = self.power_setpoint
        else:
            raise ValueError("Power must be between 0 and 6 Watts.")
        
    def get_power(self) -> str:
        return f"{self.actual_power}W"
        
    def turn_on(self):
        pass

    def turn_off(self):
        pass

    def get_power_setpoint(self) -> str:
        return f"{self.power_setpoint}W"
    
    def get_warmup_pct(self) -> str:
        return f"{self.warmup_pct}%"
    
    def open_shutter(self):
        self.shutter_open = True

    def close_shutter(self):
        self.shutter_open = False
    
    def get_shutter_status(self) -> str:
        return "1" if self.shutter_open else "0"
    
    def get_idn(self) -> str:
        return "Simulated Millennia Laser, Version 1.0, Serial Number 1234567890"
    
    def get_diode1_current(self) -> str:
        return f"{self.diode1_current}A"
    
    def get_diode2_current(self) -> str:
        return f"{self.diode2_current}A"
    
    @property
    def diode1_current(self) -> float:
        return 25.2 if self.power_setpoint > 0.5 else 0.12
    
    @property
    def diode2_current(self) -> float:
        return 25.2 if self.power_setpoint > 0.5 else 0.12

    def handle_command(self, cmd: str):
        # Handle commands with arguments
        if cmd.startswith('P:'):
            self.set_power(float(cmd[2:]))
        else:
            raise ValueError(f"Unknown Laser command: {cmd}")

    def write(self, data: bytes):
        cmd = data.decode('ascii').strip().rstrip(';').strip().upper()

        if cmd in self.command_map:
            response = self.command_map[cmd]()
        else:
            response = self.handle_command(cmd)

        if response is None:
            response = ""

        self._last_response = response.encode('ascii') + b'\r\n'

        # breakpoint()


    def read_all(self):
        return self._last_response
