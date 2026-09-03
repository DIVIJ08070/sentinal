"""AI-view smoke test — no grid, no backend, no credentials needed.

Run:  cd ingest && ../.venv/bin/python ai_view_smoke.py [/path/to/clip.mp4] [--seconds 25]
                   [--port 8893] [--out ../deliverables/screenshots/ai_view_sample.jpg]

Drives the REAL CaptureLoop + AnprDetector over a local video file (CaptureLoop
opens file paths and loops them) with the ``on_frame`` hook wired to an
AiViewServer on the given port, for ~N seconds. Then it fetches
``/ai/test.jpg`` and ``/ai`` over HTTP and asserts:

  * a JPEG > 20 KB came back for the 'test' camera key,
  * ``/ai`` lists the 'test' key with its last-frame age.

The sample frame is saved to ``--out`` (the frame with the most read plates
seen during the run when there was one, else the final frame) so a human can
eyeball the overlay. Without a clip argument a synthetic clip is generated
(anpr_smoke.build_test_video) - the pipeline still runs, but YOLO rarely
detects a drawn vehicle, so use real footage for a meaningful sample.

Exit codes: 0 = pass, 2 = ML extras missing, 3 = assertion failed.
"""
import argparse
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request

# capture.py must be imported before cv2 anywhere (RTSP-over-TCP env var).
from capture import CaptureLoop
from ai_view import AiViewServer, cam_key_for

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(HERE, "..", "deliverables", "screenshots", "ai_view_sample.jpg")
MIN_JPEG_BYTES = 20 * 1024


