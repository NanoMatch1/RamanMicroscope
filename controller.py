import serial
import time

from instruments import Instrument, ui_callable

# class SerialComs:
#     def __init__(self, com_port='COM10', baud=9600, report=True, dtr=False):
#         self.com_port = com_port
#         self.baud = baud
#         self.report = report

#         self.serial = serial.Serial()
#         self.serial.port = self.com_port
#         self.serial.baudrate = self.baud
#         self.serial.dtr = dtr
#         self.serial.open()

#     def connect(self):
#         if self.serial.is_open:
#             print("Serial port is already open.")
#             return

#         try:
#             self.serial.open()
#             print(f"Connected to {self.com_port} at {self.baud} baud.")
#         except serial.SerialException as e:
#             print(f"Error opening serial port: {e}")

#     def close(self):
#         if not self.simulate:
#             self.serial.close()


class ArduinoMEGA:

    def __init__(self, interface, com_port='COM10', baud=9600, simulate=False, report=True, dtr=False):
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

    def connect(self):
        if self.simulate:
            from simulation import SimulatedArduinoSerial
            self.serial = SimulatedArduinoSerial()

        self.serial = self._connect_to_UNO()

    def _format_command_length(self, command, threshold=56):
        """
        Splits the command string into multiple commands if its length
        exceeds the threshold. Assumes command delimiters (e.g., 'o' ... 'o')
        that enclose space-separated tokens.
        
        Parameters:
        command (str): The original command string.
        threshold (int): Maximum allowed command length.
        
        Returns:
        list: A list of command segments that are within the length limit.
        """
        if len(command) <= threshold:
            return [command]
        
        if not command[0] == command[-1]:
            raise ValueError("Command must start and end with the same delimiter.")
            return []
        
        # Check if the command is properly delimited
        if command[0] not in ['o', 'g', 'c', 's', 'm']:
            raise ValueError("Command must start with 'o', 'g', 'c', 's', or 'm'.")
        
        delimiter = command[0]
        
        # Remove the starting and ending delimiters; adjust if using a different format.
        inner = command[1:-1]
        tokens = inner.split()
        segments = []
        current_tokens = []
        
        # Account for delimiters in the length calculation.
        # The total length is: len(start_delim) + len(' '.join(tokens)) + len(end_delim)
        # Here, delimiters are assumed to be a single character each.
        for token in tokens:
            # Check if adding the token would exceed the threshold.
            # +1 for the space if current_tokens is non-empty.
            projected = len(' '.join(current_tokens + [token]))
            if projected + 2 > threshold:  # +2 for the two delimiters
                # Save current segment and start a new one.
                segment = delimiter + ' '.join(current_tokens) + delimiter
                segments.append(segment)
                current_tokens = [token]
            else:
                current_tokens.append(token)
        
        # Add the last segment if there are any tokens left.
        if current_tokens:
            segment = delimiter + ' '.join(current_tokens) + delimiter
            segments.append(segment)
        
        return segments
    
    def send_command(self, command):
        '''Simple command to send to the controller. Assumes command length is correct for buffer size'''

        if self.report is True:
            print('>MEGA:{}'.format(command))

        self._send_command_to_UNO(command)
        response = self._read_from_serial_until()

        return response
    
    def close_mono_shutter(self):
        self.send_command('mgsh offm')
    
    def open_mono_shutter(self):
        self.send_command('mgsh onm')
    
    def get_motor_positions(self, motor_list):
        command = 'g{}g'.format(' '.join(motor_list))
        # Check length here
        new_command = self._format_command_length(command) # return  a list

        motor_positions = []

        for command in new_command:
            response = self.send_command(command)

            motor_positions.append(response[0])

        return motor_positions

    def write_motor_positions(self, motor_id_dict:dict):
        command = 's{}s'.format(' '.join(['{}{}'.format(motor_id, steps) for motor_id, steps in motor_id_dict.items()]))
        # Check length here
        new_command = self._format_command_length(command)
        for command in new_command:
            response = self.send_command(command)
        
        return response

    def read_ldr0(self):
        response = self.send_command('mld0m')
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
        print("Connecting to Arduino controller...")

        UNO_serial = serial.Serial()
        UNO_serial.port = self.com_port
        UNO_serial.baudrate = self.baud
        UNO_serial.dtr = False
        UNO_serial.open()

        start_time = time.time()
        timeout = 2  # Timeout in seconds
        while UNO_serial.in_waiting == 0:
            if time.time() - start_time > timeout:
                print("Timeout waiting for Arduino to respond.")
                return UNO_serial
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





    
