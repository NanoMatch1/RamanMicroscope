import numpy as np
import matplotlib.pyplot as plt
from scipy.stats import median_abs_deviation

import numpy as np

class DataObject:
    '''A class to represent data which is manually added or generated. Used for internal or calibration uses.'''

    def __init__(self, data=None, image_data=None, filename=None, dataDir=None, metadata=None, header=None, **kwargs):
        self.data = data if data is not None else np.array([])
        self.image_data = image_data if image_data is not None else np.array([])
        self.filename = filename
        self.dataDir = dataDir if dataDir else os.path.dirname(filename)
        self.metadata = metadata if metadata is not None else {}
        self.header = header if header is not None else {}

        self.__dict__.update(kwargs)  # Allow additional attributes to be set dynamically
    
    def __repr__(self):
        return f'DataObject(filename={self.filename}, dataDir={self.dataDir})'

class LaserDetection:

    '''Class for detecting laser signals in spectrograph images. Used during live calibration to find the laser line position.'''

    def __init__(self):
        pass

    def __call__(self, image, wavelength_axis):
        """
        Call method to process the image and detect laser signal. Requires:
        - image: 2D numpy array representing the spectrograph image.
        - wavelength_axis: 1D numpy array representing the wavelength axis of the image.
        """
        is_laser_present, laser_position = self.detect_laser_signal(image)
        self.peakfit_laser(image, wavelength_axis, initial_guess=laser_position)

        return

    def generate_test_image(self, width=2048, height=148, 
                            laser_position=None, laser_width=5, 
                            background_level=4000, noise_level=150, 
                            y_center=85, y_spread=20, plot=False):
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

        if laser_position is None:
            laser_position = np.random.randint(laser_width, width - laser_width)
        # else:
            # laser_position = np.random.randint(laser_position-50, laser_position+50)

        # 2D Gaussian signal: exp(-(X-x0)^2 / 2σx^2) * exp(-(Y-y0)^2 / 2σy^2)
        laser_signal = np.exp(-0.5 * ((X - laser_position) / laser_width) ** 2) * \
                    np.exp(-0.5 * ((Y - y_center) / y_spread) ** 2)

        # Normalize signal to max ~1, scale to realistic intensity (e.g. add 500 counts)
        laser_signal *= 5000

        # Add background and Gaussian noise
        image = background_level + laser_signal + np.random.normal(0, noise_level, size=(height, width))

        if plot==True:
            plt.figure(figsize=(10, 5))
            plt.imshow(image, aspect='auto', cmap='gray', origin='lower')
            plt.colorbar(label='Intensity')
            plt.title(f"Generated Test Image with Laser at X={laser_position}")
            plt.xlabel("X (Spectral Axis)")
            plt.ylabel("Y (Spatial Axis)")
            plt.show()

        print(f"Generated test image with laser at X={laser_position} ")

        return image


    def detect_laser_signal(self, image, threshold_sigma=10, min_width=3, plot=False):
        # Step 1: Collapse in Y to get intensity along X
        profile_x = np.median(image, axis=0)  # shape = (X,)
        
        # Step 2: Estimate background using robust statistics
        med = np.median(profile_x)
        mad = median_abs_deviation(profile_x)
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

        
        if plot:
            plt.figure(figsize=(8, 4))
            plt.plot(profile_x, label='X-profile')
            plt.axhline(med, color='gray', linestyle='--', label='Median')
            plt.axhline(threshold, color='red', linestyle='--', label=f'Threshold ({threshold_sigma} MAD)')
            plt.axvline(np.argmax(signal_mask), color='green', linestyle='--', label='Laser Signal Start')
            plt.title("Laser Detection Profile")
            plt.legend()
            plt.xlabel("X (pixel)")
            plt.ylabel("Integrated Intensity")
            plt.grid(True)
            plt.show()

            plt.imshow(image, aspect='auto', cmap='gray', origin='lower')
            # add a dot at the laser position
            plt.plot(x_max, y_max, 'ro', markersize=5, label='Laser Position')
            plt.show()

        
        
        return is_laser_present, (x_max, y_max)


    
    # def peakfit_laser_signal(self, profile_x, signal_mask)
    def peakfit_laser(self, image, wavelength_axis, initial_guess=None, binning_width=20):
        
        if initial_guess is None:
            initial_guess = (np.argmax(image, axis=0), np.argmax(np.median(image, axis=0)))

        xpos, ypos = initial_guess
        

        spectrum = np.median(image[ypos - binning_width:ypos + binning_width, :], axis=0)
        dataX = wavelength_axis  # Assuming wavelength_axis is provided

        data = np.column_stack((dataX, spectrum))  # shape (2, N)

        peakfits = PeakFitter(obj, peak_detect=None)

        peakfits.select_region_2(set_range=data_range) 
        peakfits._baseline_data(lam=1000, p=0.001)
        # template_peak = (peakfits.dataX[-1] + peakfits.dataX[0])/2
        # peakfits.add_template_peak(template_peak)
        peakfits.detect_initial_peak() # finds and adds a single peak, assuming laser line
        peakfits.optimise()


        peakfits.save_results()

        if len(obj.peakfit_dict) == 0:
            print(f'No peaks found in {file}. Skipping...')
            # continue

        peak = obj.peakfit_dict['peaks'][0][1]

        if raman_shift is not None:
            peak = raman_to_wavelength(peak, raman_shift)

        obj.excitation_wavelength = peak
        calibration_dict[f"{original_wavelength:.2f}"] = obj.excitation_wavelength
        print('Laser wavelength: {}'.format(peak))
        
        
        if save_cal is True:
            exportDir = os.path.join(self.data_dir, 'export')
            if not os.path.exists(exportDir):
                os.makedirs(exportDir)
            with open(os.path.join(exportDir, 'calibration.json'), 'w') as outfile:
                json.dump(calibration_dict, outfile, indent=4)
        

    # === Example usage ===
    # image = your 2D numpy array, e.g. from a CCD
# is_laser, profile, mask = detect_laser_signal(image, plot=True)

if __name__ == "__main__":
    laser_detector = LaserDetection()
    
    # Generate a test image with a laser signal
    test_image = laser_detector.generate_test_image(laser_width=5, 
                                                     background_level=4000, noise_level=150, plot=False)
    
    # Detect the laser signal in the generated image
    # is_laser_present, initial_guess = laser_detector.detect_laser_signal(test_image, plot=False)
    
    laser_detector(test_image, np.arange(test_image.shape[1]))  # Assuming wavelength_axis is just pixel indices for this test
    # print(f"Laser signal detected: {is_laser_present}")
    # print(f"Profile X shape: {profile_x.shape}, Signal mask shape: {signal_mask.shape}")
    # print(f"laser line position: {np.argmax(signal_mask)}")
    breakpoint()