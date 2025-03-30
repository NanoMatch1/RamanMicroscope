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
            
    @simulate(expected_value='Command sent')
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





    
