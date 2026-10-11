# SENTINEL — Pitch Script & Slide Guide

**Gujarat Police CCTV Hackathon 2026 · Category 1**
**Team:** Divij Patel · Meet Patel · Krish Patel

What each slide is, and exactly what to say. Spoken lines are shown as quotes.
Target about 6 minutes, then questions. Deck: `SENTINEL_Presentation.pptx`
(8 slides, these notes are also embedded for presenter view).

---

## Slide 1 — Title (0:00–0:30)

**What this slide is:** your name, the team, and the single sentence that says
what SENTINEL does. Set the problem and the promise before any detail.

> Namaste. We're team SENTINEL — Divij, Meet and Krish, Category 1. Every
> control room radios the same question every day: where did this car go?
> Today the answer takes days of scrubbing footage across departments. SENTINEL
> answers it in sixty seconds, and ends with a document an officer can take to
> court. It's a hybrid of Model 1 plus 2 and 4, it runs CPU-only on entirely
> open-source software, and it uses the cameras Gujarat already owns — zero new
> cameras.

*Tip: say the three names clearly. Land "sixty seconds" and "zero new cameras".*

---

## Slide 2 — What it does (0:30–1:30)

**What this slide is:** the whole platform as one arc — register → detect →
alert → trace → prove. The mental model you want judges to keep.

> Here's the whole platform in five steps. One, register and view — every
> department's cameras onboard from a live catalogue onto one GIS map;
> heterogeneous feeds in one pane, nothing hard-coded. Two, detect — CPU-only
> ANPR reads plates off the live feed, each read timestamped with a confidence.
> Three, correlate and alert — every read is checked against the watchlist, and
> a match fires a real-time alert in under a second with the camera's own frame
> as evidence. Four, trace — search a plate and the timestamped route draws
> camera by camera on the map, with a physics filter that rejects impossible
> hops. Five, prove — one click exports a hash-sealed chain-of-custody dossier.

*Tip: count the beats on your fingers. This is your spine.*

---

## Slide 3 — Problems solved (1:30–2:30)

**What this slide is:** the real control-room problems from the brief, each
paired with how SENTINEL answers it. Shows you understood the ask.

> These are the real problems, and how we answer each. Twenty-six departments
> with siloed, incompatible CCTV — we integrate them through one
> catalogue-driven registry; we don't rip and replace. Days of manual footage
> search — plate in, route out in seconds. OCR misreads on real CCTV — we
> recover them with a deterministic, grammar-aware engine we call the king, and
> we always show the confidence. Evidence that dies before court — a SHA-256
> hash-chained dossier. Insider tampering — an append-only, hash-chained audit
> log where any edit breaks the chain and is caught. And scaling to eighty
> thousand cameras — video stays at the edge; only a few kilobits of metadata
> travel upstream.

*Tip: you needn't read all eight. Hit integration, seconds-not-days, the king,
and tamper-evident evidence.*

---

## Slide 4 — Tech stack (2:30–3:15)

**What this slide is:** the technologies by layer. Headline is the posture —
free, replaceable, no GPU dependency, Make-in-India friendly.

> Our stack is entirely open-source, CPU-only, with no vendor lock and no GPU
> dependency — which matters for Make-in-India procurement. React and Leaflet
> on the front end; FastAPI and PostgreSQL on the back. For ANPR: YOLOv8n for
> vehicles, a plate localizer, RapidOCR with an Indian plate-syntax gate, and
> the king on top. Streaming is RTSP over TCP with timestamps anchored to the
> stream clock. And for scale: Docker, Kubernetes, a Kafka event bus through
> Redpanda, and S3 object storage through SeaweedFS. Every piece is free and
> replaceable.

*Tip: credibility slide, keep it brisk unless a technical judge leans in.*

---

## Slide 5 — Results (3:15–4:15)

**What this slide is:** the real numbers, from live feeds and the running PoC.
Where you earn trust — every figure was measured.

> Everything here is measured, not asserted. We onboarded all thirty government
> cameras live. Our OCR went from one correct read in nineteen to eleven, and
> the king recovered the true plate on six of six of the hardest cases. Alerts
> fire in under a second. On the production components we proved: PostgreSQL
> replication at sixteen milliseconds for disaster recovery; a Kafka broker at
> fifteen thousand six hundred events a second — forty times the entire state's
> load; and object storage at the state's full snapshot rate. Our evidence is
> tamper-evident, and our scale arithmetic is computed: a hundred and fifty
> terabytes of snapshots instead of fifty-two petabytes of video.

