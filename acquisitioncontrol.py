import time
import os
import json
import tkinter as tk
import threading
import numpy as np
from tkinter import ttk, messagebox

class AcquisitionParameters:
    def __init__(self):
        self.general_parameters = {
            'acquisition_time': 1000.0,
            'filename': 'default',
            'raman_shift': 0.0,
            'laser_power': 4.5,
        }

        self.motion_parameters = {
            'start_position': {'x': 0.0, 'y': 0.0, 'z': 0.0},
            'end_position': {'x': 0.0, 'y': 0.0, 'z': 0.0},
            'resolution': {'x': 0.0, 'y': 0.0, 'z': 0.0}
        }

        self.wavelength_parameters = {
            'start_wavelength': 0.0,
            'end_wavelength': 0.0,
            'resolution': 1.0
        }

        self.polarization_parameters = {
            'input': {'start_angle': 0.0, 'end_angle': 0.0, 'resolution': 1.0},
            'output': {'start_angle': 0.0, 'end_angle': 0.0, 'resolution': 1.0}
        }

    def estimate_scan_duration(self):
        x_range = (self.motion_parameters['end_position']['x'] - self.motion_parameters['start_position']['x']) / self.motion_parameters['resolution']['x']
        y_range = (self.motion_parameters['end_position']['y'] - self.motion_parameters['start_position']['y']) / self.motion_parameters['resolution']['y']
        p_range = (self.polarization_parameters['input']['end_angle'] - self.polarization_parameters['input']['start_angle']) / self.polarization_parameters['input']['resolution']
        w_range = (self.wavelength_parameters['end_wavelength'] - self.wavelength_parameters['start_wavelength']) / self.wavelength_parameters['resolution']

        n_steps = max(1, int(x_range + 1)) * max(1, int(y_range + 1)) * max(1, int(p_range + 1)) * max(1, int(w_range + 1))
        time_per = self.general_parameters['acquisition_time'] / 1000.0
        return n_steps * time_per * 1.2


    def prompt_for_cli_parameters(self):
        print("\n--- CLI Parameter Entry ---")
        self._prompt_section(self.general_parameters, "General Parameters")
        self._prompt_nested_section(self.motion_parameters, "Motion Parameters")
        self._prompt_section(self.wavelength_parameters, "Wavelength Parameters")
        self._prompt_nested_section(self.polarization_parameters, "Polarization Parameters")

    def _prompt_section(self, param_dict, section_name):
        print(f"\n{section_name}:")
        for key, default in param_dict.items():
            while True:
                user_input = input(f"  {key} (default: {default}): ")
                if user_input == "":
                    break
                try:
                    if isinstance(default, float):
                        param_dict[key] = float(user_input)
                    elif isinstance(default, int):
                        param_dict[key] = int(user_input)
                    else:
                        param_dict[key] = user_input
                    break
                except ValueError:
                    print(f"Invalid input for {key}. Expected type {type(default).__name__}.")

    def _prompt_nested_section(self, nested_dict, section_name):
        print(f"\n{section_name}:")
        for subgroup, subdict in nested_dict.items():
            print(f"  {subgroup.capitalize()}:")
            for key, default in subdict.items():
                while True:
                    user_input = input(f"    {key} (default: {default}): ")
                    if user_input == "":
                        break
                    try:
                        if isinstance(default, float):
                            nested_dict[subgroup][key] = float(user_input)
                        elif isinstance(default, int):
                            nested_dict[subgroup][key] = int(user_input)
                        else:
                            nested_dict[subgroup][key] = user_input
                        break
                    except ValueError:
                        print(f"Invalid input for {key}. Expected type {type(default).__name__}.")

    def save_config(self, directory, filename="acquisition_config.json"):
        config = {
            'general_parameters': self.general_parameters,
            'motion_parameters': self.motion_parameters,
            'wavelength_parameters': self.wavelength_parameters,
            'polarization_parameters': self.polarization_parameters,
        }
        os.makedirs(directory, exist_ok=True)
        filepath = os.path.join(directory, filename)
        with open(filepath, 'w') as f:
            json.dump(config, f, indent=2)

    def load_config(self, filepath):
        with open(filepath, 'r') as f:
            config = json.load(f)
        self.general_parameters = config.get('general_parameters', self.general_parameters)
        self.motion_parameters = config.get('motion_parameters', self.motion_parameters)
        self.wavelength_parameters = config.get('wavelength_parameters', self.wavelength_parameters)
        self.polarization_parameters = config.get('polarization_parameters', self.polarization_parameters)



        # Example of constructing a scan sequence
        # This is just a placeholder and should be replaced with actual logic

    def save_spectrum(self, step, spectrum):
        print("saving spectrum...")

    def generate_scan_sequence(self, microscope):
        """
        Construct the scan sequence from microscope methods based on the parameters set in the this class object.
        
        Parameters:
        microscope (Microscope): The microscope object.
        
        Current heirarchy of the scan sequence is based on timing efficiency and stability of each mode. Higher numbers on the heirachy change first. Currently:
        1. Wavelength
        2. Polarization
        3. Motion
        
        So motion is the first to change.
        """

        sequence = []

        # Get the parameters
        wavelength_list = np.arange(
            self.wavelength_parameters['start_wavelength'],
            self.wavelength_parameters['end_wavelength'],
            self.wavelength_parameters['resolution']
        )

        polarization_list = np.arange(
            self.polarization_parameters['input']['start_angle'],
            self.polarization_parameters['input']['end_angle'],
            self.polarization_parameters['input']['resolution']
        )

        x_positions = np.arange(
            self.motion_parameters['start_position']['x'],
            self.motion_parameters['end_position']['x'],
            self.motion_parameters['resolution']['x']
        )

        y_positions = np.arange(
            self.motion_parameters['start_position']['y'],
            self.motion_parameters['end_position']['y'],
            self.motion_parameters['resolution']['y']
        )

        z_val = self.motion_parameters['start_position']['z'] # fixed for now
        # Create the sequence

        for wl in wavelength_list:
            for pol in polarization_list:
                for y in y_positions:
                    for x in x_positions:
                        pos = [x, y, z_val, wl, pol]
                        entry = [val if val != prev[i] else None for i, val in enumerate(pos)]
                        sequence.append(entry)
                        prev = pos  # Update previous

        return sequence

    def acquire_scan(self, microscope, cancel_event, status_callback, progress_callback):
        sequence = [f"Step {i+1}" for i in range(10)]  # placeholder scan sequence
        total = len(sequence)
        start_time = time.time()

        predicted_time = (total * self.general_parameters['acquisition_time'] / 1000.0) *1.2 # 20% overhead
        print(f"Predicted time: {predicted_time:.2f} seconds")

        acquisition_time = self.general_parameters['acquisition_time']
        raman_shift = self.general_parameters['raman_shift']
        laser_power = self.general_parameters['laser_power']
        filename = self.general_parameters['filename']


        for i, step in enumerate(sequence):
            if cancel_event.is_set():
                status_callback("Scan cancelled.")
                return
            status_callback(f"Running step {i}: {step}")
            progress_callback(i + 1, total, start_time)

            microscope.move_to(step)
            spectrum = microscope.acquire()
            self.save_spectrum(step, spectrum)
        status_callback("Scan complete.")
        progress_callback(total, total, start_time)

        print("Scan complete.")

        pass


