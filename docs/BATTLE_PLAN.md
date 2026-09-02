# SENTINEL Battle Plan — Gujarat Police CCTV Hackathon 2026

**Synthesis basis:** "Plate-to-Court in 60 Seconds" scored highest across all three judges (25/30 combined) and becomes the spine. Every judge-endorsed "steal" that fits the solo 4.5-day budget is grafted in: the physics-filtered rejected hop (endorsed by all 3 judges), the score-sheet-mirrored deck (all 3), the ₹/camera TCO slide (all 3), the trailer-cut video and rehearsal protocol (2 judges), and the triple-layer fallback stack (1 judge, high value/low cost). Conflicts resolved by (official score-sheet points) / (solo effort).

---

## 1. The Winning Concept

### **"Plate to Court in 60 Seconds" — the Evidence Machine**

One hundred teams will show YOLO boxes over traffic video and say "Kafka, microservices, scalable." We compete as something else entirely: the evidence machine. The demo starts with the judges' own plate number and ends, under a minute later, with a court-admissible, hash-sealed evidence dossier in their hands — plate typed once, route reconstructed camera-by-camera on the GIS map with per-hop confidence, watchlist alert firing live, one click to a chain-of-custody PDF an investigating officer could attach to a charge sheet. Underneath the story is the engineering that makes it un-fumble-able: confusion-tolerant plate matching so an O/0 misread still finds the vehicle, a physics filter that visibly rejects impossible hops ("214 km/h over 3.1 km — discarded as false match"), PTS-anchored timestamps that survive the sandbox's deliberately broken looping feeds, and an edge-first architecture whose 80,000-camera bandwidth math is computed, not asserted — on the cameras and DVRs Gujarat already owns, at ₹3–7k per existing camera instead of ₹25k+ per new one. Each of the three jury seats gets a designed flip-moment: the DGP hears his control-room question answered in police language with a cost he can carry into a budget meeting; the NFSU forensics chair is handed chain-of-custody by a hackathon team for the first time in their life; the DA-IICT jury watches us kill a feed on purpose and recover it. Secure, scalable, interoperable, cost-effective, maximum use of existing infrastructure — the brief's own sentence, demonstrated instead of quoted.

---

## 2. Why This Beats the Field

- **Criterion 1 (government test case) — insured twice, not hoped for.** The single biggest time block goes to hardening the judge-plate → route golden path on the *real* ~30-cam government sandbox grid, rehearsed cold-start daily. On top of raw recall tuning sits the grafted Route-Engine matcher: Indian-plate-syntax canonicalization plus weighted edit distance over OCR confusion pairs (0/O, 1/I, 5/S, 8/B, 6/G) — so when the day's unknown plate gets misread on camera 3 of 50, exact-match teams show a route with holes and we show a recovered sighting at 0.93 displayed confidence.
- **Bonus: multi-camera correlation + Criterion 5 (analytics quality) — the uncounterfeitable 30 seconds.** All three judges independently flagged the physics-filtered rejected hop as the hardest-to-fake signal in the field: a greyed-out hop on the map with the tooltip "implied speed 214 km/h — physically impossible, discarded as false ANPR match." It proves the system models vehicles moving through the world, not strings matching in a database. No YOLO-wrapper team can counterfeit it, and a forensics professor and a DGP both parse it instantly.
- **Bonus: cybersecurity/privacy/auditability/RBAC + NFSU seat — the Evidence Dossier.** One click on a route exports a PDF with per-sighting frame snapshots, SHA-256 hash chain, camera/GPS/timestamp table, operator identity, and query audit trail under a chain-of-custody header. CCTV evidence in India routinely dies between control room and charge sheet; NFSU is a forensics university and no other team in the building will speak chain-of-custody. The same export **is** the mandatory timestamped output report — one artifact, two criteria.
- **Criteria 3 + 6 (HLD soundness, 80k scalability) + bonus edge/bandwidth — arithmetic, not adjectives.** 80,000 cams × 2 Mbps = 160 Gbps centralized backhaul = impossible. District edge boxes decode + run ANPR locally; ~1–3 Kbps/camera of detection metadata travels upstream; video stays on departmental DVR/NVRs exactly as today. The brief's "existing infrastructure to the maximum practical extent" sentence, quoted back with measured numbers and a live per-feed bandwidth counter on the health dashboard.
- **Criterion 4 (platform maturity) + bonus health monitoring — live, honest failure handling.** Camera-health board (per-feed FPS, latency, last-frame age, reconnect count) and a rehearsed kill-a-feed-on-stage moment: amber → reconnecting → green, powered by the backoff-reconnect and loop-discontinuity code already in the ingest. Answering the academics' first question before they ask it beats claiming resilience on a slide.
- **Criteria 2 + 7 (presentation, completeness) + DGP seat — make scoring effortless, make cost concrete.** The deck literally mirrors the score sheet — one slide per weighted criterion, a green-tick matrix over the six bonus lines — so exhausted judges shortlisting 100+ submissions on Sept 7 evening can transcribe it straight into their rubric. The TCO slide closes in the only language procurement veterans fully trust: "₹3–7k per existing camera vs ₹25k+ per new one. You do not need a single new camera." And the 2–3 min video is cut as a trailer of the exact live-demo arc, so shortlisting judges have pre-watched the movie they'll later see performed.

