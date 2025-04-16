import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import threading
import time

from instruments import Microscope
from interface_run_me import Interface


from acquisitioncontrol import AcquisitionParameters, AcquisitionGUI
import tkinter as tk
import threading

class MockMicroscope:

    def __init__(self):
        self.config = {"ldr_scan_dict": {
            "l1": {
            "range": 500,
            "resolution": 10
            },
            "l2": {
            "range": 250,
            "resolution": 25
            },
            "l3": {
            "range": 10000,
            "resolution": 1000
            },
            "g1": {
            "range": 100,
            "resolution": 5
            },
            "g2": {
            "range": 150,
            "resolution": 5
            },
            "g3": {
            "range": 150,
            "resolution": 5
            },
            "g4": {
            "range": 150,
            "resolution": 5
            }
        },
        "hard_limits": {
            "laser_wavelength": [
            650,
            1000
            ],
            "monochromator_wavelength": [
            500,
            1300
            ],
            "grating_wavelength": [
            500,
            1300
            ]
        },
        "home_positions": {
            "1A": 0,
            "1X": -111933,
            "1Y": -11690,
            "1Z": -33497,
            "2A": 0,
            "2X": 0,
            "2Y": 0,
            "2Z": 0,
            "3A": -3774,
            "3X": -4272,
            "3Y": -4424,
            "3Z": -3240,
            "4A": 0,
            "4X": 0,
            "4Y": 0,
            "4Z": 0
        },
        "last_stage_position": {
            "X": 0,
            "Y": 0,
            "Z": 0,
            "A": 0
        },
        "action_groups": {
            "laser_wavelength": {
            "l1": "1X",
            "l2": "1Y",
            "l3": "1Z"
            },
            "grating_wavelength": {
            "g1": "3Z",
            "g2": "3A",
            "g3": "3X",
            "g4": "3Y"
            },
            "monochromator_wavelength": {
            "g3": "3X",
            "g4": "3Y"
            },
            "polarization": {
            "p_in": "4X",
            "p_out": "4Y"
            },
            "triax": {
            "triax": "triax"
            },
            "stage_movement": {
            "X": "2X",
            "Y": "2Y",
            "Z": "2Z",
            "mode": "2A"
            }
        }
        }
        self.motor_map = {}
        for group in self.config['action_groups'].values():
            self.motor_map.update(group)

    def move_stage(self, motor_positions):
        '''Moves the stage to the specified position.'''
        # print("Moving the stage to the specified position.")
        motor_dict = {}

        if isinstance(motor_positions, str):
            # Example input: "X100 Y200 Z300"
            for motor in motor_positions.split(' '):
                try:
                    name = motor[0]
                    position = int(motor[1:])
                except Exception as e:
                    print(f"Error parsing motor position: {e}")
                    continue
                if name not in self.motor_map:
                    print(f"Unknown motor name: {name}")
                    continue
                if name in motor_dict:
                    print(f"Duplicate motor name: {name}")
                    continue
                
                if position != 0:
                    motor_dict[name] = position

        elif isinstance(motor_positions, tuple):
            # Example input: (100, 200, 300)
            if len(motor_positions) != 3:
                print("Invalid motor positions tuple length.")
                return
            motor_dict = {
                'X': motor_positions[0],
                'Y': motor_positions[1],
                'Z': motor_positions[2]
            }

        elif isinstance(motor_positions, dict):
            # Example input: {'X': 100, 'Y': 200, 'Z': 300}
            motor_dict = {key:int(value) for key, value in motor_positions.items()}

        motor_id_dict = {self.motor_map[motor]: steps for motor, steps in motor_dict.items() if motor in self.motor_map}

        # self.controller.move_stage(motor_id_dict)
        self.print_move_stage(motor_dict)

    def print_move_stage(self, motion_dict):
        sequence = ''.join([f"{key}" for key in motion_dict.keys()])
        positions = ''.join([f"{motion_dict[key]}" for key in motion_dict.keys()])
        print(f"Moving {sequence} {''.join(*positions)}")



    def move_x(self, position):
        print(f"Moving X to {position}")
    
    def move_y(self, position):
        print(f"Moving Y to {position}")

    def move_z(self, position):
        print(f"Moving Z to {position}")

    def go_to_polarization_in(self, angle):
        print(f"Setting polarization input to {angle} degrees")
    
    def go_to_polarization_out(self, angle):
        print(f"Setting polarization output to {angle} degrees")

    def go_to_wavelength_all(self, wavelength):
        print(f"Setting wavelength to {wavelength} nm")
    
    def acquire(self):
        print("Acquiring spectrum...")
        return [1, 2, 3, 4, 5]

    def save_spectrum(self, filename):
        print(f"Saving spectrum to {filename}")

def open_acquisition_CLI():
    params = AcquisitionParameters()
    params.prompt_for_cli_parameters()
    print("\nFinal parameters after CLI input:")
    print("General:", params.general_parameters)
    print("Motion:", params.motion_parameters)
    print("Wavelength:", params.wavelength_parameters)
    print("Polarization:", params.polarization_parameters)
    return params

def open_acquisition_GUI():
    def run_gui():
        root = tk.Tk()
        params = AcquisitionParameters(MockMicroscope())
        app = AcquisitionGUI(root, params)
        root.mainloop()

    gui_thread = threading.Thread(target=run_gui)
    gui_thread.daemon = True  # Close GUI when main thread ends
    gui_thread.start()



if __name__ == '__main__':
    open_acquisition_GUI()
    while True:
        time.sleep(10)
    # open_acquisition_CLI()