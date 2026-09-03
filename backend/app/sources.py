"""Detection-source visibility.

Detections carry a `detector` tag: `anpr` (live AI reads), `simulator`
(scripted demo journeys) and `mock` (pipeline tests). For a live demo the
simulator rows must not appear beside genuine camera evidence, but deleting
them is destructive and unnecessary: every read path filters them out instead.

    SENTINEL_HIDE_DETECTORS="simulator,mock"   (default)
    SENTINEL_HIDE_DETECTORS=""                 -> show everything (incl. the demo journey)

Non-destructive and reversible: the rows stay in the database.
"""
import os

from sqlalchemy import true

from .models import Detection

HIDDEN_DETECTORS = frozenset(
    d.strip() for d in os.environ.get("SENTINEL_HIDE_DETECTORS", "simulator,mock").split(",") if d.strip()
)


def visible_detection():
    """SQLAlchemy criterion selecting detections whose source is not hidden."""
    if not HIDDEN_DETECTORS:
        return true()
    return ~Detection.detector.in_(sorted(HIDDEN_DETECTORS))
