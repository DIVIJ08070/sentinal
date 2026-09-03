"""Detector interface shared by the mock and real ANPR implementations.

Deliberately dependency-free: importing this module must never pull in cv2 or
any ML library.
"""

from dataclasses import dataclass
from typing import Any, List, Optional


@dataclass
class DetectionResult:
    """One detected object on one frame.

    ``bbox`` is a JSON-encoded string ``"[x1, y1, x2, y2]"`` in frame pixels
    (the backend stores bbox as a JSON string). ``snapshot_b64`` is a small
    base64 JPEG (max ~320 px wide), present only when a plate was read.
    """

    object_type: str = "vehicle"
    plate: Optional[str] = None
    plate_confidence: Optional[float] = None
    bbox: Optional[str] = None
    snapshot_b64: Optional[str] = None
    #: Coarse vehicle class from the YOLO COCO id when known — one of
    #: 'car' | 'motorcycle' | 'bus' | 'truck', else None (the mock sets 'car').
    vehicle_type: Optional[str] = None


class Detector:
    """Base class for frame detectors driven by capture.CaptureLoop."""

    #: value posted in the Detection.detector field
    name: str = "base"

    #: Per-frame overlay boxes for the live "AI view" (ingest/ai_view.py):
    #: after each ``process()`` call this holds a list of dicts
    #: ``{x1, y1, x2, y2, kind: 'vehicle'|'plate', label: str|None}`` in FRAME
    #: pixel coordinates. Purely informational - it never affects what is
    #: posted to the backend. The base default is an empty list so callers
    #: can rely on the attribute for any detector.
    last_frame_boxes: list = []

    def process(self, frame: Any, pts_ms: float, captured_at: Any) -> List[DetectionResult]:
        """Analyse one BGR numpy frame.

        ``pts_ms`` is the stream PTS in milliseconds and ``captured_at`` the
        PTS-anchored UTC datetime for the frame (gateway rule 3). Elapsed time
        between calls must be measured with ``pts_ms`` deltas, never with
        frame counts or fps (gateway rules 2 & 4).
        """
        raise NotImplementedError

    def reset(self) -> None:
        """Drop all inter-frame state.

        Called by the capture loop on every (re)connect and on every PTS
        discontinuity (gateway rule 8: each feed is a loop that hard-cuts at
        the loop point - background models, trackers and de-dup galleries
        must recover from the cut).
        """
        # Base implementation is stateless; subclasses override.
        return None
