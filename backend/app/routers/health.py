"""Camera health & bandwidth board (docs/CONTRACT_ADDENDUM.md).

Metrics arrive via the extended heartbeat POST body and are stored on the
Camera row; this endpoint aggregates them for the health dashboard. The live
per-feed Kbps counters here are the demo-visible proof of the edge-first
bandwidth story (metadata upstream, video stays at the edge).
"""
from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Camera, Detection, utcnow
from ..schemas import iso_z

router = APIRouter(prefix="/health", tags=["health"])

# Upstream metadata rate: MEASURED from the detection rows actually stored in
# the rolling window (not asserted). Bytes per detection POST = a fixed JSON
# envelope (ids, plate, confidence, timestamps, detector) + the actual stored
# snapshot/bbox payload lengths.
METADATA_WINDOW_S = 600
DETECTION_ENVELOPE_BYTES = 300


@router.get("/summary")
def health_summary(db: Session = Depends(get_db)):
    cameras = db.query(Camera).order_by(Camera.id.asc()).all()

    per_camera = [
        {
            "camera_id": camera.id,
            "name": camera.name,
            "department": camera.department,
            "status": camera.status,
            "last_seen_at": iso_z(camera.last_seen_at),
            "fps_measured": camera.fps_measured,
            "last_frame_age_s": camera.last_frame_age_s,
            "reconnects": camera.reconnects,
            "bandwidth_kbps": camera.bandwidth_kbps,
        }
        for camera in cameras
    ]

    live = [c for c in cameras if c.status == "live"]
    fps_values = [c.fps_measured for c in live if c.fps_measured is not None]
    bandwidth_values = [c.bandwidth_kbps for c in live if c.bandwidth_kbps is not None]
    one_hour_ago = utcnow() - timedelta(hours=1)
    reconnects_1h = sum(
        c.reconnects or 0
        for c in cameras
        if c.last_seen_at is not None and c.last_seen_at >= one_hour_ago
    )

    # W3: the other half of the edge-first bandwidth ratio, measured live —
    # what actually travels upstream is detection METADATA, not video.
    window_start = utcnow() - timedelta(seconds=METADATA_WINDOW_S)
    det_count, snap_chars, bbox_chars = (
        db.query(
            func.count(Detection.id),
            func.coalesce(func.sum(func.length(func.coalesce(Detection.snapshot_b64, ""))), 0),
            func.coalesce(func.sum(func.length(func.coalesce(Detection.bbox, ""))), 0),
        )
        .filter(Detection.created_at >= window_start)
        .one()
    )
    metadata_bytes = det_count * DETECTION_ENVELOPE_BYTES + int(snap_chars) + int(bbox_chars)
    metadata_kbps = round(metadata_bytes * 8.0 / 1000.0 / METADATA_WINDOW_S, 2)

    return {
        "per_camera": per_camera,
        "totals": {
            "streams_up": len(live),
            "avg_fps": round(sum(fps_values) / len(fps_values), 2) if fps_values else None,
            "total_bandwidth_kbps": round(sum(bandwidth_values), 1),
            "reconnects_1h": reconnects_1h,
            "metadata_kbps_upstream": metadata_kbps,
            "metadata_window_s": METADATA_WINDOW_S,
            "detections_window": int(det_count),
        },
    }
