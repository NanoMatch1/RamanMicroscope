import os
import numpy as np
import json
from typing import Dict, Any, Optional, Union, List, Tuple
import inspect

from calibration import PolySinModulation, LinSinModulation

class CalibrationService:
    """
    A service class responsible for loading, managing, and providing calibration functions
    for all instruments in the Raman microscope system.
    
    This service centralizes calibration logic that was previously spread across multiple classes.
    """

    def __init__(self, script_dir: str):
        """
        Initialize the calibration service.
        
        Args:
            script_dir: Path to the script directory where calibration files are stored
        """
        self.script_dir = script_dir
        self.calibration_dir = os.path.join(script_dir, 'calibrations')
        self.all_calibrations = {}
        self._load_calibrations()
        self._generate_calibrations()
        
    def _load_calibrations(self) -> Dict[str, Any]:
        """
        Load the calibration data from the calibrations_main.json file.
        
        Returns:
            Dictionary containing calibration parameters
        """
        try:
            with open(os.path.join(self.calibration_dir, 'calibrations_main.json'), 'r') as f:
                calibrations = json.load(f)
                print('Calibrations loaded from file')
            return calibrations
        except Exception as e:
            print(f"Error loading calibrations: {e}")
            return {}
    
    def _generate_calibrations(self) -> None:
        """
        Generate calibration functions from the loaded calibration data.
        Creates callable objects for each calibration type.
        """
        self.all_calibrations = self._load_calibrations()
        
        for name, calib in self.all_calibrations.items():
            if len(calib) == 7:
                print(f"Loading {name} as poly_sin")
                self.__setattr__(name, PolySinModulation(*calib))
            elif len(calib) == 6:
                print(f"Loading {name} as lin_sin")
                self.__setattr__(name, LinSinModulation(*calib))
            else:
                print(f"Loading {name} as poly1d")
                self.__setattr__(name, np.poly1d(calib))
        
        print("Calibrations successfully built.")
    
    def update_calibrations(self, report: bool = True) -> None:
        """
        Update calibrations with new auto-calibration data.
        
        Args:
            report: Whether to print a report of updated calibrations
        """
        json_files = [f for f in os.listdir(self.calibration_dir) 
                     if f.endswith('autocal.json')]
        
        if len(json_files) == 0:
            print('No autocalibration data found.')
            return
        
        report_dict = {}
        
        for file in json_files:
            with open(os.path.join(self.calibration_dir, file), 'r') as f:
                data = json.load(f)
            
            for name, calib in data.items():
                if len(calib) == 7:
                    report_dict[name] = 'poly_sin'
                    self.all_calibrations[name] = calib
                    self.__setattr__(name, PolySinModulation(*calib))
                elif len(calib) == 6:
                    report_dict[name] = 'lin_sin'
                    self.all_calibrations[name] = calib
                    self.__setattr__(name, LinSinModulation(*calib))
                else:
                    report_dict[name] = 'poly1d'
                    self.all_calibrations[name] = calib
                    self.__setattr__(name, np.poly1d(calib))
        
        if report:
            for key, value in report_dict.items():
                print(f'{key} updated as {value}')
        print('Calibrations updated with autocalibration data')
        print('-'*20)
    
    def save_calibrations(self, calibrations: Dict[str, Any], filename: str) -> None:
        """
        Save calibration data to a file.
        
        Args:
            calibrations: Dictionary of calibration parameters to save
            filename: Name of the file to save to
        """
        filepath = os.path.join(self.calibration_dir, filename)
        with open(filepath, 'w') as f:
            json.dump(calibrations, f, indent=2)
        print(f'Calibrations saved to {filepath}')
    
    def get_calibration_function(self, name: str):
        """
        Get a specific calibration function by name.
        
        Args:
            name: Name of the calibration function
            
        Returns:
            The calibration function if found, None otherwise
        """
        return getattr(self, name, None)
    
    def list_available_calibrations(self) -> List[str]:
        """
        List all available calibration functions.
        
        Returns:
            List of calibration function names
        """
        return [name for name in dir(self) 
                if not name.startswith('_') and 
                not inspect.ismethod(getattr(self, name))]
    
    # Wavelength conversion helpers
    def wavenumber_to_wavelength(self, wavenumber: float) -> float:
        """Convert from wavenumber to wavelength"""
        return 10_000_000/wavenumber
    
    def wavelength_to_wavenumber(self, wavelength: float) -> float:
        """Convert from wavelength to wavenumber"""
        return 10_000_000/wavelength
    
    def calculate_raman_shift(self, laser_wavelength: float, 
                             detector_wavelength: float) -> float:
        """
        Calculate the Raman shift given laser and detector wavelengths.
        
        Args:
            laser_wavelength: Excitation wavelength in nm
            detector_wavelength: Detection wavelength in nm
            
        Returns:
            Raman shift in wavenumbers (cm^-1)
        """
        laser_wavenumber = self.wavelength_to_wavenumber(laser_wavelength)
        detector_wavenumber = self.wavelength_to_wavenumber(detector_wavelength)
        return laser_wavenumber - detector_wavenumber
    
    def calculate_detection_wavelength(self, laser_wavelength: float, 
                                      raman_shift: float) -> float:
        """
        Calculate the detection wavelength needed for a given Raman shift.
        
        Args:
            laser_wavelength: Excitation wavelength in nm
            raman_shift: Desired Raman shift in wavenumbers (cm^-1)
            
        Returns:
            Required detection wavelength in nm
        """
        laser_wavenumber = self.wavelength_to_wavenumber(laser_wavelength)
        detector_wavenumber = laser_wavenumber - raman_shift
        return self.wavenumber_to_wavelength(detector_wavenumber)