*Tip: point at the tiles. If asked "is that real?" — yes, run the benchmark in
`deploy/poc/` live.*

---

## Slide 6 — What we achieved (4:15–5:00)

**What this slide is:** the accomplishments, framed around your differentiator,
evidence-first honesty.

> To summarize what we built: every mandatory module, working and verified on
> live feeds. A platform that's evidence-first by design — it never asserts a
> read as fact; it shows confidence, recovers misreads, and explains every
> result through TrustTrace. We added the king for deterministic plate
> reconciliation, moved to PostgreSQL in a one-command Docker stack, and proved
> the production topology with real numbers. And we did it honestly and
> affordably — CPU-only, open-source, around fifteen to twenty crore for the
> whole state, with zero new cameras.

*Tip: "evidence-first — we never assert a read as fact" is your strongest line
with a forensics panel. Say it with weight.*

---

## Slide 7 — Future implementation (5:00–5:45)

**What this slide is:** where it goes next. Key word is "proven" — the heavy
items are already demonstrated in the PoC.

> Where we go next — and the roadmap is proven, not just drawn. Sharper OCR
> through perspective rectification and a multi-engine ensemble. Moving
> detections onto the Kafka bus we already benchmarked. A PostgreSQL replica
> and a disaster-recovery site. Audit-logged, read-only adapters for VAHAN,
> SARTHI and eGujCop. Edge and regional inference across thirty points of
> presence on GSWAN. And a phased rollout — five hundred, then five thousand,
> then twenty-five thousand, then eighty thousand cameras — with new analytics
> added at software-only cost.

*Tip: stress the production tiers aren't aspirational — "we ran them and
measured them".*

---

## Slide 8 — Close (5:45–6:15)

**What this slide is:** the one line to remember, the team, the handover to
questions.

> So, in one sentence: plate to court in sixty seconds, on the cameras Gujarat
> already owns. Zero new cameras, CPU-only, open-source, and evidence-first.
> Thank you — Divij, Meet and Krish. We'd be glad to take your questions.

*Tip: pause after the sentence. Let it land before "thank you".*

---

## Q&A — answers ready before they ask

**Do you read every number plate that passes?**
No, and no ANPR does on CCTV. We read every plate a camera can actually
resolve. A vehicle gives us many frames across many cameras, so missing one
frame rarely means missing the vehicle, and the king reconciles the good frames
into the right plate. Plates that are never legible — dark, blurred, badly
angled — are honest misses, which is why camera placement and our OCR roadmap
matter.

**Does the watchlist check live only, or history too?**
Both. Every new live read is matched instantly. Re-scan checks the recent
detection history — up to thirty days — so a new watchlist entry tells you at
once if the vehicle was already seen. The route search traces any plate through
the stored sightings, scoped to any from–to time window.

**160 NVIDIA GPUs — isn't that expensive and import-dependent?**
Our core runs CPU-only, which you've seen. GPUs are an optional accelerator,
not a dependency, so procurement can follow Make-in-India — commodity
Indian-assembled servers, or the State Data Centre's cloud, with zero imported
hardware if policy requires. The GPU sizing is a reference, not a bill of
materials.

**Does the edge/regional tier mean changes at the cameras?**
No. We never touch a camera, its wiring or its VMS. Analytics run on servers in
your existing regional and central data centres, consuming the streams you
already produce. Edge boxes at junctions are an optional bandwidth optimisation
for thin rural links, and nothing in our prototype needs one.

**How do you know a record wasn't tampered with — even by an insider?**
Every sensitive action writes an append-only, hash-chained audit row. Edit any
row in the database and its hash stops matching, and every row after it breaks —
one tampered record invalidates the whole tail. Anyone can verify the chain by
recomputation. The dossier uses the same chain and binds the snapshot by its
hash, so the photo can't be swapped either.

**Is the multi-camera route real, or faked on the sandbox?**
On the sandbox, a vehicle can't physically drive from one looped camera to
another, so today's real reads are single-camera sightings. The route engine is
the same code proven by our tests to reconstruct an eight-camera journey and
reject an impossible hop; on your evaluation grid it reconstructs the real
journey.

**Why no MinIO / why these specific tools?**
We deliberately avoid vendor lock and heavy paid dependencies. MinIO gated its
registries, so we use SeaweedFS, a free S3-compatible successor; the client
code is unchanged. Everything in the stack is open-source and replaceable, and
we use no LLM in the decision path — the plate arbiter is fully deterministic.
