# Government feed — detection output report (vehicles & number plates, timestamped)

**Platform:** SENTINEL — Gujarat CCTV Hackathon 2026 prototype

**Submitted by:** Divij Patel — Individual participant (Category 1) ·
vatsunp11@gmail.com

## What was onboarded, and how

The full government sandbox grid (30 heterogeneous cameras, mixed H.264/H.265, mixed resolutions) was onboarded through the platform's catalogue sync: the backend fetched the gateway catalogue (`GET /api/ingest`) via `POST /api/cameras/sync` and registered every camera with its GIS coordinates, codec, and stream URLs. Live analysis consumed each feed over **RTSP forced over TCP** (`rtsp://103.250.160.189:8554/stream/<id>`), at most 4 concurrent captures (gateway pacing rule), with **all timestamps derived from stream PTS** anchored once per connection to the wall clock — never from arrival time or a declared frame rate. Detection pipeline: YOLOv8n vehicle detection → dedicated plate localization (open-image-models, `yolo-v9-t-384-license-plate-end2end`) → fast-plate-ocr plate reading, CPU-only.

## Plate reads (registration numbers with timestamps)

All rows below are the backend's stored records (source of truth), not a side log — the report and the platform agree by construction.

| # | Camera | Location | Plate (as read) | UTC timestamp (PTS-anchored) | Confidence |
|---:|---|---|---|---|---:|
| 1 | cam16 | Visat P2, Chandkheda | `C30000` | 2026-09-02T07:15:36.207Z | 0.37 |
| 2 | cam27 | cam27 [sandbox] | `B33333` | 2026-09-02T07:15:44.163Z | 0.36 |
| 3 | cam27 | cam27 [sandbox] | `B37711` | 2026-09-02T07:15:45.723Z | 0.39 |
| 4 | cam27 | cam27 [sandbox] | `B02222` | 2026-09-02T07:15:48.843Z | 0.36 |
| 5 | cam27 | cam27 [sandbox] | `2S9153` | 2026-09-02T07:16:12.795Z | 0.36 |
| 6 | cam16 | Visat P2, Chandkheda | `133777` | 2026-09-02T07:18:40.795Z | 0.39 |
| 7 | cam05 | Visat Teen Rasta, Chandkheda | `P30133` | 2026-09-02T07:22:04.387Z | 0.36 |
| 8 | cam01 | Chiman bhai Bridge, Ahmedabad | `6W2BBIO` | 2026-09-02T07:22:14.828Z | 0.59 |
| 9 | cam23 | cam23 [sandbox] | `CMCT701` | 2026-09-02T07:26:45.043Z | 0.63 |
| 10 | cam04 | Paldi Circle, Ahmedabad | `K07322` | 2026-09-02T07:27:26.997Z | 0.35 |
| 11 | cam04 | Paldi Circle, Ahmedabad | `V05333` | 2026-09-02T07:27:28.160Z | 0.37 |
| 12 | cam16 | Visat P2, Chandkheda | `DZ1DCF` | 2026-09-02T07:28:24.875Z | 0.48 |
| 13 | cam06 | Timbavadi Gate, Junagadh | `EJ414DD` | 2026-09-02T07:31:09.312Z | 0.44 |
| 14 | cam06 | Timbavadi Gate, Junagadh | `337777` | 2026-09-02T07:31:10.352Z | 0.37 |
| 15 | cam06 | Timbavadi Gate, Junagadh | `1J11WA99` | 2026-09-02T07:31:10.872Z | 0.47 |
| 16 | cam06 | Timbavadi Gate, Junagadh | `8555AJT` | 2026-09-02T07:31:38.992Z | 0.43 |
| 17 | cam06 | Timbavadi Gate, Junagadh | `GJ750887` | 2026-09-02T07:31:57.592Z | 0.67 |
| 18 | cam06 | Timbavadi Gate, Junagadh | `303000` | 2026-09-02T07:33:20.552Z | 0.36 |
| 19 | cam06 | Timbavadi Gate, Junagadh | `LWW452` | 2026-09-02T07:33:55.992Z | 0.41 |
| 20 | cam06 | Timbavadi Gate, Junagadh | `GJ1104284` | 2026-09-02T07:34:03.712Z | 0.88 |
| 21 | cam06 | Timbavadi Gate, Junagadh | `368BAD052` | 2026-09-02T07:34:27.392Z | 0.49 |
| 22 | cam23 | cam23 [sandbox] | `CMCC801` | 2026-09-02T07:35:19.199Z | 0.65 |
| 23 | cam23 | cam23 [sandbox] | `CMCI801` | 2026-09-02T07:35:21.279Z | 0.71 |
| 24 | cam23 | cam23 [sandbox] | `CMMC801` | 2026-09-02T07:35:24.999Z | 0.78 |
| 25 | cam23 | cam23 [sandbox] | `CMEI801` | 2026-09-02T07:35:25.519Z | 0.72 |
| 26 | cam23 | cam23 [sandbox] | `CMCI811` | 2026-09-02T07:35:26.039Z | 0.67 |
| 27 | cam23 | cam23 [sandbox] | `CMCI401` | 2026-09-02T07:35:31.159Z | 0.71 |

