import sys
import os
import numpy as np
# import h5py

from analysis_spectroscopy import DataSet
# specific analyses for each person
# from pipelines.shifan import fluorometer_tests
import matplotlib.pyplot as plt

def noise_workflow():
    dataSet = DataSet(fileDir, initialise=False)
    dataSet.initialise()
    # dataSet.access_database('slider_test')
    dataSet.index_from_filenames()
    dataSet._use_index_filenames()
    dataSet.sort_by_scan_index()
    dataSet.frames_to_spectrum(binning_region=(20,100))#binning_region=(35,45)) # edit this to the region of interest, or remove to 

    # average each spectrum
    for filename, data_obj in dataSet.data_dict.items():
        # print("filename: ", filename)
        # print("metadata: ", data_obj.metadata)
        data_obj.average = np.average(data_obj.dataY[200:1600])
        
    average_list = []
    for filename, data_obj in dataSet.data_dict.items():
        # print("filename: ", filename)
        print("metadata: ", data_obj.metadata)
        acqtime = data_obj.metadata['general_parameters']['acquisition_time']
        temperature = data_obj.metadata['_current_parameters']['detector_temperature']
        average_list.append([acqtime, data_obj.average, temperature])
        if acqtime == 20:
            baseline = data_obj

    # breakpoint()

    fig, ax = plt.subplots(2, 2)
    ax[0, 0].set_title('Raw data')
    ax[0, 1].set_title('Background subtracted data')

    for filename, data_obj in dataSet.data_dict.items():
        # data_obj._subtract_background(baseline)
        acqtime = data_obj.metadata['general_parameters']['acquisition_time']
        dataY = data_obj.dataY
        ax[0, 0].plot(data_obj.dataX, dataY, label=filename)
        dataY = dataY-(baseline.dataY*(acqtime/20)) # normalise to 20s acquisition time
        data_obj.dataY = dataY
        data_obj.data = np.column_stack((data_obj.dataX, dataY))
        ax[0, 1].plot(data_obj.dataX, dataY, label=filename)

    average_list = np.array(average_list)
    ax[1, 0].set_title('Averages')
    ax[1, 0].scatter(average_list[:, 0], average_list[:, 1], label='average')
    ax[1, 0].set_xlabel('Acquisition time (s)')
    ax[1, 1].set_title('Temperature')
    ax[1, 1].scatter(average_list[:, 0], average_list[:, 2], label='temperature')
    ax[1, 1].set_xlabel('Acquisition time (s)')

    # averages = (average_list[:, 1]-min(average_list[:, 1]))/(max(average_list[:, 1]-min(average_list[:, 1])))
    plt.show()


    # plt.plot(average_list[:, 0], averages, label='average')
    # plt.scatter(average_list[:, 0], average_list[:, 2], label='temperature')
    # plt.legend()
    # plt.show()


    # breakpoint()

    dataSet.plot_current(offset = 1000, legend=False)
    dataSet.plot_slider_comparison()
    # dataSet.export_to_csv() # > Export function here
    print("Stop here or move calibrate_excitation_wavelength up in the list to do before saving")
    # breakpoint()

series_name = r'sulfur-wavelengthscan-t4' # CHANGE THIS TO THE NAME OF THE FOLDER IN THE DATA DIRECTORY
series_name = r'time_series_21-5-2'

dirname = os.path.dirname(__file__)
dataDir = os.path.join(dirname, 'data')
fileDir = os.path.join(dataDir, series_name)

# fileDir = r'C:\Users\Sam\Data\14MayWLMoS2'

if __name__ == '__main__':
    dataSet = DataSet(fileDir, initialise=False)
    dataSet.initialise()
    # dataSet.access_database('slider_test')
    dataSet.index_from_filenames()
    dataSet._use_index_filenames()
    dataSet.sort_by_scan_index()
    dataSet.frames_to_spectrum()#binning_region=(35,45)) # edit this to the region of interest, or remove to 

    dataSet.plot_current(offset = 1000, legend=False)
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
