2025-06-10 16:26:10,290 interface.TucsenCamera [ERROR] Acquisition error: [Errno 22] Invalid argument: 'C:\\Users\\Raman\\matchbook\\RamanMicroscope\\data\\transient_data\\transient_data.npy'
2025-06-10 16:26:10,292 interface.TucsenCamera [ERROR] Traceback (most recent call last):
  File "c:\Users\Raman\matchbook\RamanMicroscope\instruments\cameras\tucsencam.py", line 413, in continuous_task
    self.save_transient_spectrum_cb(data, wavelengths)
  File "c:\Users\Raman\matchbook\RamanMicroscope\acquisitioncontrol\acqcontrol.py", line 797, in save_spectrum_transient
    np.save(save_path, image_data) # TODO: remove once integrated data viewer is complete
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\Raman\AppData\Local\Programs\Python\Python311\Lib\site-packages\numpy\lib\npyio.py", line 542, in save
    file_ctx = open(file, "wb")
               ^^^^^^^^^^^^^^^^
OSError: [Errno 22] Invalid argument: 'C:\\Users\\Raman\\matchbook\\RamanMicroscope\\data\\transient_data\\transient_data.npy'

2025-06-11 20:41:35,093 interface [ERROR] Failed to save instrument state: not enough values to unpack (expected 2, got 1)
2025-06-11 20:42:00,722 interface [ERROR] Failed to save instrument state: list index out of range
2025-06-12 13:39:37,414 interface.camera_scanner [ERROR] Unexpected error during scan: Traceback (most recent call last):
  File "c:\Users\Raman\matchbook\RamanMicroscope\acquisitioncontrol\acqcontrol.py", line 179, in _acquire_scan
    self.camera.open_stream()
  File "c:\Users\Raman\matchbook\RamanMicroscope\instruments\cameras\tucsencam.py", line 309, in open_stream
    TUCAM_Buf_Alloc(self.TUCAMOPEN.hIdxTUCam, pointer(self.tucam_data.m_frame))
  File "C:\Users\Raman\AppData\Local\Programs\Python\Python311\Lib\enum.py", line 711, in __call__
    return cls.__new__(cls, value)
           ^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\Raman\AppData\Local\Programs\Python\Python311\Lib\enum.py", line 1128, in __new__
    raise ve_exc
ValueError: -2147483132 is not a valid TUCAMRET

2025-06-20 12:28:39,843 interface.camera_scanner [ERROR] Unexpected error during scan: Traceback (most recent call last):
  File "c:\Users\Raman\matchbook\RamanMicroscope\acquisitioncontrol\acqcontrol.py", line 192, in _acquire_scan
    success, image_data = self._execute_step(step, timeout)
                          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "c:\Users\Raman\matchbook\RamanMicroscope\acquisitioncontrol\acqcontrol.py", line 234, in _execute_step
    command(change)
  File "c:\Users\Raman\matchbook\RamanMicroscope\acquisitioncontrol\acqcontrol.py", line 692, in move_stage_absolute
    self.interface.microscope.motion_control.move_motors(motor_dict, backlash=False)
  File "c:\Users\Raman\matchbook\RamanMicroscope\instruments_old.py", line 384, in move_motors
    self.wait_for_motors(list(motor_id_steps.keys()))
  File "c:\Users\Raman\matchbook\RamanMicroscope\instruments_old.py", line 157, in wait_for_motors
    status = self.extract_motor_status(response)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "c:\Users\Raman\matchbook\RamanMicroscope\instruments_old.py", line 197, in extract_motor_status
    raise ValueError(f"Failed to parse motor status: {', '.join(errors)}")
ValueError: Failed to parse motor status: Invalid motor status value: -4805 for motor 1X, Invalid motor status value: 185 for motor 1Y, Invalid motor status value: -2258 for motor 1Z, Invalid motor status value: 114 for motor 3Z, Invalid motor status value: -113 for motor 3A, Invalid motor status value: -28 for motor 3X, Invalid motor status value: 29 for motor 3Y, Invalid motor status value: 12023 for motor 4X, Invalid motor status value: 152225 for motor 4Y, Invalid motor status value: 7064 for motor 2X, Invalid motor status value: -5896 for motor 2Y, Invalid motor status value: -1280 for motor 2Z, Invalid motor status value: -50000 for motor 2A

