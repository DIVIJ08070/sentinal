"""Model 1 registry: schema upgrade, CSV import/export round-trip, audited
metadata edits, gap analysis, department-scoped tokens, catalogue sync
keeping operator-entered registry fields."""
import csv
import io
import os
import sys
from datetime import date, timedelta

import pytest

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEST_DB = os.path.join(_BACKEND_DIR, "test_sentinel.db")
sys.path.insert(0, _BACKEND_DIR)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_DB}")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import inspect, text  # noqa: E402

from app.db import Base, add_missing_columns, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.routers import cameras as cameras_router  # noqa: E402

TODAY = date.today()

CSV_HEADER = ("external_id,name,department,lat,lon,status,camera_type,ownership,"
              "installed_on,amc_expiry,maintenance_status,last_maintenance_on,storage_type,retention_days\n")


@pytest.fixture(scope="module")
def client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_add_missing_columns_upgrades_an_old_database():
    Base.metadata.drop_all(bind=engine)
    with engine.begin() as conn:  # a cameras table as an older release created it
        conn.execute(text("CREATE TABLE cameras (id INTEGER PRIMARY KEY, source VARCHAR(16), "
                          "name VARCHAR(255), status VARCHAR(16), created_at DATETIME)"))
    added = add_missing_columns()
    assert "cameras.camera_type" in added and "cameras.amc_expiry" in added
    cols = {c["name"] for c in inspect(engine).get_columns("cameras")}
    assert {"maintenance_status", "installed_on", "lat", "lon"} <= cols
    assert add_missing_columns() == []  # idempotent
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _upload(client, body: str, headers=None):
    return client.post("/api/cameras/bulk", headers=headers or {},
                       files={"file": ("cams.csv", body.encode("utf-8"), "text/csv")})


def test_bulk_import_registry_fields_and_export_roundtrip(client):
    old = (TODAY - timedelta(days=365 * 7)).isoformat()
    expired = (TODAY - timedelta(days=10)).strftime("%d-%m-%Y")  # Indian day-first form
    body = CSV_HEADER + (
        f"AMD-1,Ahmedabad Lal Darwaja,Home/Police,23.0240,72.5800,live,bullet,Ahmedabad City Police,"
        f"{old},{expired},faulty,,NVR,30\n"
        f"RTO-1,RTO Checkpost Bhilad,RTO,20.2600,72.9000,live,anpr,RTO Valsad,,,ok,,cloud,15\n"
        f"BAD-1,Bad row,RTO,1,2,live,dome,x,,,broken,,,\n"
    )
    r = _upload(client, body)
    assert r.status_code == 200, r.text
    assert r.json()["imported"] == 2
    assert any("maintenance_status" in e for e in r.json()["errors"])

    cams = {c["external_id"]: c for c in client.get("/api/cameras").json()}
    assert cams["AMD-1"]["camera_type"] == "bullet"
    assert cams["AMD-1"]["amc_expiry"] == (TODAY - timedelta(days=10)).isoformat()
    assert cams["AMD-1"]["maintenance_status"] == "faulty"

    exp = client.get("/api/cameras/export", params={"format": "csv"})
    assert exp.status_code == 200 and "attachment" in exp.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(exp.text.lstrip("﻿"))))
    assert {r["external_id"] for r in rows} >= {"AMD-1", "RTO-1"}
    # The export re-imports cleanly (round trip) and updates in place.
    r = _upload(client, exp.text.lstrip("﻿"))
    assert r.status_code == 200 and r.json()["errors"] == []
    assert len(client.get("/api/cameras").json()) == 2

    actions = [e["action"] for e in client.get("/api/audit").json()["entries"]]
    assert "camera_bulk_import" in actions and "registry_export" in actions


def test_patch_camera_is_audited_with_old_and_new(client):
    cam = next(c for c in client.get("/api/cameras").json() if c["external_id"] == "RTO-1")
    r = client.patch(f"/api/cameras/{cam['id']}", json={"maintenance_status": "under_repair",
                                                        "ownership": "RTO Valsad (Bhilad)"})
    assert r.status_code == 200 and r.json()["maintenance_status"] == "under_repair"
    entry = next(e for e in client.get("/api/audit").json()["entries"] if e["action"] == "camera_update")
    assert entry["entity_id"] == cam["id"]
    assert entry["params"]["changes"]["maintenance_status"] == {"old": "ok", "new": "under_repair"}
    assert client.patch(f"/api/cameras/{cam['id']}", json={"maintenance_status": "melted"}).status_code == 422


