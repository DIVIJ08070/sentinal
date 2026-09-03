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

---

## 4. VIDEO A on the government sandbox cameras ("CCTV cameras of your choice")

The own-feed rule allows any camera you choose. Using the sandbox is genuinely live and
needs no filming — but Video A must then visibly do the OWN-FEED jobs (choose + onboard a
camera, live viewing, ANPR, watchlist correlation, alert), not repeat Video B's catalogue tour.

Pre-flight (same as §0): run `loop_phase.py`, start `demo-live.sh` on the READY cameras,
wait for reads to scroll. Keep the ALERTS tab open and the terminal beside it.

| Beat | Do | Say |
|---|---|---|
| A1 (0:00) | CAMERAS tab, filter to the READY camera (e.g. *Timbavadi Gate, Junagadh*) | "For the own-feed demo I'm choosing one live camera from the grid — Timbavadi Gate, Junagadh." |
| A2 (0:15) | Click it → live video plays; point at its RTSP URL in the drawer | "Onboarded from its RTSP stream over TCP — any vendor camera integrates the same way, no change to the source." |
| A3 (0:40) | Terminal: plate reads scrolling | "The AI pipeline is reading plates off this feed right now — vehicle detection, plate localisation, OCR — each read PTS-timestamped with a confidence." |
| A4 (1:05) | WATCHLIST tab: show the armed plate(s); if a fresh read scrolled, add THAT plate live | "Vehicles of interest live here — I'm adding a plate this camera just read." |
| A5 (1:25) | ALERTS tab: the alert fires when the vehicle returns (or show the most recent live alert card if you're editing clips together) | "The moment the camera sees it again — alert, under a second, with the camera frame as evidence." |
| A6 (1:50) | Click the alert snapshot | "That is the actual frame the camera captured — camera-based, not typed in." |
| A7 (2:05) | ROUTE tab: trace that plate; Export Evidence Dossier | "Every sighting, timestamped, on the map — and a hash-sealed dossier in one click." |
| A8 (2:30) | Close on the map | "Live camera in, court-ready evidence out, in under three minutes." |

Recording tip: the alert in A5 depends on the vehicle's loop returning. Record A1–A4 and
A6–A8 in one take, then keep a background QuickTime recording running until the alert
fires (I will ping you the exact time) and splice that 20-second clip in as A5. Say
plainly on camera that the footage loops.

- Terminal shows `RTSP open failed` on every camera / relay pullers exit immediately →
  the gateway requires credentials (`401 Unauthorized`, in force since 3 Sept: registered
  email + access password embedded in the URL). In the terminal that runs `demo-live.sh`
  and the relay: `export GRID_RTSP_AUTH='your-registered-email@domain:ACCESS-PASSWORD'`
  (your own portal credential — never share it; the `@` is encoded for you), then start
  both. See docs/REAL_GRID.md.

---

## 5. Proving it is LIVE (not static data) — strongest first

1. **Cause → effect with an input that did not exist a minute ago.** Read a plate off the
   terminal as it scrolls, type it into WATCHLIST on camera, let the alert fire on the
   vehicle's next pass. Static data cannot answer an input the judges just watched you create.
   (On evaluation day the judges' own plate plays this role — rehearse it exactly this way.)
2. **Three clocks that agree.** In one frame: the camera's burned-in clock in the live video,
   the detection timestamp in the alert card, and the Mac menu-bar clock — all advancing.
3. **Counters that move while they watch.** The stats bar's **LAST READ — n s ago** heartbeat
   (green = data arriving now), detections climbing, reads scrolling, a new alert card sliding in.
4. **Break something and watch it heal.** Ctrl-C the relay for one camera on screen → HEALTH
   shows it drop and the reconnect count tick up → it recovers. Nobody scripts a failure.
5. **Mint the evidence dossier after the live alert** — its generated_at and hash chain are
   stamped in front of them.
6. **Raw API for the technical jury:** `curl localhost:8000/api/detections?limit=3` — JSON with
   timestamps from seconds ago.

---

## 6. AI view (green boxes) and the two demo modes

**AI view** — in the camera drawer (and each video-wall tile) a toggle **Live video | AI view**.
AI view shows the worker's own analysed frames: **green boxes = vehicles (YOLO)**, **yellow boxes =
localised plates**, labelled with the read registration + confidence, plus a HUD (camera, UTC capture
time, vehicle/plate counts). It exists only for cameras the worker is analysing (those in `DEMO_CAMS`).
On camera: switch the drawer to AI view while narrating "this is what the AI sees — every vehicle boxed,
every plate localised and read, live."

**Modes** (one word on the launcher; needs a worker restart = password prompt):
```bash
MODE=video  GRID_EMAIL=you@example.com scripts/live-with-auth.sh   # cam06 only, frames analysed 2x faster -> most reads/min (for the take)
MODE=normal GRID_EMAIL=you@example.com scripts/live-with-auth.sh   # cam06 + cam23 + cam27 -> multi-camera logs (default)
```
Tip: a single camera also frees a lot of CPU (four live ANPR streams load a 12-core Mac heavily),
so the AI view runs smoother in `video` mode.

---

## 7. Genuine-only mode (simulator data hidden)

The backend now hides simulator/mock-sourced detections, alerts, routes and stats by default
(`SENTINEL_HIDE_DETECTORS="simulator,mock"`; set it to "" to show the scripted demo journey again).
Nothing is deleted — it is a view filter. Consequences for the take:
- ALERTS shows only live alerts, each with the real vehicle crop from the camera frame.
- For the ROUTE beat use a plate that was read live (e.g. the one that just alerted): it shows every
  pass of that vehicle on its camera, ~12.6 min apart on cam06 — say on camera that looped sandbox
  footage cannot host a cross-camera journey; the same engine reconstructs one on the evaluation grid.
- `scripts/demo.sh` / `ingest/simulator.py` are no longer needed for the live demo.