2025-06-24 16:22:22,831 interface [ERROR] Failed to save instrument state: invalid literal for int() with base 10: 'true'
2025-06-24 16:23:04,181 interface.camera_scanner [ERROR] Unexpected error during scan: Traceback (most recent call last):
  File "c:\Users\Raman\matchbook\RamanMicroscope\acquisitioncontrol\acqcontrol.py", line 192, in _acquire_scan
    success, image_data = self._execute_step(step, timeout)
                          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "c:\Users\Raman\matchbook\RamanMicroscope\acquisitioncontrol\acqcontrol.py", line 234, in _execute_step
    command(change)
  File "c:\Users\Raman\matchbook\RamanMicroscope\instruments_old.py", line 1706, in go_to_wavelength_all
    self.go_to_laser_wavelength(wavelength)
  File "c:\Users\Raman\matchbook\RamanMicroscope\instruments_old.py", line 2009, in go_to_laser_wavelength
    self.go_to_laser_steps(target_positions)
  File "c:\Users\Raman\matchbook\RamanMicroscope\instruments_old.py", line 1397, in go_to_laser_steps
    self.motion_control.move_motors(motor_steps)
  File "c:\Users\Raman\matchbook\RamanMicroscope\instruments_old.py", line 384, in move_motors
    self.wait_for_motors(list(motor_id_steps.keys()))
  File "c:\Users\Raman\matchbook\RamanMicroscope\instruments_old.py", line 157, in wait_for_motors
    status = self.extract_motor_status(response)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "c:\Users\Raman\matchbook\RamanMicroscope\instruments_old.py", line 197, in extract_motor_status
    raise ValueError(f"Failed to parse motor status: {', '.join(errors)}")
ValueError: Failed to parse motor status: Invalid motor status format: Moving, Invalid motor status format: motor, Invalid motor status format: 4X-3000

2025-06-24 16:23:06,580 interface [ERROR] Failed to save instrument state: invalid literal for int() with base 10: 'true'
2025-06-24 16:23:30,082 interface.camera_scanner [ERROR] Unexpected error during scan: Traceback (most recent call last):
  File "c:\Users\Raman\matchbook\RamanMicroscope\acquisitioncontrol\acqcontrol.py", line 192, in _acquire_scan
    success, image_data = self._execute_step(step, timeout)
                          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "c:\Users\Raman\matchbook\RamanMicroscope\acquisitioncontrol\acqcontrol.py", line 234, in _execute_step
    command(change)
  File "c:\Users\Raman\matchbook\RamanMicroscope\instruments_old.py", line 1127, in go_to_polarization_in
    self.motion_control.move_motors({'p_in': angle})
  File "c:\Users\Raman\matchbook\RamanMicroscope\instruments_old.py", line 388, in move_motors
    self.wait_for_motors(list(motor_id_steps.keys()))
  File "c:\Users\Raman\matchbook\RamanMicroscope\instruments_old.py", line 157, in wait_for_motors
    status = self.extract_motor_status(response)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "c:\Users\Raman\matchbook\RamanMicroscope\instruments_old.py", line 197, in extract_motor_status
    raise ValueError(f"Failed to parse motor status: {', '.join(errors)}")
ValueError: Failed to parse motor status: Invalid motor status format: Moving, Invalid motor status format: motor, Invalid motor status format: 4X-3000

2025-06-26 23:44:03,833 interface [ERROR] Failed to save instrument state: not enough values to unpack (expected 2, got 1)
2025-06-26 23:44:05,291 interface [ERROR] Failed to save instrument state: list index out of range
2025-06-26 23:44:07,655 interface [ERROR] Failed to save instrument state: list index out of range
2025-06-26 23:44:17,370 interface [ERROR] Failed to save instrument state: not enough values to unpack (expected 2, got 1)
2025-06-30 02:50:29,371 interface.camera_scanner [ERROR] Unexpected error during scan: Traceback (most recent call last):
  File "C:\Users\Raman\matchbook\RamanMicroscope\acquisitioncontrol\acqcontrol.py", line 205, in _acquire_scan
    success, image_data = self._execute_step(step, timeout)
                          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\Raman\matchbook\RamanMicroscope\instruments\util_decorators.py", line 27, in wrapper
    raise AttributeError(f"{self.__class__.__name__} does not have 'interface.heartbeat', check if the interface is initialised correctly.")
AttributeError: CameraScanner does not have 'interface.heartbeat', check if the interface is initialised correctly.

2025-06-30 13:12:49,758 interface [ERROR] Failed to save instrument state: invalid literal for int() with base 10: '02A-00\r#CF'
2025-07-08 14:41:49,756 interface.camera_scanner [ERROR] Unexpected error during scan: Traceback (most recent call last):
  File "C:\Users\Raman\matchbook\RamanMicroscope\acquisitioncontrol\acqcontrol.py", line 193, in _acquire_scan
    self.camera.open_stream()
  File "C:\Users\Raman\matchbook\RamanMicroscope\instruments\cameras\tucsencam.py", line 316, in open_stream
    TUCAM_Buf_Alloc(self.TUCAMOPEN.hIdxTUCam, pointer(self.tucam_data.m_frame))
  File "C:\Users\Raman\AppData\Local\Programs\Python\Python311\Lib\enum.py", line 711, in __call__
    return cls.__new__(cls, value)
           ^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\Raman\AppData\Local\Programs\Python\Python311\Lib\enum.py", line 1128, in __new__
    raise ve_exc
ValueError: -2147483132 is not a valid TUCAMRET

