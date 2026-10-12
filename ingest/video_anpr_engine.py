"""Live Video ANPR Engine & API Server for SENTINEL.

Plays any local video file (or uploaded file) in a continuous capture loop,
runs the real AnprDetector (YOLOv8n + plate localizer + RapidOCR),
draws live bounding boxes + plate labels, serves an MJPEG stream, and
posts detections to the Sentinel backend database and alerts WebSocket.

Endpoints:
    GET  /api/video-anpr/stream.mjpg   Live MJPEG stream with YOLO & OCR bounding boxes
    GET  /api/video-anpr/snapshot.jpg  Latest annotated JPEG snapshot
    GET  /api/video-anpr/status        Current playback stats, FPS, counts
    GET  /api/video-anpr/detections    Recent detected license plates
    POST /api/video-anpr/play          Switch video path, camera ID, loop option
    POST /api/video-anpr/upload        Upload any MP4/AVI/MOV and start analyzing
    POST /api/video-anpr/control       Pause / resume / restart / toggle sync
"""

import os
import sys
import time
import json
import base64
import logging
import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional

# Rule 1: Set OpenCV RTSP/capture options before cv2 is imported
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
os.environ.setdefault("OPENCV_FFMPEG_LOGLEVEL", "8")

import cv2
import httpx
import uvicorn
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response, JSONResponse

# Sentinel ML imports
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from ai_view import annotate, MJPEG_BOUNDARY, JPEG_QUALITY
from detectors.anpr import AnprDetector

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("video_anpr_engine")

DEFAULT_VIDEO = os.path.join(HERE, "..", "cam06_daytime.mp4")
UPLOADS_DIR = os.path.join(HERE, "..", "deliverables", "uploads")
os.makedirs(UPLOADS_DIR, exist_ok=True)

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8001")


