#!/bin/bash
# Start script for Production
# - Uses 'uv' to run which handles the venv
# - Host 0.0.0.0 for external access
# - Port 8000
# - 1 Worker (optimized for t2.micro low resources)
# - No reload for stability

echo "Starting Travel Agent in PRODUCTION mode..."
echo "Workers: 1 (t2 optimized)"

uv run uvicorn fast_api_server:app --host 0.0.0.0 --port 8000 --workers 1
