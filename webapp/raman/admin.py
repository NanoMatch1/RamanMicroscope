from django.contrib import admin
from .models import ScanParameters, InstrumentState, ScanResult


@admin.register(ScanParameters)
class ScanParametersAdmin(admin.ModelAdmin):
    list_display = ['name', 'scan_mode', 'filename', 'created_at', 'updated_at']
    list_filter = ['scan_mode', 'created_at']
    search_fields = ['name', 'filename']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Info', {
            'fields': ('name', 'scan_mode', 'created_at', 'updated_at')
        }),
        ('General Parameters', {
            'fields': ('filename', 'acquisition_time', 'n_frames', 'laser_power')
        }),
        ('Motion Parameters', {
            'fields': ('start_position', 'end_position', 'resolution')
        }),
        ('Wavelength Parameters', {
            'fields': ('start_wavelength', 'end_wavelength', 'wavelength_resolution')
        }),
        ('Polarization Parameters', {
            'fields': ('polarization_input', 'polarization_output')
        }),
    )


@admin.register(InstrumentState)
class InstrumentStateAdmin(admin.ModelAdmin):
    list_display = ['timestamp', 'laser_status', 'camera_running', 'microscope_mode', 'instrument_ready']
    list_filter = ['laser_status', 'camera_running', 'microscope_mode', 'instrument_ready']
    readonly_fields = ['timestamp']
    
    fieldsets = (
        ('Timestamp', {
            'fields': ('timestamp',)
        }),
        ('Laser State', {
            'fields': ('laser_status', 'laser_power', 'laser_wavelength', 'laser_calibrated')
        }),
        ('Camera State', {
            'fields': ('camera_temp', 'camera_running')
        }),
        ('Spectrometer State', {
            'fields': ('grating_wavelength', 'monochromator_wavelength', 
                      'spectrometer_wavelength', 'entrance_slit_width')
        }),
        ('Position & Mode', {
            'fields': ('stage_position', 'microscope_mode')
        }),
        ('Status Flags', {
            'fields': ('instrument_ready', 'apply_live_calibration', 
                      'apply_pseudocal', 'debug_mode')
        }),
    )


@admin.register(ScanResult)
class ScanResultAdmin(admin.ModelAdmin):
    list_display = ['id', 'status', 'progress', 'started_at', 'completed_at', 'scan_parameters']
    list_filter = ['status', 'started_at']
    readonly_fields = ['started_at', 'duration']
    
    def duration(self, obj):
        return obj.duration
    duration.short_description = 'Duration'
    
    fieldsets = (
        ('Scan Info', {
            'fields': ('scan_parameters', 'status', 'started_at', 'completed_at', 'duration')
        }),
        ('Progress', {
            'fields': ('progress', 'current_step', 'total_steps')
        }),
        ('Data Files', {
            'fields': ('data_file', 'metadata_file')
        }),
        ('Error Info', {
            'fields': ('error_message',)
        }),
    )
