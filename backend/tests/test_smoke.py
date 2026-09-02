"""Mechanized version of the live-report smoke ritual (run: make test).

Covers, against a throwaway SQLite DB and FastAPI TestClient (no servers):
  1. camera + watchlist setup (seed is the real app.seed list),
  2. a scripted 8-sighting journey incl. one fuzzy misread and one trailing
     teleport -> route accepts 9 / rejects exactly the teleport,
  3. the leading-teleport (first-sighting poisoning) retro-rejection guard,
  4. alert plausibility stamping ('suspect' on the teleport alert),
  5. the fuzzy-bait watchlist entry actually firing (GJ01AB1Z39 -> GJ01AB1Z34),
  6. dossier.json hash-chain recomputation + tamper detection,
  7. the append-only audit trail (route query, ack, export, watchlist change).
"""
import base64
import hashlib
import json
import os
import sys
from datetime import datetime, timedelta

import pytest

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEST_DB = os.path.join(_BACKEND_DIR, "test_sentinel.db")
sys.path.insert(0, _BACKEND_DIR)
os.environ["DATABASE_URL"] = f"sqlite:///{_TEST_DB}"  # throwaway file DB

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine, SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app.seed import seed  # noqa: E402

BASE_T = datetime(2026, 9, 2, 8, 0, 0)
PLATE = "GJ01AB1234"


def iso(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds") + "Z"


def canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _tiny_jpeg_b64() -> str:
    """A real, decodable JPEG (Pillow ships with fpdf2) so Appendix A embeds."""
    import io

    from PIL import Image, ImageDraw

    img = Image.new("RGB", (96, 44), (28, 30, 34))
    draw = ImageDraw.Draw(img)
    draw.rectangle([8, 10, 88, 34], fill=(235, 238, 240), outline=(10, 10, 10))
    draw.text((14, 16), PLATE, fill=(15, 15, 15))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=72)
    return base64.b64encode(buf.getvalue()).decode("ascii")


TINY_JPEG = _tiny_jpeg_b64()


@pytest.fixture(scope="module")
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        seed(session)
        session.commit()
    with TestClient(app) as c:
        # 8 route cameras on a west->east Ahmedabad line, ~2 km apart, plus a
        # far Dwarka camera (~360 km) for the teleport injections.
        for i in range(8):
            r = c.post("/api/cameras", json={
                "name": f"AMD junction {i + 1}", "department": "Home/Police",
                "lat": 23.03, "lon": 72.50 + i * 0.02, "status": "live",
            })
            assert r.status_code == 200, r.text
        r = c.post("/api/cameras", json={
            "name": "Dwarka temple road", "department": "Home/Police",
            "lat": 22.24, "lon": 68.96, "status": "live",
        })
        assert r.status_code == 200
        yield c
    if os.path.exists(_TEST_DB):
        os.remove(_TEST_DB)


def post_detection(client, camera_id, plate, at, snapshot=None, conf=0.9):
    body = {
        "camera_id": camera_id, "plate": plate, "plate_confidence": conf,
        "captured_at": iso(at), "detector": "test",
    }
    if snapshot:
        body["snapshot_b64"] = snapshot
    r = client.post("/api/detections", json=body)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def journey(client):
    """8 plausible sightings (~41 km/h legs), one fuzzy misread, one trailing
    teleport, one bait-trigger decoy. Returns collected alert ids by kind."""
    alerts = {}
    for i in range(8):  # cameras 1..8, 180 s apart -> ~2 km @ ~41 km/h
        body = post_detection(
            client, i + 1, PLATE, BASE_T + timedelta(seconds=180 * i), snapshot=TINY_JPEG
        )
        alerts.setdefault("route", []).append(body["alert_id"])
    # Fuzzy misread (8<->B confusion) at camera 5, 10 s after its true
    # sighting -> same location, always accepted, flagged fuzzy at 0.93.
    body = post_detection(client, 5, "GJ01A81234", BASE_T + timedelta(seconds=180 * 4 + 10))
    alerts["fuzzy"] = body["alert_id"]
    # Trailing teleport: Dwarka (~360 km), 30 s after the last sighting.
    body = post_detection(client, 9, PLATE, BASE_T + timedelta(seconds=180 * 7 + 30))
    alerts["teleport"] = body["alert_id"]
    # Bait trigger: only watchlist match is the fuzzy-bait entry GJ01AB1Z34.
    body = post_detection(client, 3, "GJ01AB1Z39", BASE_T + timedelta(seconds=400))
    alerts["bait"] = body["alert_id"]
    return alerts