def main() -> int:
    ap = argparse.ArgumentParser(description="AI view smoke: CaptureLoop + ANPR -> AiViewServer")
    ap.add_argument("video", nargs="?", default=None, help="local clip (default: synthetic)")
    ap.add_argument("--seconds", type=float, default=25.0)
    ap.add_argument("--port", type=int, default=8893)
    ap.add_argument("--interval-ms", type=float, default=150.0)
    ap.add_argument("--out", default=os.path.normpath(DEFAULT_OUT))
    ns = ap.parse_args()

    print("=== SENTINEL AI-view smoke (local file, loopback HTTP) ===")
    try:
        from detectors.anpr import AnprDetector
    except ImportError as exc:
        print(exc)
        print("\nAI VIEW SMOKE: FAIL - ML extras missing")
        return 2

    tmp = None
    video = ns.video
    if video is None:
        from anpr_smoke import build_test_video
        tmp = tempfile.NamedTemporaryFile(suffix=".avi", delete=False)
        tmp.close()
        build_test_video(tmp.name)
        video = tmp.name
        print(f"[1] no clip given - synthetic clip at {video}")
    else:
        print(f"[1] clip: {video}")
    if not os.path.exists(video):
        print(f"\nAI VIEW SMOKE: FAIL - clip not found: {video}")
        return 3

    server = AiViewServer(ns.port).start()
    print(f"[2] AI view server on {server.base_url}  ({server.url_pattern()})")

    camera = {"id": 0, "external_id": "test", "name": "AI-view smoke (local clip)",
              "rtsp_url": None, "hls_url": video, "codec": "h264"}
    key = cam_key_for(camera)
    assert key == "test", key

    detector = AnprDetector()
    stop_event = threading.Event()
    stats = {"frames": 0, "vehicle_boxes": 0, "plate_boxes": 0, "reads": 0}
    best = {"jpeg": None, "plates": 0}
    detections = []

    def on_frame(cam, frame, boxes, pts_ms, captured_at):
        server.on_frame(cam, frame, boxes, pts_ms, captured_at)
        stats["frames"] += 1
        stats["vehicle_boxes"] += sum(1 for b in boxes if b.get("kind") == "vehicle")
        plates = [b for b in boxes if b.get("kind") == "plate"]
        stats["plate_boxes"] += len(plates)
        read = sum(1 for b in plates if b.get("label") and b["label"] != "plate")
        stats["reads"] += read
        if read > best["plates"]:
            best["plates"] = read
            best["jpeg"] = server.latest_jpeg(key)

    loop = CaptureLoop(
        camera, detector,
        on_detection=lambda cam, res, pts, at: detections.append(res),
        stop_event=stop_event,
        process_interval_ms=ns.interval_ms,
        on_frame=on_frame,
    )
    thread = threading.Thread(target=loop.run, name="cam-test", daemon=True)
    t0 = time.monotonic()
    thread.start()
    stop_event.wait(ns.seconds)
    elapsed = time.monotonic() - t0
    print(f"[3] ran {elapsed:.1f}s: {stats['frames']} frames published, "
          f"{stats['vehicle_boxes']} vehicle boxes, {stats['plate_boxes']} plate boxes, "
          f"{stats['reads']} plate reads drawn; detections emitted: {len(detections)} "
          f"({sum(1 for d in detections if d.plate)} with plate)")

    failures = []
    try:
        with urllib.request.urlopen(f"{server.base_url}/ai/{key}.jpg", timeout=5) as resp:
            ctype = resp.headers.get("Content-Type")
            cors = resp.headers.get("Access-Control-Allow-Origin")
            jpeg = resp.read()
        print(f"[4] GET /ai/{key}.jpg -> {len(jpeg)} bytes, {ctype}, CORS={cors}")
        if ctype != "image/jpeg" or cors != "*":
            failures.append(f"unexpected headers: {ctype} / CORS={cors}")
        if not jpeg.startswith(b"\xff\xd8"):
            failures.append("response is not a JPEG")
        if len(jpeg) <= MIN_JPEG_BYTES:
            failures.append(f"JPEG too small ({len(jpeg)} bytes <= {MIN_JPEG_BYTES})")
    except Exception as exc:
        jpeg = None
        failures.append(f"GET /ai/{key}.jpg failed: {exc}")

    try:
        with urllib.request.urlopen(f"{server.base_url}/ai", timeout=5) as resp:
            listing = json.loads(resp.read().decode("utf-8"))
        print(f"[5] GET /ai -> {json.dumps(listing)}")
        entry = next((e for e in listing if e.get("key") == key), None)
        if entry is None:
            failures.append(f"/ai does not list {key!r}")
        elif "last_frame_age_s" not in entry:
            failures.append("/ai entry lacks last_frame_age_s")
    except Exception as exc:
        failures.append(f"GET /ai failed: {exc}")

    # One MJPEG part, to prove the stream endpoint speaks multipart.
    try:
        req = urllib.request.Request(f"{server.base_url}/ai/{key}.mjpg")
        with urllib.request.urlopen(req, timeout=5) as resp:
            ctype = resp.headers.get("Content-Type", "")
            head = resp.read(64)
        ok = ctype.startswith("multipart/x-mixed-replace") and head.startswith(b"--")
        print(f"[6] GET /ai/{key}.mjpg -> {ctype!r}, first bytes {head[:24]!r}")
        if not ok:
            failures.append("MJPEG endpoint did not return a multipart stream")
    except Exception as exc:
        failures.append(f"GET /ai/{key}.mjpg failed: {exc}")

    stop_event.set()
    thread.join(timeout=15)
    server.stop()
    if tmp is not None:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    sample = best["jpeg"] or jpeg
    if sample:
        os.makedirs(os.path.dirname(os.path.abspath(ns.out)), exist_ok=True)
        with open(ns.out, "wb") as fh:
            fh.write(sample)
        which = f"frame with {best['plates']} read plate(s)" if best["jpeg"] else "final frame"
        print(f"[7] sample saved: {os.path.abspath(ns.out)} ({len(sample)} bytes, {which})")

    if failures:
        print("\nAI VIEW SMOKE: FAIL - " + "; ".join(failures))
        return 3
    print("\nAI VIEW SMOKE: PASS - annotated frames served over HTTP from the real pipeline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
