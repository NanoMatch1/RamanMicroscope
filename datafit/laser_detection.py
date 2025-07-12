import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import median_abs_deviation

import numpy as np

import numpy as np
from scipy.signal import find_peaks
from .data_fit import data_fit
from .baseline import baseline_als

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

def baseline_data(dataY, lam=100000, p=1e-6, subtract_median=True):
    """Apply baseline correction to the data using asymmetric least squares."""
    baseline = baseline_als(dataY, lam=lam, p=p)
    baselinedY = dataY - baseline  # Subtract baseline from original data
    if subtract_median:
        med = np.median(baselinedY)
        baselinedY -= med  # Center around zero

    return baselinedY

class Peak:

    def __init__(self, position, amplitude, width, peak_type='gaussian'):
        self.pos = position
        self.amp = amplitude
        self.width = width
        self.peak_type = peak_type

    def __repr__(self):
        return f"Peak(type={self.peak_type}, pos={self.position:.2f}, amp={self.amplitude:.2f}, width={self.width:.2f})"

class AutoPeakFitter:
    def __init__(self, dataX, dataY,
                 peak_type='gaussian',
                 peak_sign='positive',
                 ftol=1e-4, gtol=1e-4, xtol=1e-4,
                 show_plot=False):
        
        self.dataY = dataY
        self.dataX = dataX
        self.peak_type = peak_type.lower()
        self.peak_sign = peak_sign
        self.ftol, self.gtol, self.xtol = ftol, gtol, xtol


        self.Fit = data_fit()
        self.peaks = []
        self.peakfit_list = []

    def package_peaks(self, peak_list):
        '''Convert the list of peaks into a list of Peak objects.'''
        peak = peak_list[0]
        return Peak(*peak[1:4], peak_type=peak[0])

    def add_initial_peak(self, peak_index):
        """Add a single peak guess using a dataX index."""
        peak_pos = self.dataX[peak_index]
        amp = self.dataY[peak_index]
        data_range = self.dataX[-1] - self.dataX[0]

        # Estimate width (fallback = 1% of X range)
        half_max = amp / 2
        left = np.where(self.dataY[:peak_index] < half_max)[0]
        right = np.where(self.dataY[peak_index:] < half_max)[0]

        if left.size > 0 and right.size > 0:
            fwhm = self.dataX[peak_index + right[0]] - self.dataX[left[-1]]
        else:
            fwhm = data_range / 100

        self.peaks.append([
            self.peak_type,
            [peak_pos, self.dataX[0], self.dataX[-1]],                       # position + bounds
            [amp, np.min(self.dataY), np.max(self.dataY) * 2],              # amplitude + bounds
            [fwhm, data_range / 5000, data_range / 10]                        # width + bounds
        ])

    def setup_fit(self):
        self.Fit.reset_functions()
        self.Fit.set_data(np.column_stack((self.dataX, self.dataY)))

        for peak in self.peaks:
            name, posB, ampB, wB = peak
            args = [posB[0], ampB[0], wB[0]]
            bounds = [posB[1:], ampB[1:], wB[1:]]
            self.Fit.add_function(name, *args, bounds=bounds)

    def optimise(self):
        self.setup_fit()
        self.Fit.optimise(ftol=self.ftol, gtol=self.gtol, xtol=self.xtol, maxfev=100000)
        self.peakfit_list = self.Fit.get_functions()

    def run(self, initial_index=None):
        """Run the full peak fit given an index guess."""

        if initial_index is None:
            initial_index = np.argmax(self.dataY)
        self.add_initial_peak(int(initial_index))
        self.optimise()
        peak = self.package_peaks(self.peakfit_list)
        self.peaks = []  # Clear peaks for next fit

        return peak
    

