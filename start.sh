#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/venv/bin/python"
VLRAPI_DIR="$HOME/Downloads/vlrggapi"

cleanup() {
    echo ""
    echo "Shutting down..."
    kill $VLR_PID $MOCK_PID $DASH_PID 2>/dev/null
    wait $VLR_PID $MOCK_PID $DASH_PID 2>/dev/null
    echo "All services stopped."
}
trap cleanup INT TERM

echo "=== Starting VLR.gg API (port 3001) ==="
cd "$VLRAPI_DIR"
"$VENV" main.py &
VLR_PID=$!
sleep 1

echo "=== Starting Mock AWTRIX (port 7777) ==="
cd "$SCRIPT_DIR"
"$VENV" -m uvicorn mock_awtrix:app --host 0.0.0.0 --port 7777 &
MOCK_PID=$!
sleep 1

echo "=== Starting Dashboard (port 8000) ==="
"$VENV" -m uvicorn main:app --host 0.0.0.0 --port 8000 &
DASH_PID=$!

echo ""
echo "All services running:"
echo "  VLR API:    http://localhost:3001  (PID $VLR_PID)"
echo "  Mock AWTRIX: http://localhost:7777  (PID $MOCK_PID)"
echo "  Dashboard:   http://localhost:8000  (PID $DASH_PID)"
echo ""
echo "Press Ctrl+C to stop all."

wait
