# LIVE DEMO RUNBOOK — showing plate tracing on real government cameras

Everything below is real: live RTSP feeds, real ANPR, real alerts. No simulator.

## 0. Before you press record (2 minutes)

```bash
cd ~/Desktop/sentinel-hackathon
.venv/bin/python ingest/loop_phase.py          # which demo cameras are in a daylight/traffic phase NOW
```
The sandbox feeds are day-long recordings on a loop — a camera that read plates at 9 AM
can be on an empty 2 AM road an hour later. Pick a camera marked **READY**.

Then, in a second terminal kept visible beside the dashboard:
```bash
DEMO_CAMS=cam06,cam23 scripts/demo-live.sh      # use the READY cameras from loop_phase
```
It arms the watchlist with a plate those cameras genuinely read (`GJ1104284` on cam06),
starts the live ANPR worker, and prints every plate read as it lands. **Wait until reads
are scrolling before you start recording** — that is your cue.

## 1. The on-camera sequence (≈ 4–5 min)

| Beat | Do | Say |
|---|---|---|
| 1 | Dashboard open, **CAMERAS** tab, click **Sync** | "Thirty government cameras onboarded from the catalogue — mixed vendors, H.264 and HEVC, all departments." |
| 2 | Pick a department in the top-left filter (e.g. *Junagadh Police*) | "Every department's cameras on one GIS map, filterable by owner — nothing changed on their systems; we only read the streams." |
| 3 | Click **Chiman bhai Bridge** → live video plays | "This is the live government feed, playing inside our platform." |
| 4 | Point at the terminal: plate reads scrolling | "And this is the AI reading number plates off the live stream right now — YOLO finds the vehicle, a plate model finds the plate, OCR reads it, PTS-timestamped." |
| 5 | **ALERTS** tab — wait for the armed plate to come round the loop | "That plate is on the watchlist. The moment the camera reads it again — there — an alert fires in under a second, with the camera frame as evidence." |
| 6 | Click the alert's **snapshot** | "This is the actual frame the camera captured — proof the sighting is camera-based, not typed in." |
| 7 | **ROUTE** tab → type the armed plate → **Trace route** | "Search any registration and the platform reconstructs every timestamped sighting, camera by camera, with a physics filter rejecting impossible hops." |
| 8 | Click **Export Evidence Dossier (PDF)** | "One click — a SHA-256 hash-chained dossier an investigating officer can attach to a charge sheet." |
| 9 | **HEALTH** tab | "Measured frame rate, bandwidth and reconnects per camera — declared 30 fps, delivering 12.5: we time everything from the video's own clock, never the label." |

## 2. Honesty lines (judges will ask — answer before they do)

- *"Is the multi-camera route real?"* — "On the sandbox, a vehicle can't physically drive from one looped camera to another, so today's real reads are single-camera sightings. The route engine is the same code that ran your 8-camera trace; on your evaluation grid it reconstructs the real journey."
- *"What about misreads?"* — "Every read carries a confidence, a format gate rejects non-registration strings, and a confusion-tolerant matcher merges OCR variants into one vehicle — you saw one plate read four ways and resolved to one."
- *"Why does that camera show nothing?"* — "It's on the night part of its loop. Recall is driven by camera placement and lighting; our health board and camera ranking tell operators which cameras are ANPR-grade."

## 3. If something stalls mid-take

- No reads for >2 min → run `loop_phase.py` again, switch `DEMO_CAMS` to a READY camera, restart `demo-live.sh`.
- Video tile says *Connecting…* → non-warm camera; give it up to a minute, or click a warm one (Chiman bhai Bridge, Paldi Circle, Visat Teen Rasta, Visat P2, cam23, cam27).
- Alert not firing → open **WATCHLIST**, add the exact plate string you see scrolling in the terminal; the next read of it fires the alert.
