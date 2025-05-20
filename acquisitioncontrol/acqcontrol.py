import os
import time
import json
import numpy as np
import tkinter as tk

import numpy as np
import math

import traceback

class ScanSequenceGenerator:

    def __init__(self, acq_ctrl):
        self.acq_ctrl = acq_ctrl
        self.scan_mode = acq_ctrl.scan_mode
        self.motion_parameters = acq_ctrl.motion_parameters
        self.wavelength_parameters = acq_ctrl.wavelength_parameters
        self.polarization_parameters = acq_ctrl.polarization_parameters

    def _generate_array(self, start, end, step):
        """
        Return a list from start to end (exclusive) in increments of step.
        If step <= 0 or start == end, returns [start].
        """
        if step <= 0 or start == end:
            return [start]
        try:
            return np.arange(start, end, step).tolist()
        except Exception as e:
            print(f"Error generating array from {start} to {end} step {step}: {e}")
            return [start]

    def generate_map_sequence(self):
        """
        Build a 3D map scan sequence over X, Y with varying polarization and wavelength.
        Uses X resolution for both X and Y as a temporary workaround.
        Returns list of [position, polarization, wavelength] entries, with None for unchanged values.
        """
        # Unpack parameters
        wl_params = self.wavelength_parameters
        pol_params = self.polarization_parameters['input']
        motion = self.motion_parameters
        z0 = motion['start_position']['z']
        x_res = motion['resolution']['x']
        y_res = x_res  # workaround: use X resolution for Y

        # Generate axes
        wl_list = self._generate_array(wl_params['start_wavelength'], wl_params['end_wavelength'], wl_params['resolution'])
        pol_list = self._generate_array(pol_params['start_angle'], pol_params['end_angle'], pol_params['resolution'])
        x_list = self._generate_array(motion['start_position']['x'], motion['end_position']['x'], x_res)
        y_list = self._generate_array(motion['start_position']['y'], motion['end_position']['y'], y_res)

        sequence = []
        prev = [None, None, None]

        for wl in wl_list:
            for pol in pol_list:
                for y in y_list:
                    for x in x_list:
                        pos = [x, y, z0]
                        entry = [
                            pos   if pos != prev[0] else None,
                            pol   if pol != prev[1] else None,
                            wl    if wl  != prev[2] else None
                        ]
                        sequence.append(entry)
                        prev = [pos, pol, wl]

        return sequence

    def generate_linescan_sequence(self):
        """
        Build a linescan sequence between start and end XY positions.
        Points are spaced by X resolution along the line. Z is fixed.
        Returns list of [position, None, None] entries.
        """
        motion = self.motion_parameters
        start = motion['start_position']
        end   = motion['end_position']
        step  = motion['resolution']['x']
        z0    = start['z']

        # Compute number of segments
        dx = end['x'] - start['x']
        dy = end['y'] - start['y']
        length = math.hypot(dx, dy)
        num_steps = max(1, int(length / step))

        # Generate line points
        xs = np.linspace(start['x'], end['x'], num_steps + 1)
        ys = np.linspace(start['y'], end['y'], num_steps + 1)

        sequence = []
        prev_pos = None
        for x, y in zip(xs, ys):
            pos = [x, y, z0]
            entry = [pos if pos != prev_pos else None, None, None]
            sequence.append(entry)
            prev_pos = pos

        return sequence

    def generate_scan_sequence(self):
        """
        Dispatch to the appropriate scan sequence generator based on scan_mode.
        """
        if self.scan_mode == 'linescan':
            return self.generate_linescan_sequence()
        elif self.scan_mode == 'map':
            return self.generate_map_sequence()
        else:
            raise ValueError(f"Not yet implemented: {self.scan_mode}. Supported modes are 'linescan' and 'map'.")


