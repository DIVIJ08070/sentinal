# Sentinel Platform — Module Contract (SOURCE OF TRUTH)

Project: prototype for the Gujarat CCTV Hackathon 2026 (sentinel.gujarat.gov.in).
Solution model: **Hybrid — Model 1 (Registry & GIS, mandatory) + Model 2/4 (unified viewing + central AI analytics + watchlist alerts)**.
Scope of analytics for the MVP: **vehicle detection + ANPR + watchlist matching + route reconstruction**. Face recognition is documented as roadmap only, NOT implemented.

Every module MUST follow this contract exactly. If something is ambiguous, follow this file, not your own preference. Do not rename endpoints, fields, ports, or paths.

## Repo layout (each agent writes ONLY its own area)

```
sentinel-hackathon/
  README.md                    (docs agent)
  .gitignore                   (docs agent)
  Makefile                     (docs agent)
  docs/
    CONTRACT.md                (already written — do not modify)
    INTEGRATION_NOTES.md       (already written — do not modify)
    HLD.md                     (docs agent)
    SUBMISSION_CHECKLIST.md    (docs agent)
  scripts/
    dev-backend.sh             (docs agent)
    dev-frontend.sh            (docs agent)
    demo.sh                    (docs agent)
  backend/                     (backend agent)
    requirements.txt
    app/... (see below)
  ingest/                      (ingest agent)
    requirements.txt
    requirements-ml.txt
    worker.py capture.py simulator.py mock_gateway.py
    detectors/...
  frontend/                    (frontend agent)
    package.json vite.config.js index.html src/...
```

## Ports & env

- Backend (FastAPI/uvicorn): **8000**
- Frontend (Vite dev): **5173**, proxies `/api` and `/ws` to `http://localhost:8000` (ws:true for /ws)
- Mock gateway (`ingest/mock_gateway.py`): **8890**
- Env vars (all optional, with defaults):
  - `DATABASE_URL` (default `sqlite:///./sentinel.db`, relative to `backend/`)
  - `SENTINEL_HOST` (default `http://localhost:8890`) — the CCTV gateway host; on hackathon day set to the government host. Catalogue endpoint is always `{SENTINEL_HOST}/api/ingest`.
  - `BACKEND_URL` (default `http://localhost:8000`) — used by ingest worker & simulator.

## Data model (backend, SQLAlchemy; SQLite default, plain lat/lon floats — NO PostGIS dependency)

- **Camera**: id (int pk), external_id (str, nullable), source (`catalogue`|`manual`|`csv`), name, department (str), lat (float), lon (float), codec (str, e.g. `h264`/`h265`), width (int), height (int), fps_declared (float, INFORMATIONAL ONLY — never used for timing), status (`live`|`down`|`unknown`), rtsp_url, hls_url, whep_url (str, nullable), storage_type (str, nullable), retention_days (int, nullable), last_seen_at (datetime, nullable), created_at. Unique constraint on (source, external_id) when external_id not null.
- **WatchlistEntry**: id, plate (str, normalized uppercase no spaces/dashes), label (str, e.g. "Stolen vehicle — FIR 123/2026"), category (`stolen`|`wanted`|`suspect`|`blacklisted`|`other`), priority (`high`|`medium`|`low`), active (bool, default true), notes, created_at.
- **Detection**: id, camera_id (fk Camera), object_type (default `vehicle`), plate (normalized, nullable), plate_confidence (float 0–1, nullable), pts_ms (float, nullable), captured_at (datetime, REQUIRED — derived from stream PTS anchor, see INTEGRATION_NOTES), snapshot_b64 (str, nullable, small JPEG), bbox (JSON str, nullable), detector (str, e.g. `mock`|`anpr`), created_at.
- **Alert**: id, detection_id (fk), watchlist_id (fk), camera_id (fk), plate, match_type (`exact`|`fuzzy`), status (`new`|`acknowledged`), created_at, acknowledged_at.

Plate normalization (shared rule, implement in backend `app/matching.py` — the ONLY place):
`normalize(p) = uppercase, strip everything except A-Z0-9`. Matching: exact on normalized; plus fuzzy = Levenshtein distance 1 OR single OCR-confusion substitution (0↔O, 1↔I, 5↔S, 8↔B, 2↔Z) → `match_type="fuzzy"`.

## REST API (all under `/api`, JSON; FastAPI with CORS allow_origins=["*"])

