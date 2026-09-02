"""MOCK detector - deterministic, dependency-light, for pipeline testing.

This is explicitly NOT a real detector: it never reads plates from pixels.
It applies a cheap frame-difference motion gate and, every ``emit_every``-th
motion frame, emits the next plate from a fixed, configurable pool (cycling
in order - fully deterministic, no randomness). Its purpose is exercising the
capture -> detect -> POST /api/detections -> alert pipeline without ML deps.
"""

from typing import Any, List, Optional, Sequence

import numpy as np

from .base import DetectionResult, Detector

# Default pool includes the demo watchlist plate (GJ01AB1234, seeded by
# backend/app/seed.py) so a live mock run produces real alerts end to end.
DEFAULT_PLATE_POOL = (
    "GJ01AB1234",
    "GJ05CD5678",
    "GJ18EF9012",
    "GJ03KL7766",
    "MH12PQ4455",
)


class MockDetector(Detector):
    name = "mock"

    def __init__(
        self,
        plate_pool: Optional[Sequence[str]] = None,
        motion_threshold: float = 4.0,
        emit_every: int = 12,
        plate_confidence: float = 0.88,
        downsample: int = 16,
    ):
        self.plate_pool = tuple(plate_pool) if plate_pool else DEFAULT_PLATE_POOL
        self.motion_threshold = float(motion_threshold)
        self.emit_every = max(1, int(emit_every))
        self.plate_confidence = float(plate_confidence)
        self.downsample = max(1, int(downsample))

        self._prev = None          # previous downsampled grayscale frame
        self._motion_frames = 0    # motion-gated frames since last reset
        self._emitted = 0          # total plates emitted (survives reset so
                                   # the pool keeps cycling deterministically)

    def process(self, frame: Any, pts_ms: float, captured_at: Any) -> List[DetectionResult]:
        small = np.asarray(frame, dtype=np.float32)
        if small.ndim == 3:
            small = small.mean(axis=2)
        small = small[:: self.downsample, :: self.downsample]

        prev = self._prev
        self._prev = small
        if prev is None or prev.shape != small.shape:
            # No baseline yet (fresh connect / reset / resolution change -
            # mixed resolutions are expected, gateway rule 7).
            return []

        if float(np.abs(small - prev).mean()) < self.motion_threshold:
            return []

        self._motion_frames += 1
        if self._motion_frames % self.emit_every != 0:
            return []

        plate = self.plate_pool[self._emitted % len(self.plate_pool)]
        self._emitted += 1
        return [
            DetectionResult(
                object_type="vehicle",
                plate=plate,
                plate_confidence=self.plate_confidence,
                bbox=None,
                snapshot_b64=None,
            )
        ]

    def reset(self) -> None:
        # Scene discontinuity (gateway rule 8): drop the frame-difference
        # baseline so the hard cut is not misread as motion.
        self._prev = None
        self._motion_frames = 0
