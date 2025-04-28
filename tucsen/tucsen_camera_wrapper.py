import ctypes
from ctypes import byref
import os
import threading
import time
import numpy as np
import matplotlib.pyplot as plt
from PIL import Image
from ctypes import pointer, cast, POINTER
from functools import wraps

import traceback

from ctypes import pointer
from .TUCam import (
    TUCAM_INIT,
    TUCAM_OPEN,
    TUCAM_FRAME,
    TUCAM_ROI_ATTR,
    TUCAM_Buf_Alloc,
    TUCAM_Buf_Release,
    TUCAM_Buf_WaitForFrame,
    TUCAM_Buf_AbortWait,
    TUCAM_Cap_Start,
    TUCAM_Cap_Stop,
    TUCAM_Capa_SetValue,
    TUCAM_Prop_SetValue,
    TUCAM_Dev_Open,
    TUCAM_Dev_Close,
    TUCAM_Api_Init,
    TUCAM_Api_Uninit,
    TUCAM_CAPTURE_MODES,
    TUFRM_FORMATS,
    TUCAM_IDCAPA,
    TUCAM_IDPROP,
    TUCAM_Cap_SetROI,
    TUCAMRET,
    TUCAM_Prop_GetAttr,
    TUCAM_PROP_ATTR,
    TUCAM_CAPA_ATTR,
    TUCAM_Capa_GetAttr,
    TUCAM_Prop_GetValue,
    TUCAM_Capa_GetValue,
    TUCAM_FILE_SAVE,
    TUIMG_FORMATS,
    TUCAM_File_SaveImage,
    
)

def simulate(expected_value=None):
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            if self.simulate:
                return expected_value
            return func(self, *args, **kwargs)
        return wrapper
    return decorator

class TucamData:

    '''A simple class wrapper for handling the data structure of the Tucsen camera.'''

    def __init__(self, camera, filename=None, save_dir=None):
        self.camera = camera
        self.data = None

        self.m_fs = TUCAM_FILE_SAVE()
        self.m_frame = TUCAM_FRAME()
        self.m_format = TUIMG_FORMATS
        self.m_frformat = TUFRM_FORMATS
        self.m_capmode = TUCAM_CAPTURE_MODES
        self.m_frame.pBuffer = 0
        self.m_frame.ucFormatGet = TUFRM_FORMATS.TUFRM_FMT_USUAl.value
        self.m_frame.uiRsdSize = 1

        self.m_fs.nSaveFmt = self.m_format.TUFMT_TIF.value


class TucamData:

    def __init__(self, camera, filename=None, save_dir=None):
        self.camera = camera
        self.data = None

        self.m_fs = TUCAM_FILE_SAVE()
        self.m_frame = TUCAM_FRAME()
        self.m_format = TUIMG_FORMATS
        self.m_frformat = TUFRM_FORMATS
        self.m_capmode = TUCAM_CAPTURE_MODES
        self.m_frame.pBuffer = 0
        self.m_frame.ucFormatGet = TUFRM_FORMATS.TUFRM_FMT_USUAl.value
        self.m_frame.uiRsdSize = 1

        self.m_fs.nSaveFmt = self.m_format.TUFMT_TIF.value


