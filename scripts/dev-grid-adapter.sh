#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export GRID_HLS_TEMPLATE="http://localhost:8888/{id}/index.m3u8"
exec "$ROOT/.venv/bin/python" "$ROOT/ingest/grid_adapter.py" --file "$ROOT/ingest/grid_catalogue.json" --port 8890