class CameraScanner:


    def __init__(self, acq_ctrl, timeout=100000):
        self.acq_ctrl = acq_ctrl
        self.microscope = acq_ctrl.interface.microscope
        self.camera = acq_ctrl.interface.camera
        self.timeout = timeout
        self.logger = acq_ctrl.interface.logger.getChild('camera_scanner')

    def _acquire_once(self):
        """acquires a single frame and saves it."""
        self.camera.camera_lock.acquire()
        try:
            self.camera.open_stream()
            image_data = None
            n_frames = self.acq_ctrl.general_parameters['n_frames']

            for frame_idx in range(n_frames):
                new_frame = self.camera.grab_frame_safe(timeout=self.timeout)
                if new_frame is None:
                    new_frame = self._retry_frame(self.timeout, 2)

                if new_frame is None:
                    print(f"Step failed at frame {frame_idx + 1}/{n_frames}")
                    return None

                image_data = new_frame.astype(np.float32) if frame_idx == 0 else (image_data + new_frame.astype(np.float32)) / 2


            return image_data
        
        finally:
            self.camera.close_stream()
            self.camera.camera_lock.release()


    def _acquire_scan(self, cancel_event, status_cb, progress_cb, timeout=100000):
        """
        Acquire a series of averaged frames according to self.scan_sequence.
        Opens stream once, iterates steps, and cleans up safely.
        Returns a list of (step_index, step) for any failed steps.
        """
        total_steps = len(self.acq_ctrl.scan_sequence)
        start_time = time.time()
        failed_steps = []

        # Lock camera and open stream
        self.camera.camera_lock.acquire()
        try:
            self.camera.open_stream()

            for idx, step in enumerate(self.acq_ctrl.scan_sequence):
                self.acq_ctrl.hidden_parameters['scan_index'] = idx

                if cancel_event.is_set():
                    status_cb("Scan cancelled.")
                    break

                # Report progress
                self._report_step(idx, step, total_steps, start_time, status_cb, progress_cb)

                # Execute hardware commands and grab frames
                success, image_data = self._execute_step(step, timeout)
                if not success:
                    failed_steps.append((idx, step))
                    continue

                # Save transient spectrum for this step
                self.acq_ctrl.save_spectrum_transient(
                    image_data,
                    wavelength_axis=self.microscope.wavelength_axis,
                    report=False
                )

                self.acq_ctrl.save_spectrum(image_data, scan_index=idx)

        except Exception as e:
            # get the traceback
            tb = traceback.format_exc()
            self.logger.error(f"Unexpected error during scan: {tb}")
            status_cb(f"Scan aborted due to unexpected error: {e}")

        finally:
            self.camera.close_stream()
            self.camera.camera_lock.release()

        return failed_steps

    def _report_step(self, idx, step, total, start_time, status_cb, progress_cb):
        """
        Helper to update UI callbacks at the start of each scan step.
        """
        status_cb(f"Running step {idx + 1}/{total}: {step}")
        percentage = round((idx / total) * 100)
        progress_cb(percentage)

    def _execute_step(self, step, timeout, retries=5):
        """
        Apply scan commands for a step, then grab and average frames.
        Returns (True, averaged_image) or (False, None).
        """
        # 1) Apply hardware commands
        for command, change in zip(self.acq_ctrl.scan_command_hierarchy, step):
            if change is not None:
                command(change)

        # 2) Acquire frames and average
        image_data = None
        n_frames = self.acq_ctrl.general_parameters['n_frames']
        for frame_idx in range(n_frames):
            new_frame = self.camera.grab_frame_safe(timeout=timeout)
            if new_frame is None:
                new_frame = self._retry_frame(timeout, retries)

            if new_frame is None:
                print(f"Step failed at frame {frame_idx + 1}/{n_frames}")
                return False, None

            image_data = new_frame.astype(np.float32) if frame_idx == 0 else (image_data + new_frame.astype(np.float32)) / 2


        return True, image_data

    def _retry_frame(self, timeout, retries):
        """
        Retry grab_frame up to `retries` times. Returns first non-None frame or None.
        """
        for attempt in range(1, retries + 1):
            print(f"Retry {attempt}/{retries} for image data...")
            frame = self.camera.grab_frame_safe(timeout=timeout)
            if frame is not None:
                return frame
        return None



