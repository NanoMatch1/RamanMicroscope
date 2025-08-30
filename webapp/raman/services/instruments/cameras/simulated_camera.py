import time
import threading
import numpy as np
import traceback

class DummyAcquisitionControl:
    """A dummy acquisition control class to simulate the acquisition control interface."""
    
    def __init__(self):
        self.general_parameters = {'n_frames': 1}  # Default number of frames for simulation
        self.save_spectrum_transient = lambda data, wavelengths: print("Saving transient spectrum...")  # Dummy save function

class SimpleLogger:

    """A simple logger class to handle logging messages."""

    heirachy = {
        'DEBUG': 10,
        'INFO': 20,
        'WARNING': 30,
        'ERROR': 40,
        'CRITICAL': 50
    }

    def __init__(self, level='INFO'):
        self.level = level if level in self.heirachy else 'INFO'

    def log(self, message, level='INFO'):
        """Log a message at the specified level."""
        if self.heirachy[level] >= self.heirachy[self.level]:
            print(f"[{level}] {message}")

    def set_level(self, level):
        """Set the logging level."""
        if level in self.heirachy:
            self.level = level
        else:
            raise ValueError(f"Invalid logging level: {level}. Choose from {list(self.heirachy.keys())}.")

    def debug(self, message):
        """Log a debug message."""
        self.log(message, 'DEBUG')
    def info(self, message):
        """Log an info message."""
        self.log(message, 'INFO')
    def warning(self, message):
        """Log a warning message."""
        self.log(message, 'WARNING')
    def error(self, message):
        """Log an error message."""
        self.log(message, 'ERROR')
    def critical(self, message):
        """Log a critical message."""
        self.log(message, 'CRITICAL')

    def getChild(self, name):
        """Get a child logger with the specified name."""
        return SimpleLogger(level=self.level)



class SimulatedCameraInterface:

    """Simulated camera interface for testing without hardware"""
    
    def __init__(self, interface, **kwargs):
        self.interface = interface
        self.logger = interface.logger.getChild('simulated_camera')
        # acquisition parameters

        self.acqtime = 0.5 # seconds
        self.roi = (0, 1220, 2048, 148)
        self.is_running = False
        self.stop_flag = threading.Event()
        self.camera_lock = threading.RLock()

        self.command_functions = {
            'set_acqtime': self.set_exposure_time,
            'set_roi': self.set_roi,
        }

    @property
    def randomise_laser(self):
        """Check if the laser position is randomised"""
        try:
            randomise = not self.interface.microscope.laser_calibrated
        except Exception as e:
            self.logger.debug(f"Error checking laser calibration: {e}")
            randomise = True

        return randomise

    def initialise(self):
        """Initialize the simulated camera"""
        self.logger.info("Simulated camera initialized")
        self.save_transient_spectrum_cb = self.interface.acq_ctrl.save_spectrum_transient

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

    def _generate_simulated_laser_signal(self, width=2048, height=148,
                                         laser_position=None, wavelength_axis=None, laser_width=5, y_spread=20, peak_height=30000, peak_sigma=0.1):
        """
        Generate a simulated laser signal based on the simulated setup parameters.
        peak_sigma is used to control the randomization of the peak height. higher Numbers push the signal higher.
        #TODO when laser is not in spectral range, the signal should be zero.
        
        """
        wavelength_axis = self.interface.microscope.wavelength_axis
        if laser_position:
            laser_wavelength = laser_position
        elif self.interface.microscope.laser_calibrated:
            laser_wavelength = self.interface.microscope.laser_wavelength_calibrated
        else:
            laser_wavelength = self.interface.microscope.laser_wavelengths.get('l1', 785)  # Default to 785nm if not set

        Y, X = np.meshgrid(np.arange(height), np.arange(width), indexing='ij')

        if laser_wavelength is not None and wavelength_axis is not None:
            # If a laser position is given, convert it to pixel index
            index = np.argmin(abs(wavelength_axis - laser_wavelength))
            if index == 0 or index == len(wavelength_axis) - 1:
                self.logger.debug("Laser wavelength does not fall within the wavelength axis range. Signal will be zero.")
                return np.zeros((height, width), dtype=np.float32)  # 
            if self.randomise_laser:
                laser_position = np.random.randint(index - 25, index + 25) # randomize a bit around the given position
            else:
                laser_position = index
        else: 
            laser_position = np.random.randint(0, width)  # Random position in the X dimension

        # 2D Gaussian signal: exp(-(X-x0)^2 / 2σx^2) * exp(-(Y-y0)^2 / 2σy^2)
        # breakpoint()
        laser_signal = np.exp(-0.5 * ((X - laser_position) / laser_width) ** 2) * \
                    np.exp(-0.5 * ((Y - height / 2) / y_spread) ** 2)
        
        scale = np.abs(np.random.normal(peak_height, peak_height * peak_sigma))  # Peak centered at 30000, ~10% variation
        laser_signal *= scale

        simulated_laser_wavelength = wavelength_axis[laser_position] if wavelength_axis is not None else laser_position

        self.logger.debug(f"Simulated laser wavelength: {simulated_laser_wavelength} nm")

        return laser_signal

    def _generate_simulated_image(self, width=2048, height=148):
        """
        Generate simulated image data with a Gaussian peak in the center.
        Used for simulation mode to return realistic-looking spectral data.
        """

        wavelength_axis = self.interface.microscope.wavelength_axis  # Ensure wavelength axis is generated

        if wavelength_axis is None:
            wavelength_axis = np.arange(width).astype(int)  # Default to a simple range if not set
        background = 4000 # Background level
        laser_signal = self._generate_simulated_laser_signal(width=width, height=height)
        
        # Add some noise
        noise_level = 300
        noise = np.random.randint(-noise_level, noise_level, laser_signal.shape)
        
        # Create the spectral line (same for all rows)
        spectrum_image = background + laser_signal + noise
        spectrum_image = np.clip(spectrum_image, 0, 65535).astype(np.uint16)
        
        return spectrum_image
    
    def grab_frame_safe(self, timeout=100000):
        '''Workaround for temperature checking'''
        # Simulate a temperature check
        temperature = self.check_camera_temperature()
        image_data = self.grab_frame(timeout)

        return image_data

    
    def grab_frame(self, timeout=100000):        
        image_data = self._generate_simulated_image()
        # Simulate acquisition time
        self.logger.debug("Simulated camera acquiring frame...")
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
                        self.logger.debug(f"Acquiring frame {index+1}/{n_frames}...")

                        new_frame = self.grab_frame(timeout=100000)
                        if new_frame is None:
                            self.logger.info("Failed to acquire frame.")
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


if __name__ == "__main__":
    # Example usage
    import matplotlib.pyplot as plt
    class MockInterface:
        def __init__(self):
            self.logger = SimpleLogger()  # Mock logger
            self.microscope = type('Microscope', (), {'wavelength_axis': np.arange(2048), 'laser_wavelengths': {'l1': 785}})()
            self.acq_ctrl = DummyAcquisitionControl()

    interface = MockInterface()
    camera = SimulatedCameraInterface(interface)
    camera.initialise()
    camera.set_exposure_time(0.5)
    camera.set_roi((0, 0, 2048, 148))
    frame = camera.grab_frame_safe()
    
    plt.imshow(frame, cmap='plasma')
    plt.title("Simulated Camera Frame")
    plt.show()
    # camera.start_continuous_acquisition()
    # camera.acquire_frame_safe()  # Simulate a single frame acquisition
    
    # time.sleep(5)  # Let it run for a while
    # camera.stop_continuous_acquisition()