#!/usr/bin/env bash
# Scripted end-to-end demo (contract "Demo flow", steps 1-5; step 6 is the browser).
#
# Prerequisite: the backend must already be running on :8000
#   (terminal 1: ./scripts/dev-backend.sh   or   make backend)
#
# This script then:
#   1. starts ingest/mock_gateway.py on :8890 in the background (reused if already up)
#   2. waits until the gateway answers
#   3. POST /api/cameras/sync            (backend pulls the camera catalogue)
#   4. python -m app.seed                (idempotent watchlist seed, incl. GJ01AB1234)
#   5. python ingest/simulator.py        (replays a scripted vehicle journey)
# and finally prints what to do in the UI.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VENV="$ROOT/.venv"
PY="$VENV/bin/python"

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
GATEWAY_URL="http://localhost:8890"
DEMO_PLATE="GJ01AB1234"

if [ ! -x "$PY" ]; then
  echo "[demo] ERROR: $VENV not found. Run ./scripts/dev-backend.sh once first (it creates the venv)." >&2
  exit 1
fi

if ! curl -sf -o /dev/null "$BACKEND_URL/api/stats"; then
  echo "[demo] ERROR: backend not reachable at $BACKEND_URL." >&2
  echo "[demo] Start it in another terminal first: ./scripts/dev-backend.sh" >&2
  exit 1
fi

# 1. Mock gateway on :8890 (skip if something already serves the catalogue there).
if curl -sf -o /dev/null "$GATEWAY_URL/api/ingest"; then
  echo "[demo] Mock gateway already running on :8890 — reusing it"
else
  echo "[demo] Starting mock gateway on :8890 (background)"
  "$PY" "$ROOT/ingest/mock_gateway.py" >"$ROOT/.mock_gateway.log" 2>&1 &
  GATEWAY_PID=$!
  echo "[demo] mock_gateway PID $GATEWAY_PID (log: .mock_gateway.log)"

  # 2. Wait for the gateway to come up (max ~15 s).
  for i in $(seq 1 30); do
    if curl -sf -o /dev/null "$GATEWAY_URL/api/ingest"; then
      break
    fi
    if ! kill -0 "$GATEWAY_PID" 2>/dev/null; then
      echo "[demo] ERROR: mock_gateway exited early — see .mock_gateway.log" >&2
      exit 1
    fi
    sleep 0.5
  done
  if ! curl -sf -o /dev/null "$GATEWAY_URL/api/ingest"; then
    echo "[demo] ERROR: mock_gateway did not answer on :8890 within 15 s" >&2
    exit 1
  fi
  echo "[demo] Gateway is up"
fi

# 3. Sync the camera catalogue into the backend.
echo "[demo] Syncing camera catalogue -> POST /api/cameras/sync"
curl -sf -X POST "$BACKEND_URL/api/cameras/sync"
echo

# 4. Seed the watchlist (idempotent).
echo "[demo] Seeding watchlist (python -m app.seed)"
(cd "$ROOT/backend" && "$PY" -m app.seed)

# 5. Replay a scripted vehicle journey (no video/ML needed).
echo "[demo] Simulating a journey for plate $DEMO_PLATE"
"$PY" "$ROOT/ingest/simulator.py" --plate "$DEMO_PLATE"

cat <<EOF

[demo] Done. Next steps:
  1. Start the frontend if it isn't running:  ./scripts/dev-frontend.sh
  2. Open http://localhost:5173
  3. Watch live alerts arrive in the Alerts tab (watchlist hits for $DEMO_PLATE).
  4. Open the Route tab and search for $DEMO_PLATE — the timestamped route
     draws on the map with numbered sighting markers and journey stats.
EOF
