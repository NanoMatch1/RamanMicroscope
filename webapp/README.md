# Raman Microscope Web Interface

A modern web-based interface for controlling the Raman microscope, built with Django and WebSocket support for real-time data streaming.

## Features

- **Real-time Control**: Live instrument status updates and parameter monitoring
- **Web-based Dashboard**: Modern Bootstrap interface accessible from any browser
- **Live Data Visualization**: Real-time spectrum and peak detection plotting
- **Remote Access**: Control the microscope from anywhere on the network
- **Parameter Management**: Intuitive tabbed interface for scan configuration
- **Command Console**: CLI-style command execution with history

## Quick Start

### 1. Install Dependencies
```bash
pip install django channels daphne
```

### 2. Database Setup
```bash
python3 manage.py migrate
```

### 3. Start the Web Interface

**Option A: Using the startup script (recommended)**
```bash
./run_with_websockets.sh
```

**Option B: Using Daphne directly**
```bash
daphne -b 0.0.0.0 -p 8000 _project.asgi:application
```

**Option C: Using Python script**
```bash
python3 start_server.py
```

### 4. Access the Interface
Open your web browser and navigate to:
- **Dashboard**: http://localhost:8000
- **Admin Interface**: http://localhost:8000/admin (after creating superuser)

## WebSocket Endpoints

The interface uses WebSockets for real-time communication:
- **Main WebSocket**: ws://localhost:8000/ws/raman/

## Creating Admin User (Optional)

To access the Django admin interface:
```bash
python3 manage.py createsuperuser
```

## Troubleshooting

### WebSocket Connection Issues
If you see WebSocket errors in the browser console:

1. **Ensure you're using Daphne**: The standard Django `runserver` doesn't support WebSockets
2. **Check the startup method**: Use one of the methods above that includes WebSocket support
3. **Verify the port**: Make sure port 8000 is available and not blocked by firewall

### Hardware Interface Issues
- The web interface initializes in simulation mode by default
- To connect to real hardware, modify the `simulate=True` parameter in the service layer
- Check the console output for hardware connection status

## Architecture

- **Django Framework**: Web application framework
- **Django Channels**: WebSocket support for real-time communication  
- **Daphne ASGI Server**: Handles both HTTP and WebSocket protocols
- **Bootstrap UI**: Responsive web interface
- **Chart.js**: Live data visualization
- **SQLite Database**: Stores scan parameters and results

## Development

### Running in Development Mode
The interface is configured for development use. For production deployment:
1. Update `DEBUG = False` in settings
2. Configure proper database (PostgreSQL recommended)
3. Set up proper static file serving
4. Use a production ASGI server like Gunicorn with Uvicorn workers

### Adding New Features
- **Views**: Add new API endpoints in `raman/views.py`
- **Models**: Define new data structures in `raman/models.py`
- **WebSocket**: Extend real-time functionality in `raman/consumers.py`
- **Frontend**: Modify the dashboard template in `raman/templates/raman/dashboard.html`

## Support

For issues or questions about the web interface, check:
1. Browser console for JavaScript errors
2. Django server console for backend errors
3. WebSocket connection status in the interface console