## Vehicle detections without a legible plate (throttled sightings)

Plate-less vehicle sightings are PTS-throttled (max one per 3 s per camera) so busy junctions do not flood the store; each still carries a bbox and PTS-anchored timestamp.

| Camera | Location | Vehicle-only detections | First (UTC) | Last (UTC) |
|---|---|---:|---|---|
| cam01 | Chiman bhai Bridge, Ahmedabad | 48 | 2026-09-02T07:21:50.284Z | 2026-09-02T07:24:56.158Z |
| cam02 | Janpath, Ahmedabad | 59 | 2026-09-02T07:21:46.846Z | 2026-09-02T07:25:17.129Z |
| cam04 | Paldi Circle, Ahmedabad | 22 | 2026-09-02T07:15:21.838Z | 2026-09-02T07:28:21.120Z |
| cam05 | Visat Teen Rasta, Chandkheda | 44 | 2026-09-02T07:21:44.837Z | 2026-09-02T07:25:16.377Z |
| cam06 | Timbavadi Gate, Junagadh | 6 | 2026-09-02T07:31:08.272Z | 2026-09-02T07:34:21.392Z |
| cam08 | Majewadi Gate, Junagadh | 2 | 2026-09-02T07:31:41.367Z | 2026-09-02T07:34:38.377Z |
| cam10 | Char Chowk Road 2, Junagadh | 1 | 2026-09-02T07:34:04.674Z | 2026-09-02T07:34:04.674Z |
| cam12 | Tri Mandir Adalaj Tollnaka, Gandhinagar | 1 | 2026-09-02T07:31:19.127Z | 2026-09-02T07:31:19.127Z |
| cam16 | Visat P2, Chandkheda | 27 | 2026-09-02T07:15:30.806Z | 2026-09-02T07:29:56.889Z |
| cam27 | cam27 [sandbox] | 56 | 2026-09-02T07:15:41.043Z | 2026-09-02T07:38:20.932Z |

## Totals

- Detection rows stored (detector=`anpr`, this soak): **293**
- Number-plate reads: **27** (27 distinct plates)
- Vehicle-only sightings (throttled): **266**
- Cameras that produced detections: **11**
- Every plate read carries a snapshot (vehicle crop with the plate visible), bbox, PTS offset and a PTS-anchored UTC timestamp.

## Where this data lives on the platform

The same records are queryable live at `GET /api/detections` (filters: `plate=`, `camera_id=`, `since=`, `until=`) and every route/plate query can be exported as a **hash-chained evidence dossier** (chain-of-custody PDF: per-sighting snapshots, SHA-256 hash chain, camera/GPS/timestamp table, operator identity, audit trail) — the platform's court-ready form of this report.
