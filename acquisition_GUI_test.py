import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import threading

from instruments import Microscope
from interface_run_me import Interface

# class AcquisitionParameters:
#     def __init__(self):
#         self.general_parameters = {
#             'acquisition_time': 1000.0,
#             'filename': 'default',
#             'raman_shift': 0.0,
#             'laser_power': 4.5,
#         }

#         self.motion_parameters = {
#             'start_position': {'x': 0.0, 'y': 0.0, 'z': 0.0},
#             'end_position': {'x': 0.0, 'y': 0.0, 'z': 0.0},
#             'resolution': {'x': 1.0, 'y': 1.0, 'z': 1.0}
#         }

#         self.wavelength_parameters = {
#             'start_wavelength': 0.0,
#             'end_wavelength': 0.0,
#             'resolution': 1.0
#         }

#         self.polarization_parameters = {
#             'input': {'start_angle': 0.0, 'end_angle': 0.0, 'resolution': 1.0},
#             'output': {'start_angle': 0.0, 'end_angle': 0.0, 'resolution': 1.0}
#         }

#     def prompt_for_cli_parameters(self):
#         print("\n--- CLI Parameter Entry ---")
#         self._prompt_section(self.general_parameters, "General Parameters")
#         self._prompt_nested_section(self.motion_parameters, "Motion Parameters")
#         self._prompt_section(self.wavelength_parameters, "Wavelength Parameters")
#         self._prompt_nested_section(self.polarization_parameters, "Polarization Parameters")

#     def _prompt_section(self, param_dict, section_name):
#         print(f"\n{section_name}:")
#         for key, default in param_dict.items():
#             while True:
#                 user_input = input(f"  {key} (default: {default}): ")
#                 if user_input == "":
#                     break
#                 try:
#                     if isinstance(default, float):
#                         param_dict[key] = float(user_input)
#                     elif isinstance(default, int):
#                         param_dict[key] = int(user_input)
#                     else:
#                         param_dict[key] = user_input
#                     break
#                 except ValueError:
#                     print(f"Invalid input for {key}. Expected type {type(default).__name__}.")

#     def _prompt_nested_section(self, nested_dict, section_name):
#         print(f"\n{section_name}:")
#         for subgroup, subdict in nested_dict.items():
#             print(f"  {subgroup.capitalize()}:")
#             for key, default in subdict.items():
#                 while True:
#                     user_input = input(f"    {key} (default: {default}): ")
#                     if user_input == "":
#                         break
#                     try:
#                         if isinstance(default, float):
#                             nested_dict[subgroup][key] = float(user_input)
#                         elif isinstance(default, int):
#                             nested_dict[subgroup][key] = int(user_input)
#                         else:
#                             nested_dict[subgroup][key] = user_input
#                         break
#                     except ValueError:
#                         print(f"Invalid input for {key}. Expected type {type(default).__name__}.")

#     def save_config(self, directory, filename="acquisition_config.json"):
#         config = {
#             'general_parameters': self.general_parameters,
#             'motion_parameters': self.motion_parameters,
#             'wavelength_parameters': self.wavelength_parameters,
#             'polarization_parameters': self.polarization_parameters,
#         }
#         os.makedirs(directory, exist_ok=True)
#         filepath = os.path.join(directory, filename)
#         with open(filepath, 'w') as f:
#             json.dump(config, f, indent=2)

#     def load_config(self, filepath):
#         with open(filepath, 'r') as f:
#             config = json.load(f)
#         self.general_parameters = config.get('general_parameters', self.general_parameters)
#         self.motion_parameters = config.get('motion_parameters', self.motion_parameters)
#         self.wavelength_parameters = config.get('wavelength_parameters', self.wavelength_parameters)
#         self.polarization_parameters = config.get('polarization_parameters', self.polarization_parameters)


# class AcquisitionGUI:
#     def __init__(self, root, acquisition_params):
#         self.root = root
#         self.root.title("Acquisition Parameter Setup")
#         self.params = acquisition_params
#         self.entries = {}
#         self.scan_mode_enabled = tk.BooleanVar()
#         self.build_gui()

#     def build_gui(self):
#         notebook = ttk.Notebook(self.root)

