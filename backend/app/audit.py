"""Append-only audit trail — the log the Evidence Dossier cites.

Every plate search (route query), watchlist change, alert acknowledgment and
dossier export inserts one row into audit_log. Rows are only ever INSERTed —
no update/delete path exists anywhere in the app — AND the log is hash-chained
exactly like the dossier's sighting chain: each row's row_hash covers its own
canonical content plus the previous row's hash, anchored in a fixed genesis
hash. "Append-only" is therefore tamper-EVIDENT, not merely asserted: any
edit or deletion of a historical row breaks every subsequent hash on
recomputation (GET /api/audit?verify=1).

Operator identity, in priority order:
1. the authenticated token principal (``app/auth.py``, when SENTINEL_TOKENS
   is set) — authoritative, cannot be spoofed by a client header;
2. otherwise (open demo mode only) the ``X-Operator`` request header;
3. the ``SENTINEL_OPERATOR`` env var, else ``"demo-operator"``.
When auth is enabled the X-Operator header is IGNORED — a client that skips
authentication is recorded as ``unauthenticated``, never as whoever it claims.
"""
import hashlib
import json
import os

from fastapi import Request
from sqlalchemy.orm import Session

from .auth import auth_enabled, principal_for
from .models import AuditLog, utcnow

DEFAULT_OPERATOR = os.getenv("SENTINEL_OPERATOR", "demo-operator")
OPERATOR_HEADER = "X-Operator"

HASH_ALGORITHM = "sha256"
# Fixed, public genesis anchor (same canonicalization as the dossier chain).
GENESIS_HASH = hashlib.sha256(
    '{"log":"sentinel-audit-log","version":1}'.encode("utf-8")
).hexdigest()


def _canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def row_payload(entry: AuditLog) -> dict:
    """The canonical hashed content of one audit row (excludes id/row_hash)."""
    from .schemas import iso_z  # local import: schemas imports nothing from here

    return {
        "action": entry.action,
        "actor": entry.actor,
        "plate": entry.plate,
        "entity_id": entry.entity_id,
        "params": entry.params,
        "created_at": iso_z(entry.created_at),
        "prev_hash": entry.prev_hash,
    }


def compute_row_hash(entry: AuditLog) -> str:
    return _sha256_hex(_canonical_json(row_payload(entry)))


def chain_head(db: Session) -> str:
    """row_hash of the newest audit row (the chain head), or the genesis hash."""
    last = db.query(AuditLog).order_by(AuditLog.id.desc()).first()
    return (last.row_hash if last is not None and last.row_hash else None) or GENESIS_HASH


def verify_chain(db: Session) -> dict:
    """Recompute the whole chain from genesis. Returns a verdict dict.

    Rows written before the chain existed (no row_hash) are reported, not
    failed — the chain is verified from the first hashed row onward.
    """
    rows = db.query(AuditLog).order_by(AuditLog.id.asc()).all()
    prev = GENESIS_HASH
    verified = 0
    unhashed = 0
    for row in rows:
        if row.row_hash is None:
            unhashed += 1
            continue
        if row.prev_hash != prev or compute_row_hash(row) != row.row_hash:
            return {
                "verified": False,
                "broken_at_entry": row.id,
                "entries_verified": verified,
                "entries_unhashed": unhashed,
                "head": prev,
            }
        prev = row.row_hash
        verified += 1
    return {
        "verified": True,
        "broken_at_entry": None,
        "entries_verified": verified,
        "entries_unhashed": unhashed,
        "head": prev,
    }


def resolve_operator(request: Request | None) -> str:
    """Operator identity for audit rows and the dossier."""
    principal = principal_for(request)
    if principal is not None:
        return f"{principal['name']} ({principal['role']})"[:128]
    if auth_enabled():
        # Auth is on but this request carried no valid token: never fall back
        # to the spoofable header for the identity on a custody document.
        return "unauthenticated"
    if request is not None:
        header = request.headers.get(OPERATOR_HEADER)
        if header and header.strip():
            return header.strip()[:128]
    return DEFAULT_OPERATOR


def record(
    db: Session,
    action: str,
    actor: str,
    plate: str | None = None,
    entity_id: int | None = None,
    commit: bool = True,
    **params,
) -> AuditLog:
    """Append one audit row, extending the hash chain. With commit=False the
    row joins the caller's transaction (flushed so its id is available
    immediately). created_at is set here (not by the column default) because
    it is part of the hashed content."""
    entry = AuditLog(
        action=action,
        actor=actor,
        plate=plate or None,
        entity_id=entity_id,
        params=json.dumps(
            {k: v for k, v in params.items() if v is not None},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ) or None,
        created_at=utcnow(),
    )
    entry.prev_hash = chain_head(db)
    entry.row_hash = compute_row_hash(entry)
    db.add(entry)
    if commit:
        db.commit()
        db.refresh(entry)
    else:
        db.flush()
    return entry


def audit_to_dict(entry: AuditLog) -> dict:
    from .schemas import iso_z  # local import: schemas imports nothing from here

    return {
        "id": entry.id,
        "action": entry.action,
        "actor": entry.actor,
        "plate": entry.plate,
        "entity_id": entry.entity_id,
        "params": json.loads(entry.params) if entry.params else None,
        "created_at": iso_z(entry.created_at),
        "prev_hash": entry.prev_hash,
        "row_hash": entry.row_hash,
    }
