# Submission Checklist — Gujarat Police CCTV Hackathon 2026

> ## DEADLINE: 7 September 2026
>
> Upload everything to the sentinel.gujarat.gov.in portal **before** the
> deadline. Do not leave uploads for the last evening — the videos are large
> and the portal will be busy.

Solution model declared on submission: **Hybrid — Model 1 (Registry & GIS) +
Model 2/4 (unified viewing + central AI analytics + watchlist alerts)**.

---

## Deliverables

### 1. Presentation deck

- [ ] Deck prepared (10–15 slides) covering: problem framing, hybrid model
      choice, architecture (reuse the mermaid diagrams from
      [HLD.md](HLD.md) §1 and §6.1 as images), the demo storyline,
      scalability-to-80k summary (§6), security/privacy posture (§7),
      VAHAN/SARTHI/eGujCop readiness (§10), phased rollout + cost sketch (§11).
- [ ] One slide dedicated to the **evaluation test case**: designated plate →
      alerts → full timestamped route on the map. This is what judges score;
      make it the centrepiece, not an afterthought.
- [ ] One slide on gateway-rule compliance — the README's checklist→file
      mapping table condenses to a strong "we did the homework" slide.
- [ ] Exported as PDF (portal-safe) alongside the source file.

### 2. High-Level Design document

- [ ] [docs/HLD.md](HLD.md) reviewed end-to-end; numbers and assumptions
      still match the code as built.
- [ ] Exported to PDF for the portal (mermaid diagrams rendered, not raw
      fenced code — render via VS Code/mermaid-cli and check page breaks).
- [ ] Team/contact details added to the title area as the portal requires.

### 3. Demo video on OWN feed (2–3 minutes)

Record the scripted demo end-to-end on this platform. Suggested shot list
(matches `scripts/demo.sh` exactly, so it is fully rehearsable):

- [ ] 0:00 — open on the map at http://localhost:5173: ~50 catalogue cameras
      across Gujarat, markers coloured by status, StatsBar totals. One
      sentence: "catalogue-driven onboarding — nothing is hard-coded".
- [ ] 0:25 — Cameras tab / marker click → CameraDrawer with camera details and
      live HLS preview (or the graceful "stream unavailable" fallback), and a
      short glimpse of the VideoWall.
- [ ] 0:45 — Watchlist tab: show seeded entries incl. `GJ01AB1234`
      ("Stolen vehicle — FIR …"); add one entry live to show CRUD.
- [ ] 1:00 — run `./scripts/demo.sh` in a visible terminal; as the simulator
      posts sightings, alerts stream into the Alerts tab in real time
      (WebSocket), cards show plate/category/snapshot, map pans to each
      camera; acknowledge one alert. Point out a **fuzzy** match badge if one
      fires — it demonstrates OCR-confusion matching.
- [ ] 1:45 — Route tab: search `GJ01AB1234` → numbered, timestamped route
      polyline on the map + sightings table + stats (first/last seen, cameras,
      distance km). Hold on this screen — it is the hackathon test case.
- [ ] 2:15 — close with the terminal showing the six demo steps and one line
      on switching to the real gateway (`SENTINEL_HOST` + `--detector anpr`).
- [ ] Screen-recorded at 1080p+, cursor visible, UI text legible; voiceover or
      captions; length verified 2–3 min; exported MP4 (H.264).

### 4. Demo video on GOVERNMENT feed + output report

On hackathon evaluation access, repeat against the official gateway:

- [ ] `pip install -r ingest/requirements-ml.txt` done in advance (torch
      downloads are big — never on the day's clock).
- [ ] `SENTINEL_HOST=<gov host>` exported; backend restarted;
      `POST /api/cameras/sync` shown pulling the **real** catalogue (record
      this — it proves live integration, cameras/ids can change and we absorb it).
- [ ] `worker.py --detector anpr --max-cameras 4` running: show the log lines
      proving the rules — TCP transport, PTS anchoring, a reconnect with
      backoff if one occurs, non-fatal decoder warnings on join.
- [ ] Real detections appearing (map + Alerts feed); the **designated
      evaluation plate** entered into the watchlist the moment it is
      announced; alert firing on it; route reconstruction for it shown on the
      map with timestamps.
- [ ] Video recorded and exported as for deliverable 3.
- [ ] **Output report** written up: cameras synced (count, departments,
      codecs), cameras processed, detections/plates read (counts +
      confidence spread), watchlist alerts raised (with timestamps and
      match types), the designated vehicle's route table (camera, location,
      timestamp — export straight from `GET /api/vehicles/{plate}/route`),
      plus screenshots. PDF.

### 5. Links, credentials, repository

- [ ] Repository pushed and access verified from a logged-out browser (or
      access instructions for a private repo as the portal specifies).
- [ ] README quickstart re-tested **from a clean clone on a clean machine**:
      `python3 -m venv .venv` → pip install both requirements files →
      `npm install` → three scripts → demo works. Nothing depends on this
      team's laptops.
- [ ] Any hosted/demo instance URL + login credentials for judges prepared
      (viewer-role credentials, not admin), tested from outside the team
      network.
- [ ] No secrets in the repo (`git log -p` spot-check; `.env` ignored).
- [ ] Portal submission form: team details, model declaration (Hybrid
      1 + 2/4), all files uploaded, links pasted, **confirmation
      screenshot saved**.

---

## Final pass (day before the deadline)

- [ ] All four artifacts open correctly after download from the portal
      (re-download and check — not just the local copies).
- [ ] Video filenames, deck footer and report header all carry team name +
      hackathon name.
- [ ] One full rehearsal of the live pitch: clean clone → demo running in
      under 10 minutes.