#         self.general_frame = ttk.Frame(notebook)
#         self.motion_frame = ttk.Frame(notebook)
#         self.wavelength_frame = ttk.Frame(notebook)
#         self.polarization_frame = ttk.Frame(notebook)

#         notebook.add(self.general_frame, text="General")
#         notebook.add(self.motion_frame, text="Motion")
#         notebook.add(self.wavelength_frame, text="Wavelength")
#         notebook.add(self.polarization_frame, text="Polarization")
#         notebook.pack(expand=1, fill="both")

#         self.build_section(self.general_frame, self.params.general_parameters, section="general")
#         self.build_nested_section(self.motion_frame, self.params.motion_parameters, section="motion")
#         self.build_section(self.wavelength_frame, self.params.wavelength_parameters, section="wavelength")
#         self.build_nested_section(self.polarization_frame, self.params.polarization_parameters, section="polarization")

#         tk.Checkbutton(self.root, text="Enable Scan Mode", variable=self.scan_mode_enabled, command=self.toggle_scan_mode).pack(pady=5)
#         self.status_label = tk.Label(self.root, text="", fg="red")
#         self.status_label.pack()

#         self.single_button = tk.Button(self.root, text="Start Single Acquisition", command=self.start_single_acquisition)
#         self.single_button.pack(pady=5)

#         self.scan_button = tk.Button(self.root, text="Start Scan Acquisition", command=self.start_scan_acquisition)
#         self.scan_button.pack(pady=5)
#         self.scan_button.config(state="disabled")

#     def build_section(self, frame, parameters, section):
#         for key, value in parameters.items():
#             row = ttk.Frame(frame)
#             row.pack(fill='x', pady=2)
#             ttk.Label(row, text=key).pack(side='left')
#             var = tk.StringVar(value=str(value))
#             entry = ttk.Entry(row, textvariable=var)
#             entry.pack(side='right', expand=True, fill='x')
#             self.entries[f"{section}.{key}"] = (var, type(value))

#     def build_nested_section(self, frame, nested_params, section):
#         for subgroup, params in nested_params.items():
#             label = ttk.LabelFrame(frame, text=subgroup.capitalize())
#             label.pack(fill='x', pady=5, padx=5)
#             self.build_section(label, params, f"{section}.{subgroup}")

#     def toggle_scan_mode(self):
#         if self.scan_mode_enabled.get():
#             self.scan_button.config(state="normal")
#             self.status_label.config(text="Scan mode enabled")
#         else:
#             self.scan_button.config(state="disabled")
#             self.status_label.config(text="")

#     def validate_and_update_parameters(self):
#         for key, (var, expected_type) in self.entries.items():
#             val = var.get()
#             try:
#                 if expected_type == float:
#                     converted = float(val)
#                 elif expected_type == int:
#                     converted = int(val)
#                 else:
#                     converted = val

#                 section, subkey = key.split(".", 1)
#                 keys = subkey.split(".")
#                 target = getattr(self.params, f"{section}_parameters")
#                 for k in keys[:-1]:
#                     target = target[k]
#                 target[keys[-1]] = converted

#             except ValueError:
#                 self.status_label.config(text=f"Invalid type for {key}: expected {expected_type.__name__}")
#                 return False
#         self.status_label.config(text="")
#         return True

#     def start_single_acquisition(self):
#         if self.validate_and_update_parameters():
#             print("Starting single acquisition with parameters:")
#             print(self.params.general_parameters)

#     def start_scan_acquisition(self):
#         if self.validate_and_update_parameters():
#             print("Starting scan acquisition with parameters:")
#             print(self.params.motion_parameters)
#             print(self.params.wavelength_parameters)
#             print(self.params.polarization_parameters)

from acquisitioncontrol import AcquisitionParameters, AcquisitionGUI
import tkinter as tk
import threading

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
        params = AcquisitionParameters(Microscope(Interface()))
        app = AcquisitionGUI(root, params)
        root.mainloop()

    gui_thread = threading.Thread(target=run_gui)
    gui_thread.daemon = True  # Close GUI when main thread ends
    gui_thread.start()



if __name__ == '__main__':
    # root = tk.Tk()
    # params = AcquisitionParameters()
    # app = AcquisitionGUI(root, params)
    # root.mainloop()
    open_acquisition_GUI()
    open_acquisition_CLI()