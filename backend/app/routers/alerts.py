from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload

from ..db import get_db
from ..models import Alert, utcnow
from ..schemas import alert_to_dict

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("")
def list_alerts(
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    query = db.query(Alert).options(
        joinedload(Alert.camera),
        joinedload(Alert.watchlist_entry),
        joinedload(Alert.detection),
    )
    if status:
        query = query.filter(Alert.status == status)
    alerts = query.order_by(Alert.created_at.desc(), Alert.id.desc()).limit(limit).all()
    return [alert_to_dict(alert) for alert in alerts]


@router.post("/{alert_id}/ack")
def acknowledge_alert(alert_id: int, db: Session = Depends(get_db)):
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    if alert.status != "acknowledged":
        alert.status = "acknowledged"
        alert.acknowledged_at = utcnow()
        db.commit()
        db.refresh(alert)
    return alert_to_dict(alert)
