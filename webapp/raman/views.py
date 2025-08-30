from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
import json
import logging
from .services.web_service import raman_service
from .models import ScanParameters, InstrumentState

logger = logging.getLogger(__name__)


def dashboard(request):
    """Main dashboard view"""
    # Initialize hardware if not already done
    initialization_status = "Unknown"
    if not raman_service.is_hardware_ready():
        # Try to initialize in simulation mode for web interface
        logger.info("Hardware not ready, attempting initialization...")
        success = raman_service.initialize_hardware(simulate=True, debug_skip=['camera'])
        initialization_status = "Success" if success else "Failed"
        logger.info(f"Hardware initialization result: {initialization_status}")
    else:
        initialization_status = "Already Ready"
        logger.info("Hardware interface already ready")
    
    context = {
        'title': 'Raman Microscope Control',
        'hardware_status': initialization_status,
        'hardware_ready': raman_service.is_hardware_ready(),
    }
    return render(request, 'raman/dashboard.html', context)


@require_http_methods(["GET"])
def instrument_status(request):
    """API endpoint to get current instrument status"""
    try:
        status = raman_service.get_instrument_status()
        return JsonResponse(status)
    except Exception as e:
        logger.error(f"Error getting instrument status: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["GET"])
def scan_parameters(request):
    """API endpoint to get current scan parameters"""
    try:
        parameters = raman_service.get_scan_parameters()
        return JsonResponse(parameters)
    except Exception as e:
        logger.error(f"Error getting scan parameters: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def update_parameters(request):
    """API endpoint to update scan parameters"""
    try:
        data = json.loads(request.body)
        success = raman_service.update_parameters(data)
        return JsonResponse({'success': success})
    except Exception as e:
        logger.error(f"Error updating parameters: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def send_command(request):
    """API endpoint to send commands to the instrument"""
    try:
        data = json.loads(request.body)
        command = data.get('command', '')
        
        if not command:
            return JsonResponse({'error': 'No command provided'}, status=400)
        
        result = raman_service.send_command(command)
        return JsonResponse({'result': result})
        
    except Exception as e:
        logger.error(f"Error sending command: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def start_scan(request):
    """API endpoint to start a scan"""
    try:
        data = json.loads(request.body)
        
        # Extract parameters from request
        parameters = {
            'scan_mode': data.get('scan_mode', 'map'),
            'filename': data.get('filename', 'scan'),
            'acquisition_time': float(data.get('acquisition_time', 1.0)),
            'n_frames': int(data.get('n_frames', 1)),
            'laser_power': float(data.get('laser_power', 50.0)),
            'start_position': data.get('start_position', {'x': 0, 'y': 0, 'z': 0}),
            'end_position': data.get('end_position', {'x': 100, 'y': 100, 'z': 0}),
            'resolution': data.get('resolution', {'x': 1.0, 'y': 1.0, 'z': 1.0}),
            'start_wavelength': float(data.get('start_wavelength', 500.0)),
            'end_wavelength': float(data.get('end_wavelength', 600.0)),
            'wavelength_resolution': float(data.get('wavelength_resolution', 1.0)),
            'polarization_input': data.get('polarization_input', {}),
            'polarization_output': data.get('polarization_output', {}),
        }
        
        scan_id = raman_service.start_scan(parameters)
        
        if scan_id is not None:
            return JsonResponse({'success': True, 'scan_id': scan_id})
        else:
            return JsonResponse({'success': False, 'error': 'Failed to start scan'})
            
    except Exception as e:
        logger.error(f"Error starting scan: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def cancel_scan(request):
    """API endpoint to cancel the current scan"""
    try:
        success = raman_service.cancel_scan()
        return JsonResponse({'success': success})
    except Exception as e:
        logger.error(f"Error cancelling scan: {e}")
        return JsonResponse({'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def initialize_hardware(request):
    """API endpoint to manually initialize hardware"""
    try:
        data = json.loads(request.body) if request.body else {}
        simulate = data.get('simulate', True)
        debug_skip = data.get('debug_skip', ['camera'])
        
        logger.info(f"Manual hardware initialization requested: simulate={simulate}")
        success = raman_service.initialize_hardware(simulate=simulate, debug_skip=debug_skip)
        
        return JsonResponse({
            'success': success,
            'hardware_ready': raman_service.is_hardware_ready(),
            'message': 'Hardware initialized successfully' if success else 'Hardware initialization failed'
        })
    except Exception as e:
        logger.error(f"Error during manual hardware initialization: {e}")
        return JsonResponse({'error': str(e)}, status=500)
