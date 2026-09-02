"""GET /api/audit — read the append-only, hash-chained audit trail.

Newest first. Every response carries the chain head; pass ?verify=1 to
recompute the entire chain from genesis (tamper check by recomputation,
mirroring the dossier's sighting chain).
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..audit import GENESIS_HASH, HASH_ALGORITHM, audit_to_dict, chain_head, verify_chain
from ..db import get_db
from ..matching import normalize
from ..models import AuditLog

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("")
def list_audit(
    action: str | None = None,
    actor: str | None = None,
    plate: str | None = None,
    verify: bool = False,
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
    chain = {
        "algorithm": HASH_ALGORITHM,
        "genesis_hash": GENESIS_HASH,
        "head": chain_head(db),
        "canonicalization": (
            "row_hash = sha256(canonical JSON of {action, actor, plate, "
            "entity_id, params, created_at, prev_hash}); prev of row 1 is "
            "the genesis hash; canonical JSON = sorted keys, separators "
            '(",", ":"), UTF-8'
        ),
    }
    if verify:
        chain.update(verify_chain(db))
    return {"total": total, "chain": chain, "entries": [audit_to_dict(e) for e in entries]}
