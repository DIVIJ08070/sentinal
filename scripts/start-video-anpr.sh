#!/usr/bin/env bash
# Starts the Live Video ANPR Studio backend engine
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export BACKEND_URL="${BACKEND_URL:-http://localhost:8001}"
export VIDEO_ANPR_PORT="${VIDEO_ANPR_PORT:-8895}"

echo "Starting Sentinel Live Video ANPR Engine on port $VIDEO_ANPR_PORT (Backend: $BACKEND_URL)..."
"$ROOT/.venv/bin/python" "$ROOT/ingest/video_anpr_engine.py"
