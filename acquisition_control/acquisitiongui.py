import time
import json
import tkinter as tk
import threading
import numpy as np
from tkinter import ttk, messagebox


class AcquisitionGUI:
    def __init__(self, root, acquisition_params, exit_event=None):
        self.exit_event = exit_event
        print("Acquisition GUI initialized.")
        self.root = root
        self.root.title("Acquisition Parameter Setup")
        self.params = acquisition_params
        self.entries = {}
        # self.scan_mode_enabled = tk.BooleanVar()
        self.cancel_event = threading.Event()
        self.scan_thread = None
        self.start_time = None
        # self.scan_mode = tk.StringVar(value=self.params.buttom_parameters.get('scan_type', 'linescan'))
        # GUI features
        self.separate_resolution_enabled = tk.BooleanVar(value=True)
        self.z_scan_enabled = tk.BooleanVar(value=False)
        self.motion_widgets_frame = None
        


        

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

        control_frame = ttk.LabelFrame(self.motion_frame, text="Motion Settings")
        control_frame.pack(fill="x", pady=5, padx=5)

        tk.Checkbutton(
            control_frame,
            text="Enable separate resolution per axis",
            variable=self.separate_resolution_enabled,
            command=self.rebuild_motion_section
        ).pack(anchor="w")

        tk.Checkbutton(
            control_frame,
            text="Enable Z-axis scanning",
            variable=self.z_scan_enabled,
            command=self.rebuild_motion_section
        ).pack(anchor="w")


        self.build_nested_section(self.motion_frame, self.params.motion_parameters, section="motion")
        self.build_section(self.wavelength_frame, self.params.wavelength_parameters, section="wavelength")
        self.build_nested_section(self.polarization_frame, self.params.polarization_parameters, section="polarization")

        # tk.Checkbutton(self.root, text="Enable Scan Mode", variable=self.scan_mode_enabled,
        #                command=self.toggle_scan_mode).pack(pady=5)
        self.status_label = tk.Label(self.root, text="", fg="red")
        self.status_label.pack()

        self.toggle_button = tk.Button(self.root, text=f"Mode: {self.params.general_parameters.get('scan_type', 'linescan')}", command=self.toggle_scan_mode)
        self.toggle_button.pack(pady=5)

        self.single_button = tk.Button(self.root, text="Single Acquisition", command=self.start_single_acquisition)
        self.single_button.pack(pady=5)

        self.scan_button = tk.Button(self.root, text="Start Scan Acquisition", command=self.start_scan_acquisition)
        self.scan_button.pack(pady=5)
        # self.scan_button.config(state="disabled")

        self.scan_status = tk.Label(self.root, text="Idle", fg="blue")
        self.scan_status.pack(pady=5)

        self.progress_bar = tk.Label(self.root, text="[                    ]", font=("Courier", 10))
        self.progress_bar.pack(pady=2)
        self.elapsed_label = tk.Label(self.root, text="Elapsed: 0.0s")
        self.elapsed_label.pack(pady=2)
        self.estimate_label = tk.Label(self.root, text="Estimated scan time: 0.0s")
        self.estimate_label.pack(pady=2)

        self.update_button = tk.Button(self.root, text="Update Params", command=self.validate_and_update_parameters)
        self.update_button.pack(pady=5)


        self.cancel_button = tk.Button(self.root, text="Cancel Scan", command=self.cancel_scan)
        self.cancel_button.pack(pady=5)
        self.cancel_button.config(state="disabled")
        
        # --- Quit Button ---
        self.quit_button = tk.Button(self.root, text="Quit", command=self.quit_app)
        self.quit_button.pack(pady=5)

        # Motion controls frame
        self.motion_widgets_frame = ttk.Frame(self.motion_frame)
        self.motion_widgets_frame.pack(fill='both', expand=True)
        self.build_motion_controls()


    def rebuild_motion_section(self):
        for widget in self.motion_widgets_frame.winfo_children():
            widget.destroy()
        self.build_motion_controls()

    def build_motion_controls(self):
        # Clone the dictionary
        motion_params = json.loads(json.dumps(self.params.motion_parameters))

        # Drop Z if disabled
        if not self.z_scan_enabled.get():
            for key in ['start_position', 'end_position']:
                motion_params[key].pop('z', None)
        
        # Merge or separate resolution
        if not self.separate_resolution_enabled.get():
            avg_res = np.mean([
                motion_params['resolution'].get(axis, 1.0)
                for axis in motion_params['resolution']
            ])
            motion_params['resolution'] = {'all': avg_res}

        self.build_nested_section(self.motion_widgets_frame, motion_params, section="motion")



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

    # def toggle_scan_mode(self):
    #     if self.scan_mode_enabled.get():
    #         self.scan_button.config(state="normal")
    #         self.status_label.config(text="Scan mode enabled")
    #     else:
    #         self.scan_button.config(state="disabled")
    #         self.status_label.config(text="")

    def toggle_scan_mode(self):
        # current = self.scan_mode.get()
        current = self.params.button_parameters.get('scan_type')
        new_mode = "linescan" if current == "map" else "map"
        # self.scan_mode.set(new_mode)
        self.params.button_parameters['scan_type'] = new_mode

        self.toggle_button.config(text=f"Mode: {new_mode.lower()}")
        self.status_label.config(text=f"Scan mode set to {new_mode}")
        self.validate_and_update_parameters()


    def validate_and_update_parameters(self):
        self.params.general_parameters['n_frames'] = int(self.params.general_parameters['n_frames'])

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
        # self.status_label.config(text="")

        # Handle motion resolution special case
        if not self.separate_resolution_enabled.get():
            all_res = self.entries.get("motion.resolution.all")[0].get()
            try:
                res_val = float(all_res)
                for axis in ['x', 'y']:
                    self.params.motion_parameters['resolution'][axis] = res_val
                if self.z_scan_enabled.get():
                    self.params.motion_parameters['resolution']['z'] = res_val
            except ValueError:
                self.status_label.config(text="Invalid global resolution value")
                return False


        self.update_scan_estimate()
        self.params.save_config()
        return True

    def update_scan_estimate(self):
        try:
            duration = self.params.estimate_scan_duration()

            if duration > 600:
                scan_time = {'duration': duration / 60, 'units': 'minutes'}
            elif duration > 3600:
                scan_time = {'duration': duration / 3600, 'units': 'hours'}
            else:
                scan_time = {'duration': duration, 'units': 'seconds'}

            duration = scan_time['duration']
            units = scan_time['units']

            self.estimate_label.config(text=f"Estimated scan time: {duration:.1f} {units}")
            self.estimated_scan_time = scan_time
            return scan_time
        except Exception as e:
            print(f"Error estimating scan time: {e}")
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
        """Quit the application and set the exit event."""
        self.cancel_event.set()
        if self.exit_event:
            self.exit_event.set()
        self.root.destroy()
