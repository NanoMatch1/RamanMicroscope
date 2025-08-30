#!/usr/bin/env python3
"""
Startup script for the Raman Microscope Web Interface
This script starts the Django server with WebSocket support using Daphne
"""

import os
import sys
import django
from django.core.management import execute_from_command_line

def main():
    """Start the web server with WebSocket support"""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', '_project.settings')
    
    try:
        # Setup Django
        django.setup()
        
        print("🔬 Starting Raman Microscope Web Interface...")
        print("📡 WebSocket support enabled via Daphne ASGI server")
        print("🌐 Server will be available at: http://localhost:8000")
        print("⚡ WebSocket endpoint: ws://localhost:8000/ws/raman/")
        print("🛑 Press Ctrl+C to stop the server\n")
        
        # Start Daphne ASGI server
        from daphne.management.commands.runserver import Command as DaphneCommand
        command = DaphneCommand()
        command.run_from_argv(['manage.py', 'runserver', '0.0.0.0:8000'])
        
    except ImportError as e:
        print(f"❌ Error: {e}")
        print("Make sure all dependencies are installed:")
        print("pip install django channels daphne")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n🛑 Server stopped by user")
    except Exception as e:
        print(f"❌ Server error: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()