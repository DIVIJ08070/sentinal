# Real-grid ANPR evidence log

**Date:** 2026-09-02, 11:40–12:00 IST (banked on day 1, per the battle plan:
"know the true read rate on day 1, not day 4").
**Grid:** the public sandbox at `103.250.160.189` (RTSP :8554, catalogue built
by direct RTSP sweep via `ingest/grid_adapter.py --probe`, served on :8891 and
synced through the normal `POST /api/cameras/sync` path — nothing hard-coded).
**Command:** `python ingest/worker.py --detector anpr --max-cameras 4`
(production path: CaptureLoop + YOLOv8n + fast-plate-ocr, CPU-only, macOS).

## 1. Grid onboarding (measured)

- **30/30** cameras answered the RTSP sweep; catalogue synced
  `{synced: 30, live: 30, down: 0}`.
- Heterogeneous as promised: mixed **h264 / hevc**, 1280×720 and 1920×1080,
  declared fps 25 / 30 / absent.
- Declared vs delivered ("never trust the reported frame rate", gateway rule 2):
  declared 25–30 fps, **measured delivery 3.8–5.8 fps** per feed
  (cam01 3.84, cam02 5.77, cam03 5.69, cam04 4.16), last-frame age ~1.7 s,
  measured stream bandwidth 525–1,196 Kbps/feed. 0 reconnects in the window.
- 873 h264 decoder warnings in the worker log — all non-fatal (rule 6),
  capture never aborted.

## 2. Worker run — the chain fires on real footage

9.5-minute window (11:45:51 → 11:55:24 IST), 4 cameras, CPU-only:

| camera | vehicle detections POSTed | gated plate reads (conf ≥ 0.55) |
|---|---|---|
| cam01 (1080p) | 83 | **1** — `CC3111` @ 0.56, bbox `[829,705,950,813]`, JPEG snapshot attached |
| cam02 (1080p) | 108 | 0 |
| cam03 (720p) | 1 | 0 |
| cam04 (1080p) | 59 | 0 |
| **total** | **251** | **1** |

The full **capture → PTS-anchored timestamp → YOLOv8n vehicle detect → crop →
OCR → POST /api/detections → stored with snapshot** chain executed end-to-end
on live government-sandbox video (not the synthetic `anpr_smoke.py` scene).

## 3. OCR confidence spread (gates opened, diagnostic)

`ocr_spread.py` run with min-confidence 0 / min-length 3 on three further
cameras, 150 s each:

- **cam05**: 163 frames, 161 vehicle crops, **161 raw OCR reads** —
  confidence min/median/max = **0.19 / 0.30 / 0.46** (samples: `B33067` @0.24,
  `33336` @0.40, `B36076` @0.27). Plates are *detected and partially read*, but
  at this scene distance/resolution no read clears the 0.55 gate.
- **cam09**, **cam12**: 219 / 159 frames, **0 vehicle crops ≥ 32 px** — wide
  scenes with no OCR-viable vehicles in the window.

## 4. The honest numbers, and what they buy

- **True confident read rate on these cameras today: ~0.4 %** of vehicle
  detections (1/251) at the 0.55 confidence gate. The bottleneck is measured,
  not guessed: OCR fires on nearly every crop (161/161 on cam05) but
  confidence tops out ≈ 0.46 at typical scene distance — vehicle detection and
  the pipeline are not the limiting factor, plate pixel height is.
- Day-1 consequences taken: cameras now ranked by plate legibility (cam01
  best); threshold/crop-upscaling experiments belong on the worst cameras;
  re-measure daily with this same procedure; the confusion-tolerant matcher +
  physics filter are the designed-in insurance for exactly this regime.
- **Metadata-vs-video ratio, measured live** (`GET /api/health/summary` during
  the run): detection metadata upstream **0.92 Kbps** (217 detections /
  10-min window, actual stored payload bytes) vs **~3.4 Mbps** of video being
  pulled at the edge for 4 feeds — the edge-first bandwidth story produced by
  the running system, not a slide.

## Artifacts

- `docs/evidence/worker_anpr_2026-09-02.txt` — trimmed worker log (sync,
  heartbeats, every detection POST; decoder-warning spam removed, count noted
  above).
- `docs/evidence/ocr_spread_2026-09-02.txt` — raw OCR spread probe output.
- `docs/REAL_GRID.md` — grid endpoints + the earlier cam01 delivery probe
  (declared 30 fps, measured ~12.5 fps; procedure: `ingest/grid_probe.py`).
- Reproduce: `ingest/ocr_spread.py cam05,cam09 120` (from `ingest/`).

Repeat this procedure on the official gateway the day evaluation access opens
(SUBMISSION_CHECKLIST deliverable 4).
