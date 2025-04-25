import sys
import os
import numpy as np
# import h5py

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'analysis-spectroscopy','analysis_spectroscopy'))



from dataset_analysis import DataSet

# specific analyses for each person
# from pipelines.shifan import fluorometer_tests


series_name = r'sulfur-wavelengthscan-t4' # CHANGE THIS TO THE NAME OF THE FOLDER IN THE DATA DIRECTORY

# series_name = r'logic-t1'
dirname = os.path.dirname(__file__)
dataDir = os.path.join(dirname, 'data')
fileDir = os.path.join(dataDir, series_name)


if __name__ == '__main__':

    dataSet = DataSet(fileDir)
    # dataSet.save_database()
    # dataSet.access_database('ramantest')

    dataSet.frames_to_spectrum(
         # binning_region=(35,45) # uncomment this line to bin the data automatically
        )
    # breakpoint()
    # for filename, data in dataSet.data_dict.items():
    #     print(f"Filename: {filename}")
    #     print(f"Data: {data}")
        # Perform any other operations you need with the data here
        # breakpoint()
    # dataSet.load_data()
    # breakpoint()
    dataSet.subtract_single_background()
    dataSet.sort_by_excitation_wavelength()
    dataSet.plot_current(offset=1000, legend=False)
    # dataSet.plot_wavelength_scan(mode='wavelength')
    dataSet.plot_wavelength_scan_pcolourmesh(mode='wavelength', y_bin_width=1)
    # dataSet.plot_current()