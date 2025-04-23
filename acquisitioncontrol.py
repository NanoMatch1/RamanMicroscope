import time
import os
import json
import tkinter as tk
import threading
import numpy as np
from tkinter import ttk, messagebox
import sys

class AcquisitionControl:
    def __init__(self, microscope=None):
        self.microscope = microscope

        self.general_parameters = {
            'acquisition_time': 1000.0,
            'filename': 'default',
            'raman_shift': 0.0,
            'laser_power': 4.5,
            'scan_index': 0,
            'scan_type': None,
        }
        self.motion_parameters = {
            'start': {'X': 0.0, 'Y': 0.0, 'Z': 0.0},
            'end': {'X': 0.0, 'Y': 0.0, 'Z': 0.0},
            'resolution': {'X': 0.0, 'Y': 0.0, 'Z': 0.0}
        }
        self.wavelength_parameters = {
            'start': 0.0,
            'end': 0.0,
            'resolution': 1.0
        }
        self.polarization_parameters = {
            'input': {'start': 0.0, 'end': 0.0, 'resolution': 1.0},
            'output': {'start': 0.0, 'end': 0.0, 'resolution': 1.0}
        }

        self._current_parameters = {
            'sample_position': {'X': 0.0, 'Y': 0.0, 'Z': 0.0},
            'laser_wavelength': 0.0,
            'polarization_in_angle': 0.0,
            'polarization_out_angle': 0.0,
            'monochromator_wavelength': 0.0,
            'spectrometer_steps': 0.0,
            'scan_index': 0,
            'scan_type': None,
            'detector_temperature': 0.0
        }

        self.all_parameters = {dict_name: getattr(self, dict_name) for dict_name in self.__dict__.keys() if dict_name.endswith('_parameters')}

        self.load_config()
        
    def update_stage_positions(self):
        self.stage_positions = {
            'X': self.microscope.stage_positions_microns['X'],
            'Y': self.microscope.stage_positions_microns['Y'],
            'Z': self.microscope.stage_positions_microns['Z']
        }
        self._current_parameters['sample_position'] = self.stage_positions
        
    @property
    def current_stage_coordinates(self):
        current_coords = [
            self.microscope.stage_positions_microns['X'], 
            self.microscope.stage_positions_microns['Y'], 
            self.microscope.stage_positions_microns['Z']
            ]
        
        self._current_parameters['sample_position'] = {
            'X': current_coords[0], 
            'Y': current_coords[1], 
            'Z': current_coords[2]
        }

        return current_coords

    def get_all_parameters(self):
        detector_temp = self.microscope.get_detector_temperature()
        self.set_current_parameters({'detector_temperature': detector_temp})

        self._current_parameters.update(self.general_parameters)
        self._current_parameters['laser_wavelength'] = self.microscope.laser_wavelengths.get('l1', 0.0)
        self._current_parameters['monochromator_wavelength'] = self.microscope.monochromator_wavelengths.get('g3', 0.0)
        # self._current_parameters['polarization_in_angle'] = self.microscope.polarization_angles.get('in', 0.0)


        return self.all_parameters
    
    def set_current_parameters(self, parameters):
        if not isinstance(parameters, dict):
            raise ValueError("Error in AcquisitionControl.set_current_parameters: Parameters should be a dictionary.")
        for key, value in parameters.items():
            if key in self._current_parameters:
                self._current_parameters[key] = value
            else:
                raise ValueError(f"Invalid parameter: {key}")
            
    def _construct_metadata(self):
        '''Constructs the dictionary of metadata to include in the saved file. This includes all parameters in the acquisition control, as well as the current stage position and the current laser wavelength.'''
        
        metadata = self.get_all_parameters()

        return metadata
    


    def estimate_scan_duration(self):
        x_range = (self.motion_parameters['end_position']['X'] - self.motion_parameters['start_position']['X']) / self.motion_parameters['resolution']['X']
        y_range = (self.motion_parameters['end_position']['Y'] - self.motion_parameters['start_position']['Y']) / self.motion_parameters['resolution']['Y']
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
                    param_dict[key] = float(user_input) if isinstance(default, float) else int(user_input)
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
                        nested_dict[subgroup][key] = float(user_input) if isinstance(default, float) else int(user_input)
                        break
                    except ValueError:
                        print(f"Invalid input for {key}. Expected type {type(default).__name__}.")

    def save_config(self, filename="acquisition_config.json"):
        config = {
            'general_parameters': self.general_parameters,
            'motion_parameters': self.motion_parameters,
            'wavelength_parameters': self.wavelength_parameters,
            'polarization_parameters': self.polarization_parameters,
        }

        filepath = os.path.join(self.dataDir, filename)
        with open(filepath, 'w') as f:
            json.dump(config, f, indent=2)

    def load_config(self, filename="acquisition_config.json"):

        filepath = os.path.join(self.dataDir, filename)
        if not os.path.exists(filepath):
            print(f"Configuration file {filepath} not found.")
            return

        try:
            with open(filepath, 'r') as f:
                config = json.load(f)

        except FileNotFoundError:
            print("Acquisition Control configuration file not found. Using default parameters.")
        except json.JSONDecodeError:
            print("Error decoding JSON from Acquisition Control configuration file. Using default parameters.")
        except Exception as e:
            print(f"Unexpected error loading Acquisition Control configuration: {e}. Using default parameters.")

        self.general_parameters = config.get('general_parameters', self.general_parameters)
        self.motion_parameters = config.get('motion_parameters', self.motion_parameters)
        self.wavelength_parameters = config.get('wavelength_parameters', self.wavelength_parameters)
        self.polarization_parameters = config.get('polarization_parameters', self.polarization_parameters)

        print("Acquisition Control configuration loaded successfully.")

    def calculate_relative_motion(self, current_positions, target_positions):

        relative_motion = [target_positions[0] - current_positions[0], target_positions[1] - current_positions[1], target_positions[2] - current_positions[2]]

        return relative_motion

    def generate_scan_sequence(self):
        def generate_array(start, end, resolution):
            if resolution == 0 or start == end:
                return [start]
            try:
                return np.arange(start, end, resolution).tolist()
            except Exception as e:
                print(f"Error generating array: {e}")
                return [start]

        sequence = []
        wavelength_list = generate_array(
            self.wavelength_parameters['start_wavelength'],
            self.wavelength_parameters['end_wavelength'],
            self.wavelength_parameters['resolution']
        )
        polarization_list = generate_array(
            self.polarization_parameters['input']['start_angle'],
            self.polarization_parameters['input']['end_angle'],
            self.polarization_parameters['input']['resolution']
        )
        x_positions = generate_array(
            self.motion_parameters['start_position']['X'],
            self.motion_parameters['end_position']['X'],
            self.motion_parameters['resolution']['X']
        )
        y_positions = generate_array(
            self.motion_parameters['start_position']['Y'],
            self.motion_parameters['end_position']['Y'],
            self.motion_parameters['resolution']['Y']
        )
        z_val = self.motion_parameters['start_position']['Z']

        prev = [self.current_stage_coordinates, None, None]
        for wl in wavelength_list:
            for pol in polarization_list:
                for y in y_positions:
                    for x in x_positions:
                        # current_positions = self.current_stage_coordinates
                        target_positions = [x, y, z_val]
                        # relative_motion = self.calculate_relative_motion(current_positions, target_positions)
                        current = [target_positions, pol, wl]
                        entry = [current[i] if current[i] != prev[i] else None for i in range(3)]
                        sequence.append(entry)
                        prev = current
        return sequence
    
    def move_stage_absolute(self, new_coordinates):
        '''Moves the microcsope sample stage to the specified absolute position in micrometers. Used by the acquisition control to move the stage to the next position in a scan.'''
        
        current_positions = self.current_stage_coordinates
        target_microns = [new-old for new, old in zip(new_coordinates, current_positions)]

        micron_dict = {
            'X': target_microns[0],
            'Y': target_microns[1],
            'Z': target_microns[2]
        }

        motor_dict = self.microscope.calibrations.microns_to_steps(micron_dict)
        # self.microscope.move_motors(motor_dict)  # Uncomment this line to actually move the stage

        # self.microscope.move_stage(motor_dict)
        print("Sent Command {}".format(motor_dict))
        print("Stage moved to ({})".format(", ".join([f"{value:.2f}" for value in new_coordinates])))

        self.microscope.update_stage_positions(micron_dict)
        self.update_stage_positions()


    def prepare_acquisition_params(self):
        self.microscope.set_acquisition_time(self.general_parameters['acquisition_time'])  # ensures acqtime is set correctly at camera level
        self.microscope.set_laser_power(self.general_parameters['laser_power'])  # ensures laser power is set correctly at camera level


    def acquire_scan(self, cancel_event, status_callback, progress_callback):

        command_hierarchy = [
            self.move_stage_absolute,
            self.microscope.go_to_polarization_in,
            self.microscope.go_to_wavelength_all,
        ]
        sequence = self.generate_scan_sequence()
        total_steps = len(sequence)
        start_time = time.time()
        predicted_time = ((total_steps * float(self.general_parameters['acquisition_time']) / 1000.0)/3600) * 1.2
        print(f"Predicted time: {predicted_time:.2f} hours")

        self.prepare_acquisition_params() # makes sure the acquisition parameters are set correctly at the hardware level before starting the scan
        if self.microscope.microscope_mode != 'ramanmode':
            self.microscope.raman_mode()

        for index, step in enumerate(sequence):
            self.general_parameters['scan_index'] = index
            if cancel_event.is_set():
                status_callback("Scan cancelled.")
                return
            status_callback(f"Running step {index}: {step}")
            progress_callback(index + 1, total_steps, start_time)
            for command, change in zip(command_hierarchy, step):
                if change is not None:
                    command(change)
            
            image_data = self.microscope.acquire_one_frame(export_raw=False)
            if image_data is None:
                print("Error image data None")
                status_callback("Error acquiring spectrum in AcquisitionControl.acquire_scan.")
                return
            
            self.save_spectrum(image_data, scan_index=index)
            self.save_spectrum_transient(image_data, wavelength_axis=self.wavelength_axis, report=False)
        status_callback("Scan complete.")
        progress_callback(total_steps, total_steps, start_time)
        print("Scan complete.")

    # def save_transient_spectrum(self, image_data, wavelength_axis, **kwargs):
    def save_spectrum_transient(self, image_data, wavelength_axis=None, **kwargs):
        if wavelength_axis is None:
            # print("No wavelength axis provided—defaulting to pixel indices.")
            wavelength_axis = np.arange(image_data.shape[1])

        # TODO:add wavelength axis to the image data along a new axis
        save_path = os.path.join(self.microscope.dataDir, 'transient_data', 'transient_data.npy')
        if kwargs.get('report', False):
            print(f"Saving transient data to {save_path}")
        print(f"Saving transient data to {save_path}")
        np.save(save_path, image_data)
        # breakpoint()# image data along a new axis

    def save_spectrum(self, image_data, **kwargs):
        scan_index     = kwargs.get('scan_index',     self.general_parameters['scan_index'])
        wavelength_axis = kwargs.get('wavelength_axis', self.microscope.wavelength_axis)
        filename       = kwargs.get('filename',       self.general_parameters['filename'])
        save_dir       = kwargs.get('save_dir',       self.microscope.dataDir)

        # write compressed data to temporary file
        file_path = os.path.join(save_dir, f"{filename}", f"{filename}_{scan_index:06d}.npz")
        if not os.path.exists(os.path.dirname(file_path)):
            os.makedirs(os.path.dirname(file_path))

        np.savez_compressed(
            file_path,
            image=image_data,
            wavelength=wavelength_axis,
            metadata=json.dumps(self.metadata)
        )

    @property
    def wavelength_axis(self):
        return self.microscope.wavelength_axis
    
    @property
    def filename(self):
        return self.general_parameters['filename']
    
    @property
    def metadata(self):
        return self._construct_metadata()
    
    @property
    def dataDir(self):
        return self.microscope.dataDir
    
    @property
    def current_position(self):
        return self._current_parameters['sample_position']
    
    
    

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

        tk.Checkbutton(self.root, text="Enable Scan Mode", variable=self.scan_mode_enabled,
                       command=self.toggle_scan_mode).pack(pady=5)
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
        
        # --- Quit Button ---
        self.quit_button = tk.Button(self.root, text="Quit", command=self.quit_app)
        self.quit_button.pack(pady=5)

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

    def validate_and_update_parameters(self):
        for key, (var, expected_type) in self.entries.items():
            val = var.get()
            try:
                converted = float(val) if expected_type == float else int(val) if expected_type == int else val
                section, subkey = key.split(".", 1)
                keys = subkey.split(".")
                target = getattr(self.params, f"{section}_parameters")
                for k in keys[:-1]:
                    target = target[k]
                target[keys[-1]] = converted
            except ValueError:
                self.status_label.config(text=f"Invalid input for {key}: expected {expected_type.__name__}")
                return False
        self.status_label.config(text="")
        self.update_scan_estimate()
        self.params.save_config()
        return True

    def update_scan_estimate(self):
        try:
            duration = self.params.estimate_scan_duration()
            self.estimate_label.config(text=f"Estimated scan time: {duration:.1f}s")
        except Exception:
            self.estimate_label.config(text="Estimated scan time: error")

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
                args=(self.cancel_event, self.update_status, self.update_progress)
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
    
    def quit_app(self):
        """Cancel any running scan, close the GUI, and exit the application."""
        self.cancel_event.set()  # Ensure that any scan thread is signalled to stop
        self.root.destroy()
        # sys.exit(0)  # End the application