def test_route_accepts_9_rejects_only_the_teleport(client, journey):
    r = client.get(f"/api/vehicles/{PLATE}/route")
    assert r.status_code == 200
    route = r.json()
    assert len(route["points"]) == 10
    rejected = [p for p in route["points"] if p["rejected"]]
    assert len(rejected) == 1
    assert rejected[0]["camera_name"] == "Dwarka temple road"
    assert "physically impossible" in rejected[0]["rejected_reason"]
    assert route["stats"]["sightings_count"] == 9
    assert route["stats"]["rejected_count"] == 1
    fuzzy = [p for p in route["points"] if p["fuzzy"]]
    assert len(fuzzy) == 1
    assert fuzzy[0]["matched_from"] == "GJ01A81234"
    assert fuzzy[0]["match_confidence"] == pytest.approx(0.93)
    # Ordered by captured_at ascending.
    times = [p["captured_at"] for p in route["points"]]
    assert times == sorted(times)


def test_leading_teleport_retro_rejection(client, journey):
    """A false match that is chronologically FIRST must not poison the route:
    the mutually consistent chain wins and the leading outlier is rejected."""
    plate = "GJ05ZZ4321"  # not on the watchlist; matching is plate-agnostic
    t0 = BASE_T + timedelta(hours=2)
    post_detection(client, 9, plate, t0 - timedelta(seconds=45))  # Dwarka FIRST
    for i in range(3):
        post_detection(client, i + 1, plate, t0 + timedelta(seconds=180 * i))
    route = client.get(f"/api/vehicles/{plate}/route").json()
    assert len(route["points"]) == 4
    assert route["points"][0]["rejected"] is True
    assert "outlier" in route["points"][0]["rejected_reason"]
    assert [p["rejected"] for p in route["points"][1:]] == [False, False, False]
    assert route["stats"]["sightings_count"] == 3
    assert route["stats"]["rejected_count"] == 1
    # The re-accepted chain got its legs recomputed among itself.
    assert route["points"][1]["leg_km"] is None  # new chain start
    assert route["points"][2]["implied_speed_kmh"] < 100


def test_alert_plausibility_stamps(client, journey):
    r = client.get("/api/alerts", params={"limit": 200})
    by_id = {a["id"]: a for a in r.json()}
    # Every route sighting raised an exact alert; sightings 2..8 have a prior
    # plausible sighting -> 'confirmed'; the first has nothing to check.
    assert by_id[journey["route"][0]]["plausibility"] is None
    assert by_id[journey["route"][3]]["plausibility"] == "confirmed"
    # The teleport alert fires (recall-first) but is stamped suspect.
    teleport = by_id[journey["teleport"]]
    assert teleport["match_type"] == "exact"
    assert teleport["plausibility"] == "suspect"
    assert "implied speed" in teleport["plausibility_reason"]
    # Snapshot rides along on the alert card.
    assert by_id[journey["route"][0]]["detection"]["snapshot_b64"] == TINY_JPEG


def test_fuzzy_alert_gets_a_plausibility_stamp_too(client, journey):
    """Regression (live-report wart 3): the prior-sighting lookup used to
    filter on the stored MISREAD string, so a fuzzy alert could never find the
    vehicle's real prior sightings and always showed plausibility null next to
    exact rows saying 'confirmed'. The lookup now covers the matched watchlist
    plate + canonical form: the GJ01A81234 misread (camera 5, 10 s after the
    true camera-5 sighting -> same location) must stamp 'confirmed'."""
    r = client.get("/api/alerts", params={"limit": 200})
    fuzzy = {a["id"]: a for a in r.json()}[journey["fuzzy"]]
    assert fuzzy["match_type"] == "fuzzy"
    assert fuzzy["plausibility"] == "confirmed"


def test_fuzzy_bait_entry_fires(client, journey):
    assert journey["bait"] is not None
    r = client.get("/api/alerts", params={"limit": 200})
    bait = {a["id"]: a for a in r.json()}[journey["bait"]]
    assert bait["match_type"] == "fuzzy"
    assert bait["matched_from"] == "GJ01AB1Z39"
    assert bait["watchlist"]["label"].startswith("Suspect vehicle — burglary")


