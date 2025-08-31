import serial
import time
from .subsystems import MotionService

class ArduinoMEGA:

    def __init__(self, interface, com_port='COM10', baud=9600, simulate=False, report=True, dtr=False):
        self.interface = interface
        self.logger = interface.logger.getChild('Arduino')
        self.simulate = simulate
        self.com_port = com_port
        self.baud = baud
        self.report = report
        # MotionService: extracted segmentation logic (Phase 2B). Keep internal for now.
        self._motion_service = MotionService()

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
        if self.simulate or self.interface.simulate:
            from .simulation import SimulatedArduinoSerial
            self.serial = SimulatedArduinoSerial()
            return

        self.serial = self._connect_to_UNO()

    def _format_command_length(self, command, threshold=56):
        """Backward-compatible wrapper now delegating to MotionService.segment.

        threshold parameter retained (currently MotionService threshold set at init).
        If caller passes a different threshold we instantiate a throwaway service
        to avoid mutating shared instance (edge-case; not currently used).
        """
        if threshold != self._motion_service.threshold:
            return MotionService(threshold=threshold).segment(command)
        return self._motion_service.segment(command)
    
    def send_command(self, command):
        '''Simple command to send to the controller. Assumes command length is correct for buffer size'''

        self.interface.logger.coms('>MEGA:{}'.format(command))

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
        self.logger.debug(response)
        
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
        self.logger.debug(response)
        positions = response[0].split(':')[1]
        positions = positions.strip('<P>P')
        positions = positions.split(',')
        laser_steps = [int(x[1:]) for x in positions]
        self.laser_steps = laser_steps
        
        return laser_steps

    def _connect_to_UNO(self):
        self.logger.info("Connecting to Arduino controller...")

        UNO_serial = serial.Serial()
        UNO_serial.port = self.com_port
        UNO_serial.baudrate = self.baud
        UNO_serial.dtr = False
        UNO_serial.open()

        start_time = time.time()
        timeout = 2  # Timeout in seconds
        while UNO_serial.in_waiting == 0:
            if time.time() - start_time > timeout:
                self.logger.info("Timeout waiting for Arduino to respond. Assuming connection is established in resume mode")
                return UNO_serial
            time.sleep(0.1)
        
        while UNO_serial.in_waiting > 0:
            response = UNO_serial.readline().decode().strip()
            self.logger.info(f"Controller response: {response}")
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

            split_responses = response.split('\r\n')
            for item in split_responses:
                if item == end_flag:
                    return end_responses
                if item != '':
                    end_responses.append(item)

            time.sleep(0.01)





    
