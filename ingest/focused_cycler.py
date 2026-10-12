#!/usr/bin/env python3
"""Sentinel Focused Overnight ANPR Cycler.

Runs 13-minute full-loop windows on the highest-yield and candidate cameras across
Gujarat. Only 2 concurrent streams at a time to maintain high frame-rates, low CPU
usage, and respect gateway limits.

Batches (13 minutes each = 1 full 12.6m video loop):
  1. cam06 + cam23 (Demo Stars - Junagadh & Sandbox)
  2. cam27 + cam16 (Visat P2 & Sandbox)
  3. cam01 + cam05 (Chiman Bhai Bridge & Visat Teen Rasta)
  4. cam04 + cam26 (Paldi Circle & Sandbox Candidate)

Each 56-minute round runs all 8 cameras through their complete loop. Over 8 hours,
each camera gets 8 full-loop sweeps (~104 minutes active ANPR).
"""

import argparse
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Tuple

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
logger = logging.getLogger("focused_cycler")

FOCUSED_BATCHES: List[Tuple[str, str]] = [
    ("cam06", "cam23"),  # Demo Stars
    ("cam27", "cam16"),  # Usable Corridor
    ("cam01", "cam05"),  # Ahmedabad Arteries
    ("cam04", "cam26"),  # Promising Candidates
]


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def get_camera_by_ext_id(cameras: List[dict], ext_id: str) -> dict | None:
    for c in cameras:
        if c.get("external_id") == ext_id:
            return c
    return None


class FocusedCycler:
    def __init__(self, backend_url: str, duration_sec: int = 780, interval_ms: float = 200.0):
        self.backend_url = backend_url
        self.duration_sec = duration_sec  # 13 minutes default
        self.interval_ms = interval_ms
        self.client = httpx.Client(base_url=backend_url, timeout=httpx.Timeout(10.0, connect=5.0))
        self.running = True
        self.stats: Dict[str, int] = {}

        logger.info("Pre-loading 2 ANPR detector instances for dual-camera capture...")
        self.detectors = [make_detector("anpr"), make_detector("anpr")]
        logger.info("Detectors ready.")

    def stop(self):
        self.running = False

    def run(self):
        resp = self.client.get("/api/cameras")
        resp.raise_for_status()
        all_cams = resp.json()

        round_num = 1
        while self.running:
            logger.info("=" * 65)
            logger.info(">>> STARTING 13-MINUTE FULL-LOOP SWEEP ROUND %d (4 Batches)", round_num)
            logger.info("=" * 65)

            for b_idx, (ext1, ext2) in enumerate(FOCUSED_BATCHES, 1):
                if not self.running:
                    break

                cam1 = get_camera_by_ext_id(all_cams, ext1)
                cam2 = get_camera_by_ext_id(all_cams, ext2)
                pair = [c for c in [cam1, cam2] if c is not None]

                names = [f"{c['external_id']} ({c['name']})" for c in pair]
                logger.info("-----------------------------------------------------------------")
                logger.info("[Round %d | Batch %d/4] Capturing full 12.6m loop on: %s", round_num, b_idx, " & ".join(names))
                logger.info("Running for %d seconds (~%.1f mins)...", self.duration_sec, self.duration_sec / 60.0)
                logger.info("-----------------------------------------------------------------")

                self._run_pair(pair)

                # Short 15s gentle rest between batch switches
                if self.running and b_idx < len(FOCUSED_BATCHES):
                    logger.info("Batch completed. Pausing 15s before next camera pair...")
                    time.sleep(15.0)

            round_num += 1
            logger.info("Round %d finished. Total plate reads summary: %s", round_num - 1, dict(self.stats))
            if self.running:
                logger.info("Pausing 30s before starting Round %d...", round_num)
                time.sleep(30.0)

    def _run_pair(self, pair: List[dict]):
        batch_stop = threading.Event()
        threads = []

        def on_detection(camera, result, pts_ms, captured_at):
            cid = camera.get("external_id") or str(camera.get("id"))
            if result.plate:
                self.stats[cid] = self.stats.get(cid, 0) + 1
                logger.info(
                    "🎯 [%s] Plate: %-11s | %-5s | Conf: %.2f | Camera: %s",
                    cid, result.plate, result.vehicle_type or "car",
                    result.plate_confidence or 0.85, camera.get("name"),
                )

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

        for idx, cam in enumerate(pair):
            try:
                det = self.detectors[idx]
                det.reset()
                loop = CaptureLoop(
                    cam,
                    det,
                    on_detection=on_detection,
                    on_status=on_status,
                    on_metrics=on_metrics,
                    stop_event=batch_stop,
                    process_interval_ms=self.interval_ms,
                )
                t = threading.Thread(target=loop.run, name=f"worker-{cam['external_id']}", daemon=True)
                threads.append(t)
                t.start()
            except Exception as err:
                logger.error("Failed to start loop for camera %s: %s", cam.get("external_id"), err)

        t_end = time.time() + self.duration_sec
        while time.time() < t_end and self.running:
            time.sleep(1.0)

        batch_stop.set()
        for t in threads:
            t.join(timeout=4.0)


def main():
    parser = argparse.ArgumentParser(description="Sentinel Focused 13-Minute ANPR Cycler")
    parser.add_argument("--backend-url", default="http://localhost:8001", help="Backend API URL")
    parser.add_argument("--duration", type=int, default=780, help="Seconds per batch (780s = 13m full loop)")
    parser.add_argument("--interval-ms", type=float, default=200.0, help="ANPR frame interval in ms")
    args = parser.parse_args()

    cycler = FocusedCycler(backend_url=args.backend_url, duration_sec=args.duration, interval_ms=args.interval_ms)

    def sig_handler(sig, frame):
        logger.info("Stopping cycler gracefully...")
        cycler.stop()

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    cycler.run()


if __name__ == "__main__":
    main()
