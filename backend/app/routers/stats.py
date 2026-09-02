from datetime import timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Alert, Camera, Detection, WatchlistEntry, utcnow

router = APIRouter(tags=["stats"])


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
        "detections_24h": db.query(func.count(Detection.id))
        .filter(Detection.captured_at >= utcnow() - timedelta(hours=24))
        .scalar() or 0,
        "alerts_new": db.query(func.count(Alert.id))
        .filter(Alert.status == "new")
        .scalar() or 0,
        "alerts_total": db.query(func.count(Alert.id)).scalar() or 0,
    }