Cameras:
- `GET /api/cameras?department=&status=&source=` → `[Camera]`
- `POST /api/cameras` (manual create, all fields optional except name/lat/lon/department)
- `POST /api/cameras/bulk` — multipart CSV upload, columns: `external_id,name,department,lat,lon,codec,status,rtsp_url,hls_url` (missing cols tolerated) → `{imported: n, errors: [...]}`
- `POST /api/cameras/sync` — backend fetches `{SENTINEL_HOST}/api/ingest`, upserts cameras with source=`catalogue` (match on external_id; the catalogue is the contract — tolerate unknown/extra fields, missing coords → lat/lon null and status kept). Returns `{synced: n, live: n, down: n}`.
- `GET /api/cameras/geojson` → GeoJSON FeatureCollection (skip cameras with null lat/lon), properties = full camera fields.
- `POST /api/cameras/{id}/heartbeat` body `{status}` → updates status + last_seen_at (used by ingest worker).

Watchlist:
- `GET /api/watchlist` / `POST /api/watchlist` / `DELETE /api/watchlist/{id}` / `PATCH /api/watchlist/{id}` (toggle active etc.)

Detections & alerts:
- `POST /api/detections` body: `{camera_id (int) OR camera_external_id (str), object_type?, plate?, plate_confidence?, pts_ms?, captured_at (ISO8601, required), snapshot_b64?, bbox?, detector?}`. Backend resolves camera, stores detection, runs watchlist matching; on match creates Alert and broadcasts on WS. Returns `{detection_id, alert_id|null}`.
- `GET /api/detections?plate=&camera_id=&since=&until=&limit=` (plate filter uses normalize(), default limit 200, newest first)
- `GET /api/alerts?status=&limit=` → newest first, each alert embeds `camera` (id,name,lat,lon,department) + `watchlist` (label,category,priority) + `detection` (captured_at, plate_confidence, snapshot_b64)
- `POST /api/alerts/{id}/ack`

Route reconstruction (the hackathon test case):
- `GET /api/vehicles/{plate}/route?since=&until=` → `{plate, points: [{camera_id, camera_name, department, lat, lon, captured_at, pts_ms, confidence, snapshot_b64}], geojson: {LineString of [lon,lat] ordered by captured_at}, stats: {first_seen, last_seen, cameras_count, sightings_count, distance_km (haversine sum)}}`. Points ordered by captured_at ascending; plate matched via normalize(); include fuzzy matches flagged `fuzzy: true`.

Stats:
- `GET /api/stats` → `{cameras: {total, live, down, unknown, by_department: {...}}, watchlist_active, detections_24h, alerts_new, alerts_total}`

## WebSocket

- `WS /ws/alerts` — server pushes JSON messages:
  - `{"type":"alert", "alert": {—same embedded shape as GET /api/alerts—}}`
  - `{"type":"detection", "detection": {camera_id, camera_name, plate, captured_at}}` (send for every detection; fine at demo rates)
  - `{"type":"camera_status", "camera_id": n, "status": "live|down"}`
  Server must tolerate clients disconnecting; no inbound messages expected (ignore any).

## Ingest module (Python, talks ONLY to the backend REST API + video streams)

