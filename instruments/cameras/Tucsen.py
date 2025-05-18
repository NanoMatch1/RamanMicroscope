# from tucsen import TUCam
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
from tucsen.TUCam import (
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

class TucsenCamera:
    def __init__(self, interface=None, simulate=False, report=False):
        """
        Initialize the camera driver (but do not open a specific camera yet).
        """
        self.interface = interface

        # acquisition parameters
        self.acqtime = 500 # milliseconds
        self.full_roi = (0, 0, 2048, 2048)
        self.roi = (0, 1220, 2048, 148)

        # self.roi = (0, 0, 1000, 1000)

        self.camera_parameters = {}
        self.camera_capabilities = {}

        # Thread-safety and acquisition flags
        self.camera_lock = threading.Lock()
        self.stop_flag = threading.Event()
        self.is_running = False

        self.command_functions = {
            "acquire": self.safe_acquisition,
            "acqnow": self.acquire_one_frame,
            "transient": self.acquire_transient,
            "runcam": self.start_continuous_acquisition,
            "stopcam": self.stop_continuous_acquisition,
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

    def initialise(self):
        print("Initialising TUCam API...")
        # Prepare TUCAM structures
        self.TUCAMINIT = TUCAM_INIT(0, self.script_dir.encode('utf-8'))
        self.TUCAMOPEN = TUCAM_OPEN(0, 0)
        self.handle = self.TUCAMOPEN.hIdxTUCam
        
        # Real hardware initialization
        TUCAM_Api_Init(pointer(self.TUCAMINIT), 5000)
        print("TUCam API initialized.")

        self._open_camera()
        self._set_hardware_binning()
        self.set_acqtime(self.acqtime)
        self.set_image_processing(0)
        self.set_resolution(1)
        # self.set_denoise(0)
        self.set_image_and_gain()
        self.set_roi(self.roi_new)
        self.set_fan_speed(3)


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
    

    def _set_hardware_binning(self, binning_level=1):
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


    def _open_camera(self, Idx=0):
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

    def _close_camera(self):
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
        self._close_camera()
        self.uninit_api()
        print("Camera connection closed and API uninitialized.")

    def _safe_acquisition(self, target_temp=-5, export=True):
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

    def _acquire_one_frame(self, timeout=100000):
        """Low level command. Open in single-frame or soft-trigger mode, grab one, then close."""

        if self.is_running:
            print("Camera is already running. Please stop the acquisition before starting a new one.")
            return None

        self.camera_lock.acquire()
        try:
            self._open_stream(self.tucam_data.m_capmode.TUCCM_SEQUENCE)  # or TUCCM_SOFTTRIGGER
            image_data = self._grab_frame(timeout=timeout)
        finally:
            self._close_stream()
            self.camera_lock.release()

        if image_data is None:
            print("Acquisition failed - image_data is None.")
            return None
        
        # optional export can sit up here; no more fan hacks
        return image_data
    
    def _grab_frame(self, timeout=100000):
        """Low level command. While the camera stream is open, grab one frame."""
        if self.is_running is False:
            print("Camera is not running. Please start the acquisition before grabbing a frame.")
            return None
        
        image_data = self.wait_for_image_data(timeout=timeout)
        return image_data

    def _open_stream(self):
        """Allocate buffers and start the engine in the given mode."""
        self.camera_lock.acquire()
        self.is_running = True
        TUCAM_Buf_Alloc(self.hCam, pointer(self.tucam_data.m_frame))
        TUCAM_Cap_Start(self.hCam, self.tucam_data.m_capmode.TUCCM_SEQUENCE)

    def _close_stream(self):
        """Stop & release, no matter what happens during grabbing."""
        TUCAM_Buf_AbortWait(self.hCam)
        TUCAM_Cap_Stop(self.hCam)
        TUCAM_Buf_Release(self.hCam)
        self.camera_lock.release()
        self.is_running = False

    def wait_for_image_data(self, report=True, timeout=100000, debug=False):

        try:
            result = TUCAM_Buf_WaitForFrame(self.TUCAMOPEN.hIdxTUCam, pointer(self.tucam_data.m_frame), timeout)

        except Exception:
            print('Grab the frame failure')
            return None

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

    def start_continuous_acquisition(self):
        """
        Start a continuous acquisition thread until told to stop via stop_continuous_acquisition().
        Each frame is saved as .npy into self.transient_dir.
        """
        if self.is_running:
            print("Camera is already running. Please stop acquisition before starting a continuous acquisition!")
            return
        
        self._open_stream()

        n_frames = self.interface.microscope.acquisition_control.general_parameters['n_frames']
        # Set up for continuous acquisition
        def continuous_task():
            self.stop_flag.clear()

            while not self.stop_flag.is_set():
                try:
                    for index in range(n_frames):
                        print(f"Acquiring frame {i+1}/{n_frames}...")

                        new_frame = self._grab_frame(timeout=100000)
                        if new_frame is None:
                            print("Failed to acquire frame.")
                            break

                        if index == 0:
                            # First frame, set up the data array
                            data = new_frame
                        else:
                            data = (data + new_frame) / 2

                        wavelengths = self.interface.microscope.wavelength_axis
                        self.interface.acq_ctrl.save_spectrum_transient(data, wavelengths)
                        time.sleep(0.01)

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
        self.stop_flag.set()
        self.is_running = False
        self._close_stream()
        print("Continuous acquisition stopped.")