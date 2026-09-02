"""Legibility soak on the live government sandbox grid.

Runs the REAL pipeline (CaptureLoop: RTSP-over-TCP + PTS anchoring, and
AnprDetector: YOLOv8n -> plate localizer -> fast-plate-ocr) against a list of
cameras for a fixed number of minutes each, POSTing every detection to the
RUNNING backend, and tallies per-camera legibility:

    frames processed / vehicle boxes / plates localized / plates READ
    (with plate strings, confidences and PTS-anchored captured_at stamps)

Gateway rule 11 (pace the load) is enforced: cameras run in WAVES of at most
4 concurrent captures; each wave's captures are closed before the next opens.

Usage:
    python soak.py --cams cam23,cam27,cam16,cam04 --minutes 4
        [--backend http://localhost:8000] [--out stats.json]

The per-camera tally is printed as JSON at the end (and written to --out).
"""

import argparse
import json
import sys
import threading
import time
from datetime import timezone

# capture.py must be imported before cv2 anywhere (RTSP-over-TCP env var,
# gateway rule 1).
from capture import CaptureLoop

import httpx

MAX_CONCURRENT = 4  # gateway rule 11 — hard cap, never raised


def iso_z(dt) -> str:
    """UTC ISO8601 with trailing Z (contract: all timestamps are UTC + Z)."""
    return (
        dt.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


class TallyingDetector:
    """Wraps a real AnprDetector, counting frames / vehicles / localizations."""

    def __init__(self, inner, stats):
        self.inner = inner
        self.stats = stats

        # Count vehicle boxes straight off YOLO (results under-count: the
        # plate-less path is PTS-throttled by design).
        orig_predict = inner._yolo.predict

        def counting_predict(*args, **kwargs):
            out = orig_predict(*args, **kwargs)
            try:
                stats["vehicles"] += len(out[0].boxes)
            except Exception:
                pass
            return out

        inner._yolo.predict = counting_predict

        # Count successful plate localizations (vehicle-crop or full-frame).
        orig_localize = inner._localize_plate

        def counting_localize(image):
            located = orig_localize(image)
            if located is not None:
                stats["localized"] += 1
            return located

        inner._localize_plate = counting_localize

    def process(self, frame, pts_ms, captured_at):
        self.stats["frames"] += 1
        return self.inner.process(frame, pts_ms, captured_at)

    def reset(self):
        self.stats["resets"] += 1
        self.inner.reset()


def soak_camera(camera, minutes, client, stats, stop_event, post_lock):
    """One camera's soak: CaptureLoop + AnprDetector, POST every detection."""
    from detectors.anpr import AnprDetector

    detector = TallyingDetector(AnprDetector(), stats)

    def on_detection(cam, result, pts_ms, captured_at):
        payload = {
            "camera_external_id": cam["external_id"],
            "object_type": result.object_type,
            "pts_ms": pts_ms,
            "captured_at": iso_z(captured_at),
            "detector": "anpr",
        }
        if result.plate:
            payload["plate"] = result.plate
        if result.plate_confidence is not None:
            payload["plate_confidence"] = result.plate_confidence
        if result.bbox:
            payload["bbox"] = result.bbox
        if result.snapshot_b64:
            payload["snapshot_b64"] = result.snapshot_b64

        if result.plate:
            stats["reads"].append(
                {
                    "plate": result.plate,
                    "confidence": result.plate_confidence,
                    "captured_at": payload["captured_at"],
                }
            )
        else:
            stats["plateless_posts"] += 1

        try:
            with post_lock:
                resp = client.post("/api/detections", json=payload)
            resp.raise_for_status()
            stats["posted"] += 1
        except Exception as exc:  # backend hiccups never kill the capture
            stats["post_errors"] += 1
            print(f"[{cam['external_id']}] POST failed: {exc}", file=sys.stderr)

    def on_status(cam, status):
        print(f"[{cam['external_id']}] status: {status}", file=sys.stderr)

    loop = CaptureLoop(
        camera,
        detector,
        on_detection=on_detection,
        on_status=on_status,
        stop_event=stop_event,
        # CPU-only inference across up to 4 concurrent cameras: ~2 processed
        # frames/s per camera keeps the decoder ahead of the detector.
        process_interval_ms=500.0,
    )
    loop.run()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cams", required=True,
                        help="comma-separated external ids, e.g. cam23,cam27")
    parser.add_argument("--minutes", type=float, default=4.0,
                        help="soak duration per wave (default 4)")
    parser.add_argument("--backend", default="http://localhost:8000")
    parser.add_argument("--out", default=None, help="write the tally JSON here")
    args = parser.parse_args(argv)

    wanted = [c.strip() for c in args.cams.split(",") if c.strip()]
    client = httpx.Client(base_url=args.backend,
                          timeout=httpx.Timeout(15.0, connect=5.0))

    resp = client.get("/api/cameras")
    resp.raise_for_status()
    by_ext = {c.get("external_id"): c for c in resp.json()}
    cameras = []
    for ext in wanted:
        if ext not in by_ext:
            print(f"unknown camera external_id {ext!r} — skipping", file=sys.stderr)
            continue
        cameras.append(by_ext[ext])

    all_stats = {}
    post_lock = threading.Lock()  # single shared httpx client

    # Waves of <= MAX_CONCURRENT (gateway rule 11: pace the load; captures of
    # a finished wave are closed by CaptureLoop before the next wave opens).
    for wave_start in range(0, len(cameras), MAX_CONCURRENT):
        wave = cameras[wave_start:wave_start + MAX_CONCURRENT]
        names = [c["external_id"] for c in wave]
        print(f"=== wave: {names} for {args.minutes} min ===", file=sys.stderr)
        stop_event = threading.Event()
        threads = []
        for cam in wave:
            stats = all_stats.setdefault(cam["external_id"], {
                "camera": cam["external_id"],
                "name": cam.get("name"),
                "frames": 0, "vehicles": 0, "localized": 0,
                "reads": [], "plateless_posts": 0,
                "posted": 0, "post_errors": 0, "resets": 0,
                "minutes": args.minutes,
            })
            t = threading.Thread(
                target=soak_camera,
                args=(cam, args.minutes, client, stats, stop_event, post_lock),
                name=cam["external_id"], daemon=True,
            )
            threads.append(t)
            t.start()
        stop_event.wait(args.minutes * 60.0)
        stop_event.set()
        for t in threads:
            t.join(timeout=20)

    client.close()
    summary = list(all_stats.values())
    text = json.dumps(summary, indent=2)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
