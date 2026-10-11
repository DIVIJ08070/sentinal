import csv
import io
import json
import logging
from datetime import date, datetime

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import record as audit_record, resolve_operator
from ..auth import department_scope, require_role
from ..config import CATALOGUE_URL
from ..db import get_db
from ..models import Camera, utcnow
from ..schemas import (
    MAINTENANCE_STATUSES, REGISTRY_FIELDS, CameraCreate, CameraOut, CameraPatch, HeartbeatIn, iso_z,
)
from ..ws import manager

logger = logging.getLogger("sentinel.cameras")

router = APIRouter(prefix="/cameras", tags=["cameras"])

# Registry export columns. The same names are accepted by POST /cameras/bulk,
# so an export can be edited in a spreadsheet and re-imported.
EXPORT_COLUMNS = (
    "id", "external_id", "source", "name", "department", "lat", "lon", "status",
    "camera_type", "ownership", "installed_on", "amc_expiry", "maintenance_status",
    "last_maintenance_on", "codec", "width", "height", "storage_type", "retention_days",
    "rtsp_url", "hls_url", "last_seen_at",
)


# ---------------------------------------------------------------- helpers

def parse_date(value) -> date | None:
    """Tolerant date parsing for registry sheets: ISO (2024-03-31) or the
    Indian day-first forms (31-03-2024, 31/03/2024). Raises ValueError on junk."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date {text!r} (use YYYY-MM-DD or DD-MM-YYYY)")


def _maybe_date(value) -> date | None:
    try:
        return parse_date(value)
    except ValueError:
        return None


def _maintenance(value) -> str | None:
    text = (str(value).strip().lower().replace(" ", "_").replace("-", "_") if value else "")
    return text if text in MAINTENANCE_STATUSES else None


def _scoped(query, request: Request):
    scope = department_scope(request)
    return query.filter(Camera.department == scope) if scope else query


def _check_scope(request: Request, department: str | None) -> None:
    scope = department_scope(request)
    if scope and department != scope:
        raise HTTPException(
            status_code=403,
            detail=f"your token is limited to department {scope!r}",
        )


def _audit_value(value):
    return value.isoformat() if isinstance(value, (date, datetime)) else value


# ------------------------------------------------------------------- read

@router.get("", response_model=list[CameraOut])
def list_cameras(
    request: Request,
    department: str | None = None,
    status: str | None = None,
    source: str | None = None,
    camera_type: str | None = None,
    maintenance_status: str | None = None,
    db: Session = Depends(get_db),
):
    query = _scoped(db.query(Camera), request)
    if department:
        query = query.filter(Camera.department == department)
    if status:
        query = query.filter(Camera.status == status)
    if source:
        query = query.filter(Camera.source == source)
    if camera_type:
        query = query.filter(Camera.camera_type == camera_type)
    if maintenance_status:
        query = query.filter(Camera.maintenance_status == maintenance_status)
    return query.order_by(Camera.id.asc()).all()


@router.get("/export")
def export_cameras(
    request: Request,
    format: str = Query(default="csv", pattern="^(csv|json)$"),
    department: str | None = None,
    status: str | None = None,
    camera_type: str | None = None,
    maintenance_status: str | None = None,
    db: Session = Depends(get_db),
):
    """Registry export (CSV or JSON) with the same filters as the list. The
    export is an audited action. Stream URLs in the registry are
    credential-free (grid credentials are injected at connect time only)."""
    cameras = list_cameras(request, department, status, None, camera_type, maintenance_status, db)
    rows = []
    for camera in cameras:
        row = {}
        for col in EXPORT_COLUMNS:
            value = getattr(camera, col)
            row[col] = iso_z(value) if isinstance(value, datetime) else _audit_value(value)
        rows.append(row)
    audit_record(
        db, "registry_export", resolve_operator(request), format=format, rows=len(rows),
        department=department or department_scope(request), status=status,
        camera_type=camera_type, maintenance_status=maintenance_status,
    )
    stamp = utcnow().strftime("%Y%m%d-%H%M")
    if format == "json":
        return Response(
            json.dumps(rows, indent=2), media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="sentinel-registry-{stamp}.json"'},
        )
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS)
    writer.writeheader()
    for row in rows:
        # Spreadsheet formula injection guard: text cells never start with = + - @.
        writer.writerow({
            k: ("'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v)
            for k, v in row.items()
        })
    return Response(
        "﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",  # BOM: Excel opens UTF-8 correctly
        headers={"Content-Disposition": f'attachment; filename="sentinel-registry-{stamp}.csv"'},
    )


@router.get("/geojson")
def cameras_geojson(request: Request, db: Session = Depends(get_db)):
    features = []
    for camera in _scoped(db.query(Camera), request).order_by(Camera.id.asc()).all():
        if camera.lat is None or camera.lon is None:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [camera.lon, camera.lat]},
            "properties": CameraOut.model_validate(camera).model_dump(mode="json"),
        })
    return {"type": "FeatureCollection", "features": features}


# ------------------------------------------------------------------ write

@router.post("", response_model=CameraOut)
def create_camera(payload: CameraCreate, request: Request, db: Session = Depends(get_db),
                  _principal=Depends(require_role("operator"))):
    _check_scope(request, payload.department)
    camera = Camera(source="manual", **payload.model_dump())
    db.add(camera)
    try:
        db.flush()
    except IntegrityError:
        # Unique constraint on (source, external_id): a manual camera with
        # this external_id already exists.
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"a manual camera with external_id {payload.external_id!r} already exists",
        )
    audit_record(
        db, "camera_create", resolve_operator(request), entity_id=camera.id, commit=False,
        name=camera.name, department=camera.department, source="manual",
    )
    db.commit()
    db.refresh(camera)
    return camera


@router.patch("/{camera_id}", response_model=CameraOut)
def patch_camera(camera_id: int, payload: CameraPatch, request: Request, db: Session = Depends(get_db),
                 _principal=Depends(require_role("operator"))):
    """Edit registry metadata (location, ownership, type, maintenance...).
    Each change is audited with its old and new value."""
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="camera not found")
    _check_scope(request, camera.department)
    updates = payload.model_dump(exclude_unset=True)
    if "department" in updates:
        _check_scope(request, updates["department"])  # cannot move a camera out of your scope
    changes = {}
    for key, value in updates.items():
        old = getattr(camera, key)
        if old != value:
            changes[key] = {"old": _audit_value(old), "new": _audit_value(value)}
            setattr(camera, key, value)
    if changes:
        audit_record(
            db, "camera_update", resolve_operator(request), entity_id=camera.id, commit=False,
            camera=camera.external_id or camera.name, changes=changes,
        )
    db.commit()
    db.refresh(camera)
    return camera


@router.post("/bulk")
def bulk_upload(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db),
                _principal=Depends(require_role("operator"))):
    """CSV import. Columns: external_id,name,department,lat,lon,codec,status,
    rtsp_url,hls_url plus the registry fields camera_type,ownership,
    installed_on,amc_expiry,maintenance_status,last_maintenance_on,
    storage_type,retention_days,width,height - missing columns tolerated;
    rows upsert on external_id. A GET /cameras/export CSV re-imports as-is."""
    raw = file.file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded")

    reader = csv.DictReader(io.StringIO(text))
    imported = 0
    errors: list[str] = []
    scope = department_scope(request)

    for line_no, row in enumerate(reader, start=2):  # header is line 1
        values = {(k or "").strip().lower(): (v or "").strip().lstrip("'") for k, v in row.items() if k}
        name = values.get("name")
        if not name:
            errors.append(f"row {line_no}: missing name")
            continue

        try:
            lat = float(values["lat"]) if values.get("lat") else None
            lon = float(values["lon"]) if values.get("lon") else None
            retention = int(values["retention_days"]) if values.get("retention_days") else None
            width = int(values["width"]) if values.get("width") else None
            height = int(values["height"]) if values.get("height") else None
        except ValueError:
            errors.append(f"row {line_no}: invalid number (lat/lon/retention_days/width/height)")
            continue
        try:
            dates = {f: parse_date(values.get(f)) for f in ("installed_on", "amc_expiry", "last_maintenance_on")}
        except ValueError as exc:
            errors.append(f"row {line_no}: {exc}")
            continue
        maintenance = values.get("maintenance_status") or None
        if maintenance and _maintenance(maintenance) is None:
            errors.append(f"row {line_no}: maintenance_status must be one of {', '.join(MAINTENANCE_STATUSES)}")
            continue

        department = values.get("department") or None
        if scope and department != scope:
            errors.append(f"row {line_no}: department {department!r} is outside your scope {scope!r}")
            continue

        external_id = values.get("external_id") or None
        status = values.get("status") or "unknown"
        if status not in ("live", "down", "unknown"):
            status = "unknown"

        fields = {
            "name": name,
            "department": department,
            "lat": lat,
            "lon": lon,
            "codec": values.get("codec") or None,
            "width": width,
            "height": height,
            "status": status,
            "rtsp_url": values.get("rtsp_url") or None,
            "hls_url": values.get("hls_url") or None,
            "storage_type": values.get("storage_type") or None,
            "retention_days": retention,
            "camera_type": values.get("camera_type") or None,
            "ownership": values.get("ownership") or None,
            "maintenance_status": _maintenance(maintenance),
            **dates,
        }

        camera = None
        if external_id:
            camera = (
                db.query(Camera)
                .filter(Camera.source == "csv", Camera.external_id == external_id)
                .first()
            )
        if camera is not None and scope and camera.department != scope:
            # The row's own department passed the check above; the STORED
            # record must too, or a scoped user could overwrite another
            # department's camera (and move it into their scope) by its id.
            errors.append(f"row {line_no}: camera {external_id!r} belongs to another department")
            continue
        if camera is None:
            camera = Camera(source="csv", external_id=external_id)
            db.add(camera)
        for key, value in fields.items():
            setattr(camera, key, value)
        imported += 1

    audit_record(
        db, "camera_bulk_import", resolve_operator(request), commit=False,
        filename=file.filename, imported=imported, errors=len(errors),
    )
    db.commit()
    return {"imported": imported, "errors": errors}


def _catalogue_float(value):
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _catalogue_int(value):
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_catalogue_item(item: dict) -> dict | None:
    """Tolerant catalogue-record parsing: nested location.{lat,lon} OR flat
    lat/lon; nested urls.{rtsp,hls,whep} OR flat *_url; unknown fields ignored;
    missing coords -> null. Returns None when the record has no usable id."""
    raw_id = item.get("id", item.get("external_id"))
    if raw_id is None or str(raw_id).strip() == "":
        return None

    location = item.get("location") if isinstance(item.get("location"), dict) else {}
    lat = _catalogue_float(location.get("lat", item.get("lat")))
    lon = _catalogue_float(location.get("lon", item.get("lon")))

    urls = item.get("urls") if isinstance(item.get("urls"), dict) else {}
    rtsp_url = urls.get("rtsp") or item.get("rtsp_url") or None
    hls_url = urls.get("hls") or item.get("hls_url") or None
    whep_url = urls.get("whep") or item.get("whep_url") or None

    status = None
    if "live" in item and isinstance(item["live"], bool):
        status = "live" if item["live"] else "down"
    elif item.get("status") in ("live", "down", "unknown"):
        status = item["status"]

    return {
        "external_id": str(raw_id),
        "name": str(item.get("name") or f"Camera {raw_id}"),
        "department": item.get("department") or None,
        "lat": lat,
        "lon": lon,
        "codec": item.get("codec") or None,
        "width": _catalogue_int(item.get("width")),
        "height": _catalogue_int(item.get("height")),
        "fps_declared": _catalogue_float(item.get("fps", item.get("fps_declared"))),
        "status": status,
        "rtsp_url": rtsp_url,
        "hls_url": hls_url,
        "whep_url": whep_url,
        "storage_type": item.get("storage_type") or None,
        "retention_days": _catalogue_int(item.get("retention_days")),
        # Registry metadata, when the catalogue carries it (common aliases).
        "camera_type": item.get("camera_type") or item.get("type") or None,
        "ownership": item.get("ownership") or item.get("owner") or None,
        "installed_on": _maybe_date(item.get("installed_on") or item.get("install_date")),
        "amc_expiry": _maybe_date(item.get("amc_expiry") or item.get("amc_end")),
        "maintenance_status": _maintenance(item.get("maintenance_status")),
        "last_maintenance_on": _maybe_date(item.get("last_maintenance_on")),
    }


@router.post("/sync")
def sync_catalogue(request: Request, db: Session = Depends(get_db)):
    """Fetch {SENTINEL_HOST}/api/ingest and upsert cameras with
    source='catalogue', matching on external_id. Registry fields the
    catalogue does not carry never overwrite values entered by an operator."""
    try:
        response = httpx.get(CATALOGUE_URL, timeout=15.0)
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"catalogue fetch failed: {exc}")

    if isinstance(payload, dict):
        items = payload.get("cameras", payload.get("items", []))
    else:
        items = payload
    if not isinstance(items, list):
        raise HTTPException(status_code=502, detail="catalogue returned an unexpected shape")

    synced = live = down = created = 0
    now = utcnow()
    for item in items:
        if not isinstance(item, dict):
            continue
        parsed = _parse_catalogue_item(item)
        if parsed is None:
            continue

        camera = (
            db.query(Camera)
            .filter(Camera.source == "catalogue", Camera.external_id == parsed["external_id"])
            .first()
        )
        if camera is None:
            camera = Camera(source="catalogue", external_id=parsed["external_id"], status="unknown")
            db.add(camera)
            created += 1

        status = parsed.pop("status")
        parsed.pop("external_id")
        for key, value in parsed.items():
            if key in REGISTRY_FIELDS and value is None:
                continue  # keep operator-entered registry metadata
            setattr(camera, key, value)
        if status is not None:
            camera.status = status  # missing status info -> existing status kept
        if camera.status == "live":
            camera.last_seen_at = now

        synced += 1
        if camera.status == "live":
            live += 1
        elif camera.status == "down":
            down += 1

    audit_record(
        db, "camera_sync", resolve_operator(request), commit=False,
        catalogue=CATALOGUE_URL, synced=synced, created=created, live=live, down=down,
    )
    db.commit()
    logger.info("catalogue sync: %d cameras (%d live, %d down)", synced, live, down)
    return {"synced": synced, "live": live, "down": down}


@router.post("/{camera_id}/heartbeat")
async def heartbeat(camera_id: int, payload: HeartbeatIn, db: Session = Depends(get_db)):
    camera = db.get(Camera, camera_id)
    if camera is None:
        raise HTTPException(status_code=404, detail="camera not found")
    camera.status = payload.status
    camera.last_seen_at = utcnow()
    # Optional health metrics (docs/CONTRACT_ADDENDUM.md): only overwrite what
    # this heartbeat actually reported.
    for field in ("fps_measured", "last_frame_age_s", "reconnects", "bandwidth_kbps"):
        value = getattr(payload, field)
        if value is not None:
            setattr(camera, field, value)
    db.commit()
    if payload.status in ("live", "down"):
        await manager.broadcast({
            "type": "camera_status",
            "camera_id": camera.id,
            "status": payload.status,
        })
    return {"camera_id": camera.id, "status": camera.status}
