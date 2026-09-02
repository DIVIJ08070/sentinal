#!/usr/bin/env bash
# Start the Sentinel frontend (Vite dev server on :5173, proxying /api and /ws to :8000).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$ROOT/frontend"

if [ ! -d node_modules ]; then
  echo "[dev-frontend] node_modules missing — running npm install"
  npm install
fi

echo "[dev-frontend] Starting Vite on http://localhost:5173"
exec npm run dev
