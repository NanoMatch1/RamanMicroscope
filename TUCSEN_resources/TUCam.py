# TUCSEN camera Python wrapper
# Place DLL in lib/x64/TUCam.dll
import os
from ctypes import *
from enum import Enum

# DLL loading
dirname = os.path.dirname(__file__)
libpath = os.path.join(dirname, "lib", "x64", "TUCam.dll")
TUSDKdll = OleDLL(libpath)

# Enums
class TUCSEN_ERROR_CODE(Enum):
    SUCCESS = 0
    FAILURE = -1
    # ... other error codes

class TUCSEN_CAMERA_STATE(Enum):
    IDLE = 0
    CAPTURING = 1
    # ... other states

# Structs
class TUCSEN_CAMERA_INFO(Structure):
    _fields_ = [
        ("CameraID", c_int),
        ("CameraName", c_char * 256),
        # ... other fields
    ]

# API Functions
TUSDKdll.TUCSEN_Initialize.argtypes = []
TUSDKdll.TUCSEN_Initialize.restype = TUCSEN_ERROR_CODE

TUSDKdll.TUCSEN_GetCameraCount.argtypes = []
TUSDKdll.TUCSEN_GetCameraCount.restype = c_int

TUSDKdll.TUCSEN_GetCameraInfo.argtypes = [c_int, POINTER(TUCSEN_CAMERA_INFO)]
TUSDKdll.TUCSEN_GetCameraInfo.restype = TUCSEN_ERROR_CODE

# ... other function definitions ...
