import serial
import time

# Configure the serial connection
ser = serial.Serial(
    port='COM13',       # Replace with your actual port
    baudrate=9600,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    bytesize=serial.EIGHTBITS,
    timeout=1          # Read timeout in seconds
)

# Ensure the serial port is open
if not ser.is_open:
    ser.open()

# Give the connection a moment to settle
time.sleep(2)

# Function to send command
def send_command(command):
    full_command = command + '\r\n'  # Add the newline character
    ser.write(full_command.encode('ascii'))  # Send the command
    time.sleep(1)  # Wait for the device to respond
    response = ser.read_all()  # Read the response
    return response

command_dict = {
    'warm': '?WARMUP%\r\n',
    'idn': '?IDN\r\n',

}

response = send_command('?IDN\r\n').decode('ascii')
print(f"Response: {response}")
time.sleep(0.5)
response = send_command('?WARMUP%\r\n').decode('ascii')
print(f"Response: {response}")
while True:
    command = input('Enter command: \n')
    if command == 'exit':
        break
    # response = send_command(command).decode('ascii')
    if command in command_dict:
        response = send_command(command_dict[command]).decode('ascii')
    else:
        response = send_command(command).decode('ascii')
    print(f"Response: {response}")
    ser.flushInput()
    ser.flushOutput()
# Close the serial connection
ser.close()
