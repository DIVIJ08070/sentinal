#!/usr/bin/env bash
# One-shot launcher for the credentialed sandbox grid.
#   * prompts for the access password WITHOUT echo — it is never written to a
#     file or shell history and lives only in this process tree
#   * verifies the credential against cam01 before starting anything
#   * starts the HLS relay (dashboard video) in the background and live ANPR
#     mode (worker + read-tail) in the foreground; Ctrl-C stops both
#
# Usage:  GRID_EMAIL=you@example.com scripts/live-with-auth.sh
#         (optional: RELAY_CAMS=cam01,cam04  DEMO_CAMS=cam06,cam23,cam27,cam16  AUTO_ARM=3)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$ROOT/.venv/bin/python"

EMAIL="${GRID_EMAIL:-}"
[ -z "$EMAIL" ] && read -r -p "Registered email: " EMAIL
read -r -s -p "Access password for $EMAIL (not echoed): " PASS; echo
export GRID_RTSP_AUTH="$EMAIL:$PASS"; unset PASS

# Verify against the gateway before starting anything (URL form per the
# integrator guide: email with @ encoded as %40). Output is discarded so the
# credential is not echoed back by ffprobe's error lines.
ENC=$("$PY" -c 'import sys, urllib.parse as u; e, p = sys.argv[1].split(":", 1); print(u.quote(u.unquote(e), safe="") + ":" + u.quote(u.unquote(p), safe=""))' "$GRID_RTSP_AUTH")
if ffprobe -v error -rtsp_transport tcp -timeout 20000000 -select_streams v:0 \
     -show_entries stream=codec_name -of csv=p=0 "rtsp://$ENC@103.250.160.189:8554/stream/cam01" >/dev/null 2>&1; then
  echo "✓ gateway accepted the credential (cam01 answered)"
else
  echo "✗ gateway refused the credential (401) — is $EMAIL on the approved list? is the password current?"
  exit 1
fi
unset ENC

if curl -s -m 3 -o /dev/null http://localhost:8888/; then
  echo "• relay already listening on :8888 — leaving it (stop it first if it lacks the credential)"
else
  "$PY" "$ROOT/ingest/hls_relay.py" --cams "${RELAY_CAMS:-cam01,cam04}" --port 8888 > /tmp/sentinel-relay.log 2>&1 &
  RELAY=$!
  trap 'kill "$RELAY" 2>/dev/null || true' EXIT
  echo "▶ relay started (pid $RELAY, log /tmp/sentinel-relay.log)"
fi

AUTO_ARM="${AUTO_ARM:-3}" DEMO_CAMS="${DEMO_CAMS:-cam06,cam23,cam27,cam16}" "$ROOT/scripts/demo-live.sh"
