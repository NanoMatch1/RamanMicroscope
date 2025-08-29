from django.db import models
from django.contrib.auth.models import User
import json


class ScanParameters(models.Model):
    """Model to store scan configuration parameters"""
    SCAN_MODES = [
        ('map', 'Map'),
        ('linescan', 'Line Scan'),
        ('point', 'Point'),
    ]
    
    name = models.CharField(max_length=100, default='Default Configuration')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Scan mode
    scan_mode = models.CharField(max_length=20, choices=SCAN_MODES, default='map')
    
    # General parameters
    filename = models.CharField(max_length=200, default='scan')
    acquisition_time = models.FloatField(default=1.0)  # seconds
    n_frames = models.IntegerField(default=1)
    laser_power = models.FloatField(default=50.0)  # mW
    
    # Motion parameters (stored as JSON for flexibility)
    start_position = models.JSONField(default=dict)  # {'x': 0, 'y': 0, 'z': 0}
    end_position = models.JSONField(default=dict)    # {'x': 100, 'y': 100, 'z': 0}
    resolution = models.JSONField(default=dict)      # {'x': 1.0, 'y': 1.0, 'z': 1.0}
    
    # Wavelength parameters
    start_wavelength = models.FloatField(default=500.0)  # nm
    end_wavelength = models.FloatField(default=600.0)    # nm
    wavelength_resolution = models.FloatField(default=1.0)  # nm
    
    # Polarization parameters (stored as JSON)
    polarization_input = models.JSONField(default=dict)   # {'start_angle': 0, 'end_angle': 180, 'resolution': 45}
    polarization_output = models.JSONField(default=dict)  # {'start_angle': 0, 'end_angle': 180, 'resolution': 45}
    
    def __str__(self):
        return f"{self.name} ({self.scan_mode}) - {self.created_at.strftime('%Y-%m-%d %H:%M')}"


class InstrumentState(models.Model):
    """Model to track current instrument state"""
    timestamp = models.DateTimeField(auto_now=True)
    
    # Laser state
    laser_status = models.BooleanField(default=False)
    laser_power = models.FloatField(default=0.0)
    laser_wavelength = models.FloatField(default=532.0)
    laser_calibrated = models.BooleanField(default=False)
    
    # Camera state
    camera_temp = models.FloatField(default=20.0)
    camera_running = models.BooleanField(default=False)
    
    # Spectrometer state
    grating_wavelength = models.FloatField(default=500.0)
    monochromator_wavelength = models.FloatField(default=500.0)
    spectrometer_wavelength = models.FloatField(default=500.0)
    entrance_slit_width = models.FloatField(default=100.0)  # um
    
    # Stage position (stored as JSON)
    stage_position = models.JSONField(default=dict)  # {'x': 0, 'y': 0, 'z': 0}
    
    # Microscope mode
    MICROSCOPE_MODES = [
        ('ramanmode', 'Raman Mode'),
        ('imagemode', 'Image Mode'),
    ]
    microscope_mode = models.CharField(max_length=20, choices=MICROSCOPE_MODES, default='ramanmode')
    
    # Status flags
    instrument_ready = models.BooleanField(default=True)
    apply_live_calibration = models.BooleanField(default=True)
    apply_pseudocal = models.BooleanField(default=False)
    debug_mode = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"Instrument State - {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"


class ScanResult(models.Model):
    """Model to store scan results and data"""
    scan_parameters = models.ForeignKey(ScanParameters, on_delete=models.CASCADE)
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    
    STATUS_CHOICES = [
        ('running', 'Running'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
        ('failed', 'Failed'),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='running')
    
    progress = models.IntegerField(default=0)  # 0-100
    current_step = models.IntegerField(default=0)
    total_steps = models.IntegerField(default=1)
    
    # Data file paths
    data_file = models.FileField(upload_to='scan_data/', null=True, blank=True)
    metadata_file = models.FileField(upload_to='scan_metadata/', null=True, blank=True)
    
    # Error information
    error_message = models.TextField(blank=True)
    
    def __str__(self):
        return f"Scan {self.id} - {self.status} ({self.progress}%)"
    
    @property
    def duration(self):
        if self.completed_at and self.started_at:
            return self.completed_at - self.started_at
        return None
