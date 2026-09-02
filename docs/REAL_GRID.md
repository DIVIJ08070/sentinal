# Running SENTINEL against the real sandbox camera grid

The sandbox grid (from the portal's integrator guide): ~30 live looping feeds,
`cam01`…`cam30`, mixed H.264/HEVC, five resolutions, seven declared frame rates.

Measured reality (2026-09-02, `ingest/grid_probe.py` on cam01):
- **declares 30 fps, delivers ~12.5 fps** (median PTS gap exactly 80 ms) — the
  guide's "don't trust reported frame rate" rule, confirmed live
- stable over 20 s: 0 reconnects, 0 discontinuities, PTS gaps p95 = 80 ms
- ~2.9 Mbps/camera estimated → ~87 Mbps to pull all 30 (hence `--max-cameras`)

## Endpoints
| What | Where | Auth |
|---|---|---|
| Catalogue | `https://cctv.corp8.cloud/cameras.json` | access password (browser) |
| RTSP (AI ingest) | `rtsp://103.250.160.189:8554/stream/<id>` | none (direct) |
| WHEP (low-latency preview) | `http://103.250.160.189:8889/stream/<id>/whep` | none (direct) |
| HLS (dashboard preview) | `https://cctv.corp8.cloud/<id>/index.m3u8` | access password (browser session) |

## One-time: get the real catalogue (optional but recommended)
Open `https://cctv.corp8.cloud/cameras.json` in your browser (enter the access
code), save the JSON as `ingest/cameras.json`. Without it, the probe-built
`ingest/grid_catalogue.json` (already generated) works fine — it just lacks
any names/locations the CDN catalogue might carry.

## Run the full platform on the real grid
```bash
cd ~/Desktop/sentinel-hackathon

# 1. catalogue adapter on :8891 (real file if you saved it, else the probe file)
.venv/bin/python ingest/grid_adapter.py --file ingest/cameras.json    # or --file ingest/grid_catalogue.json

# 2. backend pointed at the adapter
cd backend && SENTINEL_HOST=http://localhost:8891 ../.venv/bin/uvicorn app.main:app --port 8000

# 3. sync + seed
curl -X POST localhost:8000/api/cameras/sync
cd backend && ../.venv/bin/python -m app.seed

# 4. live ingest — mock detector first (pipeline check), then real ANPR
.venv/bin/python ingest/worker.py --detector mock --max-cameras 4
.venv/bin/python ingest/worker.py --detector anpr --max-cameras 4   # needs requirements-ml.txt installed

# 5. dashboard
cd frontend && npm run dev   # http://localhost:5173
```

Useful tools:
- `ingest/grid_probe.py --cam camNN --seconds 20` — true delivery rate, PTS
  gaps, reconnects for one camera (open few, close after: pacing rule).
- `ingest/grid_adapter.py --probe --once` — rebuild the provisional catalogue.

## Notes
- Sandbox cameras carry **placeholder GIS positions** (ring around
  Gandhinagar, names suffixed `[sandbox]`) unless the CDN catalogue provides
  real ones. Route reconstruction still demonstrates fully; say so if asked.
- Dashboard HLS preview of CDN streams needs your browser's authenticated
  session and may be blocked by CORS; the WHEP endpoint is auth-free if a
  WHEP player is wired. Not demo-critical — ingest runs on RTSP regardless.
- On hackathon day: skip the adapter entirely — set
  `SENTINEL_HOST=http://<government-host>` and sync their `/api/ingest`.
- ANPR read-rate ranking per camera (battle-plan task): run the worker with
  `--detector anpr` for ~10 min, then
  `curl 'localhost:8000/api/detections?limit=1000'` and count reads per
  camera to pick the most legible cameras for the demo.