2025-07-08 15:07:36,569 interface.camera_scanner [ERROR] Unexpected error during scan: Traceback (most recent call last):
  File "C:\Users\Raman\matchbook\RamanMicroscope\acquisitioncontrol\acqcontrol.py", line 193, in _acquire_scan
    self.camera.open_stream()
  File "C:\Users\Raman\matchbook\RamanMicroscope\instruments\cameras\tucsencam.py", line 316, in open_stream
    TUCAM_Buf_Alloc(self.TUCAMOPEN.hIdxTUCam, pointer(self.tucam_data.m_frame))
  File "C:\Users\Raman\AppData\Local\Programs\Python\Python311\Lib\enum.py", line 711, in __call__
    return cls.__new__(cls, value)
           ^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\Raman\AppData\Local\Programs\Python\Python311\Lib\enum.py", line 1128, in __new__
    raise ve_exc
ValueError: -2147483132 is not a valid TUCAMRET

2025-07-14 08:06:10,412 interface [ERROR] Invalid logging level: cmd
2025-07-14 17:11:29,783 interface.camera_scanner [ERROR] Unexpected error during scan: Traceback (most recent call last):
  File "C:\Users\Raman\matchbook\RamanMicroscope\acquisitioncontrol\acqcontrol.py", line 193, in _acquire_scan
    self.camera.open_stream()
  File "C:\Users\Raman\matchbook\RamanMicroscope\instruments\cameras\tucsencam.py", line 316, in open_stream
    TUCAM_Buf_Alloc(self.TUCAMOPEN.hIdxTUCam, pointer(self.tucam_data.m_frame))
  File "C:\Users\Raman\AppData\Local\Programs\Python\Python311\Lib\enum.py", line 711, in __call__
    return cls.__new__(cls, value)
           ^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\Raman\AppData\Local\Programs\Python\Python311\Lib\enum.py", line 1128, in __new__
    raise ve_exc
ValueError: -2147483132 is not a valid TUCAMRET

2025-07-15 15:07:19,605 interface.camera_scanner [ERROR] Unexpected error during scan: Traceback (most recent call last):
  File "C:\Users\Raman\matchbook\RamanMicroscope\acquisitioncontrol\acqcontrol.py", line 193, in _acquire_scan
    self.camera.open_stream()
  File "C:\Users\Raman\matchbook\RamanMicroscope\instruments\cameras\tucsencam.py", line 317, in open_stream
    TUCAM_Buf_Alloc(self.TUCAMOPEN.hIdxTUCam, pointer(self.tucam_data.m_frame))
  File "C:\Users\Raman\AppData\Local\Programs\Python\Python311\Lib\enum.py", line 711, in __call__
    return cls.__new__(cls, value)
           ^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\Raman\AppData\Local\Programs\Python\Python311\Lib\enum.py", line 1128, in __new__
    raise ve_exc
ValueError: -2147483132 is not a valid TUCAMRET

2025-07-21 05:19:33,114 interface [ERROR] An error occurred: 'NoneType' object is not subscriptable
2025-07-21 05:19:33,114 interface [ERROR] Traceback (most recent call last):
  File "C:\Users\Raman\matchbook\RamanMicroscope\interface_run_me.py", line 149, in cli
    self.gui()
  File "C:\Users\Raman\matchbook\RamanMicroscope\interface_run_me.py", line 185, in gui
    window = MainWindow(self.acq_ctrl, self)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\Raman\matchbook\RamanMicroscope\acquisitioncontrol\pyqtGUI.py", line 330, in __init__
    self.init_ui()
  File "C:\Users\Raman\matchbook\RamanMicroscope\acquisitioncontrol\pyqtGUI.py", line 883, in init_ui
    self.lbl_est = QLabel(self.get_estimated_time())
                          ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\Raman\matchbook\RamanMicroscope\acquisitioncontrol\pyqtGUI.py", line 980, in get_estimated_time
    return f"{scan_duration['duration']} {scan_duration['units']}"
              ~~~~~~~~~~~~~^^^^^^^^^^^^
TypeError: 'NoneType' object is not subscriptable

2025-07-21 05:24:18,279 interface [ERROR] An error occurred: 'NoneType' object is not subscriptable
2025-07-21 05:24:18,289 interface [ERROR] Traceback (most recent call last):
  File "C:\Users\Raman\matchbook\RamanMicroscope\interface_run_me.py", line 149, in cli
    self.gui()
  File "C:\Users\Raman\matchbook\RamanMicroscope\interface_run_me.py", line 185, in gui
    window = MainWindow(self.acq_ctrl, self)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\Raman\matchbook\RamanMicroscope\acquisitioncontrol\pyqtGUI.py", line 330, in __init__
    self.init_ui()
  File "C:\Users\Raman\matchbook\RamanMicroscope\acquisitioncontrol\pyqtGUI.py", line 883, in init_ui
    self.lbl_est = QLabel(self.get_estimated_time())
                          ^^^^^^^^^^^^^^^^^^^^^^^^^
  File "C:\Users\Raman\matchbook\RamanMicroscope\acquisitioncontrol\pyqtGUI.py", line 980, in get_estimated_time
    return f"{scan_duration['duration']} {scan_duration['units']}"
              ~~~~~~~~~~~~~^^^^^^^^^^^^
TypeError: 'NoneType' object is not subscriptable

2025-07-22 01:24:05,628 interface [ERROR] Failed to save instrument state: Write timeout
