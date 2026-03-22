#!/usr/bin/env bash
set -euo pipefail

cleanup() {
    local exit_code=$?
    trap - EXIT INT TERM

    if [[ -n "${DASH_PID:-}" ]]; then
        kill "$DASH_PID" 2>/dev/null || true
    fi
    if [[ -n "${VLR_PID:-}" ]]; then
        kill "$VLR_PID" 2>/dev/null || true
    fi

    wait "${DASH_PID:-}" "${VLR_PID:-}" 2>/dev/null || true
    exit "$exit_code"
}

trap cleanup EXIT INT TERM

cd /app/vlrggapi
python main.py &
VLR_PID=$!

cd /app/dashboard
python -m uvicorn main:app --host 0.0.0.0 --port 8000 &
DASH_PID=$!

wait -n "$VLR_PID" "$DASH_PID"
