import csv
import io
import logging

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import CATALOGUE_URL
from ..db import get_db
from ..models import Camera, utcnow
from ..schemas import CameraCreate, CameraOut, HeartbeatIn
from ..ws import manager

logger = logging.getLogger("sentinel.cameras")

router = APIRouter(prefix="/cameras", tags=["cameras"])


@router.get("", response_model=list[CameraOut])
def list_cameras(
    department: str | None = None,
    status: str | None = None,
    source: str | None = None,
    db: Session = Depends(get_db),
):
    query = db.query(Camera)
    if department:
        query = query.filter(Camera.department == department)
    if status:
        query = query.filter(Camera.status == status)
    if source:
        query = query.filter(Camera.source == source)
    return query.order_by(Camera.id.asc()).all()


@router.post("", response_model=CameraOut)
def create_camera(payload: CameraCreate, db: Session = Depends(get_db)):
    camera = Camera(source="manual", **payload.model_dump())
    db.add(camera)
    try:
        db.commit()
    except IntegrityError:
        # Unique constraint on (source, external_id): a manual camera with
        # this external_id already exists.
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail=f"a manual camera with external_id {payload.external_id!r} already exists",
        )
    db.refresh(camera)
    return camera


@router.post("/bulk")
def bulk_upload(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """CSV import. Columns: external_id,name,department,lat,lon,codec,status,
    rtsp_url,hls_url — missing columns tolerated; rows upsert on external_id."""
    raw = file.file.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="CSV must be UTF-8 encoded")

    reader = csv.DictReader(io.StringIO(text))
    imported = 0
    errors: list[str] = []

    for line_no, row in enumerate(reader, start=2):  # header is line 1
        values = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items() if k}
        name = values.get("name")
        if not name:
            errors.append(f"row {line_no}: missing name")
            continue

        lat = lon = None
        try:
            if values.get("lat"):
                lat = float(values["lat"])
            if values.get("lon"):
                lon = float(values["lon"])
        except ValueError:
            errors.append(f"row {line_no}: invalid lat/lon")
            continue

        external_id = values.get("external_id") or None
        status = values.get("status") or "unknown"
        if status not in ("live", "down", "unknown"):
            status = "unknown"

        fields = {
            "name": name,
            "department": values.get("department") or None,
            "lat": lat,
            "lon": lon,
            "codec": values.get("codec") or None,
            "status": status,
            "rtsp_url": values.get("rtsp_url") or None,
            "hls_url": values.get("hls_url") or None,
        }

        camera = None
        if external_id:
            camera = (
                db.query(Camera)
                .filter(Camera.source == "csv", Camera.external_id == external_id)
                .first()
            )
        if camera is None:
            camera = Camera(source="csv", external_id=external_id)
            db.add(camera)
        for key, value in fields.items():
            setattr(camera, key, value)
        imported += 1

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
    }


@router.post("/sync")
def sync_catalogue(db: Session = Depends(get_db)):
    """Fetch {SENTINEL_HOST}/api/ingest and upsert cameras with
    source='catalogue', matching on external_id."""
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

    synced = live = down = 0
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

        status = parsed.pop("status")
        parsed.pop("external_id")
        for key, value in parsed.items():
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

    db.commit()
    logger.info("catalogue sync: %d cameras (%d live, %d down)", synced, live, down)
    return {"synced": synced, "live": live, "down": down}


@router.get("/geojson")
def cameras_geojson(db: Session = Depends(get_db)):
    features = []
    for camera in db.query(Camera).order_by(Camera.id.asc()).all():
        if camera.lat is None or camera.lon is None:
            continue
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [camera.lon, camera.lat]},
            "properties": CameraOut.model_validate(camera).model_dump(),
        })
    return {"type": "FeatureCollection", "features": features}


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
