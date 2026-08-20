import time
import serial
from instruments.instrument_base import Instrument
from instruments.util_decorators import ui_callable
from .simulated_triax import SimulatedTriaxSerial


class Triax(Instrument):
    def __init__(self, interface, simulate=False):
        super().__init__()
        self.interface = interface
        self.logger = interface.logger.getChild('Triax')
        self.simulate = simulate or interface.simulate
        self.calibration_service = interface.calibration_service
        self.enterance_slit_width = 0
        self.port = 'COM16'
        self.serial_config = {
            'baudrate': 4800,
            'bytesize': serial.EIGHTBITS,
            'parity':   serial.PARITY_NONE,
            'stopbits': serial.STOPBITS_ONE,
            'timeout':  2,
        }



        self.command_functions = {
            'get_spectrometer_position': self.get_spectrometer_position,
            'rg': self.get_spectrometer_position,
            'go_to_position': self.go_to_position,
            'sg': self.go_to_position,
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
    
    @property
    def is_simulated(self):
        '''Returns True if the spectrometer is simulated, False otherwise.
        When connected to a simulated spectrometer, the communication interface will have a "simulate" attribute.'''
        
        simulation_status = getattr(self.spectrometer, 'simulate', False) 
        return simulation_status
    
    def initialise(self):
        '''Connect and establish primary attributes.'''
        # self.connect()
        self.auto_connect()
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
        return response

    @ui_callable
    def other_grating(self):
        '''Set the other grating for the spectrometer.'''

        response = self.send_command('specgrat2')
        return response
        
    
    @ui_callable
    def read_enterance_slit(self):
        '''Read the current position of the entrance slit.'''
        response = self.send_command('read_enter')

        try:
            self.enterance_slit_width = int(response.strip()[1:])
        except ValueError:
            self.logger.info('Error reading entrance slit width: {}'.format(response))
            self.enterance_slit_width = 0
        return self.enterance_slit_width
    
    @ui_callable
    def read_exit_slit(self):
        '''Read the current position of the exit slit.'''
        response = self.send_command('read_exit')
        return response
    
    @ui_callable
    def move_enterance_slit(self, position):
        '''Move the entrance slit to the specified position.'''
        try:
            int(position)
        except ValueError:
            self.logger.info('Invalid input for entrance slit position: {}'.format(position))
            return
        response = self.send_command('men {}'.format(position))
        self.enterance_slit_width += int(position)
        return self.enterance_slit_width
    
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
    
    def go_to_wavelength(self, wavelength, steps_correction=1910):
        '''Moves the spectrometer to the specified wavelength. Steps correction is an artificial adjustment to push the laser closer to 100 to prevent the laser from being too far to the left. #TODO recalibrate for pixel 100, not 50'''
        try:
            wavelength = float(wavelength)
        except ValueError:
            self.logger.info('Invalid input')
            return
        
        triax_steps = self.get_triax_steps() 
        
        target_steps = round(self.interface.microscope.calibration_service.wl_to_triax(wavelength)) - steps_correction
        # 
        new_steps = target_steps - triax_steps
        # return if no movement is required
        if new_steps == 0:
            return
        
        self.logger.coms('UNO>g {}>triax'.format(new_steps))

        response = self.send_command('mg {}'.format(new_steps))
        if response == 'o':
            triax_res = self.wait_for_triax(target_steps)
            if triax_res == 'S0':
                self.logger.info('Triax moved to {} nm'.format(wavelength))
                self.triax_steps = target_steps
                return 'S0'
            else:
                self.logger.info('Triax move failed: {}'.format(triax_res))
                return 'F0'
        # Note: workaround for something not handled well by the above code #TODO fix this
        elif response.startswith('o'):
            self.logger.info('Triax coms anomaly #TODO debug. Response:{}'.format(response))
            return 'S0'

        else:
            self.logger.info('Triax communication failed:')
            self.logger.info(response)

    def wait_for_triax(self, target_steps, timeout=10):
        '''Polls the spectrometer until the target steps are reached. Note the MOTOR BUSY CHECK (E) on the spectrometer does not send a response with this configuration, so we use this command instead.'''
        start = time.time()
        while True:
            response = self.get_triax_steps()
            if response == target_steps:
                return 'S0'
            time.sleep(0.1)
            if time.time() - start > timeout:
                self.logger.info('Timeout reached')
                return 'F0'

    

    @ui_callable
    def get_spectrometer_position(self):
        '''Get the current position of the spectrometer in motor steps.'''
        self.spectrometer_position = self.get_triax_steps()
        return self.spectrometer_position
    
    @ui_callable
    def go_to_position(self, position):
        self.logger.info("Going to the position: {}".format(position))
        command = self.message_map['move_grating'] + str(position)
        response = self._send_command_to_spectrometer(command)
        return response

    def connect(self):
    # Open a serial connection to the TRIAX on COM16.
        if self.simulate:
            self.spectrometer = SimulatedTriaxSerial()
            self.state = True
            return self.spectrometer, self.state

        self.logger.info('Connecting to TRIAX on {}...'.format(self.port))

        try:
            self.spectrometer = serial.Serial(
                port=self.port,
                **self.serial_config
            )
        except serial.SerialException as error:
            self.logger.info('Failed to open {}: {}'.format(self.port, error))
            raise

        self._enter_intelligent_mode()
        self.state = True
        self.logger.info('Connected to TRIAX on {}'.format(self.port))
        return self.spectrometer, self.state


    def auto_connect(self):
        '''Connect to the TRIAX on COM16.'''
        if self.simulate:
            self.spectrometer = SimulatedTriaxSerial()
            self.state = True
            return self.spectrometer, self.state

        return self.connect()

    def _enter_intelligent_mode(self):
        '''Send byte 248 to switch to intelligent communications mode.'''
        self.logger.info('Entering intelligent mode...')
        self.spectrometer.write(bytes([248]))
        time.sleep(0.2)

        if not self._is_initialised(self.spectrometer):
            self.logger.info('Spectrometer not initialised — running init')
            self._run_initialisation()
        else:
            self.logger.info('Spectrometer already initialised — skipping init')

    def _is_initialised(self, ser):
        '''Send H0 to test if the spectrometer is already initialised.'''
        ser.reset_input_buffer()
        ser.write(b'H0\r')
        response = self._read_response(ser, wait=0.5)

        has_digits = any(char.isdigit() for char in response)

        if 'o' in response and has_digits:
            self.logger.info('H0 check passed — already initialised')
            return True
        else:
            self.logger.info(
                'H0 check failed — not initialised. Response: {!r}'.format(response)
            )
            return False

    def _run_initialisation(self):
        '''Trigger autobaud and full spectrometer initialisation
        by sending a space.'''
        self.logger.info('Sending space to trigger initialisation...')
        self.spectrometer.write(b' ')

        self.logger.info('Waiting for initialisation to complete...')
        last_data_time = time.time()
        while True:
            if self.spectrometer.in_waiting > 0:
                data = self.spectrometer.read(self.spectrometer.in_waiting)
                self.logger.info('Init: {!r}'.format(
                    data.decode('ascii', errors='replace')
                ))
                last_data_time = time.time()

            if time.time() - last_data_time > 5:
                self.logger.info('Initialisation complete')
                break

            time.sleep(0.1)

        self.logger.info('Re-entering intelligent mode after init...')
        self.spectrometer.write(bytes([248]))
        time.sleep(0.2)

        self.spectrometer.write(b' ')
        response = self._read_response(self.spectrometer, wait=0.5)
        if 'F' in response:
            self.logger.info('Intelligent mode confirmed after init')
        else:
            self.logger.info(
            'Unexpected response after init: {!r}'.format(response)
            )

    def _read_response(self, ser, wait=0.3):
        '''Read all available bytes from the serial port.'''
        time.sleep(wait)
        response = b''
        while ser.in_waiting > 0:
            response += ser.read(ser.in_waiting)
            time.sleep(0.05)
        decoded = response.decode('ascii', errors='replace')
        self.logger.info('Response: {!r}'.format(decoded))
        return decoded


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
            self.logger.info('Unknown command: {}'.format(command))
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
        '''
        Send a command string terminated by CR and return the response.
        Handles the long wait required for the initialise command.
        '''
        if self.simulate:
            # SimulatedTriaxSerial mirrors the pyserial write/read API, not
            # the pyvisa query() API used by the old GPIB implementation.
            self.spectrometer.write(command)
            return self.spectrometer.read()

        full_command = (command + '\r').encode('ascii')
        self.spectrometer.reset_input_buffer()
        self.spectrometer.write(full_command)

        # Initialise command takes up to 2 minutes
        if command == 'A':
            self.logger.info('Initialising spectrometer — waiting up to 120s...')
            time.sleep(120)

        return self._read_response(self.spectrometer, wait=0.5)

