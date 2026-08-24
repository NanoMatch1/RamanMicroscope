import serial
import time

# ============================================================
# CONFIGURATION — update COM port to match your system
# ============================================================
COM_PORT = 'COM17'
BAUD_RATE = 9600

# ============================================================
# STEP COUNTER
# ============================================================
step_counter = 0

# ============================================================
# REFERENCE WAVELENGTH
# ============================================================
REFERENCE_WAVELENGTH = 799.0  # nm — update with your known value
NM_PER_STEP = 0.04            # from test report at amplitude 600

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def send_command(ser, command, max_retries=3):
    """
    Send a command and listen for ACK or NAK.
    
    Success cases:
      - Explicit ACK (\\x06) received
      - Status update string received (laser is responding normally)
    
    Failure cases:
      - NAK (\\x15) received — retry up to max_retries times
      - Timeout — retry up to max_retries times
    """
    raw_command = command.encode('ascii')

    for attempt in range(1, max_retries + 1):
        ser.reset_input_buffer()
        ser.reset_output_buffer()

        print(f'\nSending: {command} (attempt {attempt} of {max_retries})')
        ser.write(raw_command)

        timeout = time.time() + 2  # 2 second window per attempt
        received_bytes = b''

        while time.time() < timeout:
            if ser.in_waiting > 0:
                byte = ser.read(1)
                received_bytes += byte

                # Explicit ACK
                if byte == b'\x06':
                    print('Response: ACK — command accepted')
                    return True

                # Status update string detected — treat as success
                # Status updates are printable ASCII (bytes 32-126)
                # If we accumulate printable characters it is a status string
                if len(received_bytes) > 3 and all(
                    32 <= b <= 126 or b in (10, 13)
                    for b in received_bytes
                ):
                    print('Response: Status update received — treating as success')
                    return True

                # Explicit NAK
                if byte == b'\x15':
                    print(f'Response: NAK — command rejected on attempt {attempt}')
                    break  # break inner loop to retry

        else:
            # Timeout expired without any response
            print(f'Response: Timed out on attempt {attempt}')

        # Wait briefly before retrying
        if attempt < max_retries:
            print('Retrying...')
            time.sleep(0.5)

    print('Command failed after maximum retries')
    return False

def validate_steps(value, min_val, max_val):
    """Validate a numeric input is within allowed range."""
    try:
        int_value = int(value)
        if min_val <= int_value <= max_val:
            return True
        else:
            print(f'Value must be between {min_val} and {max_val}')
            return False
    except ValueError:
        print('Please enter a valid number')
        return False


def format_value(value):
    """Format integer as 6 digit zero padded string."""
    return str(int(value)).zfill(6)

# ============================================================
# COMMAND FUNCTIONS
# ============================================================

def move_steps_increase(ser):
    """*M1!SInnnnnn# — Move piezomotor a number of steps (increase)."""
    global step_counter
    print('\n--- Move Piezomotor (Increase) ---')
    print('Moves the birefringent filter to increase wavelength direction')
    value = input('Enter number of steps (1 - 999999): ')
    if validate_steps(value, 1, 999999):
        command = f'*M1!SI{format_value(value)}#'
        success = send_command(ser, command)
        if success:
            step_counter += int(value)
            print(f'Step offset: {step_counter}')


def move_steps_decrease(ser):
    """*M1!SDnnnnnn# — Move piezomotor a number of steps (decrease)."""
    global step_counter
    print('\n--- Move Piezomotor (Decrease) ---')
    print('Moves the birefringent filter to decrease wavelength direction')
    value = input('Enter number of steps (1 - 999999): ')
    if validate_steps(value, 1, 999999):
        command = f'*M1!SD{format_value(value)}#'
        success = send_command(ser, command)
        if success:
            step_counter -= int(value)
            print(f'Step offset: {step_counter}')


