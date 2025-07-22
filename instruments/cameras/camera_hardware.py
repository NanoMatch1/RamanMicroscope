import ctypes
import numpy as np
import time

from contextlib import contextmanager
from ctypes import byref

from ctypes import pointer, cast, POINTER
from instruments.cameras.TUCam import (
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
    TUCAM_IDCAPA,
    TUCAM_IDPROP,
    TUCAM_Cap_SetROI,
    TUCAM_Prop_GetValue,
    TUCAM_Capa_GetValue,
    TUCAM_FILE_SAVE,
    TUCAM_FRAME,
    TUIMG_FORMATS,
    TUFRM_FORMATS,
    TUCAM_CAPTURE_MODES,
    TUCAM_OPEN,
    TUCAMRET,
    TUCAM_INIT,
)


class TucamData:
    def __init__(self):
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

class CameraHardwareBase:
    def open_stream(self): raise NotImplementedError
    def close_stream(self): raise NotImplementedError
    def grab_frame(self): raise NotImplementedError
    def initialise(self): raise NotImplementedError
    def set_exposure_time(self, value): raise NotImplementedError
    def set_image_and_gain(self, img_mode, gain_level): raise NotImplementedError
    def set_image_processing(self, value): raise NotImplementedError
    def set_resolution(self, resolution): raise NotImplementedError
    def set_denoise(self, value): raise NotImplementedError
    def set_fan_speed(self, speed): raise NotImplementedError
    def get_fan_speed(self): raise NotImplementedError
    def enable_auto_temperature_control(self, enable): raise NotImplementedError
    def set_target_temperature(self, target_celsius): raise NotImplementedError
    def get_temperature(self): raise NotImplementedError
    def set_roi(self, roi_tuple): raise NotImplementedError
    def close_camera(self): raise NotImplementedError
    def open_camera(self): raise NotImplementedError
    def uninit_api(self): raise NotImplementedError


