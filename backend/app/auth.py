"""Minimal token->role authentication (RBAC-lite) for state-changing actions.

Enable by setting, e.g.:

    SENTINEL_TOKENS="tok-viewer:ps-desk:viewer,tok-op:insp-sharma:operator,tok-admin:sp-admin:admin"

Roles rank viewer < operator < admin. While SENTINEL_TOKENS is UNSET (the
default, open demo mode) every request is allowed and operator identity falls
back to the X-Operator header / SENTINEL_OPERATOR env — the pre-auth demo
behaviour, so `scripts/demo.sh` needs no tokens.

When auth is ON:
- callers send `Authorization: Bearer <token>` (or `X-Auth-Token: <token>`);
- gated endpoints (watchlist mutations, alert ack, dossier export) return
  401 without a valid token and 403 below the required role;
- audit rows and the dossier's operator field take their identity from the
  TOKEN, never from the spoofable X-Operator header.

Deliberately not JWT: three static demo principals demonstrate the role gate
and give the chain-of-custody document a real authenticated principal; key
management/IAM integration stays a design provision (HLD §7).
"""
import os

from fastapi import HTTPException, Request

ROLE_RANK = {"viewer": 0, "operator": 1, "admin": 2}


def _token_map() -> dict:
    """Parse SENTINEL_TOKENS ("token:name:role,...") at call time (testable)."""
    raw = os.getenv("SENTINEL_TOKENS", "").strip()
    tokens: dict[str, dict] = {}
    for part in raw.split(","):
        bits = [b.strip() for b in part.strip().split(":")]
        if len(bits) == 3 and all(bits) and bits[2] in ROLE_RANK:
            tokens[bits[0]] = {"name": bits[1], "role": bits[2]}
    return tokens


def auth_enabled() -> bool:
    return bool(_token_map())


def principal_for(request: Request | None) -> dict | None:
    """The authenticated {name, role} for this request, or None."""
    if request is None:
        return None
    cached = getattr(request.state, "principal", None)
    if cached is not None:
        return cached
    tokens = _token_map()
    if not tokens:
        return None
    supplied = request.headers.get("X-Auth-Token")
    if not supplied:
        header = request.headers.get("Authorization", "")
        if header.lower().startswith("bearer "):
            supplied = header[7:].strip()
    principal = tokens.get(supplied or "")
    if principal is not None:
        request.state.principal = principal
    return principal


def require_role(min_role: str):
    """Dependency factory: gate an endpoint to principals of at least min_role.

    No-op while SENTINEL_TOKENS is unset (open demo mode)."""
    assert min_role in ROLE_RANK

    def dependency(request: Request):
        if not auth_enabled():
            return None
        principal = principal_for(request)
        if principal is None:
            raise HTTPException(
                status_code=401,
                detail="authentication required: send 'Authorization: Bearer <token>'",
            )
        if ROLE_RANK[principal["role"]] < ROLE_RANK[min_role]:
            raise HTTPException(
                status_code=403,
                detail=f"role '{principal['role']}' cannot perform this action "
                       f"(requires '{min_role}' or higher)",
            )
        return principal

    return dependency
