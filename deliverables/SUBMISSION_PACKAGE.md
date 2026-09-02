# SENTINEL — Submission Package (master checklist)

**Gujarat Police CCTV Hackathon 2026 — sentinel.gujarat.gov.in portal**

> ## DEADLINE: Sunday 7 September 2026 — submit BEFORE NOON
> Shortlisting happens **that same evening**; judges will be scoring 100+
> submissions in one sitting. Late = dead. Videos are large and the portal
> will be busy — upload the evening of Sept 6 if at all possible.

**Declared solution model:** Hybrid — Model 1 (Camera Registry & GIS,
mandatory) + Model 2/4 (unified viewing + central AI analytics + watchlist
alerts).
**Category:** Category 1 · **Individual** participant.

---

## 1. Requirement → artifact map

| # | Official requirement | Artifact (exact path) | Status | Remaining action |
|---|---|---|---|---|
| 1 | Presentation | `deliverables/SENTINEL_Presentation.pptx` (source: `docs/deck/build_deck.py`, screenshots in `docs/deck/shots/`) | **Ready** (12 slides, score-sheet-mirrored) | Export a portal-safe **PDF copy** (PowerPoint/Keynote → Export as PDF, or `soffice --headless --convert-to pdf`); verify fonts/screenshots survived. Add team/contact details to the title slide if the portal requires them. |
| 2 | High-Level Design (HLD) document | `deliverables/SENTINEL_HLD.pdf` (12 pages, all 3 mermaid diagrams **rendered as vector diagrams**, generated from `docs/HLD.md` via `scripts/export-hld-pdf.py`) | **Ready** | Add team/contact details to the HLD title area if the portal requires them (edit `docs/HLD.md` header → re-run `.venv/bin/python scripts/export-hld-pdf.py` → `cp docs/HLD.pdf deliverables/SENTINEL_HLD.pdf`). Eyeball all 3 diagrams + page breaks once more after any edit. |
| 3 | Demo **Video A** — own feed, 2–3 min | To record → save as `deliverables/SENTINEL_OwnFeed_Demo.mp4` | **Not recorded** (planned Sept 6, ~3 h block) | Record per the shot list in `docs/BATTLE_PLAN.md` §4 (trailer of the live-demo arc) / `docs/SUBMISSION_CHECKLIST.md` §3. 1080p+, cursor visible, voiceover or captions, MP4 (H.264), length verified 2–3 min. Upload (Section 2) and paste the **link** into the portal form. |
| 4a | Demo **Video B** — government feed | To record → save as `deliverables/SENTINEL_GovFeed_Demo.mp4` | **Not recorded** (planned Sept 5 golden run) | Record on the live sandbox grid: catalogue sync shown live, `worker.py --detector anpr` log lines (TCP transport, PTS anchoring, backoff reconnect), real detections on map/alerts, watchlist alert + route for a real plate. Close on the output report. Upload (Section 2), paste **link**. |
| 4b | **Output report** for the government feed (timestamped vehicle/plate detections) | `deliverables/GOV_FEED_OUTPUT_REPORT.md` + **`deliverables/GOV_FEED_OUTPUT_REPORT.pdf`** | **Ready** (30 cams onboarded, 27 plate reads w/ PTS-anchored UTC timestamps + confidences, 266 vehicle-only sightings, per-camera tables) | If a fresher soak is run before Sept 6, regenerate the report from the backend (source of truth) and re-export the PDF. Upload the **PDF** to the portal. |
| 5 | *(Optional)* Hosted/demo instance URL + test credentials | None yet — platform runs locally (backend :8000, frontend :5173) | **Decide by Sept 6** | Either (a) skip — the clean-clone quickstart in `README.md` is the fallback story, or (b) host frontend+backend on a VPS, set `SENTINEL_TOKENS` and hand judges the **viewer** token only (e.g. `tok-view` / role `viewer` — never admin), test from outside the home network and from a logged-out browser. |
| 6 | *(Optional)* Repository link | Local git repo only — **no remote configured yet** | **Push by Sept 6** | Create a private GitHub repo → `git remote add origin … && git push -u origin main`. Verify access per portal instructions (or add judge access notes). Before pushing: `git log -p` spot-check for secrets; confirm `.env`, `sentinel.db`, `scripts/vendor/` handling. Re-test README quickstart from a clean clone. |
| 7 | Apply-Now form answers | Section 4 of this file (150-word + 400-word summaries, tech stack, category) | **Ready** | Copy-paste; keep the word counts if the form enforces limits. |

