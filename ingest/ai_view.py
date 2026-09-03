"""Live "AI view": the frames the ANPR pipeline actually analyses, annotated.

A tiny loopback HTTP server that serves, per camera, the latest frame handed
to the detector with the detector's boxes drawn on it (vehicles green, plates
yellow with the read registration + confidence) plus a small HUD. It exists
so the dashboard / a browser tab / a screen recording can SHOW what the model
sees, next to the alerts it raises. It is deliberately side-channel only:
nothing here feeds back into capture, detection or the backend.

Endpoints (all with ``Access-Control-Allow-Origin: *``):

    GET /ai                 JSON list of camera keys with last-frame age
    GET /ai/<key>.jpg       latest annotated frame (JPEG), 404 until one exists
    GET /ai/<key>.mjpg      multipart/x-mixed-replace MJPEG stream (~10 fps)

``key`` is the camera's ``external_id`` when present, else ``str(id)`` (see
:func:`cam_key_for`). Wire-up: the worker starts one :class:`AiViewServer`
and passes :meth:`AiViewServer.on_frame` as the ``on_frame`` hook of every
``CaptureLoop`` (capture.py), which calls it after each processed frame.

Only the latest frame per key is kept (a few hundred KB per camera); frames
are drawn and JPEG-encoded in the camera thread (a few ms at <= 960 px wide)
and handed over under a lock.
"""

import json
import os
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional, Tuple

# Gateway rule 1: the RTSP transport option must exist before cv2's first
# import in the process. capture.py force-sets it; setdefault keeps that.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

import cv2
import numpy as np

DEFAULT_PORT = 8892
MAX_WIDTH = 1280                # downscale before drawing so lines stay crisp (fullscreen-sharp)
JPEG_QUALITY = 82
STREAM_PART_SLEEP_S = 0.1       # ~10 fps MJPEG
VEHICLE_COLOR = (0, 200, 90)    # BGR green
PLATE_COLOR = (0, 215, 255)     # BGR yellow
LABEL_TEXT_COLOR = (255, 255, 255)
LABEL_BG_COLOR = (25, 25, 25)
HUD_BG_COLOR = (15, 15, 15)
FONT = cv2.FONT_HERSHEY_SIMPLEX
MJPEG_BOUNDARY = "sentinelframe"


def cam_key_for(camera: dict) -> str:
    """Stable URL key for a camera record: external_id if present, else id."""
    ext = camera.get("external_id")
    return str(ext) if ext else str(camera.get("id"))


def _utc_label(captured_at) -> str:
    if captured_at is None:
        return "--:--:--Z"
    try:
        dt = captured_at.astimezone(timezone.utc)
    except Exception:
        return str(captured_at)
    return dt.strftime("%Y-%m-%d %H:%M:%S") + "Z"


def _draw_label(img, text, x, y, color, filled_bg, scale=0.55, thickness=1):
    """Text with a filled background box; (x, y) is the anchor's top-left.

    Clamped to the image so labels of boxes near the top edge stay visible.
    """
    (tw, th), baseline = cv2.getTextSize(text, FONT, scale, thickness)
    h, w = img.shape[:2]
    box_h = th + baseline + 6
    x = max(0, min(x, w - tw - 8))
    y = max(0, min(y, h - box_h))
    if filled_bg:
        cv2.rectangle(img, (x, y), (x + tw + 8, y + box_h), LABEL_BG_COLOR, -1)
        cv2.rectangle(img, (x, y), (x + tw + 8, y + box_h), color, 1)
        cv2.putText(img, text, (x + 4, y + th + 3), FONT, scale,
                    LABEL_TEXT_COLOR, thickness, cv2.LINE_AA)
    else:
        cv2.putText(img, text, (x + 4, y + th + 3), FONT, scale, color,
                    thickness, cv2.LINE_AA)


