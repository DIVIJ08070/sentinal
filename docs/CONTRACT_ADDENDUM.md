# Contract Addendum — Battle-Plan Features (backend v0.2)

Extends [CONTRACT.md](CONTRACT.md) (which remains authoritative for everything
not listed here). Everything below is implemented and smoke-tested on the
backend; the frontend builds against these shapes sight unseen. All base
endpoints keep their original shapes — this addendum only ADDS fields and
endpoints; nothing was renamed or removed.

---

## 1. Confusion-tolerant matcher (upgrade to `matching.py` rules)

Normalization is unchanged (`uppercase, strip everything except A-Z0-9`).
Matching is upgraded everywhere (watchlist alerts, route reconstruction):

- **Canonicalization**: after normalize, the backend attempts to repair a read
  into Indian plate syntax `^([A-Z]{2})(\d{1,2})([A-Z]{1,3})(\d{4})$` by
  resolving OCR-confusion twins positionally (digit in a letter slot -> its
  letter twin and vice versa). Partial/nonstandard plates are tolerated: if a
  string cannot be unambiguously repaired it is used as normalized. Canonical
  forms are a matching signal only — stored plates are NEVER rewritten.
- **Weighted edit distance**: substitution between an OCR confusion pair
  (`0/O, 1/I, 5/S, 8/B, 6/G, 2/Z`) costs **0.25**; any other edit costs
  **1.0**. Total distance `<= 1.0` -> fuzzy match. (Superset of the base
  contract's "Levenshtein 1 or single confusion substitution".)
- **`match_confidence`** (float 0–1): `exact = 1.0`; fuzzy =
  `round(1 - 0.28 * distance, 2)` -> one confusion misread scores **0.93**,
  a plain single-character edit scores **0.72**.
- **`matched_from`** (string): the raw plate read exactly as posted by the
  detector (before normalization). UI copy pattern:
  `"matched GJ01A81234 -> GJ01AB1234 (0.93)"`.
- **Fuzzy is always flagged, never silently merged**: a fuzzy result keeps its
  own stored plate; only the flags tell the operator the two reads were
  correlated.

### Where the new fields appear

`POST /api/detections` body: unchanged. The raw read is stored as
`plate_raw` and returned by `GET /api/detections` rows (nullable).

**Alerts** — `GET /api/alerts`, `POST /api/alerts/{id}/ack`, and the WS
`{"type":"alert"}` message all gain two top-level fields next to `match_type`:

```json
{
  "id": 9, "plate": "GJ01A81234", "match_type": "fuzzy",
  "match_confidence": 0.93,
  "matched_from": "GJ01A81234",
  ...unchanged embedded camera/watchlist/detection...
}
```

---

## 2. Route API — physics plausibility filter

`GET /api/vehicles/{plate}/route?since=&until=` — same envelope
(`plate, points, geojson, stats`), with upgraded points and stats.

### Each point (new fields in **bold**)

```json
{
  "camera_id": 39, "camera_name": "...", "department": "...",
  "lat": 22.2205, "lon": 68.9514,
  "captured_at": "2026-09-02T05:02:45.704Z", "pts_ms": null,
  "confidence": 0.88,              // OCR confidence (unchanged)
  "snapshot_b64": null,
  "fuzzy": false,                  // unchanged
  "match_confidence": 1.0,         // NEW - plate-match confidence (S1)
  "matched_from": "GJ01AB1234",    // NEW - raw read (S1)
  "leg_km": 384.753,               // NEW - haversine from previous ACCEPTED point
  "implied_speed_kmh": 46170.4,    // NEW - leg_km / captured_at delta
  "rejected": true,                // NEW - physics filter verdict
  "rejected_reason": "implied speed 46170 km/h over 384.8 km in 30s — physically impossible, discarded as false ANPR match"  // NEW, null when accepted
}
```

Semantics:

- Points stay ordered by `captured_at` ascending and **rejected points are
  still returned** — render them greyed with `rejected_reason` as tooltip.
- Thresholds: a hop is rejected when implied speed exceeds **180 km/h**
  (**250 km/h when the time gap is under 60 s** — jitter slack), unless the
  two points are within 50 m (same junction — always accepted).
- The **later** sighting of an impossible hop is the one rejected; the leg
  chain then continues from the previous accepted point (one false ANPR match
  cannot poison its neighbours).
- `leg_km` / `implied_speed_kmh` are `null` for the first point with
  coordinates and for points without coordinates; rejected points carry the
  offending values (for the tooltip).

### geojson / stats

- `geojson` LineString contains **accepted** points only (with coordinates).
- `stats` is computed over **accepted** sightings only and gains
  `rejected_count`:

```json
"stats": {"first_seen": "...", "last_seen": "...", "cameras_count": 8,
          "sightings_count": 9, "rejected_count": 1, "distance_km": 18.511}
```

---

## 3. Evidence Dossier

Two new endpoints (same `since`/`until` query params as the route):

### `GET /api/vehicles/{plate}/dossier.pdf`

`200`, `content-type: application/pdf`,
`content-disposition: inline; filename="dossier-<PLATE>.pdf"`.
Contents: "GUJARAT POLICE — VEHICLE MOVEMENT EVIDENCE DOSSIER" header, case
metadata (plate, generated_at UTC, operator `demo-operator`, watchlist entry
if any), route statistics, chronological sightings table (accepted rows +
red REJECTED rows with reasons; per-row short hashes), full SHA-256 hash
chain with the **final chain hash** in a highlighted block, embedded snapshot
images (Appendix A) and a chain-of-custody footer. Frontend: open in a new
tab / trigger download from a "Export Evidence Dossier" button on the route
view — no body parsing needed.

### `GET /api/vehicles/{plate}/dossier.json`

The same data machine-readable — this is also the mandatory **timestamped
output report**. Shape:

```json
{
  "plate": "GJ01AB1234",
  "generated_at": "2026-09-02T05:04:18.123Z",
  "operator": "demo-operator",
  "watchlist": {"id":1,"plate":"GJ01AB1234","label":"Stolen vehicle — FIR 123/2026 (demo)",
                 "category":"stolen","priority":"high","match_type":"exact","match_confidence":1.0} | null,
  "stats": { ...same as route stats... },
  "sightings": [{
      "seq": 1, "camera_id": 3, "camera_name": "...", "department": "...",
      "lat": 23.03, "lon": 72.60, "captured_at": "...Z", "pts_ms": null,
      "confidence": 0.79, "fuzzy": false, "match_confidence": 1.0,
      "matched_from": "GJ01AB1234", "leg_km": null, "implied_speed_kmh": null,
      "accepted": true, "rejected_reason": null,
      "snapshot_sha256": "<64 hex>|null", "snapshot_b64": "...|null",
      "prev_hash": "<64 hex>", "row_hash": "<64 hex>"
  }],
  "hash_chain": {"algorithm":"sha256","canonicalization":"...","genesis_hash":"<64 hex>",
                  "final_hash":"<64 hex>","row_count":11},
  "chain_of_custody": "CHAIN OF CUSTODY: ..."
}
```

Hash-chain verification (reproducible by any party):

1. `genesis_hash = sha256(canonical_json({plate, generated_at, operator}))`
2. per row: `row_hash = sha256(canonical_json(row minus row_hash minus
   snapshot_b64))` — the row includes `prev_hash` (row 1's prev is the
   genesis hash); snapshots are bound via `snapshot_sha256` = sha256 of the
   decoded JPEG bytes.
3. `final_hash` = last `row_hash` (genesis hash when there are no rows).
4. `canonical_json` = JSON, sorted keys, separators `(",", ":")`, UTF-8,
   `ensure_ascii=False`.

Each export gets its own `generated_at`, so PDF and JSON fetched separately
carry different (individually valid) chains.

---

## 4. Camera health & bandwidth

### Heartbeat body extension — `POST /api/cameras/{id}/heartbeat`

```json
{"status": "live",
 "fps_measured": 12.4,        // optional - measured delivery fps (frame-count delta / wall time)
 "last_frame_age_s": 0.31,    // optional - seconds since the last decoded frame
 "reconnects": 1,             // optional - successful reconnects this worker session
 "bandwidth_kbps": 2412.7}    // optional - measured/estimated stream bandwidth
```

Omitted fields keep the camera's previously stored values (so a plain
`{"status":"down"}` heartbeat does not blank the board). `fps_measured` is a
health metric only — no timing logic reads it (INTEGRATION_NOTES rule 2 holds).