def test_dossier_hash_chain_recomputes_and_detects_tampering(client, journey):
    r = client.get(f"/api/vehicles/{PLATE}/dossier.json", headers={"X-Operator": "insp-sharma"})
    assert r.status_code == 200
    d = r.json()
    assert d["operator"] == "insp-sharma"
    # Genesis and per-row recomputation.
    genesis = sha256_hex(canonical_json(
        {"plate": d["plate"], "generated_at": d["generated_at"], "operator": d["operator"]}
    ))
    assert genesis == d["hash_chain"]["genesis_hash"]
    prev = genesis
    for row in d["sightings"]:
        payload = {k: v for k, v in row.items() if k not in ("row_hash", "snapshot_b64")}
        assert payload["prev_hash"] == prev
        assert sha256_hex(canonical_json(payload)) == row["row_hash"]
        if row["snapshot_b64"]:
            assert row["snapshot_sha256"] == hashlib.sha256(
                base64.b64decode(row["snapshot_b64"])
            ).hexdigest()
        prev = row["row_hash"]
    assert prev == d["hash_chain"]["final_hash"]
    # Tampering any field breaks the recomputed chain.
    tampered = {k: v for k, v in d["sightings"][2].items() if k not in ("row_hash", "snapshot_b64")}
    tampered["captured_at"] = iso(BASE_T + timedelta(days=1))
    assert sha256_hex(canonical_json(tampered)) != d["sightings"][2]["row_hash"]
    # The dossier cites its own audit entry.
    assert d["audit"]["export_entry_id"] > 0
    assert str(d["audit"]["export_entry_id"]) in d["audit"]["statement"]
    # And the PDF renders with snapshots embedded.
    pdf = client.get(f"/api/vehicles/{PLATE}/dossier.pdf")
    assert pdf.status_code == 200
    assert pdf.headers["content-type"].startswith("application/pdf")
    assert pdf.content.startswith(b"%PDF")
    assert len(pdf.content) > 7_000  # sightings + hash chain + audit + Appendix A images


def test_audit_trail_is_written_and_queryable(client, journey):
    # Generate one of each remaining audited action.
    ack_id = journey["route"][1]
    assert client.post(f"/api/alerts/{ack_id}/ack", headers={"X-Operator": "insp-sharma"}).status_code == 200
    wl = client.post("/api/watchlist", json={"plate": "GJ11TT0001", "label": "audit test"},
                     headers={"X-Operator": "insp-sharma"})
    assert wl.status_code == 200
    assert client.delete(f"/api/watchlist/{wl.json()['id']}").status_code == 200
    client.get(f"/api/vehicles/{PLATE}/route")  # audited plate search

    audit = client.get("/api/audit", params={"limit": 500}).json()
    actions = {e["action"] for e in audit["entries"]}
    assert {"route_query", "dossier_export", "alert_ack",
            "watchlist_create", "watchlist_delete"} <= actions
    assert audit["total"] >= len(audit["entries"]) > 0
    ack_rows = [e for e in audit["entries"] if e["action"] == "alert_ack"]
    assert ack_rows[0]["actor"] == "insp-sharma"
    assert ack_rows[0]["entity_id"] == ack_id
    # Plate-scoped provenance, as cited by the dossier.
    scoped = client.get("/api/audit", params={"plate": PLATE}).json()
    assert all(e["plate"] == PLATE for e in scoped["entries"])
    assert any(e["action"] == "dossier_export" for e in scoped["entries"])


