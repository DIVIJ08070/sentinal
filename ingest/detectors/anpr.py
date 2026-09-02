"""Real ANPR detector: YOLOv8n vehicle detection + fast-plate-ocr reading.

Heavy ML dependencies are OPTIONAL and live in ingest/requirements-ml.txt;
importing this module without them raises a clear ImportError pointing there
(the default worker path, --detector mock, never imports this module).

Pipeline per frame:
  1. YOLOv8n detects vehicles (COCO classes car / motorbike / bus / truck).
  2. Each vehicle bbox is cropped from the frame BEFORE OCR.
  3. fast-plate-ocr reads a registration number from the crop.
  4. On a successful read, the result carries the bbox (JSON) and a small
     base64 JPEG snapshot of the vehicle crop (max ~320 px wide). Snapshots
     are attached ONLY when a plate was read.

The first YOLO(...) call downloads yolov8n.pt (~6 MB) if not cached; the OCR
model is fetched by fast-plate-ocr on first use.
"""

import base64
import json
import os
from typing import Any, List, Optional, Tuple

# Gateway rule 1: the RTSP transport option must exist before cv2's FIRST
# import anywhere in the process. ultralytics imports cv2 transitively at
# package-import time, so this must run before the `from ultralytics import
# YOLO` below — not merely before our own `import cv2`. capture.py force-sets
# the same value when it is imported first; setdefault keeps that authoritative.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

_INSTALL_HINT = (
    "The 'anpr' detector needs the optional ML extras (ultralytics + "
    "fast-plate-ocr), which are kept out of the default requirements on "
    "purpose. From the ingest/ directory run:\n\n"
    "    pip install -r requirements-ml.txt\n\n"
    "then retry with --detector anpr (or use --detector mock, which has no "
    "ML dependencies)."
)

try:
    from ultralytics import YOLO
except ImportError as exc:
    raise ImportError(f"ultralytics is not installed. {_INSTALL_HINT}") from exc

try:
    try:
        # fast-plate-ocr >= 1.0
        from fast_plate_ocr import LicensePlateRecognizer as _PlateRecognizer
        _DEFAULT_OCR_MODEL = "cct-xs-v1-global-model"
    except ImportError:
        # fast-plate-ocr 0.x
        from fast_plate_ocr import ONNXPlateRecognizer as _PlateRecognizer
        _DEFAULT_OCR_MODEL = "global-plates-mobile-vit-v2-model"
except ImportError as exc:
    raise ImportError(f"fast-plate-ocr is not installed. {_INSTALL_HINT}") from exc

# cv2 here is used for image ops only; the FFmpeg transport option was set at
# the top of this module, before ultralytics could pull cv2 in transitively.
import cv2
import numpy as np

from .base import DetectionResult, Detector

# COCO class ids: 2=car, 3=motorbike, 5=bus, 7=truck
VEHICLE_CLASS_IDS = (2, 3, 5, 7)


