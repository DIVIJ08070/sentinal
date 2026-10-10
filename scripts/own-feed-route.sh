#!/usr/bin/env bash
# Onboard TWO own-footage clips as cameras at two real GPS spots, then run live
# ANPR on both — the one honest way to get a genuine CROSS-CAMERA route on this
# submission (the sandbox feeds are single looping scenes, so a vehicle cannot
# cross two of them; your own footage of one vehicle passing two spots can).
#
# Film the SAME vehicle at two points on one road, 0.5–3 km apart, plates
# facing the camera, daylight. Then:
#
#   scripts/own-feed-route.sh /path/A.mp4 <latA> <lonA> /path/B.mp4 <latB> <lonB>
#
# After it prints "reads scrolling", search the shared plate in the ROUTE tab:
# you get a two-camera route with the leg distance + implied-speed chip, and
# the physics filter greys out any impossible hop. No gateway credentials
# needed — OpenCV opens a file path exactly like an RTSP camera.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="${BACKEND:-http://localhost:8000}"
PY="$ROOT/.venv/bin/python"

[ $# -eq 6 ] || { echo "usage: $0 fileA latA lonA fileB latB lonB" >&2; exit 2; }
FA="$1"; LA="$2"; OA="$3"; FB="$4"; LB="$5"; OB="$6"
[ -f "$FA" ] || { echo "no such file: $FA" >&2; exit 1; }
[ -f "$FB" ] || { echo "no such file: $FB" >&2; exit 1; }

onboard() {  # name lat lon path  -> echoes the new camera id
  "$PY" - "$BACKEND" "$1" "$2" "$3" "$4" <<'PY'
import sys, json, urllib.request
backend, name, lat, lon, path = sys.argv[1:6]
body = json.dumps({"name": name, "department": "Own Feed Demo",
                   "lat": float(lat), "lon": float(lon),
                   "codec": "h264", "rtsp_url": path}).encode()
req = urllib.request.Request(backend + "/api/cameras", data=body,
                             headers={"Content-Type": "application/json"})
try:
    print(json.load(urllib.request.urlopen(req))["id"])
except urllib.error.HTTPError as e:
    # already onboarded at this path -> reuse the existing id
    for c in json.load(urllib.request.urlopen(backend + "/api/cameras")):
        if c.get("rtsp_url") == path:
            print(c["id"]); break
    else:
        sys.exit("onboard failed: %s" % e.read().decode()[:200])
PY
}

echo "onboarding own footage as two cameras..."
IDA="$(onboard "Own Camera A" "$LA" "$OA" "$FA")"
IDB="$(onboard "Own Camera B" "$LB" "$OB" "$FB")"
echo "  Camera A id=$IDA at $LA,$OA  ($FA)"
echo "  Camera B id=$IDB at $LB,$OB  ($FB)"
echo "  (markers now on the map; open $BACKEND without /api in the dashboard)"

echo "running live ANPR on both files — Ctrl-C to stop..."
cd "$ROOT/ingest"
exec "$PY" worker.py --detector anpr --cameras "$IDA,$IDB" --interval-ms 300 --ai-view-port 8892
