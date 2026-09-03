# SENTINEL — Workflow & Integration Diagram

**Gujarat Police CCTV Hackathon 2026 · Unified CCTV Command Platform · Divij Patel**

Three views of one system: (1) the end-to-end integration workflow as built and demonstrated on the live sandbox grid, (2) the real-time detection → watchlist → alert sequence, and (3) the statewide three-tier deployment topology scaling the same contracts to ~80,000 cameras.

---

## 1. End-to-end integration workflow (as built)

Heterogeneous departmental cameras are onboarded from a catalogue (the contract), consumed read-only over RTSP/HLS with no change to existing VMS or storage, analysed live (vehicle detection → plate localisation → ANPR), correlated against the watchlist, and surfaced on the GIS command centre with route reconstruction and evidence export.

```mermaid
flowchart LR
  subgraph SRC["Departmental CCTV sources (26 departments, any vendor / VMS)"]
    CAT["Camera catalogue\n/api/ingest (id, location, codec, urls)"]
    RTSP["RTSP :8554 over TCP\n(H.264 / H.265, mixed resolutions)"]
    HLSG["HLS / WHEP\n(browser preview)"]
  end

  subgraph ING["Ingest layer — Python / OpenCV (one worker per camera, paced)"]
    CAP["capture.py\nPTS-anchored timestamps · backoff reconnect · loop-discontinuity reset"]
    DET["AI pipeline\nYOLOv8 vehicle detection → plate localisation → ANPR/OCR"]
  end

  subgraph API["Backend — FastAPI + SQLAlchemy (PostgreSQL/PostGIS-ready)"]
    REG["Camera registry\n+ GIS metadata"]
    MATCH["matching.py\nnormalise · exact / OCR-confusion fuzzy match"]
    WL[("Watchlist DB\nstolen · wanted · suspect")]
    DBX[("Detections · Alerts\nAudit trail")]
    ROUTE["Route reconstruction\ntime-ordered sightings · physics plausibility filter"]
    DOSS["Evidence dossier\nSHA-256 hash-chained PDF"]
    WS["WebSocket hub\n/ws/alerts"]
  end

  subgraph UI["Command centre — React + Leaflet"]
    MAP["GIS map · camera health · video wall"]
    ALERTS["Live alerts · watchlist · route search"]
  end

  CAT -- "POST /api/cameras/sync" --> REG
  RTSP --> CAP --> DET -- "POST /api/detections\n(plate, confidence, PTS time, snapshot)" --> MATCH
  MATCH <--> WL
  MATCH --> DBX
  MATCH -- "on match: alert < 1 s" --> WS --> ALERTS
  DBX --> ROUTE --> DOSS
  ROUTE --> ALERTS
  REG --> MAP
  HLSG --> MAP
```

---

## 2. Real-time detection → watchlist → alert sequence

```mermaid
sequenceDiagram
  participant C as Camera (RTSP over TCP)
  participant W as capture.py + ANPR detector
  participant B as Backend /api/detections
  participant M as matching.py
  participant S as WebSocket /ws/alerts
  participant U as Control-room UI

  C->>W: frames with PTS (CAP_PROP_POS_MSEC)
  W->>W: captured_at = anchor_wall + (pts − anchor_pts)
  W->>B: POST detection (plate, confidence, captured_at, snapshot)
  B->>M: normalise(plate) · exact / fuzzy (OCR-confusion) match vs watchlist
  B->>S: broadcast type=detection
  alt watchlist hit
    M->>B: create Alert (match_type exact | fuzzy, confidence)
    B->>S: broadcast type=alert (camera + watchlist + snapshot)
    S->>U: alert card · map pans to camera
    U->>B: POST /api/alerts/{id}/ack (audit-logged)
  end
  U->>B: GET /api/vehicles/{plate}/route
  B->>U: time-ordered sightings · physics-validated · GeoJSON route · dossier link
```

---

## 3. Statewide deployment topology (~80,000 cameras, edge-first)

Video never leaves departmental storage; only detection metadata (~1–3 Kbps per camera) travels upstream. The same API contracts run at every tier.

```mermaid
flowchart TB
  subgraph EDGE["EDGE — department premises / junction cabinets"]
    CAMS["Existing cameras + NVR/DVR\n(video retention stays here)"]
    EN["Edge nodes\ncapture + detect · events only upstream"]
  end
  subgraph REGION["REGIONAL — district / city PoPs (~30)"]
    RGW["Media gateways\n(restream for Tier-B cameras)"]
    GPU["GPU inference pool\nYOLO + ANPR"]
    KAF["Kafka (regional)"]
  end
  subgraph CENTRAL["CENTRAL — State Command & Control, Gandhinagar + DR site"]
    KC["Kafka (mirrored topics)"]
    SVC["API · matching · alerting services\n(Kubernetes)"]
    PG[("PostgreSQL + PostGIS")]
    OBJ[("Object storage\nsnapshots · evidence dossiers")]
    UI2["Command-centre UI · video wall\nVAHAN / SARTHI / eGujCop adapters"]
  end
  CAMS --> EN --> KAF
  CAMS --> RGW --> GPU --> KAF
  KAF --> KC --> SVC --> PG
  SVC --> OBJ
  SVC --> UI2
```