def annotate(frame_bgr, boxes: List[dict], camera_name: str = "",
             captured_at=None) -> np.ndarray:
    """Return an annotated COPY of ``frame_bgr`` at <= MAX_WIDTH wide.

    The frame is downscaled FIRST (INTER_AREA) and the boxes are scaled with
    it, so box lines and text are drawn at output resolution and stay crisp.
    """
    h, w = frame_bgr.shape[:2]
    scale = 1.0
    if w > MAX_WIDTH:
        scale = MAX_WIDTH / float(w)
        img = cv2.resize(frame_bgr, (MAX_WIDTH, max(1, int(round(h * scale)))),
                         interpolation=cv2.INTER_AREA)
    else:
        img = frame_bgr.copy()

    vehicles = plates = 0
    # Vehicles first so plate boxes/labels are drawn on top of them.
    ordered = sorted(boxes or [], key=lambda b: 0 if b.get("kind") == "vehicle" else 1)
    for b in ordered:
        try:
            x1, y1 = int(round(b["x1"] * scale)), int(round(b["y1"] * scale))
            x2, y2 = int(round(b["x2"] * scale)), int(round(b["y2"] * scale))
        except (KeyError, TypeError, ValueError):
            continue
        kind = b.get("kind")
        label = b.get("label")
        if kind == "plate":
            plates += 1
            cv2.rectangle(img, (x1, y1), (x2, y2), PLATE_COLOR, 2)
            text = label or "plate"
            # Label above the plate box; falls below it when there is no room.
            (_, th), baseline = cv2.getTextSize(text, FONT, 0.6, 2)
            ly = y1 - (th + baseline + 8)
            if ly < 0:
                ly = y2 + 2
            _draw_label(img, text, x1, ly, PLATE_COLOR, True, scale=0.6, thickness=2)
        else:
            vehicles += 1
            cv2.rectangle(img, (x1, y1), (x2, y2), VEHICLE_COLOR, 2)
            if label:
                _draw_label(img, label, x1, y1 + 2, VEHICLE_COLOR, False, scale=0.45)

    # HUD (top-left). Hershey fonts are ASCII-only, hence "-" not a middle dot.
    lines = [
        camera_name or "camera",
        "AI VIEW - live ANPR",
        _utc_label(captured_at),
        f"vehicles {vehicles}   plates {plates}",
    ]
    pad, line_h = 8, 20
    widest = max(cv2.getTextSize(t, FONT, 0.5, 1)[0][0] for t in lines)
    overlay = img.copy()
    cv2.rectangle(overlay, (0, 0), (widest + 2 * pad + 4, line_h * len(lines) + pad),
                  HUD_BG_COLOR, -1)
    cv2.addWeighted(overlay, 0.65, img, 0.35, 0, img)
    for i, text in enumerate(lines):
        color = PLATE_COLOR if i == 1 else (235, 235, 235)
        cv2.putText(img, text, (pad, pad + line_h * i + 12), FONT, 0.5, color, 1, cv2.LINE_AA)
    return img


def _placeholder_jpeg(key: str) -> bytes:
    img = np.full((270, 480, 3), HUD_BG_COLOR, dtype=np.uint8)
    cv2.putText(img, f"{key}: waiting for frames", (16, 140), FONT, 0.6,
                (200, 200, 200), 1, cv2.LINE_AA)
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 60])
    return buf.tobytes() if ok else b""


