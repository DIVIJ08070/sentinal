# Video shot scripts — the two REQUIRED submission videos

Beat-by-beat recording scripts for a solo participant on macOS. Each video is
recorded in **one continuous take** (trim the ends in QuickTime afterwards —
no cuts inside the take, judges can spot stitched demos). Everything on screen
is the real running stack; **nothing is mocked and the simulator is never run
during either recording.**

- VIDEO A — "Own feed" (2–3 min, target 2:45)
- VIDEO B — "Government feed" (screen recording + the banked
  `deliverables/GOV_FEED_OUTPUT_REPORT.md`, target 5:00)

## Recorder setup (both videos)

1. QuickTime screen recording: `Cmd+Shift+5` → "Record Entire Screen" →
   Options → Microphone: **MacBook Microphone** (narration is spoken live —
   plain English, no jargon; the lines are scripted per beat below).
2. macOS **Do Not Disturb ON** (Control Centre → Focus). Close Slack/Mail.
3. Display at native resolution, browser at 100% zoom, cursor visible.
   Font size in Terminal ≥ 16 pt so log lines are legible at 1080p.
4. Layout used by both scripts: **browser (dashboard, http://localhost:5173)
   on the left ~70% of the screen, Terminal on the right ~30%.**
5. Export: File → Export As → 1080p, H.264 MP4. Verify length (A: 2–3 min
   hard requirement). Filename carries team name + hackathon name.
6. The demo stack must already be up (backend :8000, relay :8888, adapter
   :8891, frontend :5173). **Never restart any of it to record** — check,
   don't touch:
   ```bash
   curl -s localhost:8000/api/stats | head -c 200; echo
   ps aux | grep -c "[h]ls_relay\|[f]fmpeg.*hls"   # expect 8 (relay + 7 ffmpeg pullers)
   ```

---

# VIDEO A — "Own feed" (2–3 minutes)

Mandatory content, mapped to beats: onboarding (beat 2), live/recorded
viewing (beat 3), AI detection + ANPR (beat 4), watchlist correlation
(beat 5), automatic real-time alert + visualisation (beat 6). Mock-ups
disqualify — every detection in this video is a real ANPR read of footage
the participant filmed.

**Decision (simulator):** Video A shows **only** the own-footage flow. The
DB is *not* reseeded (the live stack stays untouched), `scripts/demo.sh` is
*not* run, and no simulator sighting appears on screen: the route search is
scoped to the own plate, so pre-existing government-grid detections cannot
leak into the frame. The seeded watchlist rows are all visibly labelled
"(demo)" and are left alone.

## Preparation (day before, ~1 h + a walk)

### P1. Film the footage
- Phone, landscape, 1080p, **daylight**, 1–2 minutes of local traffic.
- Stand where **plates face the camera** (oncoming traffic): roadside at a
  speed-breaker, a gate, or a footbridge looking at approaching vehicles.
  Vehicles within ~10 m; brace the phone on a railing — no panning.
- AirDrop to the Mac: `/Users/mac/Desktop/own_feed/traffic.mp4`
  (absolute path, no spaces — this path *is* the camera URL).

### P2. Onboard the file as a camera (rehearsal pass)
OpenCV's FFmpeg backend opens plain file paths, so a recorded clip onboards
exactly like an RTSP camera — `rtsp_url` = the absolute file path. Use the
**real lat/lon of the filming spot** (Maps → long-press → copy coordinates).

```bash
curl -s -X POST localhost:8000/api/cameras -H 'Content-Type: application/json' -d '{
  "name": "Own Test Camera",
  "department": "Own Feed Demo",
  "lat": 23.0225, "lon": 72.5714,
  "codec": "h264",
  "rtsp_url": "/Users/mac/Desktop/own_feed/traffic.mp4"
}'
```
Note the returned `"id"` (call it `<ID>`, likely 31). `department` is
required by the schema. Doing this in rehearsal is fine — on recording day
the camera already exists and beat 2 re-shows the identical command against
a **second** file/camera *or* simply replays this call and shows the 409
"already exists" contract response — cleaner: delete nothing, onboard once
**on camera** on recording day and do the rehearsal with a *copy* of the
file at a different path (e.g. `traffic_rehearsal.mp4`) so recording day's
POST is genuinely the first for `traffic.mp4`.

### P3. Dry-run ANPR and pick the watchlist plates
```bash
cd /Users/mac/Desktop/sentinel-hackathon/ingest
../.venv/bin/python worker.py --detector anpr --cameras <REHEARSAL_ID>
# let it run 2 full loops of the clip, then Ctrl-C
curl -s 'localhost:8000/api/detections?camera_id=<REHEARSAL_ID>&limit=100' \
  | ../.venv/bin/python -m json.tool | grep -E '"plate"|"captured_at"|confidence'
```
- Worker note: an explicit `--cameras` id list bypasses the
  catalogue/live-only filter (fixed + committed 2 Sept), so the manual
  camera is captured; verified with a synthetic clip.
- The clip **loops**: at end-of-file the capture sees ~3 s of failed reads,
  treats the stream as lost, and reopens the file from the start (the same
  reconnect + PTS re-anchor path the gateway rules require). So every plate
  read recurs once per loop — that is the alert timing mechanism.
- Pick **1–2 plates that were actually READ** (as-read strings). Note *when*
  in the clip each read happens (the recurring read is what fires the alert
  in beat 6). If a read is a misread of the true plate by one OCR-confusion
  character, prefer adding the TRUE plate — the fuzzy badge on the alert is
  a bonus proof shot. If unsure, the exact as-read string is the guaranteed
  match.
- **If zero plates read:** re-film closer/slower traffic (speed-breaker),
  brighter light. Do not proceed to recording until the dry run reads ≥1
  plate on ≥2 consecutive loops.

## Pre-flight checklist (minutes before recording)

- [ ] Stack up (the two check commands in Recorder setup).
- [ ] `traffic.mp4` at its final absolute path; NOT yet onboarded (P2 note).
- [ ] Terminal right pane: onboarding `curl` pasted and ready (don't run).
- [ ] Terminal second tab: worker command pasted with `--cameras` blank,
      ready to fill with the returned id.
- [ ] Browser on http://localhost:5173, **Cameras tab**, map visible.
- [ ] QuickTime window with `traffic.mp4` open, paused at 0:00, tucked
      behind the browser (Cmd+Tab target for beat 3).
- [ ] Watchlist plates from P3 written on paper.
- [ ] DB not reseeded, simulator not running, `demo.sh` not touched.

## Beats (target 2:45, hard cap 3:00)

| # | Time | Action (exact clicks) | Expected on screen | Narration |
|---|------|------------------------|--------------------|-----------|
| 1 | 0:00–0:15 | Recording starts on the dashboard map. Hover the StatsBar. | Gujarat map, 30 catalogue cameras, live status colours, totals in StatsBar. | "This is SENTINEL. Thirty cameras are already registered from a live catalogue — nothing on this map is hard-coded. I'm now going to onboard a brand-new camera: footage I filmed myself this morning." |
| 2 | 0:15–0:45 | Click into Terminal. Run the prepared `POST /api/cameras` curl. Point at the JSON response id. Click the browser, refresh, pan/zoom map to the new marker. | JSON response with the new camera id; a new marker appears at the real filming location. | "One API call: a name, GPS coordinates of where I stood, and the feed URL — here, a video file, because the ingest treats a recorded file exactly like a live RTSP camera. It's on the map at the real spot I filmed from." |
| 3 | 0:45–1:05 | Cmd+Tab to QuickTime, play `traffic.mp4` for ~8 s, pause. Cmd+Tab back; optionally click one relayed grid camera marker → drawer shows live video for 3–4 s, close drawer. | The raw recorded feed; then (optional) a live government feed playing in the platform's own drawer. | "This is the recorded feed we just onboarded — real traffic, filmed on my phone. The platform also views live feeds — that's a live government camera, covered fully in the second video. Now let's run AI on my footage." |
| 4 | 1:05–1:35 | Terminal tab 2: run `worker.py --detector anpr --cameras <ID>`. Point at the connect log line. Switch to browser, hover StatsBar. | Worker logs: capture start, "connected", PTS lines. StatsBar detection count starts climbing within ~15–20 s. | "The worker opens the feed, anchors every timestamp to the video stream's own clock, and runs vehicle detection plus number-plate recognition — the same pipeline, CPU-only. Watch the detection counter: those are real plate reads from my footage." |
| 5 | 1:35–2:00 | Watchlist tab → Add form: type the P3 plate, label "Suspect vehicle — own feed demo", category `suspect`, priority `high` → Add. | The new entry appears at the top of the watchlist, above the "(demo)"-labelled seeds. | "Now the correlation step. I'm adding one of the vehicles from my footage to the watchlist — live, while the AI is running. From this second, any camera that reads this plate raises an alert on its own." |
| 6 | 2:00–2:20 | Click the Alerts tab and wait (the clip loops; the plate's next read fires it). When the alert card lands: click it, click **Acknowledge**. | Real-time alert card via WebSocket: plate, category, snapshot crop of the actual vehicle, camera name; map pans to Own Test Camera; ack recorded. | "There it is — no human asked for this. The vehicle crossed the camera again, the plate matched the watchlist, and the alert arrived in real time with the photo evidence attached. I acknowledge it, and that acknowledgment lands in the audit log." |
| 7 | 2:20–2:45 | Route tab → type the plate → Search. Hold 5 s on the sightings table. Click **Export dossier** button; let the PDF open for the final 5 s. | Timestamped sightings with snapshot cards, first/last seen stats, marker on the map; then the hash-sealed chain-of-custody PDF. | "Every sighting, timestamped from the stream clock, exportable in one click as a hash-sealed evidence dossier — the same record an investigating officer would attach to a charge sheet. Onboarding to evidence, on my own footage, in under three minutes." |

Stop recording. Trim leader/trailer only.

## Common failures & fallbacks (A)

| Failure | Fallback |
|---|---|
| Alert doesn't fire in beat 6's window | Keep talking through the route beat first, come back to Alerts — the clip loops forever, the read WILL recur (dry run proved it). Trim the wait in the exported video only if the total stays a single take. |
| Watchlist plate never re-reads (marginal read) | Use the exact as-read string from P3, not the "true" plate — exact match is guaranteed on the next loop. |
| Worker exits at start ("no live catalogue cameras") | Wrong id in `--cameras`. Re-run with the id from beat 2's JSON. Harmless on camera: one retry is honest. |
| `curl` 409 "already exists" in beat 2 | The camera was onboarded in rehearsal at this path. Point at the 409 (the API refusing a duplicate is itself a contract behaviour), then continue with the existing id. |
| StatsBar doesn't climb | Give it 30 s (first loop may be mid-gap). If still flat: the ML deps aren't the rehearsal venv — abort take, re-run P3. |
| Total runs over 3:00 | Cut beat 3's optional live-drawer glimpse (–10 s) and shorten beat 4's hover (–5 s). The 2–3 min bound is a hard requirement. |

---

# VIDEO B — "Government feed" (target 5:00)

Companion artifact: `deliverables/GOV_FEED_OUTPUT_REPORT.md` (already
written and banked — 27 timestamped plate reads, 293 detections, 30-camera
sync). The video closes on it.

## Connection budget — the honest arithmetic

The gateway publishes **no numeric connection cap**; its rule 11 is
qualitative: *pace the load, every client gets its own stream copy, open
only cameras actively being processed.* The numbers we have exercised:

- **Standing load right now:** the HLS relay holds **7** RTSP pulls
  (cam01, cam02, cam04, cam05, cam16, cam23, cam27) — that is the budget
  baseline and it stays untouched.
- **Ceiling already exercised all week:** relay 7 + ingest wave of 4
  (worker/soak hard cap) = **11 concurrent**, served by the grid during the
  camera-ranking soak without a single complaint or throttle.
- **This recording:** `soak.py --cams cam06,cam23` opens **one wave of 2**
  (cam23 gets a second stream copy — explicitly allowed and counted).
  Total = 7 + 2 = **9 concurrent, two under the ceiling we have already
  exercised**, leaving headroom for the relay's own reconnects.

**Chosen recipe: do NOT stop or trim the relay.** Restarting the relay to
"free" connections would blank the live camera drawer and the health
history in the middle of the take, and touches the running demo stack for
zero benefit — 9 ≤ 11 already closes the arithmetic. (Only if a future
recording session ever needs more than 2 soak cameras: trim the relay
`--cams` list for that session *before* it starts, never mid-take, and
restore it after. Not needed today.)

cam06 (Timbavadi Gate, 2.25 reads/min — the grid's best) and cam23
(0.58–1.5 reads/min with a recurring plate family) are the demo stars per
`docs/CAMERA_RANKING.md`.

## Pre-flight checklist

- [ ] **Daylight IST** recording slot (the ranking numbers were measured
      ~12:45 IST; several cameras go black/illegible at night).
- [ ] Stack check commands (Recorder setup) pass; relay's 7 ffmpeg pullers
      alive.
- [ ] ML deps import in the venv:
      `.venv/bin/python -c "import ultralytics, fast_plate_ocr"` — silent = OK.
- [ ] Terminal right pane, tab 1 — soak command pasted, not run:
      ```bash
      cd /Users/mac/Desktop/sentinel-hackathon/ingest
      ../.venv/bin/python soak.py --cams cam06,cam23 --minutes 6 --out /tmp/videoB_soak.json
      ```
      (6 min > the 5-min video, so the wave never ends on camera.)
- [ ] Terminal tab 2 — recent-reads watcher pasted, not run:
      ```bash
      while true; do curl -s 'http://localhost:8000/api/detections?limit=6' \
        | /Users/mac/Desktop/sentinel-hackathon/.venv/bin/python -c \
        "import json,sys; [print(d['captured_at'][11:19], 'cam', d['camera_id'], d.get('plate') or '-', d.get('plate_confidence') or '') for d in json.load(sys.stdin)]"; \
        echo ---; sleep 10; done
      ```
- [ ] Browser on http://localhost:5173, **Cameras tab**.
- [ ] `deliverables/GOV_FEED_OUTPUT_REPORT.md` open in a background window
      (rendered preview or the exported PDF), scrolled to the top.
- [ ] Watchlist candidates written down: `CMCI801` (cam23's recurring
      family: CMCC801 / CMCI811 / CMCI401 / CMCT701 / CMEI801 — one-step
      misreads of the same physical plate, per CAMERA_RANKING) — plus
      whatever exact string lands live in tab 2 during the take.

## Beats (target 5:00)

| # | Time | Action (exact clicks) | Expected on screen | Narration |
|---|------|------------------------|--------------------|-----------|
| 1 | 0:00–0:30 | Cold open on the **Cameras tab**. Click **Sync**. Hover StatsBar. | "Syncing…" → table repopulates: 30 cameras, departments, codecs (mixed H.264/HEVC), resolutions; 30 markers on the map. | "This is the government sandbox grid — thirty real cameras across Gujarat. One click pulls the live catalogue: ids, coordinates, codecs. If they add or rename cameras tomorrow, we absorb it — the catalogue is the source of truth, nothing is hard-coded." |
| 2 | 0:30–1:00 | Click **cam01 — Chiman bhai Bridge, Ahmedabad** (row or marker) → camera drawer. Let the live video play 15 s. Close. | Live traffic on the bridge, playing inside the platform's drawer (relayed HLS of the government RTSP feed). | "And this is live — Chiman bhai Bridge in Ahmedabad, right now, relayed through the platform. Every feed you'll see from here on is this real government grid." |
| 3 | 1:00–1:30 | Click the **Health tab**. Point (cursor) at cam01's declared-vs-measured FPS, per-feed Kbps, last-frame age. | Health board: measured FPS beside declared (cam01 declares 30, delivers far less), bandwidth per feed, reconnect counts, metadata-upstream Kbps line. | "We don't trust what a camera claims. This one declares thirty frames a second — we *measure* what it actually delivers. Per-feed bandwidth, last-frame age, reconnects: this is how a control room knows a camera is lying before an operator does." |
| 4 | 1:30–2:00 | Terminal tab 1: run the soak command. Point at the wave line `=== wave: ['cam06', 'cam23'] ===` and the two "status: live" lines. | ANPR pipeline starts on cam06 + cam23: connect logs, PTS anchoring. | "Now live AI on the two most legible cameras — Timbavadi Gate in Junagadh and camera 23. Note the pacing: the relay already holds seven stream copies, this adds two — nine total, inside the load we've exercised against this gateway all week. We open only what we actively process." |
| 5 | 2:00–2:45 | Terminal tab 2: start the watcher loop. Switch to browser, hover StatsBar as detections tick up. Read one fresh plate line aloud from tab 2. | Watcher prints timestamped rows: `cam 6` / `cam 23` with plate strings and confidences; StatsBar detection count climbs. | "Every row is a real read from a government camera, timestamped from the stream's own clock — plates, confidences, landing in the backend as we watch. Camera six alone reads over two plates a minute." |
| 6 | 2:45–3:15 | **Watchlist tab** → Add: plate `CMCI801`, label "Recurring suspect vehicle — cam23 (sandbox)", category `suspect`, priority `high` → Add. If tab 2 just showed a fresh cam06 read, add that exact string as a second entry. | New entries at the top of the watchlist. | "Here's the test that matters: I'm adding a plate that keeps crossing camera 23 to the watchlist — live, while the feed runs. These sandbox feeds loop, so this vehicle *will* come back. The system now owes us an alert with no further human input." |
| 7 | 3:15–4:15 | Click **Alerts tab**. While waiting, briefly revisit Health (10 s) and tab 2's rolling reads. When the alert card lands: click it, note the EXACT/FUZZY badge + match confidence, click **Acknowledge**. | Real-time WebSocket alert: plate, snapshot crop from the government feed, camera 23 (or cam06), match badge — FUZZY shows the misread it recovered (e.g. `CMCC801 → CMCI801`); map pans; ack lands. | "While we wait, the health board keeps score… and there it is. A government camera read the plate, the watchlist matched it — see the badge: the OCR actually misread one character, and the confusion-tolerant matcher recovered it with the confidence shown. This is a real-time alert on a real government feed. Acknowledged, into the audit log." |
| 8 | 4:15–5:00 | Cmd+Tab to the open **GOV_FEED_OUTPUT_REPORT**. Scroll slowly through the 27-read table and the totals. Hold on the closing paragraph. | The banked output report: onboarding method, 27 timestamped plate reads with confidences, per-camera totals, where the data lives on the platform. | "Everything you just watched is written up as the required output report: thirty cameras synced, every plate read timestamped from the stream clock, twenty-seven reads in the reference soak. The report and the platform agree by construction — these rows *are* the backend's records, and any of them exports as a hash-sealed evidence dossier. Real grid, real reads, real alerts." |

Stop recording. Let the soak wave finish on its own (or Ctrl-C after the
recorder is off). Trim ends only.

## Common failures & fallbacks (B)

| Failure | Fallback |
|---|---|
| No alert by 4:15 | Extend beat 7 (soak runs 6 min); swap beats — do the report close, return to Alerts. If the take passes ~6 min, keep rolling and trim the dead wait ONLY between beats, never inside one. Insurance: beat 6's second entry (exact string of a just-landed cam06 read) makes an exact match on the next loop near-certain. |
| cam06 reads slow (wrong time of day) | Abort and rebook a midday IST slot — the ranking rates were measured ~12:45 IST. Never fake it with the simulator. |
| Drawer video won't play in beat 2 | Use another relayed camera (cam16 Visat P2, cam04 Paldi Circle). If all HLS is down, the relay needs attention — postpone the take; do not restart it mid-take. |
| Sync button errors in beat 1 | The adapter (:8891) hiccuped. Click Sync again; the platform tolerates catalogue sync failure by design. One visible retry is honest. |
| Grid endpoint down entirely | The feeds are public and looping 24/7 — rebook. The report is already banked, so shortlisting risk is covered either way. |
| Map pans to a ring around Gandhinagar for cam23 | Expected: sandbox catalogue carries placeholder GIS for unnamed cams. If asked/narrating: "sandbox cameras without published coordinates carry placeholder positions — the pipeline is identical." |

---

## Shared final checks

- [ ] Play both exports start-to-finish with audio; UI text legible at 1080p.
- [ ] Video A length within 2:00–3:00. Video B ≤ ~5:00.
- [ ] No simulator data, no mock detector, no canned clips anywhere in frame.
- [ ] Filenames + report header carry team name and hackathon name.
- [ ] Upload well before the 7 Sept deadline (portal will be busy).
