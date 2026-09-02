"""Append-only audit trail — the log the Evidence Dossier cites.

Every plate search (route query), watchlist change, alert acknowledgment and
dossier export inserts one row into audit_log. Rows are only ever INSERTed —
no update/delete path exists anywhere in the app — so the table is an
append-only record of who queried what, when, with which parameters.

Operator identity, in priority order:
1. the authenticated token principal (``app/auth.py``, when SENTINEL_TOKENS
   is set) — authoritative, cannot be spoofed by a client header;
2. otherwise (open demo mode only) the ``X-Operator`` request header;
3. the ``SENTINEL_OPERATOR`` env var, else ``"demo-operator"``.
When auth is enabled the X-Operator header is IGNORED — a client that skips
authentication is recorded as ``unauthenticated``, never as whoever it claims.
"""
import json
import os

from fastapi import Request
from sqlalchemy.orm import Session

from .auth import auth_enabled, principal_for
from .models import AuditLog

DEFAULT_OPERATOR = os.getenv("SENTINEL_OPERATOR", "demo-operator")
OPERATOR_HEADER = "X-Operator"


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
    """Append one audit row. With commit=False the row joins the caller's
    transaction (flushed so its id is available immediately)."""
    entry = AuditLog(
        action=action,
        actor=actor,
        plate=plate or None,
        entity_id=entity_id,
        params=json.dumps(
            {k: v for k, v in params.items() if v is not None},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        ) or None,
    )
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
    }
