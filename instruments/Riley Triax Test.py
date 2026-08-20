import warnings
import pyvisa

# 1. Mute the LightField background warning
warnings.filterwarnings("ignore", message=".VI_WARN_CONFIG_NLOADED.")

# 2. Initialize PyVISA with the pure Python backend
rm = pyvisa.ResourceManager()

try:
    print("Opening connection to Triax 550 (Firmware V2.10) at Address 1...")
    triax = rm.open_resource('GPIB0::1::INSTR')
    
    # 3. Apply the exact strict rules discovered during the tool breakthrough
    triax.timeout = 5000            # Give it 5 seconds to reply
    triax.send_end = True           # CRITICAL: Force the Keithley to assert the physical EOI hardware line
    triax.write_termination = ''    # CRITICAL: Send raw data with absolutely no added '\r' or '\n'
    triax.read_termination = ''     # CRITICAL: Do not wait for a text newline; stop reading when EOI goes low

    # 4. Send the universal firmware ping that gave you the V2.10 string
    print("\nVerifying communication link...")
    triax.write('*IDN?')
    
    # Read the raw response back from the buffer
    response = triax.read().strip()
    
    print("\n=========================================")
    print("SUCCESS! Python Connection Established.")
    print(f"Spectrometer Returned: '{response}'")
    print("=========================================")

except pyvisa.errors.VisaIOError as e:
    print(f"\nVISA Error: {e}")
    print("If it timed out, try manually running triax.clear() to empty the hardware cache.")
except Exception as e:
    print(f"\nUnexpected error occurred: {e}")
finally:
    # 5. Always release the locks so you don't break the driver layer
    if 'triax' in locals():
        triax.close()
    rm.close()
    print("\nLine cleanly closed and ready for automation.")