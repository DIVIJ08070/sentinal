"""Detector implementations for the Sentinel ingest pipeline.

``mock`` is the dependency-light default; ``anpr`` is the real path and is
imported lazily so the heavy ML extras (requirements-ml.txt) are only needed
when actually requested.
"""

from .base import DetectionResult, Detector


def make_detector(kind: str, **kwargs) -> Detector:
    """Instantiate a detector by name ('mock' or 'anpr').

    'anpr' raises ImportError with install instructions when the ML extras
    are missing - callers should surface that message to the user.
    """
    if kind == "mock":
        from .mock import MockDetector

        return MockDetector(**kwargs)
    if kind == "anpr":
        from .anpr import AnprDetector

        return AnprDetector(**kwargs)
    raise ValueError(f"unknown detector {kind!r} (expected 'mock' or 'anpr')")


__all__ = ["DetectionResult", "Detector", "make_detector"]
