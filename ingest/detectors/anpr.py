"""Real ANPR detector: YOLOv8n vehicles + plate localization + fast-plate-ocr.

Heavy ML dependencies are OPTIONAL and live in ingest/requirements-ml.txt;
importing this module without them raises a clear ImportError pointing there
(the default worker path, --detector mock, never imports this module).

Pipeline per frame:
  1. YOLOv8n detects vehicles (COCO classes car / motorbike / bus / truck).
  2. Each vehicle bbox is cropped from the frame.
  3. A dedicated plate LOCALIZER (open_image_models.LicensePlateDetector,
     the fast-plate-ocr author's companion ONNX detector, model
     yolo-v9-t-384-license-plate-end2end, CPU-friendly) finds the plate
     inside the vehicle crop — fast-plate-ocr is trained on TIGHT plate
     crops, and feeding it whole vehicles capped confidence at ~0.46 on the
     real sandbox grid with a near-zero real-scene read rate. If no vehicle
     crop yields a plate, the localizer runs once on the FULL frame (plates
     on vehicles YOLO missed or clipped).
  4. The plate bbox is padded ~2 px, and crops narrower than 96 px are
     upscaled with INTER_CUBIC before OCR. This exact combination was
     validated live on the government sandbox grid (read CMMC801 off cam23).
  5. fast-plate-ocr reads the registration number.
  6. On a successful read, the result carries the bbox (JSON) and a small
     base64 JPEG snapshot of the VEHICLE crop with the plate visible (max
     ~320 px wide). Snapshots are attached ONLY when a plate was read.

If open-image-models is not installed the detector degrades to the old
whole-vehicle-crop OCR path instead of failing.

The first YOLO(...) call downloads yolov8n.pt (~6 MB) if not cached; the OCR
and plate-localizer models are fetched on first use, then cached.
"""

import base64
import json
import os
import re
from typing import Any, List, Optional, Tuple

# Gateway rule 1: the RTSP transport option must exist before cv2's FIRST
# import anywhere in the process. ultralytics imports cv2 transitively at
# package-import time, so this must run before the `from ultralytics import
# YOLO` below — not merely before our own `import cv2`. capture.py force-sets
# the same value when it is imported first; setdefault keeps that authoritative.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

