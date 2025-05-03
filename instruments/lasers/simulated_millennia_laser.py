class SimulatedMillenniaSerial:
    """
    Simulated serial interface for MillenniaLaser; parses commands and returns mock responses.
    """
    def __init__(self):
        self.power_setpoint = 0.0
        self.actual_power = 0.0
        self.warmup_pct = 100.0
        self.shutter_open = False
        self.diode1_current = 25.36  # default simulated current
        self.diode2_current = 25.36
        self.is_open = True
        self._last_response = b""

    def open(self):
        self.is_open = True

    def close(self):
        self.is_open = False

    def write(self, data: bytes):
        cmd = data.decode('ascii').strip().rstrip(';').strip().upper()
        # Handle commands
        if cmd == 'ON':
            if self.warmup_pct >= 100:
                self.actual_power = self.power_setpoint
            # no direct response
            self._last_response = b""
        elif cmd == 'OFF':
            self.actual_power = 0.0
            self._last_response = b""
        elif cmd.startswith('P:'):
            try:
                val = float(cmd[2:])
            except ValueError:
                val = 0.0
            self.power_setpoint = val
            if self.actual_power > 0:
                self.actual_power = val
            self._last_response = b""
        elif cmd == '?P':
            self._last_response = f"{self.actual_power:.2f}W\n".encode('ascii')
        elif cmd == '?PSET':
            self._last_response = f"{self.power_setpoint:.2f}W\n".encode('ascii')
        elif cmd == '?WARMUP%':
            self._last_response = f"{int(self.warmup_pct)}%\n".encode('ascii')
        elif cmd == 'SHUTTER:1':
            self.shutter_open = True
            self._last_response = b""
        elif cmd == 'SHUTTER:0':
            self.shutter_open = False
            self._last_response = b""
        elif cmd == '?SHUTTER':
            val = b"1\n" if self.shutter_open else b"0\n"
            self._last_response = val
        elif cmd == '?IDN':
            self._last_response = b"Simulated MillenniaLaser\n"
        elif cmd == '?C1':
            self._last_response = f"{self.diode1_current:.2f}A\n".encode('ascii')
        elif cmd == '?C2':
            self._last_response = f"{self.diode2_current:.2f}A\n".encode('ascii')
        else:
            # Unknown or unhandled commands
            self._last_response = b""

    def read_all(self):
        resp = self._last_response
        self._last_response = b""
        return resp