class TucamCamera:
    """
    A refactored camera class that encapsulates initialization,
    acquisition, and teardown for a Tucsen camera.
    """

    def __init__(self, interface=None, simulate=False, report=False):
        """
        Initialize the camera driver (but do not open a specific camera yet).
        """
        self.interface = interface
        self.report = report
        self.simulate = simulate
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.transient_dir = self.interface.transientDir if self.interface else os.path.join(self.script_dir, 'transient')
        self.save_dir = self.interface.saveDir if self.interface else os.path.join(self.script_dir, 'data')

        # acquisition parameters
        self.acqtime = 500 # milliseconds
        self.roi = (0, 0, 2048, 2048)
        self.full_roi = (0, 0, 2048, 2048)
        # self.roi_new = (0, 0, 2048, 2048)
        self.roi_new = (0, 1220, 2048, 148)

        # self.roi = (0, 0, 1000, 1000)

        self.camera_parameters = {}
        self.camera_capabilities = {}

        self.acquire_mode = 'spectrum'  # 'image' or 'spectrum'

        # Thread-safety and acquisition flags
        self.camera_lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.is_running = False

        self.command_functions = {
            "acquire": self.safe_acquisition,
            "acqnow": self.acquire_one_frame,
            "transient": self.acquire_transient,
            "run": self.start_continuous_acquisition,
            "stop": self.stop_continuous_acquisition,
            "refresh": self.refresh,
            "roi": self.set_roi,
            "acqtime": self.set_acqtime,
            "gain": self.set_gain,
            "gain_info": self.get_gain_attributes,
            "cam-cal": self.calibrate_best_signal,
            # "high_signal": self.set_high_signal_boost,
            "params": self.print_camera_params,
            "info": self.camera_info,
            "getinfo": self.get_camera_parameters,
            "debug": self.debug,
            "temp": self.check_camera_temperature,
            # "longexp": self.set_long_exposure_mode,
            "fan": self.set_fan_speed,
            'logtemp': self.log_camera_temperature,
            'logfan': self.test_fan_speeds,
            'setbin': self.set_hardware_binning,
            'setmode': self.set_acquire_mode,
            'setgain': self.set_image_and_gain,
            'setres': self.set_resolution,
            'setlft': self.set_lft,
            'setrgt': self.set_rgt,
            'closecam': self.close_camera_connection,
            # "safe": self.safe_acquisition,

        }

        self.tucam_data = TucamData(self)

        print('Finished TucsenCamera init')

    def allocate_buffer_and_start(self):
        TUCAM_Buf_Alloc(self.TUCAMOPEN.hIdxTUCam, pointer(self.tucam_data.m_frame))
        TUCAM_Cap_Start(self.TUCAMOPEN.hIdxTUCam, self.tucam_data.m_capmode.TUCCM_SEQUENCE.value)

    def deallocate_buffer_and_stop(self):
        TUCAM_Buf_AbortWait(self.TUCAMOPEN.hIdxTUCam)
        TUCAM_Cap_Stop(self.TUCAMOPEN.hIdxTUCam)
        TUCAM_Buf_Release(self.TUCAMOPEN.hIdxTUCam)

    def wait_for_image_data(self, report=True, timeout=10000, debug=False):

        try:
            result = TUCAM_Buf_WaitForFrame(self.TUCAMOPEN.hIdxTUCam, pointer(self.tucam_data.m_frame), timeout)
            # ImgName = os.path.join(self.script_dir, 'testing', 'test_image')
            # m_fs.pFrame = pointer(m_frame)
            # m_fs.pstrSavePath = ImgName.encode('utf-8')
            # ch:保存数据帧到硬盘 | en:Save image to disk
            # TUCAM_File_SaveImage(self.TUCAMOPEN.hIdxTUCam, m_fs)
            # print('Save the image data success, the path is %#s'%ImgName)
        except Exception:
            print('Grab the frame failure')
            return None

        if debug:
            # For debugging, print some frame details:
            print("Header size:", self.tucam_data.m_frame.usHeader)
            print("Image size:", self.tucam_data.m_frame.uiImgSize)
            print("Dimensions:", self.tucam_data.m_frame.usWidth, "x", self.tucam_data.m_frame.usHeight)
            print("Channels:", self.tucam_data.m_frame.ucChannels, "Depth:", self.tucam_data.m_frame.ucDepth, "Elem bytes:", self.tucam_data.m_frame.ucElemBytes)

        data = self._frame_to_numpy()
        return data

    def _frame_to_numpy(self):
        # Calculate total buffer size (header + image data)
        total_size = self.tucam_data.m_frame.usHeader + self.tucam_data.m_frame.uiImgSize

        # Cast pBuffer to an array of unsigned bytes
        raw_bytes = np.ctypeslib.as_array(
            cast(self.tucam_data.m_frame.pBuffer, POINTER(ctypes.c_ubyte)),
            shape=(total_size,)
        )

        # Extract the image data bytes by skipping the header
        img_bytes = raw_bytes[self.tucam_data.m_frame.usHeader: self.tucam_data.m_frame.usHeader + self.tucam_data.m_frame.uiImgSize]

        # For 16-bit data, each pixel element consists of 2 bytes.
        # Convert the raw bytes to a 16-bit numpy array.
        # Note: uiImgSize is in bytes, so the number of 16-bit elements is uiImgSize // 2.
        img_data = np.frombuffer(img_bytes.tobytes(), dtype=np.uint16)

        # Verify that the size matches the expected dimensions:
        expected_elements = self.tucam_data.m_frame.usWidth * self.tucam_data.m_frame.usHeight * self.tucam_data.m_frame.ucChannels
        if img_data.size != expected_elements:
            print("Warning: Number of image elements does not match expected dimensions.")

        # Reshape the 1D array into the 3D image shape (height, width, channels)
        try:
            img = np.reshape(img_data, (self.tucam_data.m_frame.usHeight, self.tucam_data.m_frame.usWidth, self.tucam_data.m_frame.ucChannels))
            return img
        except Exception as e:
            print("Reshape failed:", e)
            return None

    def set_image_processing(self, value=0):
        # TUIDC_ENABLEIMGPRO
        status = TUCAM_Capa_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDCAPA.TUIDC_ENABLEIMGPRO.value, value)
        if status == TUCAMRET.TUCAMRET_SUCCESS:
            print(f"Image processing set to {value}.")
        else:
            print(f"Failed to set image processing. Error code: {status}")

    def set_denoise(self, value=0):
        # TUIDC_DENOISE
        status = TUCAM_Capa_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDCAPA.TUIDC_ENABLEDENOISE.value, value)
        if status == TUCAMRET.TUCAMRET_SUCCESS:
            print(f"Denoise set to {value}.")
        else:
            print(f"Failed to set denoise. Error code: {status}")
        
    def set_resolution(self, resolution=1):
        """
        Set the camera resolution.
        """
        status = TUCAM_Capa_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDCAPA.TUIDC_RESOLUTION.value, resolution)

        if status == TUCAMRET.TUCAMRET_SUCCESS:
            print(f"Resolution set to {resolution}.")
        else:
            print(f"Failed to set resolution. Error code: {status}")

    def set_lft(self, lft=60000):

        TUCAM_Prop_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDPROP.TUIDP_LFTLEVELS.value, lft, 0)
        print(f"LFT set to {lft}.")

    def set_rgt(self, rgt=60000):
        TUCAM_Prop_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDPROP.TUIDP_RGTLEVELS.value, rgt, 0)
        print(f"RGT set to {rgt}.")

    def debug(self):
        print("Debugging...")
        breakpoint()

    def refresh(self):
        """
        Re-initialize the camera driver: closes and uninitializes the driver,
        then re-initializes. Useful if camera gets stuck or you want a clean reset.
        """
        print("Refreshing camera...")

        # Make sure to close if open, then uninit
        self.close_camera()


        # Re-init the TUCam API
        self.initialise()
        print("Camera refresh complete.")

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

    # @simulate(function_handler=lambda self, *args, **kwargs: 'Simulated camera initialized')
    def initialise(self):
        print("Initialising TUCam API...")
        # Prepare TUCAM structures
        self.TUCAMINIT = TUCAM_INIT(0, self.script_dir.encode('utf-8'))
        self.TUCAMOPEN = TUCAM_OPEN(0, 0)
        self.handle = self.TUCAMOPEN.hIdxTUCam
        
        # For simulation, set up simulated camera properties
        if self.simulate:
            self._sim_temperature = -5.0
            self._sim_exposure = self.acqtime
            self._sim_roi = self.roi_new
            self._sim_binning = 1
            self._sim_gain = 0
            self._sim_img_mode = 1
            print("Initialized simulated camera")
            return
        
        # Real hardware initialization
        TUCAM_Api_Init(pointer(self.TUCAMINIT), 5000)
        print("TUCam API initialized.")

        self.open_camera()
        self.set_hardware_binning()
        self.set_acqtime(self.acqtime)
        self.set_image_processing(0)
        self.set_resolution(1)
        # self.set_denoise(0)
        self.set_image_and_gain()
        self.set_roi(self.roi_new)
        self.set_fan_speed(3)

    def open_camera(self, Idx=0):

        if  Idx >= self.TUCAMINIT.uiCamCount:
            return

        print('Opening camera...')
        self.TUCAMOPEN = TUCAM_OPEN(Idx, 0)

        TUCAM_Dev_Open(pointer(self.TUCAMOPEN))

        if 0 == self.TUCAMOPEN.hIdxTUCam:
            print('Open the camera failure!')
            return
        else:
            print('Open the camera success!')

    def close_camera(self):
        """
        Close the currently open camera if any.
        """
        if self.TUCAMOPEN.hIdxTUCam != 0 and self.TUCAMOPEN.hIdxTUCam is not None:
            TUCAM_Dev_Close(self.TUCAMOPEN.hIdxTUCam)
            self.TUCAMOPEN.hIdxTUCam = 0  # Reset the handle
            print("Close the camera success")

    def uninit_api(self):
        """
        Uninitialize the TUCam API. Call this once you are done with all operations.
        """
        TUCAM_Api_Uninit()

    def close_camera_connection(self):
        """
        Close the camera and uninitialize the API.
        """
        self.close_camera()
        self.uninit_api()
        print("Camera connection closed and API uninitialized.")

    def set_hardware_binning(self, binning_level=1):
        """
        Configures the camera's hardware binning using TUIDC_RESOLUTION.

        :param binning_level: 0: "2048x2040(Normal)" 1: "2048x2040(Enhance)" 2: "1024x1020(2x2Bin)" 3: "512x510 (4x4Bin)
        """
        try:
            binning_level = int(binning_level)
        except ValueError:
            print("Binning level must be integer from 0-3 inclusive.")
            return

        if not hasattr(self, "TUCAMOPEN") or self.TUCAMOPEN.hIdxTUCam == 0:
            print("Error: Camera not initialized or opened.")
            return

        if binning_level not in [0, 1, 2, 3]:
            print("Error: Invalid binning level. Must be 0 (no binning) to 3 (max binning).")
            return

        # Set hardware binning via resolution setting
        status = TUCAM_Capa_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDCAPA.TUIDC_RESOLUTION.value, binning_level)

        if status == TUCAMRET.TUCAMRET_SUCCESS:
            print(f"Hardware binning set to level {binning_level}.")
        else:
            print(f"Failed to set binning. Error code: {status}")


    def safe_acquisition(self, target_temp=-5, export=True):
        """
        Acquires a frame, then waits for the temperature to drop before proceeding.
        """
        while True:
            temp = ctypes.c_double()
            TUCAM_Prop_GetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDPROP.TUIDP_TEMPERATURE.value, byref(temp), 0)

            if temp.value < target_temp:
                print(f"Temperature stable ({temp.value}°C). Acquiring frame...")
                data = self.acquire_one_frame(export=export)
                return data
            else:
                print(f"Camera too hot ({temp.value}°C). Waiting...")
                time.sleep(5)  # Wait before checking temperature again

    def set_fan_speed(self, speed=3, report=True):
        """
        Adjusts the fan speed to enhance cooling.
        Speed Levels:
        0 - Off
        1 - Low
        2 - Medium
        3 - High (Recommended for cooling)
        """
        status = TUCAM_Capa_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDCAPA.TUIDC_FAN_GEAR.value, speed)

        if status == TUCAMRET.TUCAMRET_SUCCESS:
            if report:
                print(f"Fan speed set to {speed} (High Recommended for Cooling).")
        else:
            print(f"Failed to set fan speed. Error code: {status}")


    def acquire_one_frame(self, save_dir='data', export=True):
        """
        acquire a single frame
        """
        if self.simulate:
            # Generate a simulated frame based on current settings
            width = self._sim_roi[2] if hasattr(self, '_sim_roi') else 2048
            height = self._sim_roi[3] if hasattr(self, '_sim_roi') else 148
            data = self._generate_simulated_image(width, height)

        else:
            # Real hardware acquisition
            self.allocate_buffer_and_start()
            data = self.wait_for_image_data()

            if export is True:
                self.export_data(data, 'test', overwrite=False, save_dir=os.path.join(self.script_dir, save_dir))
                time.sleep(0.001)

            self.deallocate_buffer_and_stop()
            self.set_fan_speed(3, report=False) # TODO: check if this is needed, forces fan to high speed after acquisition to work around temp bug
        return data
    
    def acquire_transient(self, save_dir='transient', export=True):
        """
        acquire a single frame
        """
        data = self.acquire_one_frame(save_dir=save_dir, export=export)
        return data
    
    def frame_to_spectrum(self, frame, crop_to_pixels=(2, -2)):
        """
        Converts a 2D image frame into a 1D spectrum.
        
        - Sums all pixels in the y-axis.

        :param frame: 2D numpy array representing the image.
        :return: 1D numpy array representing the spectrum.
        """
        if frame.ndim != 2:
            print("Input frame must be a 2D numpy array.")
            return
        frame = frame[crop_to_pixels[0]:crop_to_pixels[1], :]
        summed_array = np.average(frame, axis=0)

        return summed_array

    def start_continuous_acquisition(self):
        """
        Start a continuous acquisition thread until told to stop via stop_continuous_acquisition().
        Each frame is saved as .npy into self.transient_dir.
        """
        if self.is_running:
            print("Camera is already running continuous acquisition!")
            return
        
        self.allocate_buffer_and_start()

        # Set up for continuous acquisition
        def continuous_task():
            self.stop_flag.clear()

            while not self.stop_flag.is_set():
                try:
                    with self.camera_lock:
                        data = self.wait_for_image_data()
                    if data is None:
                        print("Failed to acquire frame.")
                        break
                    # self.export_data(data, 'transient_data', save_dir=self.transient_dir, overwrite=True)
                    wavelengths = self.interface.microscope.wavelength_axis
                    self.interface.microscope.acquisition_control.save_spectrum_transient(data, wavelengths)
                    time.sleep(0.001)
                except Exception as e:
                    print(f"Acquisition error: {e}")
                    print(traceback.format_exc())
                    break

        acq_thread = threading.Thread(target=continuous_task, daemon=True)
        acq_thread.start()

        self.is_running = True
        print("Started continuous acquisition.")

    def stop_continuous_acquisition(self):
        """
        Stop the continuous acquisition thread.
        """
        print("Stopping continuous acquisition.")
        self.stop_flag.set()
        self.is_running = False
        self.deallocate_buffer_and_stop()
    
    def check_camera_temperature(self, report=True):
        """
        Checks and prints the current camera temperature.
        """
        temp = ctypes.c_double()
        status = TUCAM_Prop_GetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDPROP.TUIDP_TEMPERATURE.value, byref(temp), 0)

        if status == TUCAMRET.TUCAMRET_SUCCESS:
            if report:
                print(f"Camera Temperature: {round(temp.value, 2)}°C")
            if temp.value > 80:
                print("WARNING: Camera is overheating! Exposure time may be reduced automatically.")
        else:
            print(f"Failed to retrieve temperature. Error code: {status}")

        return temp.value

    def set_acqtime(self, value):
        """
        Set camera exposure time to 'value' (in microseconds or ms—depends on the camera).
        """
        try:
            value = float(value)
        except ValueError:
            print("Exposure time must be a number.")
            return
        
        TUCAM_Capa_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDCAPA.TUIDC_ATEXPOSURE.value, 0)
        TUCAM_Prop_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDPROP.TUIDP_EXPOSURETM.value, value, 0)
        print(f"Set exposure to {value}")
    
    def print_camera_params(self):
        """
        Print all camera parameters.
        """
        print("Camera parameters:")
        print(f"  ROI: {self.roi}")
        print(f"  Exposure: {self.acqtime} ms")

    def set_roi(self, roi_tuple=(0, 0, 2048, 2048)):
        """
        Set camera ROI; expects a tuple: (HOffset, VOffset, Width, Height).
        """
        if roi_tuple == 'full':
            roi_tuple = self.full_roi


        elif isinstance(roi_tuple, list):
            try:
                roi_tuple = roi_tuple[0].split(',')
                roi_tuple = tuple([int(x) for x in roi_tuple])
            except ValueError:
                print("ROI values must be integers.")
        
        elif isinstance(roi_tuple, str):
            try:
                roi_tuple = roi_tuple.split(',')
                roi_tuple = tuple([int(x) for x in roi_tuple])
            except ValueError:
                print("ROI values must be integers.")

        if len(roi_tuple) != 4:
            print("ROI must be a 4-element tuple: (HOffset, VOffset, Width, Height)")
            return

        roi = TUCAM_ROI_ATTR()
        roi.bEnable = 1
        roi.nHOffset, roi.nVOffset, roi.nWidth, roi.nHeight = roi_tuple

        try:
            TUCAM_Cap_SetROI(self.TUCAMOPEN.hIdxTUCam, roi)
            print(
                "Set ROI success: HOffset={}, VOffset={}, Width={}, Height={}".format(
                    roi.nHOffset, roi.nVOffset, roi.nWidth, roi.nHeight
                )
            )
            
        except Exception as e:
            error_details = traceback.format_exc()
            result = f" > Error: {e}\n{error_details}"
            print(result)
            print(
                "Set ROI failure: HOffset={}, VOffset={}, Width={}, Height={}".format(
                    roi.nHOffset, roi.nVOffset, roi.nWidth, roi.nHeight
                )
            )

        self.roi = roi_tuple

    def set_acquire_mode(self, mode='image'):
        """
        LEGACY CODE.
        Set the camera acquisition mode to 'image' or 'spectrum'.
        """
        if mode not in ['image', 'spectrum']:
            print("Invalid acquisition mode. Must be 'image' or 'spectrum'.")
            return

        self.acquire_mode = mode
        print(f"Acquisition mode set to: {mode}")

    def _process_frame(self, frame, crop_bad_pixels=True):
        '''LEGACY CODE. 
        Processes the frame data based on the camera mode.'''
        

        # breakpoint()
        breaknow = False

        while True:
            plt.imshow(frame)
            plt.show()
            if breaknow:
                break
            
        if self.acquire_mode == 'spectrum':
            if crop_bad_pixels is True:
                frame = frame[2:-2, :, 1]
            else:
                frame = frame[:, :, 1]
            print("sending frame to spectrum")
            data = self.frame_to_spectrum(frame)
        else:
            data = frame[:, :, 1]
        return data


    def export_data(self, data, filename='default', save_dir=None, overwrite=False):
        """
        Example data export, saves to <script_dir>/data by default.
        """
        if not save_dir:
            save_dir = os.path.join(self.script_dir, 'data')
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)

        # data = self._process_frame(data)

        index = len([file for file in os.listdir(save_dir) if f'{filename}' in file])
        if overwrite is True:
            filename = f'{filename}.npy'
        else:
            filename = f'{filename}_{index}.npy'

        filepath = os.path.join(save_dir, filename)
        np.save(filepath, data)
        if save_dir != 'transient':
            print('Data saved to %s' % filepath)

    def camera_info(self):
        """Prints the camera info obtained by get_camera_parameters."""
        if len(self.camera_parameters) == 0 or len(self.camera_capabilities) == 0:
            self.get_camera_parameters()

        print("Camera Parameters:")
        for key, parameters in self.camera_parameters.items():
            # print(f"  {key}: {value}")
            print(f"{key}:")
            for param_key, param_value in parameters.items():
                print(f"  {param_key}: {param_value}")

        print("\nCamera Capabilities:")
        for key, capabilities in self.camera_capabilities.items():
            # print(f"  {key}: {value}")
            print(f"{key}:")
            for cap_key, cap_value in capabilities.items():
                print(f"  {cap_key}: {cap_value}")
        

    def get_camera_parameters(self):
        """
        Retrieves and prints all available properties and capabilities of the camera.
        Handles unknown return values gracefully.
        """
        if not hasattr(self, "TUCAMOPEN") or self.TUCAMOPEN.hIdxTUCam == 0:
            print("Error: Camera not initialized or opened.")
            return

        print("\n=== Camera Properties ===")
        for prop in TUCAM_IDPROP:
            try:
                prop_attr = TUCAM_PROP_ATTR()
                prop_attr.idProp = prop.value
                status = TUCAM_Prop_GetAttr(self.TUCAMOPEN.hIdxTUCam, byref(prop_attr))

                if status == TUCAMRET.TUCAMRET_SUCCESS:
                    print(f"{prop.name}:")
                    print(f"  Min: {prop_attr.dbValMin}")
                    print(f"  Max: {prop_attr.dbValMax}")
                    print(f"  Default: {prop_attr.dbValDft}")
                    print(f"  Step: {prop_attr.dbValStep}")

                    # Save the parameters for later use
                    self.camera_parameters[prop.name] = {
                        "min": prop_attr.dbValMin,
                        "max": prop_attr.dbValMax,
                        "default": prop_attr.dbValDft,
                        "step": prop_attr.dbValStep
                    }

                else:
                    print(f"{prop.name}: Not Available (Error Code: {status})")

            except Exception as e:
                print(f"{prop.name}: Error - {str(e)}")

        print("\n=== Camera Capabilities ===")
        for capa in TUCAM_IDCAPA:
            try:
                capa_attr = TUCAM_CAPA_ATTR()
                capa_attr.idCapa = capa.value
                status = TUCAM_Capa_GetAttr(self.TUCAMOPEN.hIdxTUCam, byref(capa_attr))

                if status == TUCAMRET.TUCAMRET_SUCCESS:
                    print(f"{capa.name}:")
                    print(f"  Min: {capa_attr.nValMin}")
                    print(f"  Max: {capa_attr.nValMax}")
                    print(f"  Default: {capa_attr.nValDft}")
                    print(f"  Step: {capa_attr.nValStep}")

                    # Save the capabilities for later use
                    self.camera_capabilities[capa.name] = {
                        "min": capa_attr.nValMin,
                        "max": capa_attr.nValMax,
                        "default": capa_attr.nValDft,
                        "step": capa_attr.nValStep
                    }

                else:
                    print(f"{capa.name}: Not Available (Error Code: {status})")

            except Exception as e:
                print(f"{capa.name}: Error - {str(e)}")

        print(f"Camera Parameters: {len(self.camera_parameters)}")
        print(f"Camera Capabilities: {len(self.camera_capabilities)}")

    def get_gain_attributes(self):
        """
        Get the attributes for the camera gain, including min, max, default, and step values.

        :return: A dictionary with 'min', 'max', 'default', and 'step' values, or None if retrieval fails.
        """
        if not hasattr(self, "TUCAMOPEN") or self.TUCAMOPEN.hIdxTUCam == 0:
            print("Error: Camera not initialized or opened.")
            return None

        attr = TUCAM_PROP_ATTR()
        attr.idProp = TUCAM_IDPROP.TUIDP_GLOBALGAIN.value
        status = TUCAM_Prop_GetAttr(self.TUCAMOPEN.hIdxTUCam, byref(attr))

        if status == TUCAMRET.TUCAMRET_SUCCESS:
            return {
                "min": attr.dbValMin,
                "max": attr.dbValMax,
                "default": attr.dbValDft,
                "step": attr.dbValStep
            }
        else:
            print(f"Failed to get camera gain attributes. Error code: {status}")
            return None
    
    def set_gain(self, gain_value):
        """
        Set the camera gain within valid limits.

        :param gain_value: Desired gain value.
        """
        if not hasattr(self, "TUCAMOPEN") or self.TUCAMOPEN.hIdxTUCam == 0:
            print("Error: Camera not initialized or opened.")
            return

        gain_attrs = self.get_gain_attributes()
        if not gain_attrs:
            return

        min_gain, max_gain = gain_attrs["min"], gain_attrs["max"]
        
        if not (min_gain <= gain_value <= max_gain):
            print(f"Error: Gain value out of range! Must be between {min_gain} and {max_gain}.")
            return

        status = TUCAM_Prop_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDPROP.TUIDP_GLOBALGAIN.value, gain_value, 0)

        if status == TUCAMRET.TUCAMRET_SUCCESS:
            print(f"Gain set to {gain_value} successfully.")
        else:
            print(f"Failed to set gain. Error code: {status}")

    # def set_high_signal_boost(self):
    #     """
    #     Configures the camera for the highest signal boost by:
    #     - Setting Image Mode to HighGain, 12Bit(HighSpeed) (`IMGMODESELECT = 3`).
    #     - Setting Gain Level to 1 (`GLOBALGAIN = 1`).
    #     TODO: Come back and check if this is the best configuration for signal boost.
    #     """
    #     if not hasattr(self, "TUCAMOPEN") or self.TUCAMOPEN.hIdxTUCam == 0:
    #         print("Error: Camera not initialized or opened.")
    #         return

    #     # Set Image Mode to HighGain, 12Bit(HighSpeed) (`IMGMODESELECT = 3`)
    #     status_mode = TUCAM_Capa_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDPROP.TUIDC_IMGMODESELECT.value, 3, 0)
        
    #     if status_mode == TUCAMRET.TUCAMRET_SUCCESS:
    #         print("Image mode set to HighGain, 12Bit(HighSpeed) (IMGMODE 3).")
    #     else:
    #         print(f"Failed to set image mode. Error code: {status_mode}")
    #         return

    #     # Set Gain Level to 1
    #     status_gain = TUCAM_Prop_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDPROP.TUIDP_GLOBALGAIN.value, 1, 0)

    #     if status_gain == TUCAMRET.TUCAMRET_SUCCESS:
    #         print("Gain set to 1 (HighGain Mode).")
    #     else:
    #         print(f"Failed to set gain. Error code: {status_gain}")

    def set_image_and_gain(self, img_mode=1, gain_level=0):
        '''Sets the image mode and gain mode to tbe best signal to noise option. Following testing, this is img_mode=1 and gain_level=0 (corresponding to the setting options in the props and capas document from tucsen).'''
        # Set Image Mode using `TUCAM_Capa_SetValue`
        mode_status = TUCAM_Capa_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDCAPA.TUIDC_IMGMODESELECT.value, img_mode)
        if mode_status != TUCAMRET.TUCAMRET_SUCCESS:
            print(f"  Failed to set image mode. Skipping...")

        # Set Gain Level using `TUCAM_Prop_SetValue`
        gain_status = TUCAM_Prop_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDPROP.TUIDP_GLOBALGAIN.value, gain_level, 0)
        if gain_status != TUCAMRET.TUCAMRET_SUCCESS:
            print(f"  Failed to set gain level. Skipping...")

    
    def SaveImageData(self):
        m_fs = TUCAM_FILE_SAVE()
        m_frame = TUCAM_FRAME()
        m_format = TUIMG_FORMATS
        m_frformat = TUFRM_FORMATS
        m_capmode = TUCAM_CAPTURE_MODES

        m_frame.pBuffer = 0
        m_frame.ucFormatGet = m_frformat.TUFRM_FMT_USUAl.value
        m_frame.uiRsdSize = 1

        m_fs.nSaveFmt = m_format.TUFMT_TIF.value

        TUCAM_Buf_Alloc(self.TUCAMOPEN.hIdxTUCam, pointer(m_frame))
        TUCAM_Cap_Start(self.TUCAMOPEN.hIdxTUCam, m_capmode.TUCCM_SEQUENCE.value)

        nTimes = 1
        for i in range(nTimes):
            try:
                result = TUCAM_Buf_WaitForFrame(self.TUCAMOPEN.hIdxTUCam, pointer(m_frame), 1000)
                ImgName = os.path.join(self.script_dir, 'Image_{}'.format(str(i)))
                m_fs.pFrame = pointer(m_frame)
                m_fs.pstrSavePath = ImgName.encode('utf-8')
                # ch:保存数据帧到硬盘 | en:Save image to disk
                TUCAM_File_SaveImage(self.TUCAMOPEN.hIdxTUCam, m_fs)
                print('Save the image data success, the path is %#s'%ImgName)
            except Exception:
                print('Grab the frame failure, index number is %#d'%i)
                continue

        TUCAM_Buf_AbortWait(self.TUCAMOPEN.hIdxTUCam)
        TUCAM_Cap_Stop(self.TUCAMOPEN.hIdxTUCam)
        TUCAM_Buf_Release(self.TUCAMOPEN.hIdxTUCam)

    def calibrate_best_signal(self):
        """
        Tests all image mode and gain combinations to find the optimal configuration for maximum signal.

        - Iterates through all valid `TUIDC_IMGMODESELECT` (image modes) and `TUIDP_GLOBALGAIN` (gain levels).
        - Captures a frame for each setting.
        - Analyzes signal strength (e.g., max pixel intensity).
        - Returns the best combination based on measured signal.

        :return: Dictionary with the best image mode, gain, and measured signal.
        """
        if not hasattr(self, "TUCAMOPEN") or self.TUCAMOPEN.hIdxTUCam == 0:
            print("Error: Camera not initialized or opened.")
            return

        # Define all valid image modes and gain levels
        test_combinations = [
            {"img_mode": 1, "gain": 0, "desc": "CMS, 12Bit"},
            {"img_mode": 2, "gain": 0, "desc": "HDR, 16Bit"},
            {"img_mode": 2, "gain": 1, "desc": "HighGain, 11Bit"},
            {"img_mode": 3, "gain": 1, "desc": "HighGain, 12Bit(HighSpeed)"},
            {"img_mode": 5, "gain": 1, "desc": "HighGain, 12Bit(Global Reset)"},
            {"img_mode": 2, "gain": 2, "desc": "LowGain, 11Bit"},
            {"img_mode": 4, "gain": 2, "desc": "LowGain, 12Bit(HighSpeed)"},
            {"img_mode": 5, "gain": 2, "desc": "LowGain, 12Bit(Global Reset)"},
        ]

        best_config = None
        best_signal = -1  # Start with an impossible signal value

        for config in test_combinations:
            print(f"Testing {config['desc']} (Mode {config['img_mode']}, Gain {config['gain']})...")

            # Set Image Mode using `TUCAM_Capa_SetValue`
            mode_status = TUCAM_Capa_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDCAPA.TUIDC_IMGMODESELECT.value, config["img_mode"])
            if mode_status != TUCAMRET.TUCAMRET_SUCCESS:
                print(f"  Failed to set image mode {config['img_mode']}. Skipping...")
                continue

            # Set Gain Level using `TUCAM_Prop_SetValue`
            gain_status = TUCAM_Prop_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDPROP.TUIDP_GLOBALGAIN.value, config["gain"], 0)
            if gain_status != TUCAMRET.TUCAMRET_SUCCESS:
                print(f"  Failed to set gain {config['gain']}. Skipping...")
                continue

            # Acquire a frame
            frame = self.acquire_one_frame(export=False)
            if frame is None:
                print("  Failed to capture frame. Skipping...")
                continue

            self.export_data(frame, 'cfg{}_gain{}'.format(config['img_mode'], config['gain']), overwrite = True)

        return

    def log_camera_temperature(self, log_interval=5, total_log_time=300, fan_speed=3):
        from datetime import datetime
        import csv

        """
        Logs the camera's temperature at regular intervals and saves the data to a CSV file.

        :param log_interval: Time (seconds) between each temperature measurement.
        :param total_log_time: Total duration (seconds) to log temperature.
        :param fan_speed: Fan speed setting (0: Off, 1: Low, 2: Medium, 3: High).
        """
        # Ensure log directory exists
        log_dir = os.path.join(self.script_dir, 'log')
        if not os.path.exists(log_dir):
            os.makedirs(log_dir)

        # Create a log file with a timestamp
        log_file = os.path.join(log_dir, f"temp_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")

        # Set fan speed
        self.set_fan_speed(fan_speed)
        print(f"Fan speed set to {fan_speed}. Starting temperature logging...")

        # Open CSV file for writing
        with open(log_file, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Timestamp", "Temperature (°C)"])

            start_time = time.time()
            while (time.time() - start_time) < total_log_time:
                temp = ctypes.c_double()
                TUCAM_Prop_GetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDPROP.TUIDP_TEMPERATURE.value, byref(temp), 0)
                current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                print(f"[{current_time}] Temperature: {temp.value:.2f}°C")
                writer.writerow([current_time, temp.value])

                time.sleep(log_interval)

        print(f"Temperature logging complete. Data saved to: {log_file}")

    def test_fan_speeds(self, log_interval=5, total_log_time=120):
        """
        Tests all fan speed settings (0 to 3) and logs temperature data for each.

        :param log_interval: Time (seconds) between each temperature measurement.
        :param total_log_time: Total duration (seconds) to log temperature per fan speed.
        """
        print("Starting fan speed test...")

        try:
            log_interval = float(log_interval)
            total_log_time = float(total_log_time)
        except ValueError:
            print("Invalid log interval or total log time. Must be a number.")
            return

        for fan_speed in range(4):  # Fan speeds 0 (off) to 3 (high)
            print(f"\nTesting Fan Speed {fan_speed}...")
            self.start_continuous_acquisition()
            self.log_camera_temperature(log_interval=log_interval, total_log_time=total_log_time, fan_speed=fan_speed)
            self.stop_continuous_acquisition()
            time.sleep(60) # Wait for camera to cool down

        print("Fan speed test complete. Check logs for results.")

    # ------------------
    # Internal Helpers
    # ------------------
    def _convert_to_numpy_old(self, frame):
        """
        Convert the frame buffer to a numpy array.
        """
        buf_type = ctypes.POINTER(ctypes.c_ubyte)
        buffer_ptr = ctypes.cast(frame.pBuffer, buf_type)
        buffer_list = list(buffer_ptr[:frame.uiImgSize])

        np_array = np.array(buffer_list, dtype=np.uint16)
        np_array = np_array.reshape((frame.usHeight, frame.usWidth, frame.ucElemBytes))
        return np_array
    
    def _convert_to_numpy(self, frame):
        # Cast the buffer pointer to a pointer to 16-bit unsigned integers.
        # breakpoint()
        buf_type = ctypes.POINTER(ctypes.c_ushort)
        # Compute the number of 16-bit elements.
        n_elements = frame.uiImgSize // 2
        buffer_ptr = ctypes.cast(frame.pBuffer, buf_type)
        # Create a numpy array directly from the ctypes pointer.
        np_array = np.ctypeslib.as_array(buffer_ptr, shape=(n_elements,))
        np_array = np_array.view('<u2')
        # Reshape the array to the correct dimensions.
        # breakpoint()
        np_array = np_array.reshape((frame.usHeight, frame.usWidth))
        return np_array


    # def get_camera_info(self):
    #     # Example stub if you have gain-attribute retrieval from TUCam
    #     gain_info = get_camera_gain_attributes(self.handle)
    #     print(gain_info)
    #     return gain_info