class RealHardware(CameraHardwareBase):
    def __init__(self, camera):
        self.camera = camera
        self.interface = camera.interface
        self.logger = camera.logger.getChild('RealHardware')
        self.scriptDir = self.interface.scriptDir
        self._stream_open = False

        self.data = TucamData()

    def initialise(self):
        self.TUCAMINIT = TUCAM_INIT(0, self.scriptDir.encode('utf-8'))
        TUCAM_Api_Init(pointer(self.TUCAMINIT), 5000)

        self.open_camera()
        self.set_hardware_binning()
        self.set_auto_exposure(0)
        self.set_exposure_time(self.camera.acqtime)
        self.set_image_processing(0)
        self.set_resolution(1)
        self.set_image_and_gain(1, 0)
        self.set_roi(self.camera.roi)
        self.set_target_temperature(-20)
        self.set_fan_speed(3)

        self.open_stream()

    def open_stream(self):
        if self._stream_open:
            self.camera.logger.debug(f"tucam.open_stream: Stream is already open.")
            return
        TUCAM_Buf_Alloc(self.TUCAMOPEN.hIdxTUCam, pointer(self.data.m_frame))
        TUCAM_Cap_Start(self.TUCAMOPEN.hIdxTUCam, self.data.m_capmode.TUCCM_SEQUENCE.value)
        self._stream_open = True

    def close_stream(self):
        TUCAM_Buf_AbortWait(self.TUCAMOPEN.hIdxTUCam)
        TUCAM_Cap_Stop(self.TUCAMOPEN.hIdxTUCam)
        TUCAM_Buf_Release(self.TUCAMOPEN.hIdxTUCam)
        self._stream_open = False

    def grab_frame(self, timeout=100000):
        ret = TUCAM_Buf_WaitForFrame(self.TUCAMOPEN.hIdxTUCam, pointer(self.data.m_frame), timeout)
        if ret != TUCAMRET.TUCAMRET_SUCCESS:
            self.camera.logger.warning(f"Frame acquisition timeout or error. Return code: {ret}")
            return None

        if not self.data.m_frame.pBuffer:
            self.camera.logger.error("Frame buffer pointer is null.")
            return None

        if self.data.m_frame.usWidth == 0 or self.data.m_frame.usHeight == 0:
            self.camera.logger.error("Invalid frame dimensions received.")
            return None

        image = self._frame_to_numpy()
        return image

    def _frame_to_numpy(self):
        total_size = self.data.m_frame.usHeader + self.data.m_frame.uiImgSize
        raw_bytes = np.ctypeslib.as_array(
            cast(self.data.m_frame.pBuffer, POINTER(ctypes.c_ubyte)),
            shape=(total_size,)
        )
        img_bytes = raw_bytes[self.data.m_frame.usHeader: self.data.m_frame.usHeader + self.data.m_frame.uiImgSize]
        img_data = np.frombuffer(img_bytes.tobytes(), dtype=np.uint16)
        expected_elements = self.data.m_frame.usWidth * self.data.m_frame.usHeight * self.data.m_frame.ucChannels
        if img_data.size != expected_elements:
            self.camera.logger.warning("Image element mismatch")
        try:
            return np.reshape(img_data, (self.data.m_frame.usHeight, self.data.m_frame.usWidth, self.data.m_frame.ucChannels))
        except Exception as e:
            self.camera.logger.error(f"Reshape failed: {e}")
            return None
        
    def set_auto_exposure(self, state=0):
        """ Set the auto exposure state of the camera.
        Disabled by default. """
        TUCAM_Capa_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDCAPA.TUIDC_ATEXPOSURE.value, state)

    def set_exposure_time(self, value):
        value = float(value) * 1000
        TUCAM_Prop_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDPROP.TUIDP_EXPOSURETM.value, value, 0)

    def set_image_and_gain(self, img_mode, gain_level):
        TUCAM_Capa_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDCAPA.TUIDC_IMGMODESELECT.value, img_mode)
        TUCAM_Prop_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDPROP.TUIDP_GLOBALGAIN.value, gain_level, 0)

    def set_image_processing(self, value):
        TUCAM_Capa_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDCAPA.TUIDC_ENABLEIMGPRO.value, value)

    def set_denoise(self, value):
        TUCAM_Capa_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDCAPA.TUIDC_ENABLEDENOISE.value, value)

    def set_resolution(self, resolution):
        TUCAM_Capa_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDCAPA.TUIDC_RESOLUTION.value, resolution)

    def set_fan_speed(self, speed):
        TUCAM_Capa_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDCAPA.TUIDC_FAN_GEAR.value, speed)

    def get_fan_speed(self):
        val = ctypes.c_int()
        TUCAM_Capa_GetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDCAPA.TUIDC_FAN_GEAR.value, byref(val))
        return val.value

    def enable_auto_temperature_control(self, enable):
        val = 1 if enable else 0
        TUCAM_Prop_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDPROP.TUIDP_AUTO_CTRLTEMP.value, val, 0)

    def set_target_temperature(self, target_celsius):
        prop_val = int(max(-50, min(50, float(target_celsius))) + 50)
        TUCAM_Prop_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDPROP.TUIDP_TEMPERATURE.value, prop_val, 0)

    def get_temperature(self):
        temp = ctypes.c_double()
        TUCAM_Prop_GetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDPROP.TUIDP_TEMPERATURE.value, byref(temp), 0)
        return temp.value

    def set_roi(self, roi_tuple):
        roi = TUCAM_ROI_ATTR()
        roi.bEnable = 1
        roi.nHOffset, roi.nVOffset, roi.nWidth, roi.nHeight = roi_tuple
        TUCAM_Cap_SetROI(self.TUCAMOPEN.hIdxTUCam, roi)

    def set_hardware_binning(self, binning_level=1):
        TUCAM_Capa_SetValue(self.TUCAMOPEN.hIdxTUCam, TUCAM_IDCAPA.TUIDC_RESOLUTION.value, binning_level)

    def open_camera(self, Idx=0):
        if  Idx >= self.TUCAMINIT.uiCamCount:
            return

        print('Opening camera...')
        self.TUCAMOPEN = TUCAM_OPEN(Idx, 0)

        TUCAM_Dev_Open(pointer(self.TUCAMOPEN))

        if 0 == self.TUCAMOPEN.hIdxTUCam:
            self.logger.info('Open the camera failure!')
            return
        else:
            self.logger.info('Open the camera success!')

    def close_camera(self):
        """
        Close the currently open camera if any.
        """
        if self.TUCAMOPEN.hIdxTUCam != 0 and self.TUCAMOPEN.hIdxTUCam is not None:
            TUCAM_Dev_Close(self.TUCAMOPEN.hIdxTUCam)
            # self.TUCAMOPEN.hIdxTUCam = 0  # Reset the handle
            self.logger.info("Close the camera success")
        
        self.uninit_api()

    
    def uninit_api(self):
        TUCAM_Api_Uninit()




