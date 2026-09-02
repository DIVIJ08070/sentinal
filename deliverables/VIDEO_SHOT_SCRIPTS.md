# Video shot scripts — the two REQUIRED submission videos

Beat-by-beat recording scripts for a solo participant on macOS. Each video is
recorded in **one continuous take** (trim the ends in QuickTime afterwards —
no cuts inside the take, judges can spot stitched demos). Everything on screen
is the real running stack; **nothing is mocked and the simulator is never run
during either recording.**

- VIDEO A — "Own feed" (2–3 min, target 2:45)
- VIDEO B — "Government feed" (screen recording + the banked
  `deliverables/GOV_FEED_OUTPUT_REPORT.md`, target 5:30)

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
   hard requirement). Filename carries participant + hackathon name, e.g. `SENTINEL_OwnFeed_Demo_DivijPatel_GujaratCCTVHackathon2026.mp4`.
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

### P1. Film the footage — TWO spots, same vehicles
The only place a **multi-camera route** can honestly exist in this
submission is our own footage (the sandbox feeds are single looping scenes),
so film **two spots** and make the same vehicle pass both:

- Phone, landscape, 1080p, **daylight**, 1–2 minutes of traffic per spot.
- Pick two points on the **same road**, ~0.5–3 km apart (Maps → long-press
  → copy exact coordinates of each spot; write both down — they go into the
  onboarding calls and drive the route map + implied-speed chip).
- Stand where **plates face the camera** (oncoming traffic): roadside at a
  speed-breaker, a gate, or a footbridge looking at approaching vehicles.
  Vehicles within ~10 m; brace the phone on a railing — no panning.
- **Guaranteeing a shared vehicle across both clips (either works):**
  1. *Traffic overlap:* film spot A, then walk/ride to spot B **in the
     direction the traffic flows** and film within the next ~15 minutes —
     on one road, several vehicles (autos, buses, delivery bikes) recur.
  2. *Own vehicle (deterministic):* brace the phone at spot A, drive your
     own vehicle past it, retrieve the phone, repeat at spot B. Your own
     plate is then guaranteed readable-in-both if the framing is right.
- AirDrop both files: `/Users/mac/Desktop/own_feed/traffic_a.mp4` and
  `/Users/mac/Desktop/own_feed/traffic_b.mp4` (absolute paths, no spaces —
  these paths *are* the camera URLs).