_INSTALL_HINT = (
    "The 'anpr' detector needs the optional ML extras (ultralytics + "
    "fast-plate-ocr + open-image-models), which are kept out of the default "
    "requirements on purpose. From the ingest/ directory run:\n\n"
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

try:
    # Plate localizer (same author as fast-plate-ocr, ONNX, CPU-ok). A missing
    # package or failed model download must never kill the ANPR path — the
    # detector degrades to whole-vehicle-crop OCR.
    from open_image_models import LicensePlateDetector as _PlateLocalizer
except ImportError:  # pragma: no cover - optional extra
    _PlateLocalizer = None

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
        # 0.35, down from 0.55 — recalibrated on the real sandbox grid
        # (docs/EVIDENCE.md): recall-first by design. The confidence is always
        # DISPLAYED on every alert/route row, and the false-positive side is
        # absorbed downstream by the confusion-tolerant matcher + the route
        # physics filter (both regression-tested), so a sub-certain read is
        # evidence with a stated confidence, not silence.
        min_plate_confidence: float = 0.35,
        dedup_window_ms: float = 5000.0,
        plateless_interval_ms: float = 3000.0,
        snapshot_max_width: int = 320,
        min_crop_px: int = 32,
        plate_model: str = "yolo-v9-t-384-license-plate-end2end",
        plate_conf: float = 0.25,
        # Plate crops narrower than this are INTER_CUBIC-upscaled before OCR;
        # 96 px + ~2 px bbox pad is the combination validated live on the
        # sandbox grid (read CMMC801 off cam23).
        ocr_min_plate_width: int = 96,
        plate_pad_px: int = 2,
        # Structural gate on OCR output. The live sandbox grid taught us the
        # localizer will happily "find" a camera's burned-in caption
        # ("Camera 01") and OCR it into plate-shaped junk (CMEP801, C0MC01,
        # 4MB8801...). Indian registrations start with a two-letter state
        # code followed by a digit; requiring that prefix (6-10 chars, >=3
        # digits) rejected every observed caption read while keeping every
        # genuine one (GJ1104284, GJ19PE8859, GJ01AB1234). Pass "" to disable
        # (e.g. non-Indian plates).
        plate_pattern: str = r"^[A-Z]{2}\d[A-Z0-9]{3,7}$",
        # Running the localizer over the WHOLE frame when no vehicle crop
        # produced a plate is precisely the path that read the caption:
        # opt-in only.
        full_frame_fallback: bool = False,
    ):
        self.vehicle_conf = float(vehicle_conf)
        self.min_plate_len = int(min_plate_len)
        self.min_plate_confidence = float(min_plate_confidence)
        self.dedup_window_ms = float(dedup_window_ms)
        self.plateless_interval_ms = float(plateless_interval_ms)
        self.snapshot_max_width = int(snapshot_max_width)
        self.min_crop_px = int(min_crop_px)
        self.plate_conf = float(plate_conf)
        self.ocr_min_plate_width = int(ocr_min_plate_width)
        self.plate_pad_px = int(plate_pad_px)
        self._plate_re = re.compile(plate_pattern) if plate_pattern else None
        self.full_frame_fallback = bool(full_frame_fallback)

        # One model instance per detector; the worker creates one detector per
        # camera thread, keeping inference thread-confined. Batch shape is
        # whatever each camera delivers - no fixed-shape batch across cameras
        # (gateway rule 7: mixed codecs/resolutions).
        self._yolo = YOLO(yolo_model)
        self._ocr = _PlateRecognizer(ocr_model or _DEFAULT_OCR_MODEL)

        # Plate localizer: optional, never fatal (degrades to vehicle-crop OCR).
        # Pinned to the CPU execution provider: onnxruntime's CoreML EP fails
        # on zero-detection frames ("dynamic shape {-1} ... zero elements")
        # and misbehaves with several concurrent camera threads in one
        # process; CPU EP is deterministic and fast enough (~t-384 model).
        self._plate_detector = None
        if _PlateLocalizer is not None and plate_model:
            try:
                self._plate_detector = _PlateLocalizer(
                    plate_model,
                    conf_thresh=self.plate_conf,
                    providers=["CPUExecutionProvider"],
                )
            except TypeError:
                # Older open-image-models without a providers kwarg.
                self._plate_detector = _PlateLocalizer(
                    plate_model, conf_thresh=self.plate_conf
                )
            except Exception as exc:  # model download/init failure
                print(f"anpr: plate localizer unavailable ({exc}); "
                      f"falling back to whole-vehicle-crop OCR")

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
        localized_any = False

        for box in prediction.boxes:
            x1, y1, x2, y2 = (int(round(v)) for v in box.xyxy[0].tolist())
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(width, x2), min(height, y2)
            if (x2 - x1) < self.min_crop_px or (y2 - y1) < self.min_crop_px:
                continue
            conf = float(box.conf[0])
            if best_vehicle is None or conf > best_vehicle[0]:
                best_vehicle = (conf, (x1, y1, x2, y2))

            # Localize the plate INSIDE the vehicle crop, then OCR the tight
            # plate region — fast-plate-ocr expects a plate crop, not a whole
            # vehicle.
            crop = frame[y1:y2, x1:x2]
            located = self._localize_plate(crop)
            if located is not None:
                localized_any = True
                ocr_src = located[0]
            elif self._plate_detector is None:
                # Degrade path (open-image-models not installed): OCR the
                # whole vehicle crop as before.
                ocr_src = crop
            else:
                # Localizer active but no plate in this vehicle crop; the
                # full-frame fallback below may still catch it.
                continue
            plate, plate_conf = self._read_plate(self._ocr_input(ocr_src))
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
                    # Snapshot only when a plate was read: the VEHICLE crop
                    # with the plate visible.
                    snapshot_b64=self._encode_snapshot(crop),
                )
            )

        # Full-frame fallback: no vehicle crop yielded a plate bbox — run the
        # localizer once over the whole frame (vehicles YOLO missed/clipped).
        if (
            self.full_frame_fallback
            and not results
            and not localized_any
            and self._plate_detector is not None
        ):
            located = self._localize_plate(frame)
            if located is not None:
                region, (px1, py1, px2, py2) = located
                plate, plate_conf = self._read_plate(self._ocr_input(region))
                if plate is not None and self._should_emit(plate, pts_ms):
                    if best_vehicle is not None:
                        _, (vx1, vy1, vx2, vy2) = best_vehicle
                        snap = frame[vy1:vy2, vx1:vx2]
                        bbox = [vx1, vy1, vx2, vy2]
                    else:
                        # No vehicle bbox: snapshot a context region around
                        # the plate so the vehicle is still visible.
                        cw, ch = (px2 - px1), (py2 - py1)
                        sx1 = max(0, px1 - 2 * cw)
                        sy1 = max(0, py1 - 4 * ch)
                        sx2 = min(width, px2 + 2 * cw)
                        sy2 = min(height, py2 + 2 * ch)
                        snap = frame[sy1:sy2, sx1:sx2]
                        bbox = [px1, py1, px2, py2]
                    results.append(
                        DetectionResult(
                            object_type="vehicle",
                            plate=plate,
                            plate_confidence=plate_conf,
                            bbox=json.dumps(bbox),
                            snapshot_b64=self._encode_snapshot(snap),
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

    def _localize_plate(self, image):
        """Best plate inside `image` via open-image-models, or None.

        Returns (padded plate crop, (x1, y1, x2, y2) in image coords).
        None when the localizer is absent, errored, or found nothing above
        plate_conf. The bbox is padded by plate_pad_px so tight boxes don't
        clip character strokes (validated live: CMMC801 on cam23).
        """
        if self._plate_detector is None:
            return None
        try:
            detections = self._plate_detector.predict(image)
        except Exception:
            return None
        best = None
        for det in detections or []:
            if best is None or det.confidence > best.confidence:
                best = det
        if best is None:
            return None
        bb = best.bounding_box
        h, w = image.shape[:2]
        pad = self.plate_pad_px
        x1, y1 = max(0, int(bb.x1) - pad), max(0, int(bb.y1) - pad)
        x2, y2 = min(w, int(bb.x2) + pad), min(h, int(bb.y2) + pad)
        if (x2 - x1) < 8 or (y2 - y1) < 4:
            return None
        return image[y1:y2, x1:x2], (x1, y1, x2, y2)

    def _ocr_input(self, region):
        """Upscale narrow plate crops before OCR.

        Crops narrower than ocr_min_plate_width px are INTER_CUBIC-upscaled
        to that width (plate pixel size was the measured bottleneck on the
        real grid; this exact preprocessing read CMMC801 off cam23 live).
        """
        h, w = region.shape[:2]
        if 0 < w < self.ocr_min_plate_width:
            scale = self.ocr_min_plate_width / float(w)
            region = cv2.resize(
                region,
                (self.ocr_min_plate_width, max(1, int(round(h * scale)))),
                interpolation=cv2.INTER_CUBIC,
            )
        return region

    def _read_plate(self, crop) -> Tuple[Optional[str], Optional[float]]:
        """Run OCR on a plate crop; returns (plate, confidence) or (None, None).

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
        # Structural gate (see plate_pattern): drops caption/watermark junk
        # that is plate-shaped to the OCR but impossible as a registration.
        if self._plate_re is not None and not self._plate_re.match(plate):
            return None, None
        if sum(ch.isdigit() for ch in plate) < 3:
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
            if h < 1 or w < 1:
                return None
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