class SimulatedHardware(CameraHardwareBase):
    def __init__(self, camera):
        self.camera = camera
        self.interface = camera.interface
        self.logger = camera.logger.getChild('SimulatedHardware')
        self.acqtime = 0.5
        self.roi = (0, 1220, 2048, 148)

    def initialise(self):
        self.logger.info("Simulated camera initialized")
        self.camera.save_transient_spectrum_cb = self.interface.acq_ctrl.save_spectrum_transient

    def open_stream(self):
        self.logger.debug("[SIM] open_stream() called.")

    def close_stream(self):
        self.logger.debug("[SIM] close_stream() called.")

    def grab_frame(self, timeout=100000):
        self.logger.debug("[SIM] grab_frame() called.")
        image_data = self._generate_simulated_image()
        time.sleep(self.acqtime)
        return image_data

    def get_temperature(self):
        return np.random.uniform(-20, -16)

    def set_exposure_time(self, value):
        try:
            self.acqtime = float(value)
            self.logger.info(f"[SIM] Exposure time set to {self.acqtime} seconds")
        except ValueError:
            self.logger.error("[SIM] Invalid exposure time value")

    def set_image_and_gain(self, img_mode, gain_level):
        self.logger.debug("[SIM] set_image_and_gain() stub.")

    def set_image_processing(self, value):
        self.logger.debug("[SIM] set_image_processing() stub.")

    def set_denoise(self, value):
        self.logger.debug("[SIM] set_denoise() stub.")

    def set_resolution(self, resolution):
        self.logger.debug("[SIM] set_resolution() stub.")

    def set_fan_speed(self, speed):
        self.logger.debug("[SIM] set_fan_speed() stub.")

    def get_fan_speed(self):
        return 3  # simulate high speed by default

    def enable_auto_temperature_control(self, enable):
        self.logger.debug(f"[SIM] Auto temperature control {'enabled' if enable else 'disabled'}.")

    def set_target_temperature(self, target_celsius):
        self.logger.info(f"[SIM] Target temperature set to {target_celsius}°C")

    def set_roi(self, roi_tuple):
        self.logger.info(f"[SIM] ROI set to {roi_tuple}")
        self.roi = roi_tuple

    def close_camera(self):
        self.logger.debug("[SIM] close_camera() stub.")

    def open_camera(self):
        self.logger.debug("[SIM] open_camera() stub.")

    def uninit_api(self):
        self.logger.debug("[SIM] uninit_api() stub.")

    @property
    def randomise_laser(self):
        try:
            return not self.interface.microscope.laser_calibrated
        except Exception as e:
            self.logger.debug(f"[SIM] Laser calibration check failed: {e}")
            return True

    def _generate_simulated_laser_signal(self, width=2048, height=148, laser_position=None, wavelength_axis=None, laser_width=5, y_spread=20, peak_height=30000, peak_sigma=0.1):
        wavelength_axis = self.interface.microscope.wavelength_axis
        if laser_position:
            laser_wavelength = laser_position
        elif self.interface.microscope.laser_calibrated:
            laser_wavelength = self.interface.microscope.laser_wavelength_calibrated
        else:
            laser_wavelength = self.interface.microscope.laser_wavelengths.get('l1', 785)

        Y, X = np.meshgrid(np.arange(height), np.arange(width), indexing='ij')

        if laser_wavelength is not None and wavelength_axis is not None:
            index = np.argmin(abs(wavelength_axis - laser_wavelength))
            if index == 0 or index == len(wavelength_axis) - 1:
                self.logger.debug("[SIM] Laser out of range; signal zero.")
                return np.zeros((height, width), dtype=np.float32)
            if self.randomise_laser:
                laser_position = np.random.randint(index - 25, index + 25)
            else:
                laser_position = index
        else:
            laser_position = np.random.randint(0, width)

        laser_signal = np.exp(-0.5 * ((X - laser_position) / laser_width) ** 2) * \
                       np.exp(-0.5 * ((Y - height / 2) / y_spread) ** 2)

        scale = np.abs(np.random.normal(peak_height, peak_height * peak_sigma))
        laser_signal *= scale
        self.logger.debug(f"[SIM] Simulated laser wavelength: {wavelength_axis[laser_position] if wavelength_axis is not None else laser_position} nm")
        return laser_signal

    def _generate_simulated_image(self, width=2048, height=148):
        wavelength_axis = self.interface.microscope.wavelength_axis
        if wavelength_axis is None:
            wavelength_axis = np.arange(width).astype(int)
        background = 4000
        laser_signal = self._generate_simulated_laser_signal(width=width, height=height)
        noise = np.random.randint(-300, 300, laser_signal.shape)
        spectrum_image = background + laser_signal + noise
        spectrum_image = np.clip(spectrum_image, 0, 65535).astype(np.uint16)
        return spectrum_image
