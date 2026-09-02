# Official gateway integration rules (from the Sentinel portal — MUST be honored by all ingest code)

Source: sentinel.gujarat.gov.in participant integration guide. These rules apply when connecting to the government camera gateway; our capture pipeline follows them at all times (mock or real).

## Endpoints
- Catalogue (the contract): `GET http://<host>/api/ingest` — returns every camera with id, location, codec, live status, stream properties, and all three URLs. Camera ids and the set of cameras CAN change. Never hard-code stream URLs or assume the URL pattern.
- RTSP `rtsp://<host>:8554/stream/<id>` — for AI inference.
- WebRTC WHEP `http://<host>:8889/stream/<id>/whep` — low-latency browser preview.
- HLS `http://<host>/live/stream/<id>/index.m3u8` — dashboards/mobile/restricted networks.

## Hard rules (each maps to code in ingest/capture.py & worker.py)
1. **Force RTSP over TCP.** Set `OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp` before importing cv2 (or equivalent per client). UDP corrupts frames behind NAT/firewalls. If 8554 is blocked, fall back to HLS.
2. **Never trust the reported frame rate** (`CAP_PROP_FPS` or camera-declared fps). It often doesn't match delivery. All time-derived metrics use timestamps, never frame counts × fps.
3. **Drive all timing from PTS** (`CAP_PROP_POS_MSEC` in OpenCV / buffer PTS in GStreamer / RTP timestamps), never from wall-clock arrival time. On connect, the gateway replays the buffered GOP so the first ~1–2 s of frames arrive FASTER than real time — arrival-time timestamps produce impossible velocities after every (re)connect. Anchor wall-clock once per connection and offset by PTS deltas.
4. **No constant-frame-rate assumption.** Inter-frame gaps are normal; do not treat a gap as a disconnect; motion/tracking models must use actual elapsed PTS.
5. **Reconnect automatically with exponential backoff** — start ~2 s, cap ~30 s. Feeds are supervised and may restart. Never tight-loop reconnect.
6. **Decoder warnings on join are non-fatal.** Mid-stream attach produces `Error constructing the frame RPS` / `Could not find ref with POC` until the first IDR frame. Log, don't abort.
7. **No uniform grid.** Mixed H.264/H.265, mixed resolutions/bitrates/frame rates. Read per-camera properties from the catalogue and size buffers/batches per camera. No fixed-shape inference batch across cameras.
8. **Expect a scene discontinuity** — each feed is a loop; at the loop point the scene hard-cuts (like a reboot). Background models, trackers, re-ID galleries, track ids must recover from a hard cut (we detect via PTS jump and call `detector.reset()`).
9. **No footage downloads.** The grid is consumed live; `/stream/<id>` answers range requests as a browser fallback and a plain curl of it yields a misleading partial file. Build against live capture only.
10. **Consume only.** Never publish/push streams to the gateway or call its control API.
11. **Pace the load.** Every client gets its own stream copy. Open only cameras actively being processed; close finished captures. (Hence worker `--max-cameras`, default 4.)

## Pre-submission checklist (from the portal)
- [ ] Every client forces RTSP over TCP.
- [ ] No timing logic depends on CAP_PROP_FPS or frame arrival time.
- [ ] Inter-frame gaps do not crash or stall the pipeline.
- [ ] Reconnect with backoff implemented and tested by restarting a feed.
- [ ] Decoder warnings on join are logged, not fatal.
- [ ] Camera list and per-camera properties read from /api/ingest.
- [ ] Pipeline handles mixed H.264/H.265 and mixed resolutions.
- [ ] Behaviour is sane across a scene discontinuity.

## Hackathon test case (what evaluation exercises)
Onboard ~50 heterogeneous, geographically distributed cameras onto one platform; centralised monitoring + AI analytics; on evaluation day a designated vehicle registration number is provided → the platform must identify, trace, and present the vehicle's complete route with timestamped location-wise movement history, plus demonstrate a watchlist database continuously cross-referenced against live feeds generating automated real-time alerts on match.
