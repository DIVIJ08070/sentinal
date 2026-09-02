#!/usr/bin/env bash
# Start the Sentinel backend (FastAPI/uvicorn on :8000).
# Creates the project venv and installs backend + ingest requirements on first run.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV="$ROOT/.venv"

if [ ! -d "$VENV" ]; then
  echo "[dev-backend] Creating virtualenv at $VENV"
  python3 -m venv "$VENV"
fi

echo "[dev-backend] Installing requirements (backend + ingest)"
"$VENV/bin/pip" install -q -r "$ROOT/backend/requirements.txt" -r "$ROOT/ingest/requirements.txt"

cd "$ROOT/backend"
echo "[dev-backend] Starting uvicorn on http://localhost:8000"
exec "$VENV/bin/uvicorn" app.main:app --port 8000 --reload