class AcquisitionControl:

    def __init__(self, interface):
        self.interface = interface
        self.logger = interface.logger.getChild('acquisition_control')

        self.camera = interface.microscope.camera
        self.acquisitionControlDir = interface.microscope.acquisitionControlDir


        # define the command hierarchy for the scan here
        self.scan_command_hierarchy = [
            self.move_stage_absolute,
            self.interface.microscope.go_to_polarization_in,
            self.interface.microscope.go_to_wavelength_all,
        ]

        self.general_parameters = {
            'acquisition_time': 1000.0,
            'filename': 'default',
            'raman_shift': 0.0,
            'laser_power': 4.5,
            'n_frames': 1,
        }

        self.hidden_parameters = {
            'scan_mode': 'linescan',
            'scan_index': 0,
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

        self._current_parameters = {
            'sample_position': {'x': 0.0, 'y': 0.0, 'z': 0.0},
            'laser_wavelength': 0.0,
            'polarization_in_angle': 0.0,
            'polarization_out_angle': 0.0,
            'monochromator_wavelength': 0.0,
            'spectrometer_steps': 0.0,
            'scan_index': 0,
            'scan_mode': 'linescan',
            'detector_temperature': 0.0
        }

        self.x_position = self._current_parameters['sample_position']['x']
        self.y_position = self._current_parameters['sample_position']['y']
        self.z_position = self._current_parameters['sample_position']['z']

        # Optional/UI-linked parameters
        self.separate_resolution = False
        self.z_scan = False
        self.scan_mode_types = ['linescan', 'map']

        self.scan_sequence = []
        self.estimated_scan_time = {'duration': 0.0, 'units': 'seconds'}
        self.all_parameters = {dict_name: getattr(self, dict_name) for dict_name in self.__dict__.keys() if dict_name.endswith('_parameters')}
        self.load_config()

        print("Acquisition Control initialized.")

    def toggle_scan_mode(self):
        self.scan_mode = 'linescan' if self.scan_mode == 'map' else 'map'
        print("Set scan mode to {}".format(self.scan_mode))

    @property
    def scan_mode(self):
        return self.hidden_parameters['scan_mode']
    
    @scan_mode.setter
    def scan_mode(self, value):
        if value in self.scan_mode_types:
            self.hidden_parameters['scan_mode'] = value
        else:
            raise ValueError("Invalid scan mode. Choose one of: {}".format(", ".join(self.scan_mode_types)))
        
    # @property
    def start_position(self):
        positions = ", ".join(str(value) for value in self.motion_parameters['start_position'].values())
        return positions
    
    def stop_position(self):
        positions = ", ".join(str(value) for value in self.motion_parameters['end_position'].values())
        return positions
    
    def update_stage_positions(self):
        self.stage_positions = {
            'x': self.interface.microscope.stage_positions_microns['x'],
            'y': self.interface.microscope.stage_positions_microns['y'],
            'z': self.interface.microscope.stage_positions_microns['z']
        }
        self._current_parameters['sample_position'] = self.stage_positions

    @property
    def current_stage_coordinates(self):
        current_coords = [
            self.interface.microscope.stage_positions_microns['x'], 
            self.interface.microscope.stage_positions_microns['y'], 
            self.interface.microscope.stage_positions_microns['z']
            ]
        
        self._current_parameters['sample_position'] = {
            'x': current_coords[0], 
            'y': current_coords[1], 
            'z': current_coords[2]
        }

        return current_coords

    def get_all_parameters(self):
        detector_temp = self.interface.microscope.get_detector_temperature()
        self.set_current_parameters({'detector_temperature': detector_temp})

        self._current_parameters.update(self.general_parameters)
        self._current_parameters['laser_wavelength'] = self.interface.microscope.laser_wavelengths.get('l1', 0.0)
        self._current_parameters['monochromator_wavelength'] = self.interface.microscope.monochromator_wavelengths.get('g3', 0.0)
        # self._current_parameters['polarization_in_angle'] = self.interface.microscope.polarization_angles.get('in', 0.0)


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
        '''Estimates the duration of the scan in seconds. This is a rough estimate based on the number of steps in the scan and the acquisition time.'''

        frames = self.general_parameters['n_frames']
        acq_time = self.general_parameters['acquisition_time']
        return self.scan_size * acq_time * frames * 1.2
    
    def update_scan_estimate(self):
        try:
            duration = self.estimate_scan_duration()


            if 3600 > duration >= 600:
                scan_time = duration / 60
                units = 'minutes'
            elif duration >= 3600:
                scan_time = duration / 3600
                units = 'hours'
            else:
                scan_time = duration
                units = 'seconds'

            scan_time = {
                'duration': round(scan_time, 2),
                'units': units
            }

            self.estimated_scan_time = scan_time
            return scan_time
        except Exception as e:
            print(f"Error estimating scan time: {e}")
        

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
            'hidden_parameters': self.hidden_parameters,
            'motion_parameters': self.motion_parameters,
            'wavelength_parameters': self.wavelength_parameters,
            'polarization_parameters': self.polarization_parameters,
        }

        filepath = os.path.join(self.acquisitionControlDir, filename)
        with open(filepath, 'w') as f:
            json.dump(config, f, indent=2)

    def load_config(self, filename="acquisition_config.json"):

        filepath = os.path.join(self.acquisitionControlDir, filename)
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

        self.general_parameters.update(config.get('general_parameters', self.general_parameters))
        self.motion_parameters.update(config.get('motion_parameters', self.motion_parameters))
        self.wavelength_parameters.update(config.get('wavelength_parameters', self.wavelength_parameters))
        self.polarization_parameters.update(config.get('polarization_parameters', self.polarization_parameters))

        print("Acquisition Control configuration loaded successfully.")

    def calculate_relative_motion(self, current_positions, target_positions):

        relative_motion = [target_positions[0] - current_positions[0], target_positions[1] - current_positions[1], target_positions[2] - current_positions[2]]

        return relative_motion

    def generate_scan_sequence(self):
        # TODO: Add linescan
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
            self.motion_parameters['start_position']['x'],
            self.motion_parameters['end_position']['x'],
            self.motion_parameters['resolution']['x']
        )
        y_positions = generate_array(
            self.motion_parameters['start_position']['y'],
            self.motion_parameters['end_position']['y'],
            self.motion_parameters['resolution']['y']
        )
        z_val = self.motion_parameters['start_position']['z']

        if self.scan_mode == 'linescan':
            self.generate_linescan_sequence()

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

        self.scan_sequence = sequence
        return sequence
    
    @property
    def scan_size(self):
        '''Returns an extimate of the scan length by calculating the distance between the start and end positions. Used as a quick scan length estimate.'''

        def get_size(start, end, resolution):
            if resolution == 0 or start == end:
                return 1
            try:
                return abs((end - start)) / resolution
            except Exception as e:
                print(f"Error generating array: {e}")
                return 1
            
        wavelength_list = get_size(
            self.wavelength_parameters['start_wavelength'],
            self.wavelength_parameters['end_wavelength'],
            self.wavelength_parameters['resolution']
        )
        polarization_list = get_size(
            self.polarization_parameters['input']['start_angle'],
            self.polarization_parameters['input']['end_angle'],
            self.polarization_parameters['input']['resolution']
        )
        x_positions = get_size(
            self.motion_parameters['start_position']['x'],
            self.motion_parameters['end_position']['x'],
            self.motion_parameters['resolution']['x']
        )
        y_positions = get_size(
            self.motion_parameters['start_position']['y'],
            self.motion_parameters['end_position']['y'],
            self.motion_parameters['resolution']['y']
        )
        z_val = get_size(
            self.motion_parameters['start_position']['z'],
            self.motion_parameters['end_position']['z'],
            self.motion_parameters['resolution']['z']
        )

        if self.hidden_parameters['scan_mode'] == 'linescan':
            length = math.hypot(x_positions, y_positions)
            num_steps = max(1, int(length / self.motion_parameters['resolution']['x']))
            scan_size = wavelength_list * polarization_list * num_steps
        elif self.hidden_parameters['scan_mode'] == 'map':
            scan_size = wavelength_list * polarization_list * x_positions * y_positions * z_val
        
        return scan_size


    def move_stage_absolute(self, new_coordinates):
        '''Moves the microcsope sample stage to the specified absolute position in micrometers. Used by the acquisition control to move the stage to the next position in a scan.'''
        
        current_positions = self.current_stage_coordinates
        target_microns = [new-old for new, old in zip(new_coordinates, current_positions)]

        micron_dict = {
            'x': target_microns[0],
            'y': target_microns[1],
            'z': target_microns[2]
        }

        motor_dict = self.interface.microscope.calibration_service.microns_to_steps(micron_dict)
        # self.interface.microscope.move_motors(motor_dict)  # Uncomment this line to actually move the stage
        self.interface.microscope.motion_control.move_motors(motor_dict)
        print("Sent Command {}".format(motor_dict))
        print("Stage moved ({})".format(", ".join([f"{value:.2f}" for value in new_coordinates])))

        self.interface.microscope.motion_control

        self.interface.microscope.update_stage_positions(micron_dict)
        self.update_stage_positions()


    def prepare_acquisition_params(self):
        self.interface.microscope.set_acquisition_time(self.general_parameters['acquisition_time'])  # ensures acqtime is set correctly at camera level
        self.interface.microscope.set_laser_power(self.general_parameters['laser_power'])  # ensures laser power is set correctly at camera level


    def build_scan_sequence(self):
        '''Builds the scan sequence from GUI parameters. Confirms parameters then calls the scan sequence.'''

        sequence_generator = ScanSequenceGenerator(self)
        self.scan_sequence = sequence_generator.generate_scan_sequence()

        return self.scan_sequence
    
    def _acquire_one_frame(self):
        '''Acquires a single frame and returns it without saving'''
        camera_scanner = CameraScanner(self)
        image_data = camera_scanner._acquire_once()
        if image_data is None:
            print("Error: image data is None. Aborting acquisition.")
            return

        return image_data

    def acquire_once(self, filename=None):
        '''Acquires a single frame and saves it.'''
        if filename is not None:
            self.general_parameters['filename'] = filename
        self.prepare_acquisition_params()  # ensures acqtime is set correctly at camera level
        self.logger.info("Acquiring single frame...")
        image_data = self._acquire_one_frame()

        self.save_spectrum_transient(image_data, wavelength_axis=self.wavelength_axis, report=True)
        index = len([file for file in os.listdir(self.interface.microscope.dataDir) if self.general_parameters['filename'] in file]) # autoincrement the scan index based on the number of files in the directory matching the filename
        self.save_spectrum(image_data, scan_index=index)

        self.logger.info("Acquisition complete.")  

    def cli_acquire_scan(self):
        """Acquires a scan sequence from the command line. Should only be called from the CLI after completing the confirmation dialogue."""
        self.prepare_acquisition_params()
        self.logger.info("Acquiring scan...")
        self.build_scan_sequence()

        class CancelEvent:
            def is_set(self):
                return False

        self.acquire_scan(
            cancel_event=CancelEvent(),
            status_callback=lambda msg: print(msg),
            progress_callback=lambda step, total, start_time: print(f"Step {step}/{total} completed in {time.time() - start_time:.2f} seconds") 
        )
        self.logger.info("Scan complete.")

    def acquire_scan(self, cancel_event, status_callback, progress_callback, timeout=100000):
        """Acquires a confirmed scan sequence. Should only be called from the UI after completing the confirmation dialogue."""

        camera_scanner = CameraScanner(self)
        failed_steps = camera_scanner._acquire_scan(cancel_event, status_callback, progress_callback, timeout)

        print("Scan complete.")

        if failed_steps:
            record_failed_steps = json.dumps(failed_steps)
            status_dir = os.path.join(self.interface.microscope.dataDir, 'status')
            if not os.path.exists(status_dir):
                os.makedirs(status_dir)
            with open(os.path.join(status_dir, 'failed_steps.json'), 'w') as f:
                json.dump(failed_steps, f, indent=2)
            print(f"Failed steps recorded in {os.path.join(status_dir, 'failed_steps.json')}")
        else:
            print("All steps completed successfully.")
        status_callback("Scan complete.")
        

    # def acquire_scan_old(self, cancel_event, status_callback, progress_callback):

    #     # TODO: FIX motion back to origin, keep track of stage pos better

    #     scan_command_hierarchy = [
    #         self.move_stage_absolute,
    #         self.interface.microscope.go_to_polarization_in,
    #         self .microscope.go_to_wavelength_all,
    #     ]

    #     sequence = self.generate_map_sequence()

    #     print(f"Predicted time: {self.estimated_scan_time['duration']:.1f} {self.estimated_scan_time['units']}")
    #     rescan_list = []

    #     self.prepare_acquisition_params() # makes sure the acquisition parameters are set correctly at the hardware level before starting the scan
    #     # if self.interface.microscope.detect_microscope_mode() == 'imagemode':
    #     #     self.interface.microscope.raman_mode()

    #     total_steps = len(sequence)
    #     start_time = time.time()
    #     print(f"Starting scan with {total_steps} steps.")

    #     for index, step in enumerate(sequence):
    #         self.general_parameters['scan_index'] = index
    #         if cancel_event.is_set():
    #             status_callback("Scan cancelled.")
    #             return
    #         status_callback(f"Running step {index}: {step}")
    #         progress_callback(index + 1, total_steps, start_time)
    #         for command, change in zip(scan_command_hierarchy, step):
    #             if change is not None:
    #                 command(change)
            
    #         for frame in range(self.general_parameters['n_frames']):
    #             print("Acquiring frame {}".format(frame + 1))

    #             new_frame = self.interface.microscope.camera.safe_acquisition(export=False)

    #             if new_frame is None:
    #                 print("Error image data None. Retryig now...")

    #                 new_frame = self.interface.microscope.camera.safe_acquisition(export=False)
    #                 if new_frame is None:
    #                     print("Error image data None")
    #                     status_callback("Error acquiring spectrum in AcquisitionControl.acquire_scan. Adding to rescan list and moving on.")
    #                     rescan_list.append(index, step)
    #                     return
                    
    #             if frame == 0:
    #                 image_data = new_frame
    #             else:
    #                 image_data = (image_data + new_frame) / 2


    #             self.save_spectrum_transient(image_data, wavelength_axis=self.wavelength_axis, report=False)
              
    #         self.save_spectrum(image_data, scan_index=index)
        
    #     if len(rescan_list) > 0:
    #         for (index, step) in rescan_list:
    #             self.general_parameters['scan_index'] = index
    #             if cancel_event.is_set():
    #                 status_callback("Scan cancelled.")
    #                 return
    #             status_callback(f"Running step {index}: {step}")
    #             progress_callback(index + 1, total_steps, start_time)
    #             for command, change in zip(scan_command_hierarchy, step):
    #                 if change is not None:
    #                     command(change)
                
    #             for frame in range(self.general_parameters['n_frames']):
    #                 print("Acquiring frame {}".format(frame))

    #                 new_frame = self.interface.microscope.acquire_one_frame(export_raw=False)

    #                 if new_frame is None:
    #                     print("Error image data None. Retryig now...")

    #                     new_frame = self.interface.microscope.acquire_one_frame(export_raw=False)
    #                     if new_frame is None:
    #                         print("Error image data None")
    #                         status_callback("Error acquiring spectrum in AcquisitionControl.acquire_scan. Adding to rescan list and moving on.")
    #                         rescan_list.append(index, step)
    #                         return
                        
    #                 if frame == 0:
    #                     image_data = new_frame
    #                 else:
    #                     image_data = (image_data + new_frame) / 2

    #                 self.save_spectrum_transient(image_data, wavelength_axis=self.wavelength_axis, report=False)
                    
    #             self.save_spectrum(image_data, scan_index=index)
            
    #     status_callback("Scan complete.")
    #     progress_callback(total_steps, total_steps, start_time)
    #     print("Scan complete.")

    # def save_transient_spectrum(self, image_data, wavelength_axis, **kwargs):
    def save_spectrum_transient(self, image_data, wavelength_axis=None, **kwargs):
        if wavelength_axis is None:
            # print("No wavelength axis provided—defaulting to pixel indices.")
            wavelength_axis = np.arange(image_data.shape[1])

        # TODO:add wavelength axis to the image data along a new axis
        save_path = os.path.join(self.interface.microscope.dataDir, 'transient_data', 'transient_data.npy')
        # if kwargs.get('report', False):
        #     print(f"Saving transient data to {save_path}")
        # print(f"Saving transient data to {save_path}")
        np.save(save_path, image_data)

    def save_spectrum(self, image_data, **kwargs):
        scan_index     = kwargs.get('scan_index',     self.hidden_parameters['scan_index'])
        wavelength_axis = kwargs.get('wavelength_axis', self.interface.microscope.wavelength_axis)
        filename       = kwargs.get('filename',       self.general_parameters['filename'])
        save_dir       = kwargs.get('save_dir',       self.interface.microscope.dataDir)

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
        return self.interface.microscope.wavelength_axis
    
    @property
    def filename(self):
        return self.general_parameters['filename']
    
    @property
    def metadata(self):
        return self._construct_metadata()
    
    @property
    def acquisitionDir(self):
        return os.path.join(self.interface.microscope.scriptDir, 'acquisition_control')
    
    @property
    def current_position(self):
        return self._current_parameters['sample_position']
    
    @property
    def scan_wavelengths(self):
        if self.wavelength_parameters['start_wavelength'] == self.wavelength_parameters['end_wavelength'] or self.wavelength_parameters['resolution'] == 0:
            return f"{self.wavelength_parameters['start_wavelength']:.2f}"
        
        wavelength_list = np.arange(
            self.wavelength_parameters['start_wavelength'],
            self.wavelength_parameters['end_wavelength'],
            self.wavelength_parameters['resolution']
        )
        wavelength_list = ", ".join([f"{wl:.2f}" for wl in wavelength_list])
        return wavelength_list
    
    @property
    def scan_polarizations_in(self):
        if self.polarization_parameters['input']['start_angle'] == self.polarization_parameters['input']['end_angle'] or self.polarization_parameters['input']['resolution'] == 0:
            return f"{self.polarization_parameters['input']['start_angle']:.2f}"
        
        polarization_list = np.arange(
            self.polarization_parameters['input']['start_angle'],
            self.polarization_parameters['input']['end_angle'],
            self.polarization_parameters['input']['resolution']
        )
        polarization_list = ", ".join([f"{pol:.2f}" for pol in polarization_list])
        return polarization_list
    
    @property
    def scan_polarizations_out(self):
        if self.polarization_parameters['output']['start_angle'] == self.polarization_parameters['output']['end_angle'] or self.polarization_parameters['output']['resolution'] == 0:
            return f"{self.polarization_parameters['output']['start_angle']:.2f}"
        
        polarization_list = np.arange(
            self.polarization_parameters['output']['start_angle'],
            self.polarization_parameters['output']['end_angle'],
            self.polarization_parameters['output']['resolution']
        )
        polarization_list = ", ".join([f"{pol:.2f}" for pol in polarization_list])
        return polarization_list
    