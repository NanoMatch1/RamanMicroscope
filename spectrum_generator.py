import numpy as np
import os
import matplotlib.pyplot as plt

class FileProcessor:

    def __init__(self, file_path, spectrum_roi=None):
        self.file_path = file_path
        self.spectrum_roi = spectrum_roi
        self.data_dict = {}

    def frame_to_spectrum(self, data):
        """ Calculate spectrum by averaging the selected ROI in the image. """

        if self.spectrum_roi is None:
            y_start, y_end = 0, data.shape[0]  # Default to full height
        else:
            y_start, y_end = self.spectrum_roi
            y_start = max(0, min(data.shape[0], y_start))
            y_end = max(0, min(data.shape[0], y_end))

        if y_end <= y_start:
            print("Invalid ROI: end must be greater than start")
            y_end = y_start + 1

        data_array = data[y_start:y_end, :]
        spectrum_data = np.mean(data_array, axis=0)

        return spectrum_data


    def load_all_files(self, directory):
        """Load all files in the given directory."""
        if not os.path.exists(directory):
            print(f"Directory {directory} does not exist.")
            return

        files = [file for file in os.listdir(directory) if file.endswith('.npy')]
        self.files = files

        if not files:
            print(f"No .npy files found in {directory}.")
            return

        for file in files:
            if file.endswith('.npy'):
                file_path = os.path.join(directory, file)
                try:
                    data = np.load(file_path)
                    if len(data.shape) == 3:
                        data = data[:, :, 0]
                    self.data_dict[file] = data
                except Exception as e:
                    print(f"Error loading file {file_path}: {e}")


        return files
    
    def save_all_spectra(self, output_directory):
        """Save all spectra to the specified directory."""
        if not os.path.exists(output_directory):
            os.makedirs(output_directory)

        for file_name, data in self.data_dict.items():
            spectrum_data = self.frame_to_spectrum(data)
            output_path = os.path.join(output_directory, f"spectrum_{file_name}.csv")
            self.save_spectrum(spectrum_data, output_path)
    

    def save_spectrum(self, spectrum_data, output_path):
        """Save the spectrum data to a file."""
        try:
            np.savetxt(output_path, spectrum_data, delimiter=',')
            print(f"Spectrum saved to {output_path}")
        except Exception as e:
            print(f"Error saving spectrum to {output_path}: {e}")

    def load_all_csv(self, directory):
        """Load all CSV files in the given directory."""
        if not os.path.exists(directory):
            print(f"Directory {directory} does not exist.")
            return

        files = [file for file in os.listdir(directory) if file.endswith('.csv')]
        self.files = files

        if not files:
            print(f"No .csv files found in {directory}.")
            return

        for file in files:
            if file.endswith('.csv'):
                file_path = os.path.join(directory, file)
                data = self.load_csv(file_path)
                if data is not None:
                    self.data_dict[file] = data


    def load_csv(self, file_path):
        """Load a CSV file."""
        try:
            data = np.loadtxt(file_path, delimiter=',')
            return data
        except Exception as e:
            print(f"Error loading CSV file {file_path}: {e}")
            return None

    def plot_current(self):
        '''plot all spectra in the data_dict'''
        for file_name, data in self.data_dict.items():
            plt.plot(data, label=file_name)
        plt.xlabel("Pixel Position")
        plt.ylabel("Intensity")

        plt.show()

if __name__ == "__main__":
    # Example usage
    input_directory = r"C:\Users\Raman\matchbook\RamanMicroscope\data\camera_calibration_data_17-04-25"
    output_directory = r"C:\Users\Raman\matchbook\RamanMicroscope\data\camera_calibration_data_17-04-25\processed_spectra"
    file_processor = FileProcessor(input_directory, spectrum_roi=(30, 60))
    # file_processor.load_all_files(input_directory)
    # file_processor.save_all_spectra(output_directory)
    # Now load the CSV files from the output directory and plot them
    input_directory = output_directory
    file_processor.load_all_csv(input_directory)
    # file_processor.plot_current()
    for file_name, data in file_processor.data_dict.items():

        plt.plot(data, label=file_name)
        plt.xlabel("Pixel Position")
        plt.ylabel("Intensity")
    plt.legend()
    plt.show()