"""Measure the TRUE delivery characteristics of a live grid camera.

Battle-plan day-1 tool: "know the true read rate on day 1, not day 4."
Runs the production CaptureLoop (same code path as the worker — TCP forcing,
PTS anchoring, backoff, discontinuity handling) against one camera for a fixed
wall-clock window and reports what was actually delivered.

Usage:
    python grid_probe.py --cam cam01 [--host 103.250.160.189] [--seconds 20]
    python grid_probe.py --url rtsp://... [--hls-url https://...] [--seconds 20]

Read-only; opens exactly one stream copy and closes it (pacing rule).
"""

import argparse
import json
import sys
import threading
import time
from datetime import datetime, timezone

from capture import CaptureLoop  # sets OPENCV_FFMPEG_CAPTURE_OPTIONS pre-cv2


class ProbeDetector:
    """Counting stub: records every frame CaptureLoop hands over."""

    def __init__(self):
        self.frames = 0
        self.resets = 0
        self.first_pts = None
        self.last_pts = None
        self.first_captured_at = None
        self.last_captured_at = None
        self.pts_gaps_ms = []

    def process(self, frame, pts_ms, captured_at):
        self.frames += 1
        if self.first_pts is None:
            self.first_pts = pts_ms
            self.first_captured_at = captured_at
        elif self.last_pts is not None:
            self.pts_gaps_ms.append(pts_ms - self.last_pts)
        self.last_pts = pts_ms
        self.last_captured_at = captured_at
        return []

    def reset(self):
        # Called on every (re)connect and PTS discontinuity.
        self.resets += 1


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cam", help="camera id on the grid, e.g. cam01")
    ap.add_argument("--host", default="103.250.160.189", help="direct RTSP/WHEP host")
    ap.add_argument("--url", help="explicit RTSP url (overrides --cam)")
    ap.add_argument("--hls-url", default=None, help="optional HLS fallback url")
    ap.add_argument("--seconds", type=float, default=20.0)
    args = ap.parse_args()

    if not args.url and not args.cam:
        ap.error("--cam or --url required")
    rtsp_url = args.url or f"rtsp://{args.host}:8554/stream/{args.cam}"

    camera = {
        "id": None,
        "name": args.cam or rtsp_url.rsplit("/", 1)[-1],
        "rtsp_url": rtsp_url,
        "hls_url": args.hls_url,
        "codec": None,
        "width": None,
        "height": None,
        "fps_declared": None,
    }

    detector = ProbeDetector()
    metrics_seen = []
    stop = threading.Event()
    loop = CaptureLoop(
        camera,
        detector,
        on_detection=lambda *a: None,
        on_metrics=lambda cam, m: metrics_seen.append(m),
        stop_event=stop,
        process_interval_ms=0.0,  # measure EVERY delivered frame
        metrics_interval_s=5.0,
    )

    started = datetime.now(timezone.utc)
    t = threading.Thread(target=loop.run, daemon=True)
    t.start()
    time.sleep(args.seconds)
    stop.set()
    t.join(timeout=15)
    wall_elapsed = (datetime.now(timezone.utc) - started).total_seconds()

    gaps = sorted(detector.pts_gaps_ms)
    pts_span_s = (
        (detector.last_pts - detector.first_pts) / 1000.0
        if detector.first_pts is not None and detector.last_pts is not None
        else None
    )
    report = {
        "camera": camera["name"],
        "rtsp_url": rtsp_url,
        "wall_seconds": round(wall_elapsed, 1),
        "frames_delivered": detector.frames,
        "fps_delivered": round(detector.frames / wall_elapsed, 2) if wall_elapsed else None,
        "fps_measured_by_loop": metrics_seen[-1]["fps_measured"] if metrics_seen else None,
        "bandwidth_kbps_est": metrics_seen[-1]["bandwidth_kbps"] if metrics_seen else None,
        "pts_span_s": round(pts_span_s, 1) if pts_span_s is not None else None,
        "pts_gap_ms_median": round(gaps[len(gaps) // 2], 1) if gaps else None,
        "pts_gap_ms_p95": round(gaps[int(len(gaps) * 0.95)], 1) if gaps else None,
        "pts_gap_ms_max": round(gaps[-1], 1) if gaps else None,
        "connects_plus_discontinuities": detector.resets,
        "reconnects": loop.reconnects,
        "first_captured_at": detector.first_captured_at.isoformat() if detector.first_captured_at else None,
        "last_captured_at": detector.last_captured_at.isoformat() if detector.last_captured_at else None,
    }
    json.dump(report, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