- `worker.py`: CLI `python worker.py [--detector mock|anpr] [--cameras id1,id2] [--max-cameras N]`. Flow: POST `/api/cameras/sync` → GET `/api/cameras?source=catalogue&status=live` → spawn one capture thread per camera (respect --max-cameras, default 4 — pace your load per INTEGRATION_NOTES). Each thread: capture frames per capture.py rules, run detector, POST detections, heartbeat on connect/disconnect.
- `capture.py`: OpenCV VideoCapture with `OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp` set BEFORE `import cv2`; PTS from `CAP_PROP_POS_MSEC`; wall-clock anchor: on first successfully read frame record `(anchor_wall=utcnow, anchor_pts)`; every frame's `captured_at = anchor_wall + (pts - anchor_pts)`. Never use per-frame arrival time; never use CAP_PROP_FPS for any timing. Discontinuity rule: if pts < last_pts OR (pts - last_pts) > 10000ms → re-anchor and call `detector.reset()`. Reconnect on read failure with exponential backoff 2s→30s (×2). Decoder warnings/log noise are non-fatal.
- `detectors/base.py`: `@dataclass DetectionResult(object_type, plate|None, plate_confidence|None, bbox|None, snapshot_b64|None)`; `class Detector: def process(self, frame, pts_ms, captured_at) -> list[DetectionResult]; def reset(self) -> None`.
- `detectors/mock.py`: deterministic lightweight motion-gated fake detector for pipeline testing (emits an occasional plate from a configurable pool; clearly labeled mock).
- `detectors/anpr.py`: real path — ultralytics YOLOv8n (vehicle classes: car/truck/bus/motorbike) + `fast-plate-ocr` for plate reading; imports guarded so the module errors with a helpful message if ML extras aren't installed (`pip install -r requirements-ml.txt`).
- `simulator.py`: NO video needed. Replays a scripted vehicle journey: takes `--plate GJ01AB1234 --minutes 3` (defaults fine), fetches cameras from backend, picks ~8 geographically plausible ones ordered to form a route, POSTs detections with increasing captured_at (now-based, spread over the last N minutes) + a few decoy plates on other cameras. Purpose: full end-to-end demo (alerts + route reconstruction) with zero ML/video deps. Prints what it did and the plate to search.
- `mock_gateway.py`: tiny stdlib/FastAPI server on 8890 serving `GET /api/ingest` returning a realistic catalogue JSON: ~50 cameras, fields `{id, name, department, location: {lat, lon}, codec (mix h264/h265), width, height, fps, live (bool, ~90% true), urls: {rtsp, hls, whep}}` — departments: Home/Police, GSRTC, Municipal Corporation, Panchayat, Health, RTO, Food & Civil Supplies; coordinates real-ish across Gujarat (Gandhinagar, Ahmedabad, Vadodara, Surat, Rajkot, Jamnagar, Dwarka, Somnath, Dahod, Valsad, Bhuj, Mehsana). RTSP urls may point at `rtsp://localhost:8554/stream/<id>` (only meaningful if user runs their own MediaMTX; that's fine). Backend's sync must handle this shape AND tolerate flat `lat`/`lon` fields as fallback.

## Frontend (React 18 + Vite 5 + Leaflet, plain CSS, dark "command centre" theme)

package.json deps (pin): react@^18.3, react-dom@^18.3, leaflet@^1.9.4, react-leaflet@^4.2.1, hls.js@^1.5. Dev: vite@^5, @vitejs/plugin-react.
Layout: left = full-height Leaflet map; right = tabbed panel (Alerts | Watchlist | Route | Cameras); top = StatsBar. Components in `src/components/`: MapView, StatsBar, AlertsPanel, WatchlistPanel, RouteSearch, CameraDrawer, VideoWall (grid of HLS players for live cameras, opened from a button).
Behaviour:
- MapView: markers colored by status (live=green, down=red, unknown=grey), clustering NOT required; department filter; clicking a marker opens CameraDrawer (camera details + live preview via hls.js using camera.hls_url when present, graceful "stream unavailable" fallback).
- AlertsPanel: live via `WS /ws/alerts` (reconnect with backoff), shows alert cards (plate, category badge, camera, time, snapshot if present), ack button; new alert briefly highlights + pans map to camera.
- WatchlistPanel: table + add/remove form.
- RouteSearch: input plate → GET route → table of timestamped sightings + draws polyline & numbered markers on map; shows stats (first/last seen, cameras, distance).
- API base: use relative `/api` + `/ws` (vite proxy handles dev).
- `src/api.js` single fetch wrapper; `src/ws.js` hook `useAlertsSocket(onMessage)`.

## Demo flow (what `scripts/demo.sh` orchestrates, and README documents)

1. `mock_gateway.py` up (8890) → 2. backend up (8000) → 3. `POST /api/cameras/sync` → 4. seed watchlist (backend `app/seed.py` adds ~6 watchlist entries incl. demo plate `GJ01AB1234` and a fuzzy-bait plate) → 5. `simulator.py --plate GJ01AB1234` → 6. frontend (5173): live alerts appear, search route for GJ01AB1234 → timestamped route on map.
`backend/app/seed.py`: `python -m app.seed` seeds watchlist only (cameras come from sync); idempotent.

## Non-negotiable quality bars

- Every service starts with plain `pip install -r requirements.txt` / `npm install` — no system deps beyond Python 3.12, Node 20, ffmpeg.
- Requirements pinned to major versions; no heavyweight deps in the default path (torch/ultralytics ONLY in requirements-ml.txt).
- All timestamps stored/returned as UTC ISO8601 with `Z`.
- Code must run on macOS (dev) and Linux (deployment) — no OS-specific paths.