def test_gap_analysis_finds_uncovered_aged_and_faulty(client):
    g = client.get("/api/registry/gap-analysis", params={"coverage_km": 25}).json()
    by_name = {d["district"]: d for d in g["coverage"]["districts"]}
    assert by_name["Ahmedabad"]["covered"] is True
    assert by_name["Dang"]["covered"] is False and by_name["Kutch"]["covered"] is False
    assert g["summary"]["districts_total"] == 33
    assert [a["external_id"] for a in g["ageing"]["aged"]] == ["AMD-1"]
    assert [a["external_id"] for a in g["ageing"]["amc_expired"]] == ["AMD-1"]
    attention = {a["external_id"]: a["maintenance_status"] for a in g["maintenance"]["needs_attention"]}
    assert attention == {"AMD-1": "faulty", "RTO-1": "under_repair"}
    assert any("district HQs have no registry camera" in f for f in g["findings"])

    page = client.get("/api/registry/gap-analysis.html")
    assert page.status_code == 200 and "registry gap analysis" in page.text
    assert "Dang" in page.text
    assert any(e["action"] == "gap_analysis_report" for e in client.get("/api/audit").json()["entries"])


def test_department_scoped_token(client, monkeypatch):
    monkeypatch.setenv("SENTINEL_TOKENS", "tok-rto:rto-desk:operator:RTO,tok-admin:sp-admin:admin")
    rto = {"Authorization": "Bearer tok-rto"}
    admin = {"Authorization": "Bearer tok-admin"}
    seen = {c["external_id"] for c in client.get("/api/cameras", headers=rto).json()}
    assert seen == {"RTO-1"}
    assert len(client.get("/api/cameras", headers=admin).json()) == 2
    police = next(c for c in client.get("/api/cameras", headers=admin).json() if c["external_id"] == "AMD-1")
    assert client.patch(f"/api/cameras/{police['id']}", json={"ownership": "x"}, headers=rto).status_code == 403
    r = _upload(client, CSV_HEADER + "AMD-9,Other dept,Home/Police,23,72,live,,,,,,,,\n", headers=rto)
    assert r.json()["imported"] == 0 and "outside your scope" in r.json()["errors"][0]
    # Hijack attempt: claim the Police camera's external_id with the RTO's own
    # department - must be refused, and the stored record left untouched.
    r = _upload(client, CSV_HEADER + "AMD-1,Hijacked,RTO,1,1,live,,,,,,,,\n", headers=rto)
    assert r.json()["imported"] == 0 and "belongs to another department" in r.json()["errors"][0]
    police_after = next(c for c in client.get("/api/cameras", headers=admin).json()
                        if c["external_id"] == "AMD-1")
    assert police_after["name"] == police["name"] and police_after["department"] == "Home/Police"
    rows = client.get("/api/cameras/export", params={"format": "json"}, headers=rto).json()
    assert [r["external_id"] for r in rows] == ["RTO-1"]
    assert client.get("/api/registry/gap-analysis", headers=rto).json()["summary"]["cameras"] == 1


def test_sync_keeps_operator_entered_registry_fields(client, monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return [{"id": "cam01", "name": "Grid cam 1", "department": "Sandbox",
                     "location": {"lat": 23.05, "lon": 72.55}, "live": True,
                     "type": "ptz", "owner": "Traffic Police"}]

    monkeypatch.setattr(cameras_router.httpx, "get", lambda *a, **k: FakeResponse())
    assert client.post("/api/cameras/sync").json()["synced"] == 1
    cam = next(c for c in client.get("/api/cameras").json() if c["external_id"] == "cam01")
    assert cam["camera_type"] == "ptz" and cam["ownership"] == "Traffic Police"  # catalogue aliases
    client.patch(f"/api/cameras/{cam['id']}", json={"maintenance_status": "due"})
    client.post("/api/cameras/sync")  # catalogue has no maintenance field
    cam = next(c for c in client.get("/api/cameras").json() if c["external_id"] == "cam01")
    assert cam["maintenance_status"] == "due"
