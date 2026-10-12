#!/usr/bin/env python3
"""Sentinel 30-Camera Overnight Round-Robin ANPR Ingest Cycler.

Cycles through all 30 CCTV cameras across Gujarat in batches (default 3 cameras
concurrently for 3 minutes each). Captures live RTSP feeds, executes ANPR plate
recognition, and commits detections, vehicle types, and timestamps into PostgreSQL.

In an 8-hour overnight run, every single camera is visited ~16 times, ensuring
comprehensive vehicle and license plate records across all 30 cameras for the
hackathon judges.
"""

import argparse
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List

# Force TCP RTSP before cv2 import anywhere
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|fflags;discardcorrupt"
os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "8")
os.environ.setdefault("GRID_RTSP_AUTH", "divijpatel0807@gmail.com:YXK9-4EBK-BG35")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from capture import CaptureLoop
from detectors import make_detector
import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(threadName)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("overnight_cycler")


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def fetch_all_cameras(client: httpx.Client) -> List[dict]:
    resp = client.get("/api/cameras")
    resp.raise_for_status()
    cams = resp.json()
    # Sort numerically by external_id (cam01 .. cam30) or id
    def sort_key(c):
        ext = c.get("external_id") or ""
        digits = "".join(ch for ch in ext if ch.isdigit())
        return int(digits) if digits else c.get("id", 0)
    cams.sort(key=sort_key)
    return cams


class RoundRobinIngester:
    def __init__(self, backend_url: str, batch_size: int = 3, duration_sec: int = 180, interval_ms: float = 250.0):
        self.backend_url = backend_url
        self.batch_size = batch_size
        self.duration_sec = duration_sec
        self.interval_ms = interval_ms
        self.client = httpx.Client(base_url=backend_url, timeout=httpx.Timeout(10.0, connect=5.0))
        self.running = True
        self.stats: Dict[str, int] = {}  # external_id -> plate_count

        logger.info("Pre-loading %d ANPR detector instances into memory for instant batch switching...", batch_size)
        self.detectors = [make_detector("anpr") for _ in range(batch_size)]
        logger.info("Detectors ready!")

    def stop(self):
        self.running = False

    def run(self):
        all_cams = fetch_all_cameras(self.client)
        if not all_cams:
            logger.error("No cameras found in backend!")
            return

        logger.info("Found %d cameras to cycle. Batch size: %d, Duration per batch: %ds", len(all_cams), self.batch_size, self.duration_sec)
        
        # Partition into batches
        batches = [all_cams[i : i + self.batch_size] for i in range(0, len(all_cams), self.batch_size)]
        round_num = 1

        while self.running:
            logger.info("=" * 60)
            logger.info(">>> STARTING OVERNIGHT SWEEP ROUND %d (Total cameras: %d, Batches: %d)", round_num, len(all_cams), len(batches))
            logger.info("=" * 60)

            for batch_idx, batch in enumerate(batches, 1):
                if not self.running:
                    break

                cam_names = [f"{c.get('external_id')}:{c.get('name')}" for c in batch]
                logger.info("------------------------------------------------------------")
                logger.info("[Round %d | Batch %d/%d] Ingesting: %s", round_num, batch_idx, len(batches), ", ".join(cam_names))
                logger.info("Running for %d seconds...", self.duration_sec)
                logger.info("------------------------------------------------------------")

                self._run_batch(batch)

            round_num += 1
            logger.info("Round %d completed. Summary of plates read so far: %s", round_num - 1, dict(self.stats))

    def _run_batch(self, batch_cams: List[dict]):
        batch_stop_event = threading.Event()
        threads = []
        loops = []

        def on_detection(camera, result, pts_ms, captured_at):
            cid = camera.get("external_id") or str(camera.get("id"))
            if result.plate:
                self.stats[cid] = self.stats.get(cid, 0) + 1
                logger.info("🎯 [%s] Plate: %-11s | Type: %-5s | Conf: %.2f | Camera: %s", cid, result.plate, result.vehicle_type or "car", result.plate_confidence or 0.85, camera.get("name"))

            payload = {
                "camera_id": camera["id"],
                "camera_external_id": camera.get("external_id"),
                "object_type": result.object_type or "vehicle",
                "pts_ms": pts_ms,
                "captured_at": iso_z(captured_at),
                "detector": "anpr",
            }
            if getattr(result, "vehicle_type", None):
                payload["vehicle_type"] = result.vehicle_type
            if result.plate:
                payload["plate"] = result.plate
            if result.plate_confidence is not None:
                payload["plate_confidence"] = float(result.plate_confidence)
            if result.bbox:
                payload["bbox"] = result.bbox
            if result.snapshot_b64:
                payload["snapshot_b64"] = result.snapshot_b64

            try:
                self.client.post("/api/detections", json=payload)
            except Exception as exc:
                logger.debug("Failed to POST detection: %s", exc)

        def on_status(camera, status):
            try:
                self.client.post(f"/api/cameras/{camera['id']}/heartbeat", json={"status": status})
            except Exception:
                pass

        def on_metrics(camera, metrics):
            payload = {"status": "live"}
            payload.update({k: v for k, v in metrics.items() if v is not None})
            try:
                self.client.post(f"/api/cameras/{camera['id']}/heartbeat", json=payload)
            except Exception:
                pass

        for idx, cam in enumerate(batch_cams):
            try:
                detector = self.detectors[idx % len(self.detectors)]
                detector.reset()
                loop = CaptureLoop(
                    cam,
                    detector,
                    on_detection=on_detection,
                    on_status=on_status,
                    on_metrics=on_metrics,
                    stop_event=batch_stop_event,
                    process_interval_ms=self.interval_ms,
                )
                t = threading.Thread(target=loop.run, name=f"worker-{cam.get('external_id')}", daemon=True)
                loops.append(loop)
                threads.append(t)
                t.start()
            except Exception as err:
                logger.error("Failed to start loop for camera %s: %s", cam.get("external_id"), err)

        # Let the batch run for duration_sec, checking if user wants to exit
        t_end = time.time() + self.duration_sec
        while time.time() < t_end and self.running:
            time.sleep(1.0)

        # Stop this batch
        batch_stop_event.set()
        for t in threads:
            t.join(timeout=3.0)


def main():
    parser = argparse.ArgumentParser(description="Sentinel 30-Camera Overnight Round-Robin Cycler")
    parser.add_argument("--backend-url", default="http://localhost:8001", help="Backend API URL")
    parser.add_argument("--batch-size", type=int, default=3, help="Concurrent cameras (default 3)")
    parser.add_argument("--duration", type=int, default=180, help="Seconds per batch (default 180s = 3m)")
    parser.add_argument("--interval-ms", type=float, default=250.0, help="ANPR frame interval in ms")
    args = parser.parse_args()

    ingester = RoundRobinIngester(
        backend_url=args.backend_url,
        batch_size=args.batch_size,
        duration_sec=args.duration,
        interval_ms=args.interval_ms,
    )

    def sig_handler(sig, frame):
        logger.info("Shutdown signal received. Stopping cycler...")
        ingester.stop()

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    ingester.run()


if __name__ == "__main__":
    main()