### `GET /api/cameras` (and `/api/cameras/geojson` properties)

Camera objects gain nullable `fps_measured`, `last_frame_age_s`,
`reconnects`, `bandwidth_kbps`.

### `GET /api/health/summary` (NEW)

```json
{
  "per_camera": [{
    "camera_id": 1, "name": "...", "department": "...", "status": "live",
    "last_seen_at": "...Z", "fps_measured": 10.8, "last_frame_age_s": 0.44,
    "reconnects": 0, "bandwidth_kbps": 136.9
  }, ...all cameras, id ascending...],
  "totals": {
    "streams_up": 45,                  // cameras with status == live
    "avg_fps": 17.3,                   // mean fps_measured over live cameras (null if none)
    "total_bandwidth_kbps": 107857.7,  // sum over live cameras
    "reconnects_1h": 10                // sum of reconnects for cameras seen in the last hour
  }
}
```

Ingest reports real measured values (`capture.py`/`worker.py`: fps from frame
deltas over wall time, bandwidth estimated from measured resolution x measured
fps x codec bits-per-pixel — OpenCV exposes decoded frames, not transport
bytes). `simulator.py` posts plausible metrics for every live camera so the
health board is fully populated in the no-video demo.

---

## 5. Simulator behaviour change (demo coherence)

`ingest/simulator.py` now spaces the scripted journey's timestamps
**physically plausibly**: per-leg travel time = haversine leg distance at an
urban 35–60 km/h. `--minutes` is a **floor** — the journey is stretched beyond
it when the chosen cameras are too far apart to cover at plausible speeds
(with the default Ahmedabad cluster this lands around ~25 min). Without this,
the backend physics filter would correctly reject the golden-path demo route.
The journey still ends "now"; decoys are unchanged. It also POSTs health
heartbeats for all live cameras (Section 4).

---

## 6. Smoke additions (verified)

- Standard smoke unchanged: route for `GJ01AB1234` returns 8 ordered points,
  all accepted, distance ~18.5 km, urban leg speeds.
- Fuzzy read `GJ01A81234` posted on a route camera -> appears in the route
  flagged `fuzzy: true, match_confidence: 0.93, matched_from: "GJ01A81234"`,
  and raises a fuzzy alert with the same fields.
- Teleport detection (same plate, camera ~385 km away, 30 s later) ->
  `rejected: true` with the implied-speed reason; excluded from geojson,
  `distance_km`, and stats (`rejected_count: 1`).
- `dossier.pdf` -> 200 `application/pdf`, multi-page, snapshot embedded;
  `dossier.json` hash chain recomputes cleanly and detects a tampered row.
