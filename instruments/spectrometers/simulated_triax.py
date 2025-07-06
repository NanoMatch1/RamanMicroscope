from copy import copy

class SimulatedTriaxSerial:

    '''Simulated class for a TRIAX spectrometer serial interface. This class simulates the behavior of a TRIAX spectrometer for testing purposes.
    
    Notes: 
    - only enterance slit can be read and managed, exit slit is not implemented and requires separate logic statements in this self.write() method.'''

    def __init__(self):
        self.spectrometer_position = 105000
        self.enterance_slit_width = 0
        self.response = 'o'
        self.simulate = True  # Flag to indicate this is a simulated interface

        self.command_map = {
        'H0': self.get_spectrometer_position,
        'F0': self._move_grating,
        'j0,0': self._read_enterance_slit,
        'k0,0': self._move_enterance_slit,
        }
        
        print("Connected to TRIAX spectrometer (simulated).")

    def _move_grating(self, steps):
        '''Simulates moving the grating to a specified position in steps.'''
        try:
            steps = int(steps)
        except ValueError:
            print(f'Invalid input for grating position: {steps}')
            return 'Error'
        self.spectrometer_position += int(steps)
        return f"o{self.spectrometer_position}"
    
    def _read_enterance_slit(self, *args):
        '''Simulates reading the current position of the entrance slit.'''
        # For simulation, we return a fixed value or a random one
        return f"o{self.enterance_slit_width}"
    
    def _move_enterance_slit(self, position):
        '''Simulates moving the entrance slit to a specified position.'''
        try:
            position = int(position)
            self.enterance_slit_width += position
            return f"o{self.enterance_slit_width}"
        except ValueError:
            print(f'Invalid input for entrance slit position: {position}')
            return 'Error'

    def write(self, command):
        '''Simulates writing a command to the spectrometer.'''
        if command.startswith('k0,0'):
            value = command.split(',')[-1].strip()
            self.response = self._move_enterance_slit(value)
            return
        
        elif command == 'j0,0':
            self.response = self._read_enterance_slit()
            return

        com = command.split(',')

        if com[0] in self.command_map:
            if len(com) > 1:
                self.response = self.command_map[com[0]](*com[1:])
            else:
                self.response = self.command_map[com[0]]()

    def get_spectrometer_position(self):
        # Simulate reading the current position in steps
        # For example, return a random number of steps
        return f"o{self.spectrometer_position}"
    
    def read(self):
        '''Simulates reading a response from the spectrometer.'''
        response = copy(self.response)
        self.response = 'o'  # Clear the response after reading
        return response
