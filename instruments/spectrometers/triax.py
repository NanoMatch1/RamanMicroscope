import time
import pyvisa
from ..instrument_base import Instrument
from ..ui_decorators import ui_callable
from simulated_triax import SimulatedTriaxSerial


class Triax(Instrument):
    def __init__(self, interface, simulate=False):
        super().__init__()
        self.interface = interface
        self.simulate = simulate or interface.simulate
        self.calibration_service = interface.calibration_service

        self.command_functions = {
            'get_spectrometer_position': self.get_spectrometer_position,
            'rg': self.get_spectrometer_position,
            'go_to_position': self.go_to_position,
            'ren': self.read_enterance_slit,
            'rex': self.read_exit_slit,
            'men': self.move_enterance_slit,
            'mex': self.move_exit_slit,
            'mg': self.move_grating_relative,
            'initialise': self.initialise_spectrometer,
            'specgrat1': self.default_grating,
            'specgrat2': self.other_grating,
        }

        self.spectrometer_position = 380000

        # 108659 = 750 nm

        self.message_map = {
            'initialise': 'A',
            'specgrat1': 'a0',
            'specgrat2': 'b0',
            'comsmode': '02000',
            'get_grating_steps': 'H0',
            'read_grating': 'H0',
            'rg': 'H0',
            'grating': 'F0,',
            'move_grating': 'F0,',
            'mg': 'F0,',
            'read_enter': 'j0,0',
            'ren': 'j0,0',
            'read_exit': 'j0,3',
            'rex': 'j0,3',
            'move_enter': 'k0,0,',
            'men': 'k0,0,',
            'move_exit': 'k0,3,',
            'mex': 'k0,3,',
            'tpol': 'E', # poll motors after move command sent
            'ccd_mode': 'f0',
            'ccd': 'f0',
            'apd_mode': 'e0',
            'apd': 'e0',
            # 'gotoir': 'F0,375131'
            #'entrance mirror to front enterance': 'c0',
            #'entrance mirror to side enterance': 'd0'
        }

        self._integrity_checker()

    def __str__(self):
        return "TRIAX Spectrometer"
    
    def initialise(self):
        '''Connect and establish primary attributes.'''
        self.connect()
        self.get_spectrometer_position()
        # self.generate_wavelength_axis()
        self.interface.microscope.generate_wavelength_axis() # TODO: move from microscope to spectrometer. Use @property to generate wavelength axis on the fly
        return self.spectrometer_position

    @ui_callable
    def initialise_spectrometer(self):
        '''Initialise the spectrometer.'''
        response = self.send_command('initialise')

    @ui_callable
    def default_grating(self):
        '''Set the default gratin;'g for the spectrometer.'''
        response = self.send_command('specgrat1')
        # print(response)
        return response

    @ui_callable
    def other_grating(self):
        '''Set the other grating for the spectrometer.'''

        response = self.send_command('specgrat2')
        # print(response)
        return response
    
    @ui_callable
    def read_enterance_slit(self):
        '''Read the current position of the entrance slit.'''
        response = self.send_command('read_enter')
        return response
    
    @ui_callable
    def read_exit_slit(self):
        '''Read the current position of the exit slit.'''
        response = self.send_command('read_exit')
        return response
    
    @ui_callable
    def move_enterance_slit(self, position):
        '''Move the entrance slit to the specified position.'''
        response = self.send_command('men {}'.format(position))
        return response
    
    @ui_callable
    def move_exit_slit(self, position):
        '''Move the exit slit to the specified position.'''
        response = self.send_command('mex {}'.format(position))
        return response
    
    @ui_callable
    def move_grating_relative(self, position):
        '''Move the grating the specified number of steps.'''
        response = self.send_command('mg {}'.format(position))
        return response
    
    def go_to_wavelength(self, wavelength):
        '''Moves the spectrometer to the specified wavelength.'''
        try:
            wavelength = float(wavelength)
        except ValueError:
            print('Invalid input')
            return
        
        triax_steps = self.get_triax_steps()
        
        target_steps = round(self.interface.microscope.calibrations.wl_to_triax(wavelength))
        # 
        new_steps = target_steps - triax_steps
        # return if no movement is required
        if new_steps == 0:
            return
        
        print('UNO>g {}>triax'.format(new_steps))

        response = self.send_command('mg {}'.format(new_steps))
        if response == 'o':
            triax_res = self.wait_for_triax(target_steps)
            if triax_res == 'S0':
                print('Triax moved to {} nm'.format(wavelength))
                self.triax_steps = target_steps
                return 'S0'
            else:
                print('Triax move failed: {}'.format(triax_res))
                return 'F0'

        else:
            print('Triax communication failed:')
            print(response)

    def wait_for_triax(self, target_steps, timeout=10):
        '''Polls the spectrometer until the target steps are reached. Note the MOTOR BUSY CHECK (E) on the spectrometer does not send a response with this configuration, so we use this command instead.'''
        start = time.time()
        while True:
            response = self.get_triax_steps()
            if response == target_steps:
                return 'S0'
            time.sleep(0.1)
            if time.time() - start > timeout:
                print('Timeout reached')
                return 'F0'

    

    @ui_callable
    def get_spectrometer_position(self):
        '''Get the current position of the spectrometer in motor steps.'''
        self.spectrometer_position = self.get_triax_steps()
        return self.spectrometer_position
    
    @ui_callable
    def go_to_position(self, position):
        print("Going to the position: {}".format(position))
        command = self.message_map['move_grating'] + str(position)
        response = self._send_command_to_spectrometer(command)
        return response

    def connect(self):
        # Open a connection to the instrument
        if self.simulate:
            self.spectrometer = SimulatedTriaxSerial()
        print("Connecting to TRIAX spectrometer...")
        rm = pyvisa.ResourceManager()
        rm.list_resources()
        breakpoint()
        self.spectrometer = rm.open_resource('GPIB0::1::INSTR')  # Replace with the actual VISA address of your instrument

        self.spectrometer.write('WHERE AM I')
        time.sleep(0.0001)
        self.state = self.spectrometer.read()
        print(self.state)

        print('Connected to TRIAX spectrometer.')

        return self.spectrometer, self.state

    def get_triax_steps(self):
        '''Polls the spectrometer for position and returns the current position in steps.'''
        response = self._send_command_to_spectrometer(self.message_map['get_grating_steps'])
        self.triax_steps = int(response.strip()[1:])
        return self.triax_steps
        
    def _command_parser(self, command):
        '''Parses the command to ensure it is in the correct format for the spectrometer.'''
        com_set = command.split(' ')
        new_command = self.message_map.get(com_set[0], None)
        if new_command is None:
            print('Unknown command: {}'.format(command))
            return None

        if len(com_set) > 1:
            new_command += com_set[1]
        
        return new_command
    
    def send_command(self, command):
        '''Send a command to the spectrometer.'''
        coms = self._command_parser(command)
        response = self._send_command_to_spectrometer(coms)
        return response
    
    def _send_command_to_spectrometer(self, command, report=True):
        self.spectrometer.write(command)
        time.sleep(0.0001)

        if command == 'A':
            count = 100
            while count > 0:
                print('Initialising: Sleeping for {} seconds'.format(count))
                time.sleep(1)
                count -= 1
        
        response = self.spectrometer.read()
        return response
