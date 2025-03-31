import serial
import time

from instruments import Instrument, simulate, ui_callable

def command_formatter(command):
    '''Formats the command to be sent to the Arduino MEGA controller.'''

    hardware_command = ['gsh', 'ld0']

    if command.split(' ')[0] in hardware_command:
        return 'm{}m'.format(command)
    else:
        return 'o{}o'.format(command)

class ArduinoController:
    """
    Controller class for the Arduino MEGA that manages up to 16 stepper motors organized in 4 modules
    with 4 motors each (A, X, Y, Z per module).
    """

    def __init__(self, interface, com_port='COM10', baud=9600, simulate=False, report=True):
        self.interface = interface
        self.simulate = simulate
        self.com_port = com_port
        self.baud = baud
        self.report = report

        # Motor mapping configuration - PLACEHOLDER_MOTOR_MAP
        # This maps the old motor designations (A/B, and individual motor functions) to the new module-motor system
        # Format: {old_designation: [module_number, motor_letter]}
        self.motor_map = {
            # Laser motors (previously module A)
            'l1': ['1', 'X'],  # Module 1, motor X
            'l2': ['1', 'Y'],  # Module 1, motor Y
            'l3': ['1', 'Z'],  # Module 1, motor Z
            'l4': ['1', 'A'],  # Module 1, motor A
            
            # Monochromator motors (previously module B)
            'g1': ['2', 'X'],  # Module 2, motor X
            'g2': ['2', 'Y'],  # Module 2, motor Y
            'g3': ['2', 'Z'],  # Module 2, motor Z
            'g4': ['2', 'A'],  # Module 2, motor A
            
            # Additional motors can be mapped here
            # 'stage_x': ['3', 'X'],  # Example: Module 3, motor X for stage X axis
            # 'stage_y': ['3', 'Y'],  # Example: Module 3, motor Y for stage Y axis
            # 'stage_z': ['3', 'Z'],  # Example: Module 3, motor Z for stage Z axis
        }

        # Command mapping
        self.message_map = {
            # Motor position reporting commands
            'get_laser_positions': self._get_laser_positions_command,
            'get_monochromator_positions': self._get_monochromator_positions_command,
            'gpa': self._get_laser_positions_command,
            'gpb': self._get_monochromator_positions_command,
            
            # Individual motor control - these now use module/motor addressing
            'l1': self._map_motor_command,
            'l2': self._map_motor_command,
            'l3': self._map_motor_command, 
            'l4': self._map_motor_command,
            'g1': self._map_motor_command,
            'g2': self._map_motor_command,
            'g3': self._map_motor_command,
            'g4': self._map_motor_command,
            
            # Set position commands - handle differently now
            'setposa': self._set_laser_positions_command,
            'setposb': self._set_monochromator_positions_command,
            
            # Running status commands - need to check all relevant motors
            'aisrun': self._check_laser_motors_running,
            'bisrun': self._check_monochromator_motors_running,
            
            # Other commands that stay the same
            'ld0': 'ld0',
            'gsh': 'gsh',
            
            # New mode commands
            'ramanmode': 'ramanmode',
            'imagemode': 'imagemode',
        }

        # Simulate memory for motor positions and states
        if self.simulate:
            self._initialize_simulation_state()

    def _initialize_simulation_state(self):
        """Initialize the simulation state for all motors"""
        # Create a simulated state for all 16 motors (4 modules x 4 motors)
        self._sim_motor_positions = {
            # Module 1 (previously laser motors)
            '1A': 0, '1X': 100000, '1Y': 100000, '1Z': 0,
            # Module 2 (previously monochromator motors)
            '2A': 0, '2X': 200000, '2Y': 200000, '2Z': 0,
            # Module 3 (available for expansion)
            '3A': 0, '3X': 0, '3Y': 0, '3Z': 0,
            # Module 4 (available for expansion)
            '4A': 0, '4X': 0, '4Y': 0, '4Z': 0
        }
        self._sim_motor_running = {
            '1': False, '2': False, '3': False, '4': False
        }

    def _get_laser_positions_command(self, command_parts):
        """Command handler for getting laser motor positions"""
        # Returns positions for motors in module 1
        return 'get_module_positions 1'
    
    def _get_monochromator_positions_command(self, command_parts):
        """Command handler for getting monochromator motor positions"""
        # Returns positions for motors in module 2
        return 'get_module_positions 2'
    
    def _map_motor_command(self, command_parts):
        """Maps old motor commands (l1, g2, etc.) to new module-motor format"""
        if len(command_parts) < 2:
            return None  # Not enough information
            
        motor_name = command_parts[0].lower()
        if motor_name not in self.motor_map:
            return None  # Unknown motor
            
        module, motor = self.motor_map[motor_name]
        steps = command_parts[1]
        
        # Format: <module><motor><steps>
        return f"{module}{motor}{steps}"
    
    def _set_laser_positions_command(self, command_parts):
        """Command handler for setting absolute positions of laser motors"""
        if len(command_parts) < 2:
            return None
            
        positions = command_parts[1].split(',')
        if len(positions) < 4:
            return None
            
        # Convert old format (X,Y,Z,A values) to new format (individual motor commands)
        commands = []
        motor_letters = ['X', 'Y', 'Z', 'A']
        
        for i, pos in enumerate(positions[:4]):
            if pos.strip():  # Only process non-empty positions
                module = '1'  # Laser motors are in module 1
                motor = motor_letters[i]
                commands.append(f"set_absolute_position {module}{motor} {pos}")
                
        return commands
    
    def _set_monochromator_positions_command(self, command_parts):
        """Command handler for setting absolute positions of monochromator motors"""
        if len(command_parts) < 2:
            return None
            
        positions = command_parts[1].split(',')
        if len(positions) < 4:
            return None
            
        # Convert old format (X,Y,Z,A values) to new format (individual motor commands)
        commands = []
        motor_letters = ['X', 'Y', 'Z', 'A']
        
        for i, pos in enumerate(positions[:4]):
            if pos.strip():  # Only process non-empty positions
                module = '2'  # Monochromator motors are in module 2
                motor = motor_letters[i]
                commands.append(f"set_absolute_position {module}{motor} {pos}")
                
        return commands
    
    def _check_laser_motors_running(self, command_parts):
        """Check if any of the laser motors are running"""
        # Check if motors in module 1 are running
        return "check_module_running 1"
    
    def _check_monochromator_motors_running(self, command_parts):
        """Check if any of the monochromator motors are running"""
        # Check if motors in module 2 are running
        return "check_module_running 2"

    def initialise(self):
        self.connect()

    @simulate(expected_value=serial.Serial)
    def connect(self):
        self.serial = self._connect_to_arduino()
        # Initialize simulated motor positions if in simulation mode
        if self.simulate:
            self._initialize_simulation_state()

    def _format_command(self, command):
        '''
        Formats the command by checking command type and building the appropriate
        Arduino MEGA command using the message_map.
        '''
        command_parts = command.split(' ')
        command_type = command_parts[0].lower()
        
        try:
            command_handler = self.message_map[command_type]
            # If it's a function, call it
            if callable(command_handler):
                new_command = command_handler(command_parts)
                if new_command is None:
                    return None
                # If the handler returns a list, we need to run multiple commands
                if isinstance(new_command, list):
                    return new_command
                return new_command
            else:
                # If it's a string, use it directly
                if len(command_parts) > 1:
                    return ' '.join([command_handler] + command_parts[1:])
                return command_handler
        except KeyError:
            # If not found in mapping, pass through the original command
            return command
    
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
        
        # Direct motor movement command (format: 1X1000, 2Y-500, etc.)
        if len(cmd_type) >= 2 and cmd_type[0] in "1234" and cmd_type[1] in "AXYZ":
            try:
                module = cmd_type[0]
                motor = cmd_type[1]
                steps = int(cmd_type[2:]) if len(cmd_type) > 2 else int(parts[1])
                
                motor_key = f"{module}{motor}"
                self._sim_motor_positions[motor_key] += steps
                
                # Set the motor as running initially, then immediately mark it as done
                self._sim_motor_running[module] = True
                self._sim_motor_running[module] = False
                
                return ['Moving motor', '#CF']
            except (ValueError, KeyError):
                return ['F0:Invalid motor command', '#CF']
        
        # Handle position reporting commands
        if cmd_type.startswith("get_module_positions"):
            if len(parts) > 1:
                module = parts[1]
                
                # Format positions for the requested module
                motor_positions = []
                for motor in "AXYZ":
                    pos = self._sim_motor_positions.get(f"{module}{motor}", 0)
                    motor_positions.append(f"{motor}{pos}")
                    
                positions_str = ','.join(motor_positions)
                return [f'S0:<P>{positions_str}</P>', '#CF']
        
        # Handle motor running status check
        if cmd_type.startswith("check_module_running"):
            if len(parts) > 1:
                module = parts[1]
                running = self._sim_motor_running.get(module, False)
                status = "R1" if running else "S0"
                return [f'{status}:{module}', '#CF']
        
        # Handle absolute position setting
        if cmd_type.startswith("set_absolute_position"):
            if len(parts) > 2:
                try:
                    motor_id = parts[1]  # Format: 1X, 2Y, etc.
                    position = int(parts[2])
                    
                    self._sim_motor_positions[motor_id] = position
                    return ['S0:Position set', '#CF']
                except (ValueError, KeyError):
                    return ['F0:Invalid position command', '#CF']
        
        # Handle shutter commands
        if cmd_type == 'gsh':
            # Shutter command
            status = "on" if len(parts) > 1 and parts[1] == "on" else "off"
            return [f'S0:Shutter {status}', '#CF']
        
        # Handle LDR reading
        if cmd_type == 'ld0':
            # Simulate LDR0 reading
            return ['t3000', '#CF']
        
        # Handle mode commands
        if cmd_type == 'ramanmode':
            return ['Moving to Raman Mode...', '#CF']
        
        if cmd_type == 'imagemode':
            return ['Moving to Image Mode...', '#CF']
            
        # Default response for unrecognized commands
        return ['F0:Unknown command', '#CF']
            
    @simulate(function_handler=lambda self, orig_com, **kwargs: self._simulate_command_response(command_formatter(self._format_command(orig_com))))
    def send_command(self, orig_com):
        """
        Send a command to the Arduino MEGA.
        
        This method handles both single commands and batches of commands when a command
        handler returns a list of commands to execute.
        """
        formatted_command = self._format_command(orig_com)
        
        # Handle command lists (for commands that need to be split into multiple commands)
        if isinstance(formatted_command, list):
            all_responses = []
            for cmd in formatted_command:
                wrapped_cmd = command_formatter(cmd)
                if self.report:
                    print(f'>MEGA:{wrapped_cmd}')
                self._send_command_to_arduino(wrapped_cmd)
                response = self._read_from_serial_until()
                all_responses.extend(response)
            return all_responses
        
        # Handle single commands
        if formatted_command is None:
            return None
            
        wrapped_command = command_formatter(formatted_command)
        if self.report:
            print(f'>MEGA:{wrapped_command}')
        self._send_command_to_arduino(wrapped_command)
        response = self._read_from_serial_until()
        
        return response

    def get_monochromator_motor_positions(self):
        """Get the positions of the monochromator motors (Module 2)"""
        response = self.send_command('get_monochromator_positions')
        
        # Retry once if response is empty (handles potential communication issues)
        if not response:
            response = self.send_command('get_monochromator_positions')
            
        if self.report:
            print(response)
        
        try:
            # New format handling: <P>X200000,Y200000,Z0,A0</P>
            positions_data = response[0].split(':', 1)[1] if ':' in response[0] else response[0]
            positions_data = positions_data.strip('<P></P>')
            positions = positions_data.split(',')
            
            # Extract values from format X200000,Y200000,Z0,A0
            monochromator_steps = [int(pos[1:]) for pos in positions if pos and pos[0] in "XYZA"]
            
            # Fill with zeros if we don't have 4 values
            while len(monochromator_steps) < 4:
                monochromator_steps.append(0)
                
            self.monochromator_steps = monochromator_steps[:4]  # Ensure we only have 4 values
            return self.monochromator_steps
            
        except (IndexError, ValueError) as e:
            print(f"Error parsing monochromator positions: {e}")
            return [0, 0, 0, 0]  # Default to zeros if parsing fails
    
    def get_laser_motor_positions(self):
        """Get the positions of the laser motors (Module 1)"""
        response = self.send_command('get_laser_positions')
        
        # Retry once if response is empty
        if not response:
            response = self.send_command('get_laser_positions')
            
        if self.report:
            print(response)
        
        try:
            # New format handling: <P>X100000,Y100000,Z0,A0</P>
            positions_data = response[0].split(':', 1)[1] if ':' in response[0] else response[0]
            positions_data = positions_data.strip('<P></P>')
            positions = positions_data.split(',')
            
            # Extract values from format X100000,Y100000,Z0,A0
            laser_steps = [int(pos[1:]) for pos in positions if pos and pos[0] in "XYZA"]
            
            # Fill with zeros if we don't have 4 values
            while len(laser_steps) < 4:
                laser_steps.append(0)
                
            self.laser_steps = laser_steps[:4]  # Ensure we only have 4 values
            return self.laser_steps
            
        except (IndexError, ValueError) as e:
            print(f"Error parsing laser positions: {e}")
            return [0, 0, 0, 0]  # Default to zeros if parsing fails

    def _connect_to_arduino(self):
        """Connect to the Arduino MEGA"""
        arduino_serial = serial.Serial(self.com_port, self.baud, timeout=1)
        
        # Wait for initial communication from Arduino
        time.sleep(2)  # Give Arduino time to reset after serial connection
        
        # Clear any initial messages
        while arduino_serial.in_waiting > 0:
            response = arduino_serial.readline().decode().strip()
            print(response)
            
        print("Connected to Arduino MEGA controller")
        return arduino_serial
    
    def _send_command_to_arduino(self, command):
        """Send a command to the Arduino MEGA"""
        self.serial.write(f"{command}\n".encode())
        time.sleep(0.1)  # Short delay to allow Arduino to process

    def _read_command_from_arduino(self):
        """Read a response from the Arduino MEGA"""
        response = ''
        while self.serial.in_waiting > 0:
            response += self.serial.readline().decode()
        return response
        
    def _read_from_serial_until(self, end_flag='#CF'):
        """Read from serial until a specific end flag is encountered"""
        end_responses = []

        while True:
            response = self._read_command_from_arduino()
            
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