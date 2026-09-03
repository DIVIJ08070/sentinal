import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..matching import canonicalize, find_watchlist_match, normalize
from ..models import Alert, Camera, Detection, WatchlistEntry
from ..schemas import DetectionCreate, DetectionOut, alert_to_dict, as_naive_utc, iso_z
from ..sources import visible_detection
from ..ws import manager
from .routes import (
    MAX_SPEED_KMH,
    MAX_SPEED_SHORT_GAP_KMH,
    SAME_LOCATION_KM,
    SHORT_GAP_S,
    haversine_km,
)

router = APIRouter(prefix="/detections", tags=["detections"])

_MIN_DT_S = 0.1  # divide-by-zero guard (same as the route physics filter)


def _alert_plausibility(
    db: Session, camera: Camera, plates: set[str], captured_at, exclude_detection_id: int
) -> tuple[str | None, str | None]:
    """Physics sanity check at ALERT time, using the exact thresholds of the
    route physics filter (routes.py): implied speed from the vehicle's most
    recent prior sighting with coordinates to this one.

    ``plates`` is the set of stored-plate spellings that count as "the same
    vehicle" for the prior-sighting lookup: the detection's own normalized
    read, the matched watchlist entry's plate, and the canonical repaired
    form. Without this, a FUZZY alert (stored misread string, e.g.
    GJ01A81234) could never find the vehicle's real prior sightings and
    always carried plausibility null next to exact rows saying 'confirmed'.

    Recall-first by design — nothing is suppressed. 'suspect' just means the
    alerts feed and the route view already agree: this sighting implies a
    physically impossible hop and the route engine will reject it.
    Returns (plausibility, reason): ('confirmed'|'suspect'|None, str|None).
    """
    if camera.lat is None or camera.lon is None:
        return None, None  # cannot be physics-checked
    prior = (
        db.query(Detection, Camera)
        .join(Camera, Detection.camera_id == Camera.id)
        .filter(
            Detection.plate.in_(sorted(p for p in plates if p)),
            Detection.id != exclude_detection_id,
            Detection.captured_at <= captured_at,
            Camera.lat.isnot(None),
            Camera.lon.isnot(None),
        )
        .order_by(Detection.captured_at.desc(), Detection.id.desc())
        .first()
    )
    if prior is None:
        return None, None  # first sighting: nothing to check against
    prior_detection, prior_camera = prior
    leg_km = haversine_km(prior_camera.lat, prior_camera.lon, camera.lat, camera.lon)
    if leg_km <= SAME_LOCATION_KM:
        return "confirmed", None
    dt_s = (captured_at - prior_detection.captured_at).total_seconds()
    implied_kmh = (leg_km / max(dt_s, _MIN_DT_S)) * 3600.0
    threshold = MAX_SPEED_SHORT_GAP_KMH if dt_s < SHORT_GAP_S else MAX_SPEED_KMH
    if implied_kmh > threshold:
        return "suspect", (
            f"implied speed {implied_kmh:.0f} km/h over {leg_km:.1f} km in {dt_s:.0f}s "
            f"from previous sighting at {prior_camera.name} — physically implausible; "
            f"likely false ANPR match (route physics filter will adjudicate)"
        )
    return "confirmed", None


def _resolve_camera(db: Session, payload: DetectionCreate) -> Camera:
    if payload.camera_id is not None:
        camera = db.get(Camera, payload.camera_id)
        if camera is not None:
            return camera
    if payload.camera_external_id is not None:
        # Catalogue cameras take precedence when the same external_id exists
        # under another source (e.g. a csv import).
        camera = (
            db.query(Camera)
            .filter(Camera.external_id == payload.camera_external_id, Camera.source == "catalogue")
            .first()
        ) or (
            db.query(Camera)
            .filter(Camera.external_id == payload.camera_external_id)
            .first()
        )
        if camera is not None:
            return camera
    raise HTTPException(status_code=404, detail="camera not found")


def _bbox_to_json_str(bbox) -> str | None:
    if bbox is None:
        return None
    if isinstance(bbox, str):
        return bbox
    return json.dumps(bbox)


@router.post("")
async def create_detection(payload: DetectionCreate, db: Session = Depends(get_db)):
    camera = _resolve_camera(db, payload)
    plate = normalize(payload.plate) or None

    detection = Detection(
        camera_id=camera.id,
        object_type=payload.object_type or "vehicle",
        vehicle_type=payload.vehicle_type,
        plate=plate,
        plate_raw=(payload.plate if plate else None),
        plate_confidence=payload.plate_confidence,
        pts_ms=payload.pts_ms,
        captured_at=as_naive_utc(payload.captured_at),
        snapshot_b64=payload.snapshot_b64,
        bbox=_bbox_to_json_str(payload.bbox),
        detector=payload.detector,
    )
    db.add(detection)
    db.flush()

    alert = None
    if plate:
        entries = db.query(WatchlistEntry).filter(WatchlistEntry.active.is_(True)).all()
        entry, match_type, match_confidence = find_watchlist_match(plate, entries)
        if entry is not None:
            # Prior sightings of the SAME VEHICLE, not the same misread string:
            # the raw normalized read, the matched watchlist plate, and the
            # canonical (confusion-repaired) form all identify this vehicle.
            same_vehicle = {plate, entry.plate, canonicalize(plate)}
            plausibility, plausibility_reason = _alert_plausibility(
                db, camera, same_vehicle, detection.captured_at, detection.id
            )
            alert = Alert(
                detection_id=detection.id,
                watchlist_id=entry.id,
                camera_id=camera.id,
                plate=plate,
                match_type=match_type,
                match_confidence=match_confidence,
                matched_from=payload.plate,
                plausibility=plausibility,
                plausibility_reason=plausibility_reason,
                status="new",
            )
            db.add(alert)

    db.commit()

    await manager.broadcast({
        "type": "detection",
        "detection": {
            "camera_id": camera.id,
            "camera_name": camera.name,
            "plate": plate,
            "captured_at": iso_z(detection.captured_at),
        },
    })
    if alert is not None:
        db.refresh(alert)
        await manager.broadcast({"type": "alert", "alert": alert_to_dict(alert)})

    return {"detection_id": detection.id, "alert_id": alert.id if alert is not None else None}


@router.get("", response_model=list[DetectionOut])
def list_detections(
    plate: str | None = None,
    camera_id: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    query = db.query(Detection).filter(visible_detection())  # hide simulator/mock rows
    if plate:
        query = query.filter(Detection.plate == normalize(plate))
    if camera_id is not None:
        query = query.filter(Detection.camera_id == camera_id)
    if since is not None:
        query = query.filter(Detection.captured_at >= as_naive_utc(since))
    if until is not None:
        query = query.filter(Detection.captured_at <= as_naive_utc(until))
    return (
        query.order_by(Detection.captured_at.desc(), Detection.id.desc())
        .limit(limit)
        .all()
    )
