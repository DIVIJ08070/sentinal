#!/usr/bin/env bash
# LIVE DEMO MODE — real ANPR on the demo-star government cameras, streamed into
# the dashboard, with the watchlist armed so a REAL alert fires on a live feed.
#
# What it does (idempotent; Ctrl-C stops everything):
#   1. checks the stack is up (backend :8000, dashboard :5173)
#   2. resolves the demo cameras' registry ids (default cam06 + cam23 — the two
#      cameras with the highest measured plate read-rate, docs/CAMERA_RANKING.md)
#   3. arms the watchlist with plates those cameras GENUINELY read — the sandbox
#      feeds loop, so the same real vehicles come round again and trigger an
#      alert on camera within a few minutes
#   4. starts the live ANPR worker on those cameras and prints every plate read
#      in this terminal as it lands (keep this terminal beside the dashboard
#      while recording)
#
# Usage:  scripts/demo-live.sh
#         DEMO_CAMS=cam06 ARM_PLATES=GJ1104284,GJ19PE8859 scripts/demo-live.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="${BACKEND_URL:-http://localhost:8000}"
CAMS="${DEMO_CAMS:-cam06,cam23}"
ARM="${ARM_PLATES:-GJ1104284}"
PY="$ROOT/.venv/bin/python"

for u in "$BACKEND/api/stats" "http://localhost:5173/"; do
  curl -sf -m 3 -o /dev/null "$u" || { echo "✗ not running: $u — start the stack first (README: How to run)"; exit 1; }
done
echo "✓ stack up"

IDS=$(curl -s "$BACKEND/api/cameras" | "$PY" -c "
import json, sys
want = set('$CAMS'.split(','))
cams = [c for c in json.load(sys.stdin) if c.get('external_id') in want]
print(','.join(str(c['id']) for c in cams))
for c in cams: print(f\"  {c['external_id']:6} id={c['id']:<3} {c['name']}\", file=sys.stderr)
")
[ -n "$IDS" ] || { echo "✗ cameras $CAMS not in registry — run: curl -X POST $BACKEND/api/cameras/sync"; exit 1; }

"$PY" - "$BACKEND" "$ARM" <<'EOF'
import json, sys, urllib.request
backend, plates = sys.argv[1], [p.strip().upper() for p in sys.argv[2].split(",") if p.strip()]
existing = {w["plate"] for w in json.load(urllib.request.urlopen(f"{backend}/api/watchlist"))}
for p in plates:
    if p in existing:
        print(f"✓ watchlist already has {p}"); continue
    body = json.dumps({"plate": p, "label": "Live demo — stolen vehicle (FIR 221/2026)",
                       "category": "stolen", "priority": "high"}).encode()
    req = urllib.request.Request(f"{backend}/api/watchlist", data=body,
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req).read()
    print(f"✓ armed watchlist with {p}")
EOF

# Live tail of plate reads (new rows only), beside the worker output.
# AUTO_ARM=N (default 3): the first N high-confidence live reads that are not
# yet on the watchlist get added automatically, so each such vehicle raises a
# REAL alert when its camera's loop brings it round again. Set AUTO_ARM=0 to
# disable.
"$PY" - "$BACKEND" "${AUTO_ARM:-3}" <<'EOF' &
import json, sys, time, urllib.request
backend, auto_arm = sys.argv[1], int(sys.argv[2])
seen, first, armed = set(), True, 0
try:
    listed = {w["plate"] for w in json.load(urllib.request.urlopen(f"{backend}/api/watchlist"))}
except Exception:
    listed = set()

def arm(plate, cam):
    body = json.dumps({"plate": plate, "category": "stolen", "priority": "high",
                       "label": f"Live demo — auto-armed from a live read on camera {cam}"}).encode()
    req = urllib.request.Request(f"{backend}/api/watchlist", data=body,
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req).read()

print("── live plate reads (only reads that land from now on) ───────────")
while True:
    try:
        rows = json.load(urllib.request.urlopen(f"{backend}/api/detections?limit=30"))
    except Exception:
        time.sleep(3); continue
    if first:
        # Seed with history so the terminal shows ONLY new, live reads —
        # otherwise the first poll dumps the last 30 stored rows on camera.
        seen.update(d["id"] for d in rows); first = False
        continue
    for d in reversed(rows):
        if d.get("plate") and d["id"] not in seen:
            seen.add(d["id"])
            conf = d.get("plate_confidence") or 0
            print(f"  {d['captured_at'][11:19]}  cam {d['camera_id']:<3} plate {d['plate']:<11} "
                  f"conf {conf:.2f}", flush=True)
            if armed < auto_arm and conf >= 0.6 and d["plate"] not in listed:
                try:
                    arm(d["plate"], d["camera_id"]); listed.add(d["plate"]); armed += 1
                    print(f"  ⚡ auto-armed {d['plate']} — alert fires when camera "
                          f"{d['camera_id']} loops back to it", flush=True)
                except Exception as exc:
                    print(f"  (auto-arm failed: {exc})", flush=True)
    time.sleep(3)
EOF
TAIL=$!
trap 'kill $TAIL 2>/dev/null || true' EXIT

echo "▶ LIVE ANPR on $CAMS (registry ids $IDS) — open the dashboard ALERTS tab; Ctrl-C to stop"
# Foreground (not exec) so the EXIT trap still reaps the read-tail when the
# worker ends for any reason, not only an interactive Ctrl-C.
"$PY" "$ROOT/ingest/worker.py" --detector anpr --cameras "$IDS"
