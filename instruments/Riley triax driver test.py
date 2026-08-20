import serial
import time

ser = serial.Serial(
    port='COM16',        # change to your port
    baudrate=4800,
    bytesize=serial.EIGHTBITS,
    parity=serial.PARITY_NONE,
    stopbits=serial.STOPBITS_ONE,
    timeout=2
)

time.sleep(0.5)

ser.write(b'H0\r')
time.sleep(0.5)
response = ser.read(ser.in_waiting)

# Init (Only required after Triax is powercycled. Does nothing otherwise)
has_digits = any(char.isdigit() for char in response.decode('ascii', errors='replace'))

if 'o' in response.decode('ascii', errors='replace') and has_digits:
    print("✅ TRIAX already initialised — skipping init")
else:
    print("⚠️  TRIAX not initialised — init required")
    ser.write(b' \r')
    time.sleep(1)  # Wait for the Triax to fully initialize


# Open Intelligent mode
ser.write(bytes([248]))

# Check two-character response
ser.write(b'H0\r')
time.sleep(0.5)
response = ser.read(ser.in_waiting)
print("Response to H0:", response.decode('ascii', errors='replace'))

# Send wavelength move command
ser.write(b'Z61,1,20000.000\r')
time.sleep(0.5)

# Read response
response = ser.read(ser.in_waiting)
print("Response:", response.decode('ascii', errors='replace'))

ser.close()
