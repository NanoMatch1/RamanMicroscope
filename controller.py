import serial
import time

from instruments import Instrument, simulate, ui_callable

def command_formatter(command):
    '''Formats the command to be sent to the Arduino UNO - this is a workaround until the firmware is updated.'''

    hardware_command = ['gsh', 'ld0']

    if command.split(' ')[0] in hardware_command:
        return 'm{}m'.format(command)
    else:
        return 'o{}o'.format(command)

class ArduinoUNO:

    def __init__(self, interface, com_port='COM10', baud=9600, simulate=False, report=True):
        self.interface = interface
        self.simulate = simulate
        self.com_port = com_port
        self.baud = baud
        self.report = report

        # if the firmware commands change, update this dictionary
        self.message_map = {
            'get_laser_positions': 'Apos',
            'gpb': 'Bpos',
            'get_monochromator_positions': 'Bpos',
            'gpa': 'Apos',
            'lambda': 'lambda',
            'atest': 'Atest',
            'btest': 'Btest',
            'ctest': 'Ctest',
            'creport': 'Creport',
            'astatus': 'Astatus',
            'bstatus': 'Bstatus',
            'cstatus': 'Cstatus',
            'g1': 'BX',
            'g2': 'BY',
            'g3': 'BZ',
            'g4': 'BA',
            'l1' : 'AX',
            'l2' : 'AY',
            'l3' : 'AZ',
            'l4' : 'AA',
            'setposa': 'Asetpos',
            'setposb' : 'Bsetpos',
            'aisrun': 'Aisrun',
            'bisrun': 'Bisrun',
            'ld0': 'ld0',
            'gsh': 'gsh',
        }

        self.response_map = {
            # 'get_monochromator_positions': self._process_grating_positions,
        }


    def initialise(self):
        self.connect()

    @simulate(expected_value=serial.Serial)
    def connect(self):
        self.serial = self._connect_to_UNO()
        # Initialize simulated motor positions if in simulation mode
        if self.simulate:
            self._sim_laser_motors = [100000, 100000, 0, 0]  # Initial simulated positions for laser motors
            self._sim_monochromator_motors = [200000, 200000, 0, 0]  # Initial simulated positions for monochromator motors
            self._sim_motor_running = False

    def _format_command_length(self, command):
        '''Formats the command by checking length and compiling the correct command from the message_map. Work around until firmware is updated.'''
        command_set = command.split(' ')
        try:
            new_command = self.message_map[command_set[0].lower()]
        except KeyError:
            # print('Command not recognized by Arduino UNO: {}'.format(command))
            return command # if not recognized, return the original command and attempt to send it anyway

        if len(command_set) > 1:
            new_command = ' '.join([new_command] + command_set[1:])
        else:
            new_command = '{}'.format(new_command)
        
        return new_command
    
    def _simulate_command_response(self, command):
        """Generate appropriate simulated responses for different commands"""
        if command.startswith('o'):
            cmd = command[1:-1]  # Strip the 'o' and 'o' markers
        elif command.startswith('m'):
            cmd = command[1:-1]  # Strip the 'm' and 'm' markers
        else:
            cmd = command
            
        parts = cmd.split(' ')
        cmd_type = parts[0].lower()
        
        # Check for motor movement commands (AX, AY, etc)
        if cmd_type in ['ax', 'ay', 'az', 'aa', 'bx', 'by', 'bz', 'ba']:
            if len(parts) > 1:
                try:
                    steps = int(parts[1])
                    motor_type = cmd_type[0].upper()  # A or B
                    motor_index = {'X': 0, 'Y': 1, 'Z': 2, 'A': 3}[cmd_type[1].upper()]
                    
                    # Move the appropriate simulated motor
                    if motor_type == 'A':
                        self._sim_laser_motors[motor_index] += steps
                    else:  # motor_type == 'B'
                        self._sim_monochromator_motors[motor_index] += steps
                        
                    # In real operation, this would be R1 for running, but we simulate completion immediately
                    return ['S0:Success', '#CF']
                except (ValueError, IndexError):
                    return ['F0:Invalid command', '#CF']
        
        # Handle specific command types
        if cmd_type == 'apos' or cmd_type == 'get_laser_positions':
            positions = ','.join([f"X{self._sim_laser_motors[0]}", 
                                 f"Y{self._sim_laser_motors[1]}", 
                                 f"Z{self._sim_laser_motors[2]}", 
                                 f"A{self._sim_laser_motors[3]}"])
            return [f'S0:<P>{positions}</P>', '#CF']
            
        elif cmd_type == 'bpos' or cmd_type == 'get_monochromator_positions':
            positions = ','.join([f"X{self._sim_monochromator_motors[0]}", 
                                 f"Y{self._sim_monochromator_motors[1]}", 
                                 f"Z{self._sim_monochromator_motors[2]}", 
                                 f"A{self._sim_monochromator_motors[3]}"])
            return [f'S0:<P>{positions}</P>', '#CF']
            
        elif cmd_type == 'aisrun':
            return ['S0:Not running', '#CF']  # Always return not running in simulation
            
        elif cmd_type == 'bisrun':
            return ['S0:Not running', '#CF']  # Always return not running in simulation
            
        elif cmd_type == 'ld0':
            # Simulate LDR0 (light sensor) reading - could be made more sophisticated
            # Higher means more light detected
            return [f'S0:3000', '#CF']
            
        elif cmd_type == 'gsh':
            # Shutter command
            status = "on" if "on" in cmd.lower() else "off"
            return [f'S0:Shutter {status}', '#CF']
            
        elif cmd_type == 'setposa':
            # Set absolute position for laser motors
            if len(parts) > 1:
                try:
                    positions = parts[1].split(',')
                    if len(positions) >= 4:
                        self._sim_laser_motors = [int(p) for p in positions[:4]]
                    else:
                        # If fewer positions provided, only update those specified
                        for i, p in enumerate(positions):
                            if p.strip():
                                self._sim_laser_motors[i] = int(p)
                    return ['S0:Positions set', '#CF']
                except ValueError:
                    return ['F0:Invalid position values', '#CF']
            return ['F0:Missing position values', '#CF']
            
        elif cmd_type == 'setposb':
            # Set absolute position for monochromator motors
            if len(parts) > 1:
                try:
                    positions = parts[1].split(',')
                    if len(positions) >= 4:
                        self._sim_monochromator_motors = [int(p) for p in positions[:4]]
                    else:
                        # If fewer positions provided, only update those specified
                        for i, p in enumerate(positions):
                            if p.strip():
                                self._sim_monochromator_motors[i] = int(p)
                    return ['S0:Positions set', '#CF']
                except ValueError:
                    return ['F0:Invalid position values', '#CF']
            return ['F0:Missing position values', '#CF']
            
        # Default response for unrecognized commands
        return ['F0:Unknown command', '#CF']
            
    @simulate(function_handler=lambda self, orig_com, **kwargs: self._simulate_command_response(command_formatter(self._format_command_length(orig_com))))
    def send_command(self, orig_com):
        new_com = self._format_command_length(orig_com)
        if new_com is None:
            return None
        new_com = command_formatter(new_com)

        if self.report is True:
            print('>UNO:{}'.format(new_com))
        self._send_command_to_UNO(new_com)
        response = self._read_from_serial_until()
        
        return response

    def get_monochromator_motor_positions(self):
        response = self.send_command('get_monochromator_positions')
        if response == []:
            response = self.send_command('get_monochromator_positions') # bug with controller returning empty list, try again # TODO: seems to be related to an extra end flag #CF in the firmware. Will be fixed in the next firmware update.
        if self.report:
            print(response)
        
        positions = response[0].split(':')[1]
        positions = positions.strip('<P>P')
        positions = positions.split(',')
        monochromator_steps = [int(x[1:]) for x in positions]
        self.monochromator_steps = monochromator_steps
        
        return monochromator_steps
    
    def get_laser_motor_positions(self):
        response = self.send_command('get_laser_positions')
        if response == []:
            response = self.send_command('get_laser_positions') # TODO: firmware bug, will be fixed in the next update
        if self.report:
            print(response)
        positions = response[0].split(':')[1]
        positions = positions.strip('<P>P')
        positions = positions.split(',')
        laser_steps = [int(x[1:]) for x in positions]
        self.laser_steps = laser_steps
        
        return laser_steps

    def _connect_to_UNO(self):
        UNO_serial = serial.Serial(self.com_port, self.baud, timeout=1)
        while UNO_serial.in_waiting == 0:
            time.sleep(0.1)
        while UNO_serial.in_waiting > 0:
            response = UNO_serial.readline().decode().strip()
            print(response)
        return UNO_serial
    
    def _send_command_to_UNO(self, command):
        self.serial.write('{}\n'.format(command).encode())
        time.sleep(0.1)

    def _read_command_from_uno(self):
        response = ''
        while self.serial.in_waiting > 0:
            response += self.serial.readline().decode()
        return response

    def _read_from_serial_until(self, end_flag='#CF'):
        end_responses = []

        while True:
            response = self._read_command_from_uno()
            
            if response == '':
                time.sleep(0.01)
                continue

            if self.report is True:
                print(response)
            split_responses = response.split('\r\n')
            for item in split_responses:
                if item == end_flag:
                    return end_responses
                if item != '':
                    end_responses.append(item)

            time.sleep(0.01)





    
