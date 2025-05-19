import time
import threading
import numpy as np
import traceback


# everywhere you have `print("…")`, replace with:
# self.logger.info("Acquiring frame %d/%d…", i+1, n_frames)
# or for errors:
# self.logger.error("Failed to acquire frame.")

class SimulatedCameraInterface():

    """Simulated camera interface for testing without hardware"""
    
    def __init__(self, interface, **kwargs):
        self.interface = interface
        self.logger = interface.logger.getChild('simulated_camera')
        # acquisition parameters

        self.acqtime = 0.5 # seconds
        self.roi = (0, 1220, 2048, 148)
        self.is_running = False
        self.save_transient_spectrum_cb = interface.acq_ctrl.save_spectrum_transient
        self.stop_flag = threading.Event()
        self.camera_lock = threading.Lock()

        self.command_functions = {
            'set_acqtime': self.set_exposure_time,
            'set_roi': self.set_roi,
        }

    def initialise(self):
        """Initialize the simulated camera"""
        self.logger.info("Simulated camera initialized")

    def set_exposure_time(self, exposure_time):
        """Set the camera's exposure time"""
        try:
            self.acqtime = float(exposure_time)
            self.logger.info(f"Set exposure time to {self.acqtime} seconds")
        except ValueError:
            self.logger.error("Invalid exposure time value")

    def check_camera_temperature(self):
        """Check the camera temperature"""
        # Simulate a temperature check
        temperature = np.random.uniform(-8, -6)  # Simulated temperature in Celsius
        return temperature

    def set_roi(self, roi):
        """Set the camera's region of interest (ROI)"""
        self.logger.info(f"Setting ROI to {roi}")
        try:
            x1, y1, x2, y2 = roi
            if x1 < 0 or y1 < 0 or x2 > 2048 or y2 > 148:
                raise ValueError("ROI coordinates out of bounds")
            self.roi = roi
            self.logger.info(f"ROI set to {self.roi}")
        except ValueError:
            self.logger.error("Invalid ROI format. Expected (x1, y1, x2, y2)")

    def _generate_simulated_image(self, width=2048, height=148):
        """
        Generate simulated image data with a Gaussian peak in the center.
        Used for simulation mode to return realistic-looking spectral data.
        """
        # Create a 2D array of zeros with the specified dimensions
        img = np.zeros((height, width), dtype=np.uint16)

        # Create a 1D Gaussian peak profile for spectral data
        x = np.arange(width)
        center = width // 2
        sigma = width // 40  # Width of the peak
        amplitude = 40000  # Height of the peak (16-bit so max is 65535)
        
        # Calculate Gaussian
        gaussian = amplitude * np.exp(-(x - center)**2 / (2 * sigma**2))
        
        # Add some noise
        noise_level = 800
        noise = np.random.normal(0, noise_level, width)
        
        # Create the spectral line (same for all rows)
        spectral_line = gaussian + noise
        spectral_line = np.clip(spectral_line, 0, 65535).astype(np.uint16)
        
        # Fill all rows with this spectral line, with slight variations
        for i in range(height):
            row_noise = np.random.normal(0, noise_level * 0.2, width)
            img[i, :] = np.clip(spectral_line + row_noise, 0, 65535).astype(np.uint16)
            
        # Add a simulated peak shift based on instance parameters
        # In simulation, we can modify the peak position based on internal state
        # For example, the current simulated wavelength setting
        
        # For a multi-channel image (like RGB), expand dimensions
        # This simulates a single-channel image for now
        sim_frame = np.expand_dims(img, axis=2)
        
        return sim_frame
    
    def grab_frame(self, timeout=100000):        
        image_data = self._generate_simulated_image()
        # Simulate acquisition time
        self.logger.info("Simulated camera acquiring frame...")
        time.sleep(self.acqtime)
        return image_data

    def open_stream(self):
        """Open the camera stream (simulated)"""
        # self.logger.info("Simulated camera stream opened")
        pass
    
    def close_stream(self):
        """Close the camera stream (simulated)"""
        # self.logger.info("Simulated camera stream closed")
        pass

    def start_continuous_acquisition(self):
        """
        Start a continuous acquisition thread until told to stop via stop_continuous_acquisition().
        Each frame is saved as .npy into self.transient_dir.
        """
        if self.is_running:
            self.logger.info("Camera is already running. Please stop acquisition before starting a continuous acquisition!")
            return
        
        self.open_stream()

        n_frames = self.interface.acq_ctrl.general_parameters['n_frames']
        # Set up for continuous acquisition
        def continuous_task():
            self.stop_flag.clear()

            while not self.stop_flag.is_set():
                try:
                    for index in range(n_frames):
                        self.logger.info(f"Acquiring frame {index+1}/{n_frames}...")

                        new_frame = self.grab_frame(timeout=100000)
                        if new_frame is None:
                            self.logger.error("Failed to acquire frame.")
                            break

                        if index == 0:
                            # First frame, set up the data array
                            data = new_frame.astype(np.float32) # NOTE: The conversion to float32 is important for averaging across n_frames > 10. It prevents overflow, but we're also going to save as float32 to prevent quantization noise upon conversion to uint16.
                        else:
                            data = (data + new_frame.astype(np.float32)) / 2

                        wavelengths = self.interface.microscope.wavelength_axis
                        self.save_transient_spectrum_cb(data, wavelengths)
                        time.sleep(0.01)

                except Exception as e:
                    self.logger.error(f"Acquisition error: {e}")
                    self.logger.error(traceback.format_exc())
                    break

        acq_thread = threading.Thread(target=continuous_task, daemon=True)
        acq_thread.start()

        self.is_running = True
        self.logger.info("Started continuous acquisition.")


    def stop_continuous_acquisition(self):
        """
        Stop the continuous acquisition thread.
        """
        self.stop_flag.set()
        self.is_running = False
        self.close_stream()
        self.logger.info("Continuous acquisition stopped.")

