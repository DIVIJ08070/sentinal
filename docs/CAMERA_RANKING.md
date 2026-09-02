# Camera legibility ranking — live sandbox grid soak

**Method.** Each camera was soaked on the LIVE government sandbox grid (`rtsp://103.250.160.189:8554/stream/<id>`, RTSP forced over TCP, gateway rule 1) in 4-minute waves of at most 4 concurrent captures (rule 11; some cameras soaked across several waves, 4–12 min total, rates normalized per soaked minute), using the real pipeline: CaptureLoop (PTS-anchored timestamps, discontinuity reset) → YOLOv8n vehicle detection → open-image-models plate localization (`yolo-v9-t-384-license-plate-end2end`) → fast-plate-ocr. All timing is PTS-derived — never frame-count x fps, never arrival time. Every detection was POSTed live to the running backend (`POST /api/detections`, detector=`anpr`). CPU-only inference (`ingest/soak.py`).

Totals: **3677 frames processed, 27 plate reads** across 12 cameras.

| Rank | Camera | Name | Reads/min | Localizations/min | Vehicles/min | Best conf | Plates seen | Verdict |
|---:|---|---|---:|---:|---:|---:|---|---|
| 1 | cam06 | Timbavadi Gate, Junagadh | 2.25 | 7.25 | 7.2 | 0.88 | 1J11WA99, 303000, 337777, 368BAD052, 8555AJT, EJ414DD (+3) | **demo-star** |
| 2 | cam23 | cam23 [sandbox] | 0.58 | 1.00 | 0.0 | 0.78 | CMCC801, CMCI401, CMCI801, CMCI811, CMCT701, CMEI801 (+1) | **demo-star** |
| 3 | cam16 | Visat P2, Chandkheda | 0.38 | 1.88 | 11.8 | 0.48 | 133777, C30000, DZ1DCF | **usable** |
| 4 | cam27 | cam27 [sandbox] | 0.33 | 3.25 | 12.8 | 0.39 | 2S9153, B02222, B33333, B37711 | **usable** |
| 5 | cam01 | Chiman bhai Bridge, Ahmedabad | 0.25 | 24.75 | 140.5 | 0.59 | 6W2BBIO | **usable** |
| 6 | cam05 | Visat Teen Rasta, Chandkheda | 0.25 | 6.25 | 46.5 | 0.36 | P30133 | **usable** |
| 7 | cam04 | Paldi Circle, Ahmedabad | 0.25 | 2.12 | 7.6 | 0.37 | K07322, V05333 | **usable** |
| 8 | cam02 | Janpath, Ahmedabad | 0.00 | 2.25 | 71.2 | 0.00 | — | **poor** |
| 9 | cam08 | Majewadi Gate, Junagadh | 0.00 | 1.00 | 0.5 | 0.00 | — | **poor** |
| 10 | cam12 | Tri Mandir Adalaj Tollnaka, Gandhinagar | 0.00 | 0.25 | 0.2 | 0.00 | — | **poor** |
| 11 | cam03 | O.N.G.C. Office, Chandkheda | 0.00 | 0.25 | 0.0 | 0.00 | — | **poor** |
| 12 | cam10 | Char Chowk Road 2, Junagadh | 0.00 | 0.00 | 0.2 | 0.00 | — | **poor** |

**Verdicts.** demo-star = ≥0.5 reads/min over the whole soak (front the demo with these); usable = ≥0.2 reads/min (route corroboration); poor = below that (empty/static scenes, distant geometry or blur — keep for map coverage, not for ANPR).

**Load note.** Waves ran up to 4 cameras concurrently on one CPU-only machine; under a dedicated 2-camera wave cam23 read at 1.5 plates/min with confidences up to 0.78 (CMMC801 et al.), so per-camera rates above are conservative lower bounds for demo conditions where fewer feeds run ANPR at once.

Skipped up front: cam07, cam09 (black night scenes on the prior single-frame scan — no legible content).