---

## 3. Day-by-Day Plan (Sept 2 → Sept 7)

Solo senior dev. Existing modules referenced: `ingest/` (RTSP-over-TCP, PTS anchoring, backoff reconnect, loop-discontinuity reset, detector plugins), `backend/` (FastAPI: registry, watchlist, detections, alerts WS, route API, stats), `dashboard/` (React + Leaflet GIS, alerts panel, watchlist mgmt, route search, HLS wall), `mock-gateway/` (50-cam simulator), `docs/` (HLD, checklist). Working assumption ≈ 9 focused hrs/day after today.

### Sept 2 (today, ~5 h) — Reality first: the real grid
- **(3.5 h)** Point `ingest/` at the real ~30-cam public RTSP sandbox grid. Fix whatever breaks (H.265 decode load, auth quirks, PTS jumps). Log raw ANPR read-rate per camera; rank cameras by plate legibility. *Know the true read rate on day 1, not day 4.*
- **(1 h)** Verify the YOLO/ANPR detector plugin runs CPU-only at degraded FPS (finale hardware is unknown — GPU absence must degrade, not kill).
- **(0.5 h)** Write the rehearsal script skeleton + start the daily cold-start ritual: kill everything, boot from zero, trace GJ01AB1234 on the mock gateway.

### Sept 3 (9 h) — Recall engineering + physics filter (the graded artifact)
- **(3 h)** Confusion-tolerant matcher in `backend/` route + watchlist paths: canonicalize Indian plate syntax (GJ-01-AB-1234), weighted Levenshtein with per-character confusion costs (0/O, 1/I, 5/S, 8/B, 6/G). Ranked results with displayed confidence — never silent auto-merge.
- **(3 h)** Physics plausibility filter in the route API: implied speed per hop from GIS distance / PTS-anchored Δt; impossible transitions rejected. `dashboard/` renders rejected hops greyed on the Leaflet map with a plain-language reason tooltip, accepted hops with per-leg confidence chips.
- **(1.5 h)** Surface match confidence in every alert and search result ("matched GJ01A81234 → GJ01AB1234, 0.93").
- **(1 h)** Rehearsal #1 on the real grid: cold-start → plate → route. Any failure freezes feature work until fixed (Peechha rule, judge-endorsed).
- **(0.5 h)** Daily cold-start drill + notes.