---

## 2. Upload instructions (videos & documents)

### YouTube (preferred for videos — links stay fast under portal load)

1. studio.youtube.com → Create → Upload videos.
2. Title + description from Section 3 below.
3. Details page: **"No, it's not made for kids"**; Show more → untick "Allow
   embedding" only if the portal requires; leave remixing/comments off
   (Comments: **Off**) — judges need playback, not engagement.
4. Visibility: **Unlisted** (never Private — Private links 404 for judges;
   never Public — no need to be in search).
5. Wait for HD processing to finish (a just-uploaded link plays at 360p);
   check the badge says 1080p before sharing.
6. **Test each link in an incognito/logged-out window** on a phone network
   (not home Wi-Fi) before pasting into the portal.

### Google Drive (fallback / for the PDF report if the portal prefers files-by-link)

1. Upload to a dedicated folder `SENTINEL — Gujarat CCTV Hackathon 2026`.
2. Share → General access: **"Anyone with the link" — Viewer** (not
   Commenter/Editor).
3. Gear icon: leave "Viewers can download" **enabled** (judges may need the
   file offline).
4. Copy link for the **file**, not the folder, unless the portal asks for one
   folder link.
5. Test in incognito.

### Portal uploads

Upload the PPTX (and its PDF copy), `SENTINEL_HLD.pdf`, and
`GOV_FEED_OUTPUT_REPORT.pdf` directly as files where the form has upload
fields; paste video links (and optional repo/hosted URLs) in the link fields.
**Save a screenshot of the confirmation page.**

---

## 3. Suggested video titles + descriptions

### Video A (own feed)

**Title:** `SENTINEL — Plate to Court in 60 Seconds | Own-Feed Demo | Gujarat Police CCTV Hackathon 2026`

**Description:**
> SENTINEL (Hybrid Model 1 + 2/4) — unified CCTV registry, GIS, live viewing,
> ANPR analytics, watchlist alerts and route reconstruction.
> In this 2–3 min demo on the platform's own 50-camera feed: a registration
> number is typed once → the timestamped route is reconstructed
> camera-by-camera on the GIS map → a fuzzy OCR misread is recovered at
> displayed confidence → a physically impossible hop is rejected by the
> physics filter ("214 km/h — discarded") → a live watchlist alert fires and
> is acknowledged into the audit log → a feed is killed and auto-recovers →
> one click exports a SHA-256 hash-chained chain-of-custody Evidence Dossier.
> Category 1, individual submission.

### Video B (government feed)

**Title:** `SENTINEL — Live Government Sandbox Grid (30 Cameras) | Gujarat Police CCTV Hackathon 2026`

**Description:**
> SENTINEL running against the official hackathon CCTV gateway: live catalogue
> sync onboards all 30 heterogeneous government cameras (mixed H.264/H.265,
> mixed resolutions, no hard-coded URLs), RTSP forced over TCP, PTS-anchored
> timestamps, at most 4 concurrent captures (gateway pacing rule), CPU-only
> YOLOv8n + plate localization + OCR producing real number-plate reads —
> shown live on the map, in the alerts feed, and in the timestamped output
> report submitted alongside this video. Category 1, individual submission.

---

## 4. Apply-Now form answers (copy-paste ready)

### Category

**Category 1 — Individual.**
Solution model: **Hybrid — Model 1 (Camera Registry & GIS) + Model 2/4
(unified viewing + central AI analytics + watchlist alerts).**

### Solution summary — 150 words

SENTINEL is an evidence machine: type a registration number once and get a
court-ready answer in sixty seconds. Built as Hybrid Model 1 + 2/4, it
onboarded the full government sandbox — 30 heterogeneous cameras — through
catalogue-driven sync, with RTSP-over-TCP ingestion, PTS-anchored timestamps,
and CPU-only ANPR that produced 27 real plate reads in the first live soak.
Route reconstruction plots a vehicle's timestamped, location-wise movement on
a GIS map; confusion-tolerant matching (0/O, 1/I, 5/S) recovers OCR misreads
with displayed confidence, and a physics filter visibly rejects impossible
hops ("214 km/h — discarded as false match"). One click exports a SHA-256
hash-chained chain-of-custody evidence dossier with snapshots, audit trail
and operator identity. Scaling to 80,000 cameras is computed, not asserted:
edge-first ANPR sends 1–3 Kbps of metadata per camera upstream — video never
leaves departmental DVRs — at ₹3–7k per existing camera, zero new cameras.

### Solution summary — 400 words