class AiViewServer:
    """Loopback MJPEG/JPEG server for annotated frames, one slot per camera."""

    def __init__(self, port: int = DEFAULT_PORT, host: str = "127.0.0.1"):
        self.host = host
        self._frames: Dict[str, Tuple[bytes, float, str, str]] = {}
        self._lock = threading.Lock()
        self._stopping = threading.Event()
        view = self

        class _Server(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True

        class _Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args):  # keep the worker log clean
                return

            def _cors(self):
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Cache-Control", "no-cache, no-store")

            def do_OPTIONS(self):
                self.send_response(204)
                self._cors()
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_GET(self):
                path = self.path.split("?", 1)[0].rstrip("/")
                try:
                    if path == "/ai":
                        return self._json(view.status())
                    if path.startswith("/ai/") and path.endswith(".jpg"):
                        return self._jpeg(path[4:-4])
                    if path.startswith("/ai/") and path.endswith(".mjpg"):
                        return self._mjpeg(path[4:-5])
                    return self._json({"error": "not found",
                                       "endpoints": ["/ai", "/ai/<key>.jpg", "/ai/<key>.mjpg"]},
                                      status=404)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    return  # client went away - normal for MJPEG viewers

            def _json(self, payload, status=200):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self._cors()
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _jpeg(self, key):
                entry = view.latest(key)
                if entry is None:
                    return self._json({"error": f"no frame yet for {key!r}"}, status=404)
                data = entry[0]
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _mjpeg(self, key):
                self.send_response(200)
                self._cors()
                self.send_header("Content-Type",
                                 f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY}")
                self.send_header("Connection", "close")
                self.end_headers()
                placeholder = None
                while not view._stopping.is_set():
                    entry = view.latest(key)
                    if entry is None:
                        if placeholder is None:
                            placeholder = _placeholder_jpeg(key)
                        data = placeholder
                    else:
                        data = entry[0]
                    self.wfile.write(
                        f"--{MJPEG_BOUNDARY}\r\nContent-Type: image/jpeg\r\n"
                        f"Content-Length: {len(data)}\r\n\r\n".encode("ascii")
                    )
                    self.wfile.write(data)
                    self.wfile.write(b"\r\n")
                    self.wfile.flush()
                    time.sleep(STREAM_PART_SLEEP_S)

        self._server = _Server((host, int(port)), _Handler)
        self.port = self._server.server_address[1]
        self._thread: Optional[threading.Thread] = None

    # ------------------------------------------------------------ lifecycle

    def start(self) -> "AiViewServer":
        if self._thread is None:
            self._thread = threading.Thread(
                target=self._server.serve_forever, name="ai-view", daemon=True
            )
            self._thread.start()
        return self

    def stop(self) -> None:
        self._stopping.set()
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception:
            pass

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def url_pattern(self) -> str:
        return f"{self.base_url}/ai/<cam_key>.mjpg  (snapshot: /ai/<cam_key>.jpg, index: /ai)"

    # ------------------------------------------------------------- publish

    def publish(self, cam_key: str, frame_bgr, boxes: List[dict],
                camera_name: str = "", captured_at=None) -> None:
        """Annotate and store the latest frame for ``cam_key``."""
        img = annotate(frame_bgr, boxes, camera_name or cam_key, captured_at)
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
        if not ok:
            return
        entry = (buf.tobytes(), time.monotonic(), _utc_label(captured_at), camera_name or cam_key)
        with self._lock:
            self._frames[cam_key] = entry

    def on_frame(self, camera, frame, boxes, pts_ms, captured_at) -> None:
        """Adapter matching capture.CaptureLoop's ``on_frame`` signature."""
        self.publish(cam_key_for(camera), frame, boxes,
                     camera_name=camera.get("name") or "", captured_at=captured_at)

    # --------------------------------------------------------------- reads

    def latest(self, cam_key: str):
        with self._lock:
            return self._frames.get(cam_key)

    def latest_jpeg(self, cam_key: str) -> Optional[bytes]:
        entry = self.latest(cam_key)
        return entry[0] if entry else None

    def status(self) -> List[dict]:
        now = time.monotonic()
        with self._lock:
            items = list(self._frames.items())
        return [
            {
                "key": key,
                "camera": name,
                "last_frame_age_s": round(now - ts, 2),
                "captured_at": captured,
                "jpg": f"/ai/{key}.jpg",
                "mjpg": f"/ai/{key}.mjpg",
            }
            for key, (_, ts, captured, name) in sorted(items)
        ]


if __name__ == "__main__":  # manual check: serves a synthetic frame on :8892
    import argparse

    ap = argparse.ArgumentParser(description="AI view server self-test")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ns = ap.parse_args()
    srv = AiViewServer(ns.port).start()
    demo = np.full((720, 1280, 3), (60, 64, 70), dtype=np.uint8)
    srv.publish("demo", demo, [
        {"x1": 300, "y1": 200, "x2": 900, "y2": 600, "kind": "vehicle", "label": "vehicle 0.91"},
        {"x1": 520, "y1": 500, "x2": 700, "y2": 545, "kind": "plate", "label": "GJ01AB1234 0.97"},
    ], camera_name="demo camera", captured_at=datetime.now(timezone.utc))
    print(f"serving {srv.url_pattern()} - Ctrl-C to stop")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        srv.stop()