class LaserDetection:

    '''Class for detecting laser signals in spectrograph images. Used during live calibration to find the laser line position.
    Also handles simulation of laser signals for simulated cameras.'''

    def __init__(self, interface=None, logger_level='INFO'):
        # self.logger = SimpleLogger(level=logger_level)
        self.interface = interface
        self.logger = interface.logger if interface else SimpleLogger(level=logger_level)
        self.calibrated_wavelength = None
        pass

    def detect_laser(self, image, wavelength_axis, show_plot=False):
        """
        Call method to process the image and detect laser signal. Requires:
        - image: 2D numpy array representing the spectrograph image.
        - wavelength_axis: 1D numpy array representing the wavelength axis of the image.
        """
        # 
        is_laser_present, laser_position = self.detect_laser_peak(image)
        if not is_laser_present:
            print("No laser signal detected in the image.")
            return None

        dataY = self.image_to_spectrum(image, laser_position)
        dataY = self.baseline_data(dataY, show_plot=show_plot, subtract_median=True)
        dataX = wavelength_axis
        fitter = AutoPeakFitter(dataX, dataY, show_plot=show_plot)
        peak = fitter.run(initial_index=laser_position[0])

        if self.logger.level <= 9 or show_plot == True:
            plt.figure(figsize=(10, 5))
            plt.plot(dataX, dataY, label='Spectrum')

            pos, amp, width = peak.pos, peak.amp, peak.width
            plt.plot(dataX, amp * np.exp(-((dataX - pos) ** 2) / (2 * width ** 2)), label=f'Peak at {pos:.2f}')
            plt.xlabel('Wavelength (nm)')
            plt.ylabel('Intensity')
            plt.title('Detected Laser Spectrum')
            plt.legend()
            plt.show()
        
        self.calibrated_wavelength = round(peak.pos, 3)
        self.logger.info(f"Detected laser peak at position: {peak.pos:.2f}")
        return peak
    
    def baseline_data(self, dataY, lam=10000, p=1e-6, show_plot=False, subtract_median=True):
        baselinedY = baseline_data(dataY, lam=lam, p=p, subtract_median=subtract_median)
        
        if self.logger.level == "DEBUG" or show_plot == True:
            plt.figure(figsize=(10, 5))
            plt.plot(np.arange(len(dataY)), dataY, label='Original Spectrum')
            plt.plot(np.arange(len(baselinedY)), baselinedY, label='Baselined Spectrum', alpha=0.7)
            plt.xlabel('Pixel Index')
            plt.ylabel('Intensity')
            plt.title('Baseline Correction')
            plt.legend()
            plt.show()
        
        return baselinedY

    def image_to_spectrum(self, image, laser_position, binning_width=20):
        """Generate a 1D spectrum by averaging over a specified width in the Y dimension."""

        xpos, ypos = laser_position
        spectrum = np.median(image[ypos - binning_width:ypos + binning_width, :], axis=0)
        self.dataY = spectrum

        return self.dataY
    
    def generate_laser_signal(self, width=2048, height=148, 
                              laser_position=None, wavelength_axis=None, laser_width=5, y_centre=85, y_spread=20):
        """Generates a synthetic laser signal for testing purposes."""
        pass


    def generate_test_image(self, width=2048, height=148, 
                            laser_position=None, wavelength_axis=None, laser_width=5, 
                            background_level=4000, noise_level=150, 
                            y_center=85, y_spread=20, show_plot=False):
        """
        Generate a synthetic 2D spectrograph image with a simulated laser signal.

        The output is a 2D array where the background is uniform plus Gaussian noise.
        A laser signal is added as a 2D elliptical Gaussian intensity peak:
        - Along the X-axis, the signal is narrow (simulating spectral localization).
        - Along the Y-axis, it is broader (simulating vertical spread from diffraction or slit effects).

        Parameters:
        - width (int): Width of the image (X dimension, i.e., spectral axis).
        - height (int): Height of the image (Y dimension, i.e., spatial axis).
        - laser_position (int or None): X-coordinate of the laser peak center. 
        If None, a random position within the image width is chosen.
        - wavelength_axis (1D np.ndarray): Wavelength axis, to be used with the laser_position in order to calibrate laser_position to the CCD array.
        - laser_width (float): Standard deviation of the laser signal in X (spectral width).
        - background_level (float): Mean background intensity across the image.
        - noise_level (float): Standard deviation of the Gaussian noise added to all pixels.
        - y_center (float): Y-coordinate (vertical) center of the laser peak.
        - y_spread (float): Standard deviation of the laser intensity along Y.

        Returns:
        - image (2D np.ndarray): Synthetic image with background, noise, and a simulated laser line.
        """
        # Create coordinate grid
        Y, X = np.meshgrid(np.arange(height), np.arange(width), indexing='ij')

        if laser_position is not None and wavelength_axis is not None:
            # If a laser position is given, convert it to pixel index
            index = np.argmin(np.abs(wavelength_axis - laser_position))
            laser_position = np.random.randint(index - 25, index + 25) # randomize a bit around the given position
        else: 
            laser_position = np.random.randint(0, width)  # Random position in the X dimension
        # else:
            # laser_position = np.random.randint(laser_position-50, laser_position+50)

        # 2D Gaussian signal: exp(-(X-x0)^2 / 2σx^2) * exp(-(Y-y0)^2 / 2σy^2)
        laser_signal = np.exp(-0.5 * ((X - laser_position) / laser_width) ** 2) * \
                    np.exp(-0.5 * ((Y - y_center) / y_spread) ** 2)

        # Normalize signal to max ~1, scale to realistic intensity (e.g. add 500 counts)
        laser_signal *= 5000

        # Add background and Gaussian noise
        if np.random.random() < 0.1:
            image = background_level + np.random.normal(0, noise_level, size=(height, width))
            # sometimes, return a completely noisy image
            return image
        
        image = background_level + laser_signal + np.random.normal(0, noise_level, size=(height, width))

        if self.logger.level == "DEBUG" or show_plot==True:
            plt.figure(figsize=(10, 5))
            plt.imshow(image, aspect='auto', cmap='gray', origin='lower')
            plt.colorbar(label='Intensity')
            plt.title(f"Generated Test Image with Laser at X={laser_position}")
            plt.xlabel("X (Spectral Axis)")
            plt.ylabel("Y (Spatial Axis)")
            plt.show()

        print(f"Generated test image with laser at X={laser_position} ")

        return image


    def detect_laser_peak(self, image, threshold_sigma=10, min_width=3, show_plot=False):
        '''Searches for a laser peak in the image by integrating along the X-axis and applying a threshold based on robust statistics.Returns a tuple (is_laser_present, (x_max, y_max)) where is_laser_present is True if a peak is found, and (x_max, y_max) are the coordinates of the peak.'''
        
        # Step 1: Collapse in Y to get intensity along X
        profile_x = np.median(image, axis=0)  # shape = (X,)
        
        # Step 2: Estimate background using robust statistics
        med = np.median(profile_x)
        mad = median_abs_deviation(profile_x)


        self.logger.debug(f"Median: {med}, MAD: {mad}")

        threshold = med + threshold_sigma * mad

        # Step 3: Find where signal exceeds threshold
        signal_mask = profile_x > threshold


        # Step 4: Optional: filter by minimum width
        from scipy.ndimage import label
        labeled, num_features = label(signal_mask)
        sizes = np.bincount(labeled.ravel())
        sizes[0] = 0  # ignore background
        valid = sizes >= min_width
        is_laser_present = valid.any()

        x_max = np.argmax(profile_x)
        y_max = np.argmax(image[:, x_max])  # Find the Y position of the maximum signal in the X profile

        # if self.logger.level <= 10 or show_plot:
        #     plt.figure(figsize=(8, 4))
        #     plt.plot(profile_x, label='X-profile')
        #     plt.axhline(med, color='gray', linestyle='--', label='Median')
        #     plt.axhline(threshold, color='red', linestyle='--', label=f'Threshold ({threshold_sigma} MAD)')
        #     plt.axvline(np.argmax(signal_mask), color='green', linestyle='--', label='Laser Signal Start')
        #     plt.title("Laser Detection Profile")
        #     plt.legend()
        #     plt.xlabel("X (pixel)")
        #     plt.ylabel("Integrated Intensity")
        #     plt.grid(True)
        #     plt.show()

        #     plt.imshow(image, aspect='auto', cmap='gray', origin='lower')
        #     # add a dot at the laser position
        #     plt.plot(x_max, y_max, 'ro', markersize=5, label='Laser Position')
        #     plt.show()

        
        
        return is_laser_present, (x_max, y_max)  

if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.append(str(Path(__file__).resolve().parents[1]))  # Add main_folder to path manually

    from datafit.data_fit import data_fit
    from datafit.baseline import baseline_als

    laser_detector = LaserDetection(logger_level='INFO')
    test_image = laser_detector.generate_test_image(laser_width=5, laser_position=785, wavelength_axis=np.arange(2048), background_level=4000, noise_level=150)
    laser_detector.detect_laser(test_image, np.arange(test_image.shape[1]))  # Assuming 
    