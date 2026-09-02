"""Sentinel ingest worker - captures camera streams and posts detections.

Usage:
    python worker.py [--detector mock|anpr] [--cameras id1,id2] [--max-cameras N]

Flow (docs/CONTRACT.md, ingest module):
    1. POST {BACKEND_URL}/api/cameras/sync   - backend pulls the catalogue
       from {SENTINEL_HOST}/api/ingest (camera list and per-camera properties
       always come from the catalogue, gateway checklist item 6).
    2. GET  /api/cameras?source=catalogue&status=live
    3. Spawn one CaptureLoop thread per camera, capped by --max-cameras
       (default 4 - gateway rule 11: pace the load, open only cameras that
       are actively processed).
    4. Each thread: PTS-anchored capture (capture.py), detector inference,
       POST /api/detections, heartbeat POSTs on connect/disconnect.
    5. Ctrl-C: stop event -> loops exit, captures released, final "down"
       heartbeats sent, threads joined.

The worker talks ONLY to the backend REST API and the video streams; it never
publishes to or controls the gateway (gateway rule 10).
"""

import argparse
import logging
import os
import signal
import sys
import threading
from datetime import timezone

# Import capture FIRST: it sets OPENCV_FFMPEG_CAPTURE_OPTIONS (RTSP over TCP,
# gateway rule 1) at module-import time, before cv2 can be imported anywhere.
from capture import CaptureLoop

import httpx

from detectors import make_detector

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")
DEFAULT_MAX_CAMERAS = 4
SHUTDOWN_JOIN_TIMEOUT_S = 10.0

logger = logging.getLogger("ingest.worker")


def iso_z(dt) -> str:
    """UTC ISO8601 with trailing Z (contract: all timestamps are UTC + Z)."""
    return (
        dt.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Sentinel ingest worker: capture live camera streams, run a "
        "detector, and POST detections to the backend.",
    )
    parser.add_argument(
        "--detector",
        choices=["mock", "anpr"],
        default="mock",
        help="detector implementation (anpr needs requirements-ml.txt extras)",
    )
    parser.add_argument(
        "--cameras",
        default=None,
        metavar="id1,id2",
        help="comma-separated backend camera ids to capture (default: all live "
        "catalogue cameras, capped by --max-cameras)",
    )
    parser.add_argument(
        "--max-cameras",
        type=int,
        default=DEFAULT_MAX_CAMERAS,
        metavar="N",
        help="maximum concurrent captures (default %(default)s - every client "
        "gets its own stream copy, so pace the load; gateway rule 11)",
    )
    return parser.parse_args(argv)


def fetch_cameras(client: httpx.Client, args) -> list:
    """Sync the catalogue through the backend, then list live cameras."""
    try:
        resp = client.post("/api/cameras/sync")
        resp.raise_for_status()
        logger.info("camera sync: %s", resp.json())
    except Exception as exc:
        logger.warning(
            "camera sync failed (%s) - continuing with cameras already known to the backend",
            exc,
        )

    if args.cameras:
        # An explicit --cameras id list is the operator's word: fetch the FULL
        # registry (manual/csv/catalogue, any status) and select exactly those
        # ids, so a manually onboarded camera (e.g. own recorded footage
        # registered via POST /api/cameras with a file path as rtsp_url) can be
        # captured too. The source=catalogue&status=live filter below only
        # guards the default select-everything path.
        resp = client.get("/api/cameras")
        resp.raise_for_status()
        cameras = resp.json()
        cameras.sort(key=lambda c: c.get("id") or 0)
        wanted = {int(part) for part in args.cameras.split(",") if part.strip()}
        cameras = [c for c in cameras if c.get("id") in wanted]
        missing = wanted - {c.get("id") for c in cameras}
        if missing:
            logger.warning(
                "requested camera ids not registered in the backend: %s",
                sorted(missing),
            )
        for cam in cameras:
            if cam.get("status") != "live" or cam.get("source") != "catalogue":
                logger.info(
                    "explicitly requested camera %s (source=%s, status=%s) - "
                    "capturing as ordered",
                    cam.get("id"), cam.get("source"), cam.get("status"),
                )
    else:
        resp = client.get(
            "/api/cameras", params={"source": "catalogue", "status": "live"}
        )
        resp.raise_for_status()
        cameras = resp.json()
        cameras.sort(key=lambda c: c.get("id") or 0)

    if len(cameras) > args.max_cameras:
        logger.info(
            "limiting to %d of %d live cameras (gateway rule 11: pace the load)",
            args.max_cameras, len(cameras),
        )
        cameras = cameras[: args.max_cameras]
    return cameras


