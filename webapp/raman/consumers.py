import json
import asyncio
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from .services.web_service import raman_service

logger = logging.getLogger(__name__)


class RamanConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time communication with the Raman microscope interface.
    Handles live data updates, status monitoring, and bidirectional communication.
    """
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.update_task = None
    
    async def connect(self):
        """Accept WebSocket connection and start periodic updates"""
        try:
            await self.accept()
            logger.info("WebSocket connection established")
            
            # Send connection confirmation
            await self.send(text_data=json.dumps({
                'type': 'connection_established',
                'message': 'WebSocket connected successfully'
            }))
            
            # Start periodic status updates
            self.update_task = asyncio.create_task(self.periodic_updates())
            
            # Send initial status
            await self.send_status_update()
            
        except Exception as e:
            logger.error(f"Error during WebSocket connection: {e}")
            await self.close()
    
    async def disconnect(self, close_code):
        """Clean up when WebSocket disconnects"""
        logger.info(f"WebSocket disconnected with code: {close_code}")
        
        if self.update_task:
            self.update_task.cancel()
    
    async def receive(self, text_data):
        """Handle messages from WebSocket client"""
        try:
            data = json.loads(text_data)
            message_type = data.get('type')
            
            if message_type == 'command':
                await self.handle_command(data.get('command', ''))
            elif message_type == 'request_status':
                await self.send_status_update()
            elif message_type == 'request_scan_parameters':
                await self.send_scan_parameters()
            elif message_type == 'ping':
                await self.send(text_data=json.dumps({'type': 'pong'}))
            else:
                logger.warning(f"Unknown message type: {message_type}")
                
        except json.JSONDecodeError:
            logger.error("Invalid JSON received from WebSocket")
        except Exception as e:
            logger.error(f"Error processing WebSocket message: {e}")
    
    async def handle_command(self, command):
        """Handle command execution"""
        try:
            result = await self.execute_command(command)
            await self.send(text_data=json.dumps({
                'type': 'command_result',
                'command': command,
                'result': result
            }))
        except Exception as e:
            logger.error(f"Error executing command '{command}': {e}")
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': f"Command failed: {e}"
            }))
    
    @database_sync_to_async
    def execute_command(self, command):
        """Execute command through the service layer"""
        return raman_service.send_command(command)
    
    @database_sync_to_async
    def get_instrument_status(self):
        """Get current instrument status"""
        return raman_service.get_instrument_status()
    
    @database_sync_to_async
    def get_scan_parameters(self):
        """Get current scan parameters"""
        return raman_service.get_scan_parameters()
    
    @database_sync_to_async
    def get_scan_status(self):
        """Get current scan status"""
        return raman_service.get_scan_status()
    
    async def send_status_update(self):
        """Send instrument status update to client"""
        try:
            status = await self.get_instrument_status()
            await self.send(text_data=json.dumps({
                'type': 'status_update',
                'status': status
            }))
        except Exception as e:
            logger.error(f"Error sending status update: {e}")
    
    async def send_scan_parameters(self):
        """Send scan parameters to client"""
        try:
            parameters = await self.get_scan_parameters()
            await self.send(text_data=json.dumps({
                'type': 'scan_parameters',
                'parameters': parameters
            }))
        except Exception as e:
            logger.error(f"Error sending scan parameters: {e}")
    
    async def send_scan_progress(self, progress_data):
        """Send scan progress update to client"""
        try:
            await self.send(text_data=json.dumps({
                'type': 'scan_progress',
                'progress': progress_data.get('progress', 0),
                'current_step': progress_data.get('current_step', 0),
                'total_steps': progress_data.get('total_steps', 1),
                'status': progress_data.get('status', 'running')
            }))
        except Exception as e:
            logger.error(f"Error sending scan progress: {e}")
    
    async def send_spectrum_update(self, wavelength_axis, intensity_data):
        """Send live spectrum data to client"""
        try:
            await self.send(text_data=json.dumps({
                'type': 'spectrum_update',
                'wavelength': wavelength_axis.tolist() if hasattr(wavelength_axis, 'tolist') else wavelength_axis,
                'intensity': intensity_data.tolist() if hasattr(intensity_data, 'tolist') else intensity_data
            }))
        except Exception as e:
            logger.error(f"Error sending spectrum update: {e}")
    
    async def send_peak_update(self, wavelength_axis, raw_data, fitted_data=None):
        """Send peak detection data to client"""
        try:
            message = {
                'type': 'peak_update',
                'wavelength': wavelength_axis.tolist() if hasattr(wavelength_axis, 'tolist') else wavelength_axis,
                'raw_data': raw_data.tolist() if hasattr(raw_data, 'tolist') else raw_data
            }
            
            if fitted_data is not None:
                message['fitted_data'] = fitted_data.tolist() if hasattr(fitted_data, 'tolist') else fitted_data
            
            await self.send(text_data=json.dumps(message))
        except Exception as e:
            logger.error(f"Error sending peak update: {e}")
    
    async def send_console_message(self, message):
        """Send console message to client"""
        try:
            await self.send(text_data=json.dumps({
                'type': 'console_message',
                'message': message
            }))
        except Exception as e:
            logger.error(f"Error sending console message: {e}")
    
    async def periodic_updates(self):
        """Periodic task to send status updates"""
        while True:
            try:
                # Send status update every 2 seconds
                await self.send_status_update()
                
                # Check for scan progress updates
                scan_status = await self.get_scan_status()
                if scan_status:
                    await self.send_scan_progress(scan_status)
                
                # Send simulated spectrum data for demonstration
                await self.send_simulated_spectrum()
                
                await asyncio.sleep(2)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in periodic updates: {e}")
                await asyncio.sleep(5)  # Wait longer before retrying
    
    async def send_simulated_spectrum(self):
        """Send simulated spectrum data for demonstration"""
        try:
            import numpy as np
            
            # Generate simulated spectrum data
            wavelength = np.linspace(400, 800, 400)
            # Simple Gaussian peak for demonstration
            center = 532  # Laser wavelength
            width = 50
            intensity = 1000 * np.exp(-((wavelength - center) ** 2) / (2 * width ** 2))
            # Add some noise
            noise = np.random.normal(0, 50, len(intensity))
            intensity += noise
            intensity = np.maximum(intensity, 0)  # Ensure non-negative
            
            await self.send_spectrum_update(wavelength, intensity)
            
            # Also send peak data (subset around the peak)
            peak_range = (center - 100, center + 100)
            peak_mask = (wavelength >= peak_range[0]) & (wavelength <= peak_range[1])
            peak_wavelength = wavelength[peak_mask]
            peak_intensity = intensity[peak_mask]
            
            # Generate fitted peak
            fitted_intensity = 1000 * np.exp(-((peak_wavelength - center) ** 2) / (2 * (width/2) ** 2))
            
            await self.send_peak_update(peak_wavelength, peak_intensity, fitted_intensity)
            
        except ImportError:
            # NumPy not available, skip simulation
            pass
        except Exception as e:
            logger.error(f"Error sending simulated spectrum: {e}")