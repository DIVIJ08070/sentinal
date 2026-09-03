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

## RTSP / WHEP authentication (in force since 3 Sept 2026, ~14:00 IST)

The gateway authenticates every RTSP and WHEP connection with your **registered
email and access password embedded in the URL**; only approved emails connect:

    rtsp://<email>:<password>@103.250.160.189:8554/stream/<id>     (email's @ encoded as %40)

Every client here (worker, relay, probes) takes the credential from your own
shell and injects it at connect time — nothing is stored in the catalogue,
registry, dashboard or repo. The `@` in the email is encoded for you:

```bash
export GRID_RTSP_AUTH='you@example.com:ACCESS-PASSWORD'   # type it yourself; never paste it in chat or commit it
.venv/bin/python ingest/hls_relay.py --cams cam01,cam04 --port 8888   # relay (terminal 1, with the export)
AUTO_ARM=3 DEMO_CAMS=cam06,cam23,cam27,cam16 scripts/demo-live.sh      # worker + read-tail (terminal 2, same export)
```
Test the credential first:
`ffplay -rtsp_transport tcp 'rtsp://you%40example.com:ACCESS-PASSWORD@103.250.160.189:8554/stream/cam01'`.
Note: FFmpeg prints the input URL in its own error lines, so the relay's local
`ingest/.hls_relay/*/ffmpeg.log` files (gitignored) may contain the credential.

## Demo presets and the live "AI view"

`scripts/live-with-auth.sh` takes a `MODE` (explicit `DEMO_CAMS` / `INTERVAL_MS`
still override; the active mode is printed at launch):

| MODE | Cameras | Interval | Use |
|---|---|---|---|
| `normal` (default) | `cam06,cam23,cam27` | 300 ms | dashboard demo, three feeds side by side |
| `video` | `cam06` | 150 ms | screen recording: one camera, twice the frames analysed → more reads/min |

```bash
MODE=video GRID_EMAIL=you@example.com scripts/live-with-auth.sh
```

`INTERVAL_MS` is the minimum elapsed **stream PTS** between frames handed to
the detector (`worker.py --interval-ms`); it paces CPU load, never timing.

The worker also serves the **AI view** — the frames it actually analysed, with
YOLO vehicle boxes (green), localized plates (yellow, labelled with the read
registration + confidence) and a HUD (camera, UTC capture time, counts) — on a
loopback port (`--ai-view-port`, default 8892, `AI_VIEW_PORT=0` disables):

    http://127.0.0.1:8892/ai              JSON: camera keys + last-frame age
    http://127.0.0.1:8892/ai/cam06.jpg    latest annotated frame
    http://127.0.0.1:8892/ai/cam06.mjpg   ~4 fps MJPEG stream (open in a browser tab / <img>)

Offline check without the grid: `cd ingest && ../.venv/bin/python ai_view_smoke.py /path/to/clip.mp4`
(writes `deliverables/screenshots/ai_view_sample.jpg`).

## Decoder-concealment frames (grey smear)

After a lost packet, a mid-stream join or a loop point, FFmpeg emits frames whose
unreconstructable regions are flat mid-grey blocks until the next keyframe. Measured
live on cam06 (HEVC): ~half the delivered frames in a lossy minute, 80-100% flat-grey
pixels vs 3-12% for clean frames. `capture.py` skips frames above
`CORRUPT_FLAT_FRACTION` (0.35) — no detection, not published to the AI view — leaving
PTS/anchor state untouched. Log line: `skipped N decoder-concealment frame(s)`.