def set_step_amplitude(ser):
    """*M1!SAnnnnnn# — Set step amplitude (400-1000, default 600)."""
    print('\n--- Set Step Amplitude ---')
    print('Controls rotation speed and step size of piezomotor')
    print('Higher values = faster rotation and larger steps')
    print('Default: 600 | At 600, one step = ~0.04 nm wavelength shift')
    print('WARNING: Do not set below 400')
    value = input('Enter step amplitude (400 - 1000): ')
    if validate_steps(value, 400, 1000):
        command = f'*M1!SA{format_value(value)}#'
        send_command(ser, command)


def set_step_width(ser):
    """*M1!SWnnnnnn# — Set step width/prolongation in microseconds (default 0)."""
    print('\n--- Set Step Width (Prolongation) ---')
    print('Controls step size in microseconds')
    print('Higher values = larger steps')
    print('Default: 0')
    value = input('Enter step width in microseconds (0 - 999999): ')
    if validate_steps(value, 0, 999999):
        command = f'*M1!SW{format_value(value)}#'
        send_command(ser, command)


def set_step_time_off(ser):
    """*M1!SOnnnnnn# — Set time between steps in microseconds (default 1000)."""
    print('\n--- Set Step Time Off ---')
    print('Controls time between steps in microseconds')
    print('Higher values = slower tuning')
    print('Default: 1000')
    value = input('Enter time off in microseconds (0 - 999999): ')
    if validate_steps(value, 0, 999999):
        command = f'*M1!SO{format_value(value)}#'
        send_command(ser, command)


def restore_defaults(ser):
    """Restore all piezomotor settings to factory defaults from test report."""
    print('\n--- Restoring Factory Defaults ---')
    print('Step Amplitude : 600')
    print('Step Width     : 0')
    print('Step Time Off  : 1000')
    confirm = input('Confirm restore defaults? (y/n): ')
    if confirm.lower() == 'y':
        send_command(ser, '*M1!SA000600#')
        send_command(ser, '*M1!SW000000#')
        send_command(ser, '*M1!SO001000#')
        print('Defaults restored')

# ============================================================
# MAIN MENU
# ============================================================

def print_menu():
    estimated_wl = REFERENCE_WAVELENGTH + (step_counter * NM_PER_STEP)
    print('\n' + '=' * 50)
    print('  TIGER Piezomotor Control')
    print('  1DBuP RS-232 Interface')
    print('=' * 50)
    print(f'  Current step offset  : {step_counter}')
    print(f'  Estimated wavelength : {estimated_wl:.3f} nm')
    print('-' * 50)
    print('  1  —  Move steps increase')
    print('  2  —  Move steps decrease')
    print('  3  —  Set step amplitude')
    print('  4  —  Set step width')
    print('  5  —  Set step time off')
    print('  6  —  Restore factory defaults')
    print('  0  —  Exit')
    print('=' * 50)


def main():
    print(f'\nConnecting to {COM_PORT} at {BAUD_RATE} baud...')

    try:
        ser = serial.Serial(
            port=COM_PORT,
            baudrate=BAUD_RATE,
            bytesize=8,
            parity='N',
            stopbits=1,
            timeout=2
        )
        print(f'Connected successfully on {COM_PORT}')

    except serial.SerialException as e:
        print(f'Failed to connect: {e}')
        print('Check your COM port number and that no other software is using it')
        return

    try:
        while True:
            print_menu()
            choice = input('Enter choice: ').strip()

            if choice == '1':
                move_steps_increase(ser)
            elif choice == '2':
                move_steps_decrease(ser)
            elif choice == '3':
                set_step_amplitude(ser)
            elif choice == '4':
                set_step_width(ser)
            elif choice == '5':
                set_step_time_off(ser)
            elif choice == '6':
                restore_defaults(ser)
            elif choice == '0':
                print('\nClosing connection...')
                break
            else:
                print('Invalid choice — please enter a number from the menu')

    finally:
        ser.close()
        print('Connection closed')


if __name__ == '__main__':
    main()
