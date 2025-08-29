"""
Web service layer for interfacing with the existing Raman microscope hardware interface.
This module provides a bridge between Django and the existing Interface class.
"""

import os
import sys
import threading
import json
import logging
from typing import Dict, Any, Optional, List

# Add the services directory to Python path for imports
services_dir = os.path.dirname(__file__)
if services_dir not in sys.path:
    sys.path.insert(0, services_dir)
    
# Also add the parent directory of webapp for any additional imports needed
webapp_parent = os.path.dirname(os.path.dirname(os.path.dirname(services_dir)))
if webapp_parent not in sys.path:
    sys.path.insert(0, webapp_parent)

logger = logging.getLogger(__name__)


class RamanMicroscopeService:
    """
    Service class to manage the Raman microscope interface and provide
    a clean API for Django views and WebSocket consumers.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    def __new__(cls):
        # Singleton pattern to ensure only one interface instance
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return
            
        self.interface = None
        self.current_scan = None
        self._scan_lock = threading.Lock()
        self._initialized = True
        logger.info("RamanMicroscopeService initialized")
    
    def initialize_hardware(self, simulate=True, debug_skip=None):
        """Initialize the hardware interface"""
            
        logger.info(f"Attempting to initialize hardware interface (simulate={simulate})")
        
        try:
            # Import here to avoid circular imports and path issues
            logger.info("Importing Interface class...")
            from interface_run_me import Interface
            logger.info("Interface class imported successfully")
            
            logger.info(f"Creating Interface instance with simulate={simulate}, debug_skip={debug_skip}")
            self.interface = Interface(
                simulate=simulate,
                com_port='COM10',
                debug_skip=debug_skip
            )
            logger.info("Hardware interface initialized successfully")
            return True
            
        except ImportError as e:
            logger.error(f"Failed to import Interface class: {e}")
            logger.error(f"Current sys.path: {sys.path[:3]}...")  # Show first few paths
            logger.error("Make sure the interface_run_me.py file is accessible")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize hardware interface: {e}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return False
    
    def is_hardware_ready(self) -> bool:
        """Check if hardware interface is ready"""
        return self.interface is not None
    
    def get_instrument_status(self) -> Dict[str, Any]:
        """Get current instrument status"""
        if not self.interface:
            return self._get_default_status()
            
        try:
            microscope = self.interface.microscope
            laser = self.interface.laser
            camera = self.interface.camera
            
            status = {
                'laser_status': getattr(microscope, 'laser_status', False),
                'laser_power': getattr(laser, 'current_power', 0.0),
                'laser_wavelength': getattr(microscope, 'report_laser_wavelength', 532.0),
                'laser_calibrated': getattr(microscope, 'laser_calibrated', False),
                
                'camera_temp': getattr(microscope, 'report_camera_temp', 20.0),
                'camera_running': getattr(camera, 'is_running', False),
                
                'grating_wavelength': getattr(microscope, 'report_grating_wavelength', 500.0),
                'monochromator_wavelength': getattr(microscope, 'report_monochromator_wavelength', 500.0),
                'spectrometer_wavelength': getattr(microscope, 'report_spectrometer_wavelength', 500.0),
                'entrance_slit_width': getattr(microscope, 'report_enterance_slit_width', 100.0),
                
                'stage_position': getattr(microscope, 'stage_positions_microns', {'x': 0, 'y': 0, 'z': 0}),
                'microscope_mode': getattr(microscope, 'microscope_mode', 'ramanmode'),
                
                'instrument_ready': getattr(microscope, 'instrument_ready', True),
                'apply_live_calibration': getattr(microscope, 'apply_live_calibration', True),
                'apply_pseudocal': getattr(microscope, 'apply_pseudocal', False),
                'debug_mode': getattr(microscope, 'apply_debug_mode', False),
                
                'scan_running': self.current_scan is not None,
            }
            
            return status
            
        except Exception as e:
            logger.error(f"Error getting instrument status: {e}")
            return self._get_default_status()
    
    def _get_default_status(self) -> Dict[str, Any]:
        """Return default status when hardware is not available"""
        return {
            'laser_status': False,
            'laser_power': 0.0,
            'laser_wavelength': 532.0,
            'laser_calibrated': False,
            'camera_temp': 20.0,
            'camera_running': False,
            'grating_wavelength': 500.0,
            'monochromator_wavelength': 500.0,
            'spectrometer_wavelength': 500.0,
            'entrance_slit_width': 100.0,
            'stage_position': {'x': 0, 'y': 0, 'z': 0},
            'microscope_mode': 'ramanmode',
            'instrument_ready': False,
            'apply_live_calibration': True,
            'apply_pseudocal': False,
            'debug_mode': False,
            'scan_running': False,
        }
    
    def send_command(self, command: str) -> str:
        """Send a command to the instrument interface"""
        logger.info(f"Received command: '{command}'")
        
        if not self.interface:
            logger.warning("Hardware interface not initialized, attempting to initialize...")
            success = self.initialize_hardware(simulate=True, debug_skip=['camera'])
            if not success:
                error_msg = "Hardware interface not initialized and initialization failed. Check server logs for details."
                logger.error(error_msg)
                return error_msg
            
        try:
            logger.info(f"Sending command '{command}' to interface...")
            result = self.interface.process_gui_command(command)
            logger.info(f"Command '{command}' executed, result: {result}")
            return str(result) if result is not None else "Command executed successfully"
        except Exception as e:
            error_msg = f"Error executing command '{command}': {e}"
            logger.error(error_msg)
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            return error_msg
    
    def get_scan_parameters(self) -> Dict[str, Any]:
        """Get current scan parameters from the acquisition control"""
        if not self.interface or not hasattr(self.interface, 'acq_ctrl'):
            return self._get_default_scan_parameters()
            
        try:
            acq_ctrl = self.interface.acq_ctrl
            
            parameters = {
                'scan_mode': acq_ctrl.scan_mode,
                'general_parameters': acq_ctrl.general_parameters,
                'motion_parameters': acq_ctrl.motion_parameters,
                'wavelength_parameters': acq_ctrl.wavelength_parameters,
                'polarization_parameters': acq_ctrl.polarization_parameters,
            }
            
            return parameters
            
        except Exception as e:
            logger.error(f"Error getting scan parameters: {e}")
            return self._get_default_scan_parameters()
    
    def _get_default_scan_parameters(self) -> Dict[str, Any]:
        """Return default scan parameters"""
        return {
            'scan_mode': 'map',
            'general_parameters': {
                'filename': 'scan',
                'acquisition_time': 1.0,
                'n_frames': 1,
                'laser_power': 50.0,
            },
            'motion_parameters': {
                'start_position': {'x': 0, 'y': 0, 'z': 0},
                'end_position': {'x': 100, 'y': 100, 'z': 0},
                'resolution': {'x': 1.0, 'y': 1.0, 'z': 1.0},
            },
            'wavelength_parameters': {
                'start_wavelength': 500.0,
                'end_wavelength': 600.0,
                'resolution': 1.0,
            },
            'polarization_parameters': {
                'input': {'start_angle': 0, 'end_angle': 180, 'resolution': 45},
                'output': {'start_angle': 0, 'end_angle': 180, 'resolution': 45},
            },
        }
    
    def update_parameters(self, parameters: Dict[str, Any]) -> bool:
        """Update scan parameters"""
        if not self.interface or not hasattr(self.interface, 'acq_ctrl'):
            logger.warning("Cannot update parameters: hardware interface not available")
            return False
            
        try:
            acq_ctrl = self.interface.acq_ctrl
            
            # Update parameters based on the provided data
            for section, params in parameters.items():
                if hasattr(acq_ctrl, section):
                    section_obj = getattr(acq_ctrl, section)
                    if isinstance(section_obj, dict):
                        section_obj.update(params)
                    else:
                        # Handle non-dict attributes
                        for key, value in params.items():
                            if hasattr(section_obj, key):
                                setattr(section_obj, key, value)
            
            # Save configuration
            if hasattr(acq_ctrl, 'save_config'):
                acq_ctrl.save_config()
                
            return True
            
        except Exception as e:
            logger.error(f"Error updating parameters: {e}")
            return False
    
    def start_scan(self, parameters: Dict[str, Any], progress_callback=None) -> Optional[int]:
        """Start a scan with the given parameters"""
        if not self.interface:
            logger.error("Cannot start scan: hardware interface not available")
            return None
            
        with self._scan_lock:
            if self.current_scan is not None:
                logger.warning("Cannot start scan: another scan is already running")
                return None
            
            try:
                # Import here to avoid circular imports
                from django.apps import apps
                ScanParameters = apps.get_model('raman', 'ScanParameters')
                ScanResult = apps.get_model('raman', 'ScanResult')
                
                # Create scan result record
                scan_params = ScanParameters.objects.create(
                    scan_mode=parameters.get('scan_mode', 'map'),
                    filename=parameters.get('filename', 'scan'),
                    acquisition_time=parameters.get('acquisition_time', 1.0),
                    n_frames=parameters.get('n_frames', 1),
                    laser_power=parameters.get('laser_power', 50.0),
                    start_position=parameters.get('start_position', {'x': 0, 'y': 0, 'z': 0}),
                    end_position=parameters.get('end_position', {'x': 100, 'y': 100, 'z': 0}),
                    resolution=parameters.get('resolution', {'x': 1.0, 'y': 1.0, 'z': 1.0}),
                    start_wavelength=parameters.get('start_wavelength', 500.0),
                    end_wavelength=parameters.get('end_wavelength', 600.0),
                    wavelength_resolution=parameters.get('wavelength_resolution', 1.0),
                    polarization_input=parameters.get('polarization_input', {}),
                    polarization_output=parameters.get('polarization_output', {}),
                )
                
                scan_result = ScanResult.objects.create(
                    scan_parameters=scan_params,
                    status='running'
                )
                
                self.current_scan = scan_result
                
                # Update hardware parameters
                self.update_parameters(parameters)
                
                # Start scan in background thread
                def run_scan():
                    try:
                        # This would integrate with the existing scan logic
                        # For now, simulate a scan
                        import time
                        for i in range(101):
                            if scan_result.status == 'cancelled':
                                break
                            scan_result.progress = i
                            scan_result.current_step = i
                            scan_result.save()
                            if progress_callback:
                                progress_callback(i)
                            time.sleep(0.1)  # Simulate scan progress
                        
                        if scan_result.status != 'cancelled':
                            scan_result.status = 'completed'
                            scan_result.progress = 100
                            scan_result.save()
                            
                    except Exception as e:
                        logger.error(f"Scan failed: {e}")
                        scan_result.status = 'failed'
                        scan_result.error_message = str(e)
                        scan_result.save()
                    finally:
                        self.current_scan = None
                
                scan_thread = threading.Thread(target=run_scan, daemon=True)
                scan_thread.start()
                
                return scan_result.id
                
            except Exception as e:
                logger.error(f"Error starting scan: {e}")
                self.current_scan = None
                return None
    
    def cancel_scan(self) -> bool:
        """Cancel the currently running scan"""
        with self._scan_lock:
            if self.current_scan is None:
                return False
                
            try:
                self.current_scan.status = 'cancelled'
                self.current_scan.save()
                logger.info("Scan cancelled")
                return True
                
            except Exception as e:
                logger.error(f"Error cancelling scan: {e}")
                return False
    
    def get_scan_status(self) -> Optional[Dict[str, Any]]:
        """Get current scan status"""
        if self.current_scan is None:
            return None
            
        try:
            self.current_scan.refresh_from_db()
            return {
                'scan_id': self.current_scan.id,
                'status': self.current_scan.status,
                'progress': self.current_scan.progress,
                'current_step': self.current_scan.current_step,
                'total_steps': self.current_scan.total_steps,
                'started_at': self.current_scan.started_at.isoformat(),
                'error_message': self.current_scan.error_message,
            }
        except:
            return None


# Global service instance
raman_service = RamanMicroscopeService()