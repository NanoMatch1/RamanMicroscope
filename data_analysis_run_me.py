import sys
import os
import numpy as np
# import h5py

from analysis_spectroscopy import DataSet
# specific analyses for each person
# from pipelines.shifan import fluorometer_tests

series_name = r'sulfur-wavelengthscan-t4' # CHANGE THIS TO THE NAME OF THE FOLDER IN THE DATA DIRECTORY
series_name = r'14MayWLMoS2'

dirname = os.path.dirname(__file__)
dataDir = os.path.join(dirname, 'data')
fileDir = os.path.join(dataDir, series_name)

# fileDir = r'C:\Users\Sam\Data\14MayWLMoS2'

if __name__ == '__main__':
    dataSet = DataSet(fileDir, initialise=False)
    # dataSet.access_database('slider_test')
    dataSet.initialise()
    dataSet.index_from_filenames()
    dataSet._use_index_filenames()
    dataSet.sort_by_scan_index()
    dataSet.frames_to_spectrum()#binning_region=(35,45)) # edit this to the region of interest, or remove to 


    dataSet.plot_slider_comparison()
    # dataSet.export_to_csv() # > Export function here
    print("Stop here or move calibrate_excitation_wavelength up in the list to do before saving")
    # breakpoint()
    dataSet.subtract_background_files(show=True)
    # dataSet.plot_current(offset = 1000, legend=False)
    dataSet.calibrate_excitation_wavelength(save_cal=True, raman_shift=385) 
    # dataSet.save_database()
    # dataSet.access_database()
    dataSet.baseline_all(lam = 1000000, p = 0.000001, show=True)
    dataSet.plot_2D_test(mode='raman', y_bin_width=1)
    dataSet.save_database()