class VideoAnprPlayer:
    def __init__(self, default_video: str = DEFAULT_VIDEO):
        self.video_path = os.path.normpath(default_video)
        self.camera_id = 6
        self.camera_name = "Madhuram Bypass Road Fix-2 (cam06 daytime)"
        self.loop = True
        self.sync_backend = True
        self.is_paused = False
        self.running = False

        self.detector = AnprDetector()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Stream state
        self._latest_jpeg: Optional[bytes] = None
        self._latest_frame_ts = time.monotonic()
        self._boxes: List[dict] = []
        self._fps: float = 25.0
        self._frame_count: int = 0
        self._vehicle_count: int = 0
        self._plate_count: int = 0
        self._recent_detections: List[dict] = []
        self._http_client = httpx.Client(timeout=2.0)
        self._last_backend_posts: dict[str, float] = {}

    def start(self):
        if not self.running:
            self.running = True
            self._thread = threading.Thread(target=self._run_loop, name="anpr-player", daemon=True)
            self._thread.start()
            logger.info("Video ANPR player thread started for %s", self.video_path)

    def stop(self):
        self.running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def switch_video(self, video_path: str, camera_id: int = 6, camera_name: str = "Custom Video Feed", loop: bool = True):
        with self._lock:
            self.video_path = video_path
            self.camera_id = camera_id
            self.camera_name = camera_name
            self.loop = loop
            self.detector.reset()
            self._boxes = []
            self._last_backend_posts.clear()
        logger.info("Switched video to: %s", video_path)

    def _post_to_backend(self, detection: dict):
        if not self.sync_backend:
            return
        plate = detection.get("plate")
        now_ts = time.time()
        # Cooldown: Prevent repeated video loops from spamming the backend/alerts with the same vehicle
        if plate:
            last_ts = self._last_backend_posts.get(plate, 0.0)
            if (now_ts - last_ts) < 600.0:  # 10 minute cooldown per plate
                return
            self._last_backend_posts[plate] = now_ts
        try:
            payload = {
                "camera_id": self.camera_id,
                "camera_external_id": f"cam{self.camera_id:02d}",
                "object_type": "vehicle",
                "plate": plate,
                "plate_confidence": float(detection.get("confidence", 0.9)),
                "captured_at": detection.get("detected_at"),
                "snapshot_b64": detection.get("snapshot_b64"),
                "vehicle_type": detection.get("vehicle_type"),
                "detector": "anpr",
            }
            resp = self._http_client.post(f"{BACKEND_URL}/api/detections", json=payload)
            if resp.status_code in (200, 201):
                logger.info("Posted detection to backend: %s (%s, conf=%.2f)", plate, detection.get("vehicle_type"), detection.get("confidence", 0.0))
        except Exception as exc:
            logger.debug("Backend post failed: %s", exc)

    def _run_loop(self):
        while self.running:
            current_path = self.video_path
            if not os.path.exists(current_path):
                logger.warning("Video file not found: %s - waiting...", current_path)
                time.sleep(2.0)
                continue

            cap = cv2.VideoCapture(current_path)
            if not cap.isOpened():
                logger.error("Could not open video file: %s", current_path)
                time.sleep(2.0)
                continue

            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            frame_delay = 1.0 / max(5.0, min(fps, 30.0))
            pts_ms = 0.0
            inference_interval_ms = 180.0  # Run full detection every 180 ms (~5.5 Hz)
            last_inference_pts = -1000.0

            logger.info("Playing %s @ %.1f FPS (delay %.3fs)", current_path, fps, frame_delay)

            while self.running and current_path == self.video_path:
                if self.is_paused:
                    time.sleep(0.1)
                    continue

                t0 = time.monotonic()
                ret, frame = cap.read()
                if not ret:
                    if self.loop:
                        logger.info("Looping video: %s", current_path)
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        self.detector.reset()
                        pts_ms = 0.0
                        last_inference_pts = -1000.0
                        continue
                    else:
                        break

                pts_ms += frame_delay * 1000.0
                now_utc = datetime.now(timezone.utc)

                # Run ANPR detector at throttled interval
                if (pts_ms - last_inference_pts) >= inference_interval_ms:
                    last_inference_pts = pts_ms
                    try:
                        results = self.detector.process(frame, pts_ms, now_utc)
                        boxes = list(getattr(self.detector, "last_frame_boxes", []))
                        with self._lock:
                            self._boxes = boxes
                            self._vehicle_count = sum(1 for b in boxes if b.get("kind") == "vehicle")
                            self._plate_count = sum(1 for b in boxes if b.get("kind") == "plate")

                        for r in results:
                            if r.plate:
                                item = {
                                    "plate": r.plate,
                                    "confidence": round(float(r.plate_confidence or 0.85), 3),
                                    "vehicle_type": r.vehicle_type or "car",
                                    "detected_at": now_utc.isoformat(),
                                    "camera_id": self.camera_id,
                                    "camera_name": self.camera_name,
                                    "snapshot_b64": r.snapshot_b64,
                                }
                                with self._lock:
                                    # Deduplicate within last 3 seconds
                                    if not any(d["plate"] == r.plate for d in self._recent_detections[:5]):
                                        self._recent_detections.insert(0, item)
                                        self._recent_detections = self._recent_detections[:50]
                                self._post_to_backend(item)
                    except Exception as err:
                        logger.error("Detector inference error: %s", err)

                # Annotate current frame with freshest boxes
                with self._lock:
                    current_boxes = list(self._boxes)
                    cam_name = self.camera_name

                annotated = annotate(frame, current_boxes, cam_name, now_utc)
                ok, jpeg_buf = cv2.imencode(".jpg", annotated, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
                if ok:
                    with self._lock:
                        self._latest_jpeg = jpeg_buf.tobytes()
                        self._latest_frame_ts = time.monotonic()
                        self._frame_count += 1

                elapsed = time.monotonic() - t0
                sleep_s = max(0.005, frame_delay - elapsed)
                time.sleep(sleep_s)

            cap.release()
            time.sleep(0.5)

    def get_status(self) -> dict:
        with self._lock:
            return {
                "video_path": os.path.basename(self.video_path),
                "camera_name": self.camera_name,
                "camera_id": self.camera_id,
                "is_paused": self.is_paused,
                "loop": self.loop,
                "sync_backend": self.sync_backend,
                "frame_count": self._frame_count,
                "vehicles_in_frame": self._vehicle_count,
                "plates_in_frame": self._plate_count,
                "total_reads": len(self._recent_detections),
                "latest_read": self._recent_detections[0] if self._recent_detections else None,
            }

    def get_recent_detections(self) -> List[dict]:
        with self._lock:
            return list(self._recent_detections)

    def get_latest_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._latest_jpeg


player = VideoAnprPlayer()

from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(app: FastAPI):
    player.start()
    yield
    player.stop()

app = FastAPI(
    title="Sentinel Video ANPR Service",
    description="Live Video ANPR Stream & Plate Detector",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/video-anpr/status")
def status():
    return player.get_status()


@app.get("/api/video-anpr/detections")
def detections():
    return player.get_recent_detections()


@app.get("/api/video-anpr/snapshot.jpg")
def snapshot():
    jpeg = player.get_latest_jpeg()
    if not jpeg:
        raise HTTPException(status_code=404, detail="No frame yet")
    return Response(content=jpeg, media_type="image/jpeg", headers={"Access-Control-Allow-Origin": "*"})


@app.get("/api/video-anpr/stream.mjpg")
def stream():
    def frame_generator():
        while True:
            jpeg = player.get_latest_jpeg()
            if jpeg:
                yield (
                    f"--{MJPEG_BOUNDARY}\r\n"
                    f"Content-Type: image/jpeg\r\n"
                    f"Content-Length: {len(jpeg)}\r\n\r\n"
                ).encode("ascii") + jpeg + b"\r\n"
            time.sleep(0.04)  # ~25 FPS delivery

    return StreamingResponse(
        frame_generator(),
        media_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}",
        headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-cache"}
    )


@app.post("/api/video-anpr/play")
def play_video(data: dict):
    path = data.get("video_path") or DEFAULT_VIDEO
    if not os.path.isabs(path):
        path = os.path.join(HERE, "..", path)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail=f"File not found: {path}")

    cam_id = data.get("camera_id", 6)
    cam_name = data.get("camera_name", "Madhuram Bypass Road (cam06 daytime)")
    loop = data.get("loop", True)

    player.switch_video(path, camera_id=cam_id, camera_name=cam_name, loop=loop)
    return {"status": "ok", "playing": os.path.basename(path)}