### P2. Onboard the files as cameras (rehearsal pass)
OpenCV's FFmpeg backend opens plain file paths, so a recorded clip onboards
exactly like an RTSP camera — `rtsp_url` = the absolute file path. Use the
**real lat/lon of each filming spot** (they must differ — the GIS distance
between them is what the route's leg-km / implied-speed chip computes).

```bash
curl -s -X POST localhost:8000/api/cameras -H 'Content-Type: application/json' -d '{
  "name": "Own Camera A — <spot A landmark>",
  "department": "Own Feed Demo",
  "lat": <SPOT_A_LAT>, "lon": <SPOT_A_LON>,
  "codec": "h264",
  "rtsp_url": "/Users/mac/Desktop/own_feed/traffic_a.mp4"
}'
curl -s -X POST localhost:8000/api/cameras -H 'Content-Type: application/json' -d '{
  "name": "Own Camera B — <spot B landmark>",
  "department": "Own Feed Demo",
  "lat": <SPOT_B_LAT>, "lon": <SPOT_B_LON>,
  "codec": "h264",
  "rtsp_url": "/Users/mac/Desktop/own_feed/traffic_b.mp4"
}'
```
Note the returned ids (call them `<ID_A>`/`<ID_B>`, likely 31/32).
`department` is required by the schema. Doing this in rehearsal is fine —
but cleaner: delete nothing, onboard once **on camera** on recording day and
do the rehearsal with *copies* of the files at different paths (e.g.
`traffic_a_rehearsal.mp4`) so recording day's POSTs are genuinely the first
for the final paths.

### P3. Dry-run ANPR and pick the plates
```bash
cd /Users/mac/Desktop/sentinel-hackathon/ingest
../.venv/bin/python worker.py --detector anpr --cameras <REHEARSAL_ID_A>,<REHEARSAL_ID_B>
# let it run 2 full loops of each clip, then Ctrl-C
curl -s 'localhost:8000/api/detections?camera_id=<REHEARSAL_ID_A>&limit=100' \
  | ../.venv/bin/python -m json.tool | grep -E '"plate"|"captured_at"|confidence'
# repeat for <REHEARSAL_ID_B>
```
- Worker note: an explicit `--cameras` id list bypasses the
  catalogue/live-only filter (fixed + committed 2 Sept), so the manual
  cameras are captured; verified with a synthetic clip.
- Each clip **loops**: at end-of-file the capture sees ~3 s of failed reads,
  treats the stream as lost, and reopens the file from the start (the same
  reconnect + PTS re-anchor path the gateway rules require). So every plate
  read recurs once per loop — that is the alert timing mechanism.
- **Find the route star:** a plate (or one-confusion-character variants of
  it) read at BOTH cameras. That plate's route search in beat 7 is the
  submission's only honest **multi-camera route**: two cameras, an accepted
  hop with a leg-km / implied-speed chip. Because the clips loop, later
  re-reads imply impossible back-and-forth hops — the route view greys
  those out with the physics reason, which is a bonus proof shot on REAL
  footage, narrated honestly (see beat 7).
- Also pick **1–2 plates** for the watchlist alert (as-read strings from
  either camera). If a read is a misread of the true plate by one
  OCR-confusion character, prefer adding the TRUE plate — the fuzzy badge
  on the alert is a bonus proof shot. If unsure, the exact as-read string
  is the guaranteed match.
- **If zero plates read at one spot:** re-film that spot (closer/slower
  traffic, brighter light). Do not proceed to recording until the dry run
  reads ≥1 plate per camera on ≥2 consecutive loops, and ≥1 plate is shared
  across both cameras. (If after honest effort no shared plate exists, fall
  back to the single-camera script — never stitch or fake the second
  sighting.)

## Pre-flight checklist (minutes before recording)

- [ ] Stack up (the two check commands in Recorder setup).
- [ ] `traffic_a.mp4` + `traffic_b.mp4` at their final absolute paths; NOT
      yet onboarded (P2 note).
- [ ] Terminal right pane: BOTH onboarding `curl`s pasted and ready (don't
      run).
- [ ] Terminal second tab: worker command pasted with `--cameras` blank,
      ready to fill with the two returned ids.
- [ ] Browser on http://localhost:5173, **Cameras tab**, map visible.
- [ ] QuickTime window with `traffic_a.mp4` open, paused at 0:00, tucked
      behind the browser (Cmd+Tab target for beat 3).
- [ ] Route-star plate + watchlist plates from P3 written on paper.
- [ ] Alerts tab: stale demo alerts show as *Acknowledged* (they were acked
      2 Sept) — set the Alerts status filter to **New** so the frame starts
      clean.
- [ ] DB not reseeded, simulator not running, `demo.sh` not touched.

## Beats (target 2:45, hard cap 3:00)

| # | Time | Action (exact clicks) | Expected on screen | Narration |
|---|------|------------------------|--------------------|-----------|
| 1 | 0:00–0:15 | Recording starts on the dashboard map. Hover the StatsBar. | Gujarat map, 30 catalogue cameras, live status colours, totals in StatsBar. | "This is SENTINEL. Thirty cameras are already registered from a live catalogue — nothing on this map is hard-coded. I'm now going to onboard two brand-new cameras: footage I filmed myself, at two spots on the same road." |
| 2 | 0:15–0:45 | Click into Terminal. Run BOTH prepared `POST /api/cameras` curls back-to-back. Point at the two JSON response ids. Click the browser, refresh, pan/zoom map to the two new markers. | Two JSON responses with the new camera ids; two new markers appear at the real filming locations. | "Two API calls: a name, the GPS coordinates of where I stood, and the feed URL — here, video files, because the ingest treats a recorded file exactly like a live RTSP camera. Both are on the map at the real spots I filmed from — half a kilometre apart on the same road." |
| 3 | 0:45–1:00 | Cmd+Tab to QuickTime, play `traffic_a.mp4` for ~6 s, pause. Cmd+Tab back. | The raw recorded feed from spot A. | "This is camera A's feed — real traffic, filmed on my phone. Live government feeds are covered fully in the second video. Now let's run AI on my footage." |
| 4 | 1:00–1:35 | Terminal tab 2: run `worker.py --detector anpr --cameras <ID_A>,<ID_B>`. Point at the two connect log lines. Switch to browser, hover StatsBar. | Worker logs: two capture starts, "connected", PTS lines. StatsBar detection count starts climbing within ~15–20 s. | "One worker opens both feeds, anchors every timestamp to each video stream's own clock, and runs vehicle detection plus number-plate recognition — the same pipeline, CPU-only. Watch the detection counter: those are real plate reads from my footage." |
| 5 | 1:35–2:00 | Watchlist tab → Add form: type the P3 plate, label "Suspect vehicle — own feed demo", category `suspect`, priority `high` → Add. | The new entry appears at the top of the watchlist, above the "(demo)"-labelled seeds. | "Now the correlation step. I'm adding one of the vehicles from my footage to the watchlist — live, while the AI is running. From this second, any camera that reads this plate raises an alert on its own." |
| 6 | 2:00–2:20 | Click the Alerts tab and wait (the clip loops; the plate's next read fires it). When the alert card lands: click it, click **Acknowledge**. | Real-time alert card via WebSocket: plate, category, snapshot crop of the actual vehicle, camera name; map pans to Own Test Camera; ack recorded. | "There it is — no human asked for this. The vehicle crossed the camera again, the plate matched the watchlist, and the alert arrived in real time with the photo evidence attached. I acknowledge it, and that acknowledgment lands in the audit log." |
| 7 | 2:20–2:50 | Route tab → type the **route-star plate** (read at BOTH cameras, per P3) → Search. Hold 5 s on the map polyline + accepted-hop chip; if a loop-induced re-read produced a greyed rejected hop, point at its tooltip for 2 s. Click **Export dossier**; let the PDF open for the final 5 s. | A genuine two-camera route: numbered timestamped sightings at Camera A then Camera B, polyline between the real GPS spots, leg-km / implied-speed chip on the accepted hop (and, when the loops re-read, a greyed physics-rejected hop with its plain-language reason); then the hash-sealed chain-of-custody PDF. | "And the test case: this vehicle passed both my cameras. The route reconstructs camera-by-camera — the hop between them carries the real distance and the implied speed, computed from the stream clocks. [If a rejected hop is visible:] The greyed hop is the physics filter working on real footage — the looping file re-read the plate at an impossible implied speed, and the system discarded it and says why. One click exports it all as a hash-sealed evidence dossier — the record an investigating officer would attach to a charge sheet. Onboarding to a multi-camera route to evidence, on my own footage, in under three minutes." |

Stop recording. Trim leader/trailer only.

## Common failures & fallbacks (A)

| Failure | Fallback |
|---|---|
| Alert doesn't fire in beat 6's window | Keep talking through the route beat first, come back to Alerts — the clip loops forever, the read WILL recur (dry run proved it). Trim the wait in the exported video only if the total stays a single take. |
| Watchlist plate never re-reads (marginal read) | Use the exact as-read string from P3, not the "true" plate — exact match is guaranteed on the next loop. |
| Worker exits at start ("no live catalogue cameras") | Wrong id in `--cameras`. Re-run with the id from beat 2's JSON. Harmless on camera: one retry is honest. |
| `curl` 409 "already exists" in beat 2 | The camera was onboarded in rehearsal at this path. Point at the 409 (the API refusing a duplicate is itself a contract behaviour), then continue with the existing id. |
| StatsBar doesn't climb | Give it 30 s (first loop may be mid-gap). If still flat: the ML deps aren't the rehearsal venv — abort take, re-run P3. |
| Total runs over 3:00 | Shorten beat 3's QuickTime glimpse to 3 s (–5 s), beat 4's hover (–5 s), and skip the rejected-hop pointing in beat 7 (–5 s). The 2–3 min bound is a hard requirement. |
| Route star only read at one camera on recording day | The clips are the same files that passed P3 — re-run the route search after one more loop (~2 min); the read WILL recur. If the take is at risk, fall back to the single-camera route on the watchlist plate and keep the honest narration — never claim a hop that is not on screen. |

---

# VIDEO B — "Government feed" (target 5:30)

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
- **This recording:** `worker.py --detector anpr --cameras 6,23` opens
  **2 captures** (cam06 + cam23; cam23 gets a second stream copy —
  explicitly allowed and counted). Total = 7 + 2 = **9 concurrent, two
  under the ceiling we have already exercised**, leaving headroom for the
  relay's own reconnects.

  **Why the worker and not `soak.py`:** the worker posts *measured* health
  heartbeats every 10 s (`fps_measured` = real delivered frame rate,
  `bandwidth_kbps` from measured resolution × measured fps, last-frame
  age, reconnects — `ingest/worker.py` `on_metrics`), so the cam06/cam23
  rows on the Health board update live on camera with genuinely measured
  numbers. `soak.py` posts detections but no metrics heartbeats — with it,
  every number on the board would still be whatever the morning demo
  harness posted, and the narration would be pointing at stale synthetic
  values while saying "we measure". Never do that.

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
- [ ] Terminal right pane, tab 1 — worker command pasted, not run:
      ```bash
      cd /Users/mac/Desktop/sentinel-hackathon/ingest
      ../.venv/bin/python worker.py --detector anpr --cameras 6,23
      ```
      (6 and 23 are the backend DB ids of cam06/Timbavadi Gate and cam23 —
      confirm with `curl -s localhost:8000/api/cameras` if the DB was ever
      re-synced. The worker runs until Ctrl-C, so it never ends on camera;
      stop it only after the recorder is off.)
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

## Beats (target 5:30)

Note the order: the workers start **before** the Health beat, so by the time
the board is on screen the cam06/cam23 rows carry genuinely **measured**
numbers (the worker posts a measured heartbeat every 10 s). Never point at a
row and call it "measured" unless a live worker is attached to that camera.

| # | Time | Action (exact clicks) | Expected on screen | Narration |
|---|------|------------------------|--------------------|-----------|
| 1 | 0:00–0:30 | Cold open on the **Cameras tab**. Click **Sync**. Hover StatsBar. | "Syncing…" → table repopulates: 30 cameras, departments, codecs (mixed H.264/HEVC), resolutions; 30 markers on the map. | "This is the government sandbox grid — thirty real cameras across Gujarat. One click pulls the live catalogue: ids, coordinates, codecs. If they add or rename cameras tomorrow, we absorb it — the catalogue is the source of truth, nothing is hard-coded." |
| 2 | 0:30–1:00 | Click **cam01 — Chiman bhai Bridge, Ahmedabad** (row or marker) → camera drawer. Let the live video play 15 s. Close. | Live traffic on the bridge, playing inside the platform's drawer (relayed HLS of the government RTSP feed). | "And this is live — Chiman bhai Bridge in Ahmedabad, right now, relayed through the platform. Every feed you'll see from here on is this real government grid." |
| 3 | 1:00–1:30 | Terminal tab 1: run the worker command. Point at the two "connected" / heartbeat log lines. | ANPR pipeline starts on cam06 + cam23: connect logs, PTS anchoring, first metrics heartbeats. | "Now live AI on the two most legible cameras — Timbavadi Gate in Junagadh and camera 23. Note the pacing: the relay already holds seven stream copies, this adds two — nine total, inside the load we've exercised against this gateway all week. We open only what we actively process." |
| 4 | 1:30–2:00 | Click the **Health tab**. Point (cursor) at the **cam23** and **cam06** rows: declared vs measured FPS, per-feed Kbps, last-frame age — watch a value refresh. | Health board: cam06/cam23 rows updating every ~10 s with measured values from the workers just started (camera 23 declares 25 fps — the measured column shows what it actually delivers right now); other rows show their last recorded heartbeat. | "These two rows are being measured right now by the workers we just started: real delivered frame rate, real bandwidth, refreshed every ten seconds — camera 23 *declares* twenty-five frames a second; the measured column is what it actually delivers. The other rows hold each camera's last recorded heartbeat from this morning's demo harness — the board only ever shows what was actually reported, and only a camera with a live worker attached is measured in real time. We open only what we actively process." |
| 5 | 2:00–2:45 | Terminal tab 2: start the watcher loop. Switch to browser, hover StatsBar as detections tick up. Read one fresh plate line aloud from tab 2. | Watcher prints timestamped rows: `cam 6` / `cam 23` with plate strings and confidences; StatsBar detection count climbs. | "Every row is a real read from a government camera, timestamped from the stream's own clock — plates, confidences, landing in the backend as we watch. Camera six alone reads over two plates a minute." |
| 6 | 2:45–3:15 | **Watchlist tab** → Add: plate `CMCI801`, label "Recurring suspect vehicle — cam23 (sandbox)", category `suspect`, priority `high` → Add. If tab 2 just showed a fresh cam06 read, add that exact string as a second entry. | New entries at the top of the watchlist. | "Here's the test that matters: I'm adding a plate that keeps crossing camera 23 to the watchlist — live, while the feed runs. These sandbox feeds loop, so this vehicle *will* come back. The system now owes us an alert with no further human input." |
| 7 | 3:15–4:15 | Click **Alerts tab**. While waiting, briefly revisit Health (10 s — the two measured rows again) and tab 2's rolling reads. When the alert card lands: click it, note the EXACT/FUZZY badge + match confidence, click **Acknowledge**. | Real-time WebSocket alert: plate, snapshot crop from the government feed, camera 23 (or cam06), match badge — FUZZY shows the misread it recovered (e.g. `CMCC801 → CMCI801`); map pans; ack lands. | "While we wait, the health board keeps score… and there it is. A government camera read the plate, the watchlist matched it — see the badge: the OCR actually misread one character, and the confusion-tolerant matcher recovered it with the confidence shown. This is a real-time alert on a real government feed. Acknowledged, into the audit log." |
| 8 | 4:15–4:45 | **Route tab** → type `CMCI801` → Search. Hold on the sightings table; point at the fuzzy chips and the `matched_from` reads (`CMCC801`, `CMEI801`, `CMCI811`, `CMCI401`). | Timestamped sightings of the recurring cam23 vehicle: exact read at 1.00 plus fuzzy-recovered misreads with confidence chips, first/last seen stats, marker on the map. | "And the route view for that same vehicle: every sighting timestamped from the stream clock, and look at the recoveries — the OCR read this plate four different ways, and the matcher pulled every misread back to the same vehicle, each labelled with its confidence, never silently merged. One honest caveat: these sandbox feeds are single looping scenes, so a cross-camera journey physically cannot exist here — the multi-camera route with the physics filter is demonstrated on our own two-camera footage in the companion video." |
| 9 | 4:45–5:30 | Cmd+Tab to the open **GOV_FEED_OUTPUT_REPORT**. Scroll slowly through the 27-read table and the totals. Hold on the closing paragraph. | The banked output report: onboarding method, 27 timestamped plate reads with confidences, per-camera totals, where the data lives on the platform. | "Everything you just watched is written up as the required output report: thirty cameras synced, every plate read timestamped from the stream clock, twenty-seven reads in the reference soak. The report and the platform agree by construction — these rows *are* the backend's records, and any of them exports as a hash-sealed evidence dossier. Real grid, real reads, real alerts." |

Stop recording. Ctrl-C the worker only after the recorder is off. Trim ends
only.

## Common failures & fallbacks (B)

| Failure | Fallback |
|---|---|
| No alert by 4:15 | Extend beat 7 (the worker runs until Ctrl-C); swap beats — do the route + report close, return to Alerts. If the take passes ~6 min, keep rolling and trim the dead wait ONLY between beats, never inside one. Insurance: beat 6's second entry (exact string of a just-landed cam06 read) makes an exact match on the next loop near-certain. |
| Route search in beat 8 comes back empty | You typed a different spelling than the stored reads — search `CMCI801` exactly (the historical reads from the banked soak are already in the DB, so the beat cannot be empty unless the DB was reseeded — which this script forbids). |
| Health rows for cam06/cam23 not updating in beat 4 | The worker isn't connected yet — give it 20 s (metrics post every 10 s after connect), show tab 1's log lines meanwhile. Never narrate any OTHER row as "measured": rows without a live worker show their last recorded heartbeat, and saying otherwise is a fabrication a judge can catch by cross-checking the submitted report. |
| cam06 reads slow (wrong time of day) | Abort and rebook a midday IST slot — the ranking rates were measured ~12:45 IST. Never fake it with the simulator. |
| Drawer video won't play in beat 2 | Use another relayed camera (cam16 Visat P2, cam04 Paldi Circle). If all HLS is down, the relay needs attention — postpone the take; do not restart it mid-take. |
| Sync button errors in beat 1 | The adapter (:8891) hiccuped. Click Sync again; the platform tolerates catalogue sync failure by design. One visible retry is honest. |
| Grid endpoint down entirely | The feeds are public and looping 24/7 — rebook. The report is already banked, so shortlisting risk is covered either way. |
| Map pans to a ring around Gandhinagar for cam23 | Expected: sandbox catalogue carries placeholder GIS for unnamed cams. If asked/narrating: "sandbox cameras without published coordinates carry placeholder positions — the pipeline is identical." |

---

## Shared final checks

- [ ] Play both exports start-to-finish with audio; UI text legible at 1080p.
- [ ] Video A length within 2:00–3:00. Video B ≤ ~5:30.
- [ ] No simulator data, no mock detector, no canned clips anywhere in frame.
- [ ] Filenames + report header carry the participant name (Divij Patel — Individual, Category 1) and hackathon name.
- [ ] Upload well before the 7 Sept deadline (portal will be busy).