class AnprDetector(Detector):
    name = "anpr"

    def __init__(
        self,
        yolo_model: str = "yolov8n.pt",
        ocr_model: Optional[str] = None,
        vehicle_conf: float = 0.4,
        min_plate_len: int = 6,
        min_plate_confidence: float = 0.55,
        dedup_window_ms: float = 5000.0,
        plateless_interval_ms: float = 3000.0,
        snapshot_max_width: int = 320,
        min_crop_px: int = 32,
    ):
        self.vehicle_conf = float(vehicle_conf)
        self.min_plate_len = int(min_plate_len)
        self.min_plate_confidence = float(min_plate_confidence)
        self.dedup_window_ms = float(dedup_window_ms)
        self.plateless_interval_ms = float(plateless_interval_ms)
        self.snapshot_max_width = int(snapshot_max_width)
        self.min_crop_px = int(min_crop_px)

        # One model instance per detector; the worker creates one detector per
        # camera thread, keeping inference thread-confined. Batch shape is
        # whatever each camera delivers - no fixed-shape batch across cameras
        # (gateway rule 7: mixed codecs/resolutions).
        self._yolo = YOLO(yolo_model)
        self._ocr = _PlateRecognizer(ocr_model or _DEFAULT_OCR_MODEL)

        self._recent_plates = {}        # plate -> last emitted pts_ms
        self._last_plateless_pts = None

    # -------------------------------------------------------------- process

    def process(self, frame: Any, pts_ms: float, captured_at: Any) -> List[DetectionResult]:
        prediction = self._yolo.predict(
            frame,
            conf=self.vehicle_conf,
            classes=list(VEHICLE_CLASS_IDS),
            verbose=False,
        )[0]

        height, width = frame.shape[:2]
        results: List[DetectionResult] = []
        best_vehicle: Optional[Tuple[float, Tuple[int, int, int, int]]] = None

        for box in prediction.boxes:
            x1, y1, x2, y2 = (int(round(v)) for v in box.xyxy[0].tolist())
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(width, x2), min(height, y2)
            if (x2 - x1) < self.min_crop_px or (y2 - y1) < self.min_crop_px:
                continue
            conf = float(box.conf[0])
            if best_vehicle is None or conf > best_vehicle[0]:
                best_vehicle = (conf, (x1, y1, x2, y2))

            # Crop the vehicle bbox BEFORE OCR - the OCR model expects a
            # tight vehicle/plate region, not the full scene.
            crop = frame[y1:y2, x1:x2]
            plate, plate_conf = self._read_plate(crop)
            if plate is None:
                continue
            if not self._should_emit(plate, pts_ms):
                continue
            results.append(
                DetectionResult(
                    object_type="vehicle",
                    plate=plate,
                    plate_confidence=plate_conf,
                    bbox=json.dumps([x1, y1, x2, y2]),
                    # Snapshot only when a plate was read.
                    snapshot_b64=self._encode_snapshot(crop),
                )
            )

        if not results and best_vehicle is not None:
            # Plate-less vehicle sightings are throttled by elapsed PTS so a
            # busy junction does not flood the backend; no snapshot attached.
            if (
                self._last_plateless_pts is None
                or (pts_ms - self._last_plateless_pts) >= self.plateless_interval_ms
            ):
                self._last_plateless_pts = pts_ms
                _, (x1, y1, x2, y2) = best_vehicle
                results.append(
                    DetectionResult(
                        object_type="vehicle",
                        plate=None,
                        plate_confidence=None,
                        bbox=json.dumps([x1, y1, x2, y2]),
                        snapshot_b64=None,
                    )
                )
        return results

    # ---------------------------------------------------------------- reset

    def reset(self) -> None:
        # Scene discontinuity (gateway rule 8): the de-dup gallery and the
        # plate-less throttle reference PTS values from before the cut.
        self._recent_plates.clear()
        self._last_plateless_pts = None

    # -------------------------------------------------------------- helpers

    def _read_plate(self, crop) -> Tuple[Optional[str], Optional[float]]:
        """Run OCR on a vehicle crop; returns (plate, confidence) or (None, None).

        Handles every fast-plate-ocr output shape:
          * >= 1.1: list of PlatePrediction(plate=..., char_probs=...)
          * 1.0:    (plates, confidences) tuple with return_confidence=True
          * 0.x:    list/str of plates (no confidences)
        (Verified via `make anpr-smoke` — 1.1.0 returns PlatePrediction, and
        naively unpacking it silently killed every read.)
        """
        try:
            try:
                output = self._ocr.run(crop, return_confidence=True)
            except TypeError:
                # Older fast-plate-ocr without return_confidence support.
                output = self._ocr.run(crop)
        except Exception:
            return None, None

        raw, confidence = None, None
        if isinstance(output, tuple) and len(output) == 2:
            plates, confidences = output
            if plates is not None and len(plates) > 0:
                raw = plates[0] if isinstance(plates, (list, tuple)) else plates
                if confidences is not None:
                    try:
                        per_char = np.asarray(confidences, dtype=np.float32)
                        confidence = float(per_char.reshape(per_char.shape[0], -1)[0].mean())
                    except Exception:
                        confidence = None
        elif isinstance(output, (list, tuple)) and len(output) > 0:
            first = output[0]
            if hasattr(first, "plate"):  # fast-plate-ocr >= 1.1 PlatePrediction
                raw = first.plate
                probs = getattr(first, "char_probs", None)
                if probs is not None:
                    try:
                        confidence = float(np.asarray(probs, dtype=np.float32).mean())
                    except Exception:
                        confidence = None
            else:
                raw = first
        elif isinstance(output, str):
            raw = output

        if raw is None:
            return None, None
        # Strip the recognizer's '_' padding and any non-alphanumerics; the
        # backend applies the canonical normalization (app/matching.py).
        plate = "".join(ch for ch in str(raw).upper() if ch.isalnum())
        if len(plate) < self.min_plate_len:
            return None, None
        if confidence is not None and confidence < self.min_plate_confidence:
            return None, None
        return plate, confidence

    def _should_emit(self, plate: str, pts_ms: float) -> bool:
        """PTS-windowed de-dup so one pass of a vehicle yields one detection."""
        last = self._recent_plates.get(plate)
        if last is not None and 0 <= (pts_ms - last) < self.dedup_window_ms:
            return False
        if len(self._recent_plates) > 256:
            self._recent_plates.clear()
        self._recent_plates[plate] = pts_ms
        return True

    def _encode_snapshot(self, crop) -> Optional[str]:
        """JPEG-encode the vehicle crop at <= snapshot_max_width, base64."""
        try:
            image = crop
            h, w = image.shape[:2]
            if w > self.snapshot_max_width:
                scale = self.snapshot_max_width / float(w)
                image = cv2.resize(
                    image,
                    (self.snapshot_max_width, max(1, int(round(h * scale)))),
                    interpolation=cv2.INTER_AREA,
                )
            ok, buf = cv2.imencode(".jpg", image, [int(cv2.IMWRITE_JPEG_QUALITY), 72])
            if not ok:
                return None
            return base64.b64encode(buf.tobytes()).decode("ascii")
        except Exception:
            return None