### Sept 4 (9 h) — Trust layer + operational maturity
- **(3.5 h)** Evidence Dossier export: one click on a route → PDF with per-sighting frame snapshots, SHA-256 hash chain, camera ID/GPS/timestamp table, operator identity, query audit trail, chain-of-custody header. Same generator emits the mandatory timestamped location-wise movement report. Keep it a simple PDF — no case-management module.
- **(2 h)** RBAC-lite: JWT roles (admin/operator/viewer); append-only audit log of every plate search, watchlist change, and alert acknowledgment — the same log the dossier cites. Alert-ack workflow in the alerts panel.
- **(2 h)** Camera-health board in `dashboard/`: per-feed FPS, latency, last-frame age, reconnect count, uptime %, live Kbps counter per feed; auto-alert on feed drop. One-click feed-kill switch on `mock-gateway/` for the chaos beat.
- **(1 h)** Rehearsal #2 on the real grid — explicitly stress the loop-discontinuity reset and kill-a-feed recovery (rehearse the stunt; if reconnect ever hangs, it gets cut).
- **(0.5 h)** Cold-start drill.

### Sept 5 (9 h) — FREEZE + government-feed artifacts
- **(0 h — a decision, not a task)** **Ingest/PTS code is frozen from this morning.** The PTS-anchoring and discontinuity-reset code is the crown jewel; it does not get touched again.
- **(3 h)** Golden run on the real grid → record the **government-feed demo video** and generate the **timestamped output report** from the dossier exporter, closing shot on the PDF. Recorded today, not Sept 6 night.
- **(2 h)** 80k tiering one-pager for the HLD: 160 Gbps vs metadata-tier arithmetic, cams-per-edge-node table, low-connectivity store-and-forward note, honest scoping ("architecture + measured ratios on one machine, not a deployed fleet").
- **(1.5 h)** Triple-layer fallback stack: `DEMO_MODE` env flag; fully local 50-cam `mock-gateway/` run with zero venue-network dependency; pre-recorded insert clips **for the resilience/health beats only — never for the plate trace** (a canned clip on the judge-supplied plate, detected by a forensics jury, ends the bid).
- **(1.5 h)** Rehearsal #3: full timed run with one *unscripted* injected failure.
- **(1 h)** Buffer / overflow from the week.

### Sept 6 (9 h) — Submission package day (fenced; not raidable by code)
- **(3 h)** **Own-feed 2–3 min video**, cut as a trailer of the exact live-demo arc: alert fires → operator traces → rejected hop shown → dossier printed. Real software, screen-captured, zero slideware.
- **(3 h)** **PPT** (≤12 slides, Section 5 below): score-sheet mirror + persona flip-moments + TCO slide.
- **(1.5 h)** **HLD polish**: tiered edge architecture diagram, bandwidth math, audit chain, physics-filter design note.
- **(1 h)** Assemble submission: both videos, timestamped report, PPT, HLD, links, repo README with run instructions.
- **(0.5 h)** Dress run entirely on the offline local fallback.

### Sept 7 (≤4 h) — Buffer and submit early
- **(1 h)** Final cold-start rehearsal on the real grid.
- **(1 h)** Final review of every submission artifact against the official checklist.
- **(0.5 h)** **Submit before noon.** Never at the deadline.
- **(1.5 h)** True slack — the only real insurance a solo schedule has.

**Honest total: ~45 h across 5.5 days.** The spine's overlapping items were merged to pay for the grafts: the spine's 0.25-day "confidence heuristic" is superseded by the full physics filter; the score-sheet mirror, TCO slide, and trailer cut live inside the presentation/video blocks rather than adding new ones; the Deployable-Day-One metadata-mode *toggle* is cut (Section 6) and its bandwidth story carried by the live Kbps counters + one slide.

---

## 4. The Demo Script

### Live finale — 8–10 minutes, five beats

