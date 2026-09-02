"""GET /api/audit — read the append-only audit trail (newest first)."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..audit import audit_to_dict
from ..db import get_db
from ..matching import normalize
from ..models import AuditLog

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
def list_audit(
    action: str | None = None,
    actor: str | None = None,
    plate: str | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    query = db.query(AuditLog)
    if action:
        query = query.filter(AuditLog.action == action)
    if actor:
        query = query.filter(AuditLog.actor == actor)
    if plate:
        query = query.filter(AuditLog.plate == normalize(plate))
    total = db.query(AuditLog).count()
    entries = query.order_by(AuditLog.id.desc()).limit(limit).all()
    return {"total": total, "entries": [audit_to_dict(e) for e in entries]}