Every control room asks the same question: where did this car go? Today the
answer takes days of manually scrubbing footage across departmental silos,
and what is found often dies before court for lack of provable integrity.
SENTINEL answers it in sixty seconds, and ends with a document an
investigating officer can attach to a charge sheet.

SENTINEL is a Hybrid Model 1 + 2/4 platform. Model 1: a catalogue-driven
camera registry and GIS — during evaluation it onboarded the entire
government sandbox (30 heterogeneous cameras, mixed H.264/H.265, mixed
resolutions, multiple departments) through one sync call; no stream URL,
camera id or codec is hard-coded. Model 2/4: unified live viewing (HLS video
wall), central AI analytics, and watchlist alerting over real-time
WebSockets.

Everything claimed is measured. On the live sandbox grid, the CPU-only
pipeline — RTSP forced over TCP, PTS-anchored timestamps that survive the
sandbox's looping feeds, YOLOv8n vehicle detection, dedicated plate
localization, fast-plate-ocr — produced 27 real number-plate reads with
confidences up to 0.88, each stored with a snapshot and a PTS-anchored UTC
timestamp.

Type a plate once and the route engine reconstructs its timestamped,
location-wise movement on the map. Confusion-tolerant matching (0/O, 1/I,
5/S, 8/B) recovers OCR misreads with displayed confidence instead of leaving
holes, and a physics plausibility filter computes implied speed per hop and
visibly rejects impossible transitions ("214 km/h over 3.1 km — discarded as
false ANPR match"): the system models vehicles moving through the world, not
strings matching in a database.

One click exports a chain-of-custody Evidence Dossier: per-sighting frame
snapshots, a SHA-256 hash chain with tamper detection, camera/GPS/timestamp
table, operator identity, and the append-only audit trail of every query.
Role-based access (viewer/operator/admin) gates mutations and exports.

Scale is arithmetic, not adjectives: 80,000 cameras × 2 Mbps centralized is
160 Gbps of impossible backhaul. SENTINEL's edge-first tier runs ANPR on
district edge boxes beside existing DVR/NVRs; only 1–3 Kbps per camera of
detection metadata travels upstream, and video never leaves departmental
storage — maximum use of infrastructure Gujarat already owns, at ₹3–7k per
existing camera versus ₹25k+ per new one.

Operational maturity is demonstrated, not claimed: a per-feed health board
(FPS, latency, live Kbps), backoff reconnect that recovers a killed feed on
stage, and honest failure handling throughout.

Plate to court in sixty seconds — on the cameras Gujarat already owns.

### Tech stack

Python 3.12 · FastAPI · SQLAlchemy + SQLite · OpenCV + FFmpeg (RTSP-over-TCP,
PTS-anchored capture) · Ultralytics YOLOv8n (vehicle detection) ·
open-image-models YOLO-v9-t plate localization · fast-plate-ocr ·
fpdf2 (hash-chained evidence dossier PDF) · React 18 · Vite 5 · Leaflet
(GIS) · hls.js (live video wall) · WebSockets (real-time alerts) ·
token-based RBAC + append-only audit log · pytest regression suite ·
CPU-only inference (no GPU required).

---

## 5. Final pre-submit verification (run Sept 7 morning)

- [ ] Portal form: team details, **Category 1 / Individual**, model
      declaration **Hybrid 1 + 2/4**, summaries pasted (word limits!).
- [ ] All file uploads attached: presentation (PPTX + PDF),
      `SENTINEL_HLD.pdf`, `GOV_FEED_OUTPUT_REPORT.pdf`.
- [ ] Both video links open **logged-out / incognito, on mobile data** and
      play at 1080p; titles/descriptions carry hackathon + team name.
- [ ] Video A verified 2–3 min; Video B shows live catalogue sync + real
      detections + route; neither uses canned footage for the plate trace.
- [ ] Repo link (if given) opens from a logged-out browser; README
      quickstart re-tested from a **clean clone**; no secrets in history;
      `.env` ignored.
- [ ] Hosted URL (if given) reachable from outside the team network;
      **viewer-role** credentials only; they work.
- [ ] Re-download every uploaded file from the portal (or Drive) and open
      it — check the judges' copy, not the local one.
- [ ] Filenames, deck footer, report header all carry team name + hackathon
      name.
- [ ] **Submit before noon.** Save the confirmation screenshot to
      `deliverables/`.
- [ ] Shortlisting is the same evening — after submitting, rehearse the live
      finale; do not touch frozen ingest/PTS code.
