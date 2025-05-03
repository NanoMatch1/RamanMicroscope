class SimulatedTriaxSerial:

    def __init__(self):
        self.triax_steps = 0

        self.command_map = {
        'H0': triax_steps,
        }
        pass

    def write(self, command):
        # Simulate writing to the serial port
        # print(f"Simulated write: {command}")
        pass

    def read(self):
        pass

    def triax_steps(self):
        # Simulate reading the current position in steps
        # For example, return a random number of steps
        return f"o{self.triax_steps}"

    def get_triax_steps(self):
        '''Polls the spectrometer for position and returns the current position in steps.'''
        response = self._send_command_to_spectrometer(self.message_map['get_grating_steps'])
        self.triax_steps = int(response.strip()[1:])
        return self.triax_steps