class AcquisitionGUI:
    def __init__(self, root, acquisition_params):
        self.root = root
        self.root.title("Acquisition Parameter Setup")
        self.params = acquisition_params
        self.entries = {}
        self.scan_mode_enabled = tk.BooleanVar()
        self.cancel_event = threading.Event()
        self.scan_thread = None
        self.start_time = None
        self.build_gui()

    def build_gui(self):
        notebook = ttk.Notebook(self.root)

        self.general_frame = ttk.Frame(notebook)
        self.motion_frame = ttk.Frame(notebook)
        self.wavelength_frame = ttk.Frame(notebook)
        self.polarization_frame = ttk.Frame(notebook)

        notebook.add(self.general_frame, text="General")
        notebook.add(self.motion_frame, text="Motion")
        notebook.add(self.wavelength_frame, text="Wavelength")
        notebook.add(self.polarization_frame, text="Polarization")
        notebook.pack(expand=1, fill="both")

        self.build_section(self.general_frame, self.params.general_parameters, section="general")
        self.build_nested_section(self.motion_frame, self.params.motion_parameters, section="motion")
        self.build_section(self.wavelength_frame, self.params.wavelength_parameters, section="wavelength")
        self.build_nested_section(self.polarization_frame, self.params.polarization_parameters, section="polarization")

        tk.Checkbutton(self.root, text="Enable Scan Mode", variable=self.scan_mode_enabled, command=self.toggle_scan_mode).pack(pady=5)
        self.status_label = tk.Label(self.root, text="", fg="red")
        self.status_label.pack()

        self.single_button = tk.Button(self.root, text="Start Single Acquisition", command=self.start_single_acquisition)
        self.single_button.pack(pady=5)

        self.scan_button = tk.Button(self.root, text="Start Scan Acquisition", command=self.start_scan_acquisition)
        self.scan_button.pack(pady=5)
        self.scan_button.config(state="disabled")

        self.scan_status = tk.Label(self.root, text="Idle", fg="blue")
        self.scan_status.pack(pady=5)

        self.progress_bar = tk.Label(self.root, text="[                    ]", font=("Courier", 10))
        self.progress_bar.pack(pady=2)
        self.elapsed_label = tk.Label(self.root, text="Elapsed: 0.0s")
        self.elapsed_label.pack(pady=2)
        self.estimate_label = tk.Label(self.root, text="Estimated scan time: 0.0s")
        self.estimate_label.pack(pady=2)


        self.cancel_button = tk.Button(self.root, text="Cancel Scan", command=self.cancel_scan)
        self.cancel_button.pack(pady=5)
        self.cancel_button.config(state="disabled")


    def build_section(self, frame, parameters, section):
        for key, value in parameters.items():
            row = ttk.Frame(frame)
            row.pack(fill='x', pady=2)
            ttk.Label(row, text=key).pack(side='left')
            var = tk.StringVar(value=str(value))
            entry = ttk.Entry(row, textvariable=var)
            entry.pack(side='right', expand=True, fill='x')
            self.entries[f"{section}.{key}"] = (var, type(value))

    def build_nested_section(self, frame, nested_params, section):
        for subgroup, params in nested_params.items():
            label = ttk.LabelFrame(frame, text=subgroup.capitalize())
            label.pack(fill='x', pady=5, padx=5)
            self.build_section(label, params, f"{section}.{subgroup}")

    def toggle_scan_mode(self):
        if self.scan_mode_enabled.get():
            self.scan_button.config(state="normal")
            self.status_label.config(text="Scan mode enabled")
        else:
            self.scan_button.config(state="disabled")
            self.status_label.config(text="")

    def live_update_param(self, key, value, expected_type, section):
        try:
            if expected_type == float:
                value = float(value)
            elif expected_type == int:
                value = int(value)
            subkeys = key.split(".")
            target = getattr(self.params, f"{section}_parameters")
            for sub in subkeys[:-1]:
                target = target[sub]
            target[subkeys[-1]] = value
            self.update_scan_estimate()
        except ValueError:
            pass

    def update_scan_estimate(self):
        try:
            duration = self.params.estimate_scan_duration()
            self.estimate_label.config(text=f"Estimated scan time: {duration:.1f}s")
        except Exception:
            self.estimate_label.config(text="Estimated scan time: error")

    def validate_and_update_parameters(self):
        for key, (var, expected_type) in self.entries.items():
            val = var.get()
            try:
                if expected_type == float:
                    converted = float(val)
                elif expected_type == int:
                    converted = int(val)
                else:
                    converted = val

                section, subkey = key.split(".", 1)
                keys = subkey.split(".")
                target = getattr(self.params, f"{section}_parameters")
                for k in keys[:-1]:
                    target = target[k]
                target[keys[-1]] = converted
                self.update_scan_estimate()

            except ValueError:
                self.status_label.config(text=f"Invalid type for {key}: expected {expected_type.__name__}")
                return False
        self.status_label.config(text="")
        return True

    def start_single_acquisition(self):
        if self.validate_and_update_parameters():
            print("Starting single acquisition with parameters:")
            print(self.params.general_parameters)

    def start_scan_acquisition(self):
        if self.validate_and_update_parameters():
            self.cancel_event.clear()
            self.scan_button.config(state="disabled")
            self.cancel_button.config(state="normal")
            self.scan_status.config(text="Scan started...")
            self.start_time = time.time()
            self.scan_thread = threading.Thread(
                target=self.params.acquire_scan,
                args=(MockMicroscope(), self.cancel_event, self.update_status, self.update_progress)
            )
            self.scan_thread.start()
            self.root.after(500, self.poll_scan_thread)

    def poll_scan_thread(self):
        if self.scan_thread and self.scan_thread.is_alive():
            self.root.after(500, self.poll_scan_thread)
        else:
            self.scan_button.config(state="normal")
            self.cancel_button.config(state="disabled")

    def cancel_scan(self):
        self.cancel_event.set()
        self.update_status("Cancelling scan...")
    
    def update_status(self, message):
        self.scan_status.config(text=message)

    def update_progress(self, current, total, start_time):
        bar_length = 20
        filled_length = int(bar_length * current // total)
        bar = '[' + '#' * filled_length + ' ' * (bar_length - filled_length) + ']'
        self.progress_bar.config(text=bar)
        elapsed = time.time() - start_time
        self.elapsed_label.config(text=f"Elapsed: {elapsed:.1f}s")


class MockMicroscope:
    def move_to(self, step):
        import time
        time.sleep(0.5)

    def acquire(self):
        return [0] * 1000  # dummy spectrum