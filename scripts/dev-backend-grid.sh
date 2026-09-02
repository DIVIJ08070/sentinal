#!/usr/bin/env bash
# Backend wired to the REAL sandbox grid via the local catalogue adapter (:8891).
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SENTINEL_HOST="${SENTINEL_HOST:-http://localhost:8891}"
exec "$SCRIPT_DIR/dev-backend.sh"