def test_audit_log_hash_chain_verifies_and_detects_tampering(client, journey):
    """The audit log is hash-chained like the dossier: every row's row_hash
    covers its canonical content + the previous row's hash. ?verify=1
    recomputes the whole chain; editing any historical row breaks it."""
    from app.audit import GENESIS_HASH
    from app.models import AuditLog

    audit = client.get("/api/audit", params={"verify": 1, "limit": 500}).json()
    chain = audit["chain"]
    assert chain["algorithm"] == "sha256"
    assert chain["genesis_hash"] == GENESIS_HASH
    assert chain["verified"] is True
    assert chain["broken_at_entry"] is None
    assert chain["entries_verified"] == audit["total"] > 0
    # Head is the newest row's hash, and rows link prev->row by recomputation.
    newest = audit["entries"][0]
    assert chain["head"] == newest["row_hash"]
    prev = sha256_hex(canonical_json({
        "action": newest["action"], "actor": newest["actor"],
        "plate": newest["plate"], "entity_id": newest["entity_id"],
        "params": canonical_json(newest["params"]) if newest["params"] is not None else None,
        "created_at": newest["created_at"], "prev_hash": newest["prev_hash"],
    }))
    assert prev == newest["row_hash"]

    # A dossier generated now cites the current chain head as its export entry.
    d = client.get(f"/api/vehicles/{PLATE}/dossier.json").json()
    assert d["audit"]["chain_head"]
    assert d["audit"]["chain_head"][:16] in d["audit"]["statement"]
    head_after = client.get("/api/audit").json()["chain"]["head"]
    assert head_after == d["audit"]["chain_head"]

    # Tamper with one historical row directly in the DB (attacker with SQL
    # access): the chain must break exactly there, then verify again once
    # the original value is restored.
    with SessionLocal() as session:
        row = session.query(AuditLog).order_by(AuditLog.id.asc()).first()
        original = row.actor
        row.actor = "tampered-actor"
        session.commit()
        tampered_id = row.id
    try:
        broken = client.get("/api/audit", params={"verify": 1}).json()["chain"]
        assert broken["verified"] is False
        assert broken["broken_at_entry"] == tampered_id
    finally:
        with SessionLocal() as session:
            row = session.get(AuditLog, tampered_id)
            row.actor = original
            session.commit()
    assert client.get("/api/audit", params={"verify": 1}).json()["chain"]["verified"] is True


def test_dossier_no_sightings_is_a_certified_negative(client, journey):
    """W1: probing a nonsense plate must NOT yield an official-looking evidence
    dossier — the export flags itself as a certified negative result."""
    r = client.get("/api/vehicles/GJ99XX0007/dossier.json")
    assert r.status_code == 200  # dossier.json IS the report contract: 200 + flag, not 404
    d = r.json()
    assert d["no_sightings"] is True
    assert "ABSENCE" in d["notice"]
    assert d["stats"]["sightings_count"] == 0
    assert d["stats"]["rejected_count"] == 0
    assert d["sightings"] == []
    # Empty route: chain is genesis-only and still tamper-evident.
    assert d["hash_chain"]["final_hash"] == d["hash_chain"]["genesis_hash"]
    pdf = client.get("/api/vehicles/GJ99XX0007/dossier.pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    # A plate WITH sightings must not carry the flag.
    d2 = client.get(f"/api/vehicles/{PLATE}/dossier.json").json()
    assert d2["no_sightings"] is False
    assert d2["notice"] is None


AUTH_TOKENS = "tok-view:ps-desk:viewer,tok-op:insp-sharma:operator,tok-admin:sp-admin:admin"


def test_auth_open_demo_mode_unchanged(client, journey):
    """Without SENTINEL_TOKENS the pre-auth demo behaviour is untouched."""
    r = client.post("/api/watchlist", json={"plate": "GJ77AA0001", "label": "open mode"})
    assert r.status_code == 200
    assert client.delete(f"/api/watchlist/{r.json()['id']}").status_code == 200


def test_auth_token_role_gate(client, journey, monkeypatch):
    """RBAC-lite: 401 without a token, 403 below role, and the audit/dossier
    operator identity comes from the TOKEN — X-Operator is ignored."""
    monkeypatch.setenv("SENTINEL_TOKENS", AUTH_TOKENS)
    body = {"plate": "GJ77AA0002", "label": "authed"}
    assert client.post("/api/watchlist", json=body).status_code == 401
    assert client.post(
        "/api/watchlist", json=body, headers={"Authorization": "Bearer tok-view"}
    ).status_code == 403
    r = client.post(
        "/api/watchlist", json=body,
        headers={"Authorization": "Bearer tok-op", "X-Operator": "spoofed-name"},
    )
    assert r.status_code == 200
    entry_id = r.json()["id"]
    audit = client.get("/api/audit", params={"limit": 5}).json()
    created = [e for e in audit["entries"] if e["action"] == "watchlist_create"][0]
    assert created["actor"] == "insp-sharma (operator)"  # token identity, not the header

    # Dossier export is gated and stamps the token principal as operator.
    assert client.get(f"/api/vehicles/{PLATE}/dossier.json").status_code == 401
    d = client.get(
        f"/api/vehicles/{PLATE}/dossier.json",
        headers={"X-Auth-Token": "tok-op", "X-Operator": "spoofed-name"},
    ).json()
    assert d["operator"] == "insp-sharma (operator)"

    assert client.delete(
        f"/api/watchlist/{entry_id}", headers={"Authorization": "Bearer tok-admin"}
    ).status_code == 200