@app.post("/api/video-anpr/upload")
async def upload_video(file: UploadFile = File(...)):
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in (".mp4", ".avi", ".mov", ".mkv", ".ts"):
        raise HTTPException(status_code=400, detail="Unsupported video format. Allowed: .mp4, .avi, .mov, .mkv")

    target_path = os.path.join(UPLOADS_DIR, file.filename)
    content = await file.read()
    with open(target_path, "wb") as f:
        f.write(content)

    player.switch_video(target_path, camera_id=6, camera_name=f"Uploaded: {file.filename}", loop=True)
    return {
        "status": "ok",
        "filename": file.filename,
        "size_bytes": len(content),
        "message": f"Analyzing uploaded video '{file.filename}' live!"
    }


@app.post("/api/video-anpr/control")
def control(data: dict):
    action = data.get("action")
    if action == "pause":
        player.is_paused = True
    elif action == "resume":
        player.is_paused = False
    elif action == "toggle_pause":
        player.is_paused = not player.is_paused
    elif action == "toggle_sync":
        player.sync_backend = not player.sync_backend
    elif action == "restart":
        player.switch_video(player.video_path, player.camera_id, player.camera_name, player.loop)
    return player.get_status()


if __name__ == "__main__":
    port = int(os.environ.get("VIDEO_ANPR_PORT", "8895"))
    logger.info("Starting Video ANPR Service on http://0.0.0.0:%d", port)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
