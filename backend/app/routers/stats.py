from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Alert, Camera, Detection, WatchlistEntry, utcnow
from ..sources import visible_detection

router = APIRouter(tags=["stats"])


def _iso(dt):
    """UTC ISO8601 with a trailing Z (stored datetimes are naive UTC)."""
    if dt is None:
        return None
    text = dt.isoformat()
    return text.replace("+00:00", "Z") if dt.tzinfo else text + "Z"


@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    status_counts = dict(
        db.query(Camera.status, func.count(Camera.id)).group_by(Camera.status).all()
    )
    by_department = {
        (department or "Unassigned"): count
        for department, count in db.query(Camera.department, func.count(Camera.id))
        .group_by(Camera.department)
        .all()
    }

    return {
        "cameras": {
            "total": sum(status_counts.values()),
            "live": status_counts.get("live", 0),
            "down": status_counts.get("down", 0),
            "unknown": status_counts.get("unknown", 0),
            "by_department": by_department,
        },
        "watchlist_active": db.query(func.count(WatchlistEntry.id))
        .filter(WatchlistEntry.active.is_(True))
        .scalar() or 0,
        # All detection/alert figures exclude hidden sources (simulator/mock).
        "detections_24h": db.query(func.count(Detection.id))
        .filter(visible_detection())
        .filter(Detection.captured_at >= utcnow() - timedelta(hours=24))
        .scalar() or 0,
        "alerts_new": db.query(func.count(Alert.id))
        .join(Detection, Alert.detection_id == Detection.id)
        .filter(visible_detection(), Alert.status == "new")
        .scalar() or 0,
        "alerts_total": db.query(func.count(Alert.id))
        .join(Detection, Alert.detection_id == Detection.id)
        .filter(visible_detection())
        .scalar() or 0,
        # Liveness heartbeat for the dashboard: when the pipeline last delivered
        # a detection / raised an alert (server receive time, so it reflects
        # "is data arriving now", independent of stream PTS).
        "last_detection_at": _iso(
            db.query(func.max(Detection.created_at)).filter(visible_detection()).scalar()
        ),
        "last_alert_at": _iso(
            db.query(func.max(Alert.created_at))
            .join(Detection, Alert.detection_id == Detection.id)
            .filter(visible_detection())
            .scalar()
        ),
    }
