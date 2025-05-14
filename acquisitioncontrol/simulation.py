from .acqcontrol import AcquisitionControl
from .acqgui import AcquisitionGUI
import os
import threading
import time
import numpy as np
import tkinter as tk

class DummyMicroscope:
    def __init__(self):
        self.stage_positions_microns = {'x': 0.0, 'y': 0.0, 'z': 0.0}
        self.laser_wavelengths = {'l1': 532.0}
        self.monochromator_wavelengths = {'g3': 500.0}
        self.dataDir = os.path.join(os.path.dirname(__file__), 'data')
        self.scriptDir = os.path.dirname(__file__)
        self.acquisitionControlDir = self.scriptDir
        self.motion_control = None
        self.calibration_service = None

    def get_detector_temperature(self):
        return -50.0

    def set_acquisition_time(self, time):
        pass

    def set_laser_power(self, power):
        pass

    def raman_mode(self):
        pass

    def acquire_one_frame(self, export_raw=False):
        return np.random.rand(100, 100)
    
    def go_to_polarization_in(self, angle):
        print("Setting input polarization angle to {}".format(angle))

    def go_to_polarization_out(self, angle):
        print("Setting output polarization angle to {}".format(angle))
    
    def go_to_wavelength_all(self, wavelength):
        print("Setting wavelength to {}".format(wavelength))
    
    def move_motors(self, motor_dict):
        for motor, steps in motor_dict.items():
            print(f"Moving {motor} by {steps} steps")


def run_gui(exit_event):
    """Run the GUI in a separate thread."""
    root = tk.Tk()
    acq = AcquisitionControl(microscope=DummyMicroscope())
    gui = AcquisitionGUI(root, acq)
    gui.exit_event = exit_event  # Pass the shared event
    root.mainloop()

if __name__ == '__main__':
    exit_event = threading.Event()
    threading.Thread(target=run_gui, args=(exit_event,), daemon=True).start()

    while not exit_event.is_set():
        time.sleep(10)
        print("Main thread is running. Press QUIT to exit.")