def main(argv=None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(threadName)-12s %(message)s",
    )
    args = parse_args(argv)
    client = httpx.Client(base_url=BACKEND_URL, timeout=httpx.Timeout(10.0, connect=5.0))

    try:
        cameras = fetch_cameras(client, args)
    except Exception as exc:
        logger.error("cannot list cameras from backend at %s: %s", BACKEND_URL, exc)
        client.close()
        return 1
    if not cameras:
        logger.error(
            "no live catalogue cameras to capture (run mock_gateway.py and check "
            "SENTINEL_HOST / --cameras filter)"
        )
        client.close()
        return 1

    stop_event = threading.Event()

    def on_detection(camera, result, pts_ms, captured_at):
        payload = {
            "camera_id": camera["id"],
            "object_type": result.object_type,
            "pts_ms": pts_ms,
            "captured_at": iso_z(captured_at),
            "detector": args.detector,
        }
        if result.plate:
            payload["plate"] = result.plate
        if result.plate_confidence is not None:
            payload["plate_confidence"] = result.plate_confidence
        if result.bbox:
            payload["bbox"] = result.bbox
        if result.snapshot_b64:
            payload["snapshot_b64"] = result.snapshot_b64
        try:
            resp = client.post("/api/detections", json=payload)
            resp.raise_for_status()
            body = resp.json()
            if body.get("alert_id"):
                logger.info(
                    "ALERT %s: plate=%s camera=%s captured_at=%s",
                    body["alert_id"], result.plate, camera.get("name"),
                    payload["captured_at"],
                )
            else:
                logger.debug(
                    "detection %s: plate=%s camera=%s",
                    body.get("detection_id"), result.plate, camera.get("name"),
                )
        except Exception as exc:
            # Backend hiccups must never kill a capture thread.
            logger.warning("failed to POST detection for camera %s: %s", camera.get("id"), exc)

    def on_status(camera, status):
        """Heartbeat to the backend on connect ('live') / disconnect ('down')."""
        try:
            resp = client.post(
                f"/api/cameras/{camera['id']}/heartbeat", json={"status": status}
            )
            resp.raise_for_status()
            logger.info("heartbeat: camera %s -> %s", camera.get("id"), status)
        except Exception as exc:
            logger.warning("heartbeat failed for camera %s: %s", camera.get("id"), exc)

    def on_metrics(camera, metrics):
        """Periodic health heartbeat with MEASURED values (capture.py):
        fps_measured (frame-count delta / wall time = real delivery rate),
        last_frame_age_s, reconnects, bandwidth_kbps (estimated from measured
        resolution x measured fps x codec bits/pixel)."""
        payload = {"status": "live"}
        payload.update({k: v for k, v in metrics.items() if v is not None})
        try:
            resp = client.post(f"/api/cameras/{camera['id']}/heartbeat", json=payload)
            resp.raise_for_status()
            logger.debug("metrics heartbeat: camera %s %s", camera.get("id"), metrics)
        except Exception as exc:
            logger.warning("metrics heartbeat failed for camera %s: %s", camera.get("id"), exc)

    threads = []
    for cam in cameras:
        try:
            # One detector instance per camera thread: detector state (motion
            # baselines, de-dup windows) is per-stream, and inference stays
            # thread-confined.
            detector = make_detector(args.detector)
        except ImportError as exc:
            logger.error("%s", exc)
            client.close()
            return 2
        loop = CaptureLoop(
            cam,
            detector,
            on_detection=on_detection,
            on_status=on_status,
            on_metrics=on_metrics,
            stop_event=stop_event,
        )
        threads.append(
            threading.Thread(target=loop.run, name=f"cam-{cam['id']}", daemon=True)
        )

    def handle_signal(signum, frame):
        logger.info("shutdown requested (signal %s) - closing captures...", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    for thread in threads:
        thread.start()
    logger.info(
        "ingest worker running: %d camera(s), detector=%s, backend=%s (Ctrl-C to stop)",
        len(threads), args.detector, BACKEND_URL,
    )

    try:
        while not stop_event.is_set() and any(t.is_alive() for t in threads):
            stop_event.wait(1.0)
    except KeyboardInterrupt:
        # Fallback if the signal handler was replaced.
        logger.info("KeyboardInterrupt - closing captures...")
    finally:
        stop_event.set()

    for thread in threads:
        # Grace period lets loops release captures and send 'down' heartbeats.
        thread.join(timeout=SHUTDOWN_JOIN_TIMEOUT_S)
    stragglers = [t.name for t in threads if t.is_alive()]
    if stragglers:
        logger.warning(
            "threads still blocked in a network read at exit (daemonized, will be "
            "reaped by the OS): %s",
            stragglers,
        )
    client.close()
    logger.info("worker stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
