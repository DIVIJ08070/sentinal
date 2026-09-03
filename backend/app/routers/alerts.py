from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session, joinedload

from ..audit import record as audit_record, resolve_operator
from ..auth import require_role
from ..db import get_db
from ..models import Alert, Detection, utcnow
from ..schemas import alert_to_dict
from ..sources import visible_detection

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("")
def list_alerts(
    status: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Alert)
        .join(Detection, Alert.detection_id == Detection.id)
        .filter(visible_detection())  # hide simulator/mock-sourced alerts
        .options(
            joinedload(Alert.camera),
            joinedload(Alert.watchlist_entry),
            joinedload(Alert.detection),
        )
    )
    if status:
        query = query.filter(Alert.status == status)
    alerts = query.order_by(Alert.created_at.desc(), Alert.id.desc()).limit(limit).all()
    return [alert_to_dict(alert) for alert in alerts]


@router.post("/{alert_id}/ack")
def acknowledge_alert(alert_id: int, request: Request, db: Session = Depends(get_db),
                      _principal=Depends(require_role("operator"))):
    alert = db.get(Alert, alert_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="alert not found")
    if alert.status != "acknowledged":
        alert.status = "acknowledged"
        alert.acknowledged_at = utcnow()
        audit_record(
            db, "alert_ack", resolve_operator(request), plate=alert.plate,
            entity_id=alert.id, commit=False, match_type=alert.match_type,
        )
        db.commit()
        db.refresh(alert)
    return alert_to_dict(alert)