| Beat | Time | What happens | Jury seat it flips |
|---|---|---|---|
| **1. Cold open** | 0:00–1:00 | Wall already live on all ~50 heterogeneous feeds when judges walk up; health board solid green; live per-feed Kbps counters visible. No login screen, no loading. One line: "Twenty-six departments, one pane of glass, on the cameras Gujarat already owns." | Everyone — the platform simply *exists* |
| **2. The ask** | 1:00–4:30 | Judge reads out the registration number. Operator types it **exactly as given** into the single Trace box, hits Enter. Map animates the route camera-by-camera: timestamps, plate-crop evidence cards, per-hop confidence chips. Then the two engineered reveals: (a) point to a sighting card where OCR actually read `GJ01A81234` and the matcher recovered the true plate at 0.93 — "an exact-match system would have a hole here"; (b) the greyed-out hop: "implied speed 214 km/h over 3.1 km — physically impossible, discarded as a false ANPR match on camera 27." *(Conflict resolved: we do not theatrically corrupt the judge's input — J1 called that a parlour trick — we show the same recall proof on a genuine misread in the results.)* | DA-IICT + NFSU — mechanism, not adjectives |
| **3. Proof of life** | 4:30–6:00 | The same plate crosses another live camera; watchlist alert fires with an audible ping; operator acknowledges it — the ack lands in the audit log on screen. Proves live inference, not replay. | Brass — this is the control room at 2 a.m. |
| **4. The chaos beat** | 6:00–7:30 | Presenter kills a feed on stage, unprompted. Health board: green → amber → reconnecting → green. "That's the backoff-reconnect path — the same code that survived your looping sandbox feeds." | DA-IICT — failure handling demonstrated, not claimed |
| **5. Plate to court** | 7:30–9:30 | One click: Evidence Dossier PDF — hashed frames, camera/GPS/timestamp table, operator identity, full audit trail. **Hand the printed dossier to the panel** — a prop they keep after you leave. Close on the cost line: "₹3–7k per existing camera. You do not need a single new camera. Plate to court in sixty seconds." | NFSU + DGP — the sentence and the object that outlive the demo |

**Rehearsal protocol (judge-endorsed, non-negotiable):** three full timed dress runs with a written spoken script and shot list — one against the real grid, one with an unscripted injected failure, one entirely on the offline local fallback. Any rehearsal failure freezes feature work until fixed. Carry a second imaged machine.

### 2–3 min submission video — shot list (trailer of the exact arc above)
1. **0:00–0:15** — Cold open: full live video wall, health board green, title card: *"SENTINEL — Plate to Court in 60 Seconds."*
2. **0:15–0:45** — Plate typed into the Trace box → route animates hop-by-hop on the GIS map with timestamps and confidence chips.
3. **0:45–1:10** — The two proof shots: fuzzy-recovered misread at 0.93; greyed rejected hop with the physics tooltip.
4. **1:10–1:35** — Live watchlist alert fires + audible ping; operator ack → audit log entry.
5. **1:35–2:00** — Feed killed → health board amber → auto-recovery to green.
6. **2:00–2:30** — One click → Evidence Dossier PDF scrolls (hashes, custody header); end card: cost line + "80,000 cameras. ₹3–7k each. Zero new cameras."

*(Government-feed video: same skeleton, shot on the real ~30-cam grid, closing on the generated timestamped output report.)*

---

## 5. Presentation Narrative

Max 12 slides; one slide per weighted criterion so a tired judge can transcribe the deck into their rubric; zero jargon in the first five.

1. **The question your control room radios every day** — "Where did this car go?" Answered in 60 seconds, ending in court. (Concept paragraph from Section 1.)
2. **The 60-second story** — five-beat demo arc as one visual strip: plate in → route → alert → recovery → dossier out.
3. **Criterion 1 — the test case, proven** — stills + link: judge-plate trace on the government sandbox grid; recall engineering (confusion matcher) named as the insurance.
4. **Criterion 5 — analytics you can trust** — the rejected hop and the 0.93 recovery, side by side: "we show you what the system refused to believe, and why."
5. **The Evidence Dossier** — chain-of-custody PDF anatomy: hashes, audit trail, custody header. *For NFSU: detections treated as evidence, not bounding boxes.*
6. **Criterion 3 — HLD** — tiered edge architecture on one diagram: departmental DVR/NVRs untouched, edge ANPR, metadata upstream. Interoperable across the 26 departments via registry APIs.
7. **Criterion 6 — the 80k arithmetic** — 160 Gbps centralized vs ~3 Kbps/cam metadata tier; computed, honestly scoped, live Kbps counters as proof.
8. **Criterion 4 — built for the 2 a.m. shift** — health board, kill-a-feed recovery frames, alert-ack workflow, RBAC roles.
9. **The cost slide (DGP slide)** — ₹3–7k per *existing* camera vs ₹25k+ per new one; video never leaves departmental storage; "You do not need a single new camera."
10. **Bonus green-tick matrix** — all six bonus lines, each tick captioned with the demo beat or artifact that proves it (no unproven ticks).
11. **Criterion 7 — submission completeness** — the artifact map: PPT, HLD, own-feed video, government-feed video, timestamped report, repo.
12. **Close** — the sentence: *"Plate to court in sixty seconds — on the cameras Gujarat already owns."*

---

## 6. Deliberately NOT Building

- **Face recognition (FRS)** — a legal-and-accuracy minefield a solo dev cannot defend under NFSU questioning; "roadmap, not demo."
- **Full case-management module** — the dossier stays a simple PDF; this is the plan's most likely self-inflicted wound and it eats days 2–3 if allowed.
- **Kafka/microservices rewrite** — the monolith demos identically at 50 feeds; the 80k story is architecture + arithmetic, and brass have watched that vendor slide for 20 years.
- **Metadata-only degraded-mode toggle (Deployable's second live stunt)** — two live stunts double the on-stage failure surface; the kill-a-feed beat carries resilience, the Kbps counters + cost slide carry the bandwidth story at ~zero risk.
- **Crowd-density / anomaly analytics tiles** — the judges scored these as "shallow add-ons a DA-IICT juror pulls the thread on"; depth on the graded artifact beats a thirteenth thin checkmark.
- **80,000 synthetic cameras seeded in the registry** — proves Leaflet clustering, not scale, and was flagged as the claim most likely to be labeled a stunt; the honest capacity table replaces it.
- **Enterprise IAM / DPDP "compliance"** — JWT roles + append-only audit log only; every legal statement scoped as "design provision," never "compliant today" — overclaiming to a forensics jury inverts credibility.
- **New ingest/PTS features after Sept 5 morning** — the PTS-anchoring and discontinuity code is the crown jewel; frozen means frozen.

---

## 7. Risks & Fallbacks

1. **ANPR misses the judges' unknown plate on the day (kills Criterion 1 — nothing compensates).**
   *Mitigation:* recall over precision — confusion-tolerant matcher with ranked confidence; thresholds tuned on the real grid's worst cameras starting day 1; daily cold-start rehearsal; physics filter catches the false-positive side of aggressive matching. Read-rate measured Sept 2, so the true number is known before anything is promised.
2. **Solo schedule with zero slack — one sick day or hardware failure collapses the plan.**
   *Mitigation:* both videos and the report recorded Sept 5–6, never Sept 7; Sept 7 is pure buffer with submission before noon; second imaged machine carried to the finale; detector verified CPU-only so missing GPU degrades instead of kills.
3. **Event feeds differ from the rehearsal sandbox (codecs, clock skew, mid-loop discontinuities → a route with time going backwards, lethal before forensics judges).**
   *Mitigation:* PTS-anchor and discontinuity-reset paths explicitly stress-tested in rehearsal #2 on the real grid; ingest frozen after Sept 5 morning; all timestamps in the UI and dossier come from the PTS-anchored clock, never wall clock.
4. **The kill-a-feed stunt backfires if reconnect hangs on stage.**
   *Mitigation:* the stunt is rehearsed in every dress run against the real grid; standing rule — if it fails once in rehearsal it is cut from the live show and covered by the pre-recorded resilience insert instead. Fallback clips exist **only** for the resilience/health beats; the judge-plate trace is always live (a detected replay there ends the bid).
5. **Venue network or sandbox endpoint dies mid-demo.**
   *Mitigation:* triple-layer fallback — `DEMO_MODE` flag, fully local 50-cam mock gateway needing zero venue network, and one dress rehearsal run entirely offline so the fallback path is itself rehearsed, not theoretical. The government-feed proof is already banked on video at shortlisting time either way.

---

*One sentence to leave in the room: **"Plate to court in sixty seconds — on the cameras Gujarat already owns."***
