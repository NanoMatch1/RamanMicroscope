import sys
import os
import numpy as np
# import h5py

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'analysis-spectroscopy','analysis_spectroscopy'))



from dataset_analysis import DataSet

# specific analyses for each person
# from pipelines.shifan import fluorometer_tests


series_name = r'sulfur-wavelengthscan-t4'
# series_name = r'logic-t1'
dataDir = r'C:\Users\sjbrooke\matchbook\RamanMicroscope\data'
fileDir = os.path.join(dataDir, series_name)


if __name__ == '__main__':

    dataSet = DataSet(fileDir)
    # dataSet.save_database()
    # dataSet.access_database('ramantest')

    dataSet.frames_to_spectrum(
        # binning_region=(30,120)
        )
    # breakpoint()
    # for filename, data in dataSet.data_dict.items():
    #     print(f"Filename: {filename}")
    #     print(f"Data: {data}")
        # Perform any other operations you need with the data here
        # breakpoint()
    # dataSet.load_data()
    # breakpoint()
    dataSet.plot_current(offset=1000, legend=False)
    dataSet.plot_wavelength_scan()
    # dataSet.plot_current()