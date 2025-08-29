#!/bin/bash

# Raman Microscope Web Interface Startup Script
# This script starts the Django server with WebSocket support

echo "🔬 Starting Raman Microscope Web Interface..."
echo "📡 WebSocket support enabled via Daphne ASGI server"
echo "🌐 Server will be available at: http://localhost:8000"
echo "⚡ WebSocket endpoint: ws://localhost:8000/ws/raman/"
echo "🛑 Press Ctrl+C to stop the server"
echo ""

# Start the ASGI server with Daphne
daphne -b 0.0.0.0 -p 8000 _project.asgi:application