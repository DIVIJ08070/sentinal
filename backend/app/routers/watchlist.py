from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ..audit import record as audit_record, resolve_operator
from ..auth import require_role
from ..db import get_db
from ..matching import canonicalize, find_watchlist_match, normalize
from ..models import Alert, Camera, Detection, WatchlistEntry, utcnow
from ..schemas import WatchlistCreate, WatchlistOut, WatchlistPatch, alert_to_dict
from ..sources import visible_detection
from ..ws import manager

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.post("/rescan")
async def rescan_recent_sightings(
    request: Request,
    since_hours: float = Query(default=24.0, gt=0, le=24 * 30),
    db: Session = Depends(get_db),
    _principal=Depends(require_role("operator")),
):
    """Retroactive matching: correlate every ACTIVE watchlist entry against the
    recent sighting history and raise alerts for matches that have none yet.

    Operationally this is what happens when a new stolen-vehicle report lands
    on the watchlist — the control room wants to know at once whether that
    vehicle has already been seen, not only from the next frame onward. Uses
    the same matcher (exact / confusion-tolerant fuzzy) and the same alert-time
    physics plausibility check as live detections, so alerts raised from
    history are indistinguishable in quality from live ones. Hidden sources
    (simulator/mock) are never scanned. Every created alert is broadcast over
    the WebSocket so the alerts panel updates live.
    """
    from .detections import _alert_plausibility  # local import: avoids a router import cycle

    entries = db.query(WatchlistEntry).filter(WatchlistEntry.active.is_(True)).all()
    if not entries:
        return {"created": 0, "scanned": 0, "since_hours": since_hours}

    since = utcnow() - timedelta(hours=since_hours)
    already = {
        detection_id for (detection_id,) in db.query(Alert.detection_id).all()
    }
    rows = (
        db.query(Detection, Camera)
        .join(Camera, Detection.camera_id == Camera.id)
        .filter(visible_detection(), Detection.plate.isnot(None), Detection.captured_at >= since)
        .order_by(Detection.captured_at.asc(), Detection.id.asc())
        .all()
    )

    created: list[Alert] = []
    for detection, camera in rows:
        if detection.id in already:
            continue
        entry, match_type, match_confidence = find_watchlist_match(detection.plate, entries)
        if entry is None:
            continue
        same_vehicle = {detection.plate, entry.plate, canonicalize(detection.plate)}
        plausibility, reason = _alert_plausibility(db, camera, same_vehicle, detection.captured_at, detection.id)
        alert = Alert(
            detection_id=detection.id,
            watchlist_id=entry.id,
            camera_id=camera.id,
            plate=detection.plate,
            match_type=match_type,
            match_confidence=match_confidence,
            matched_from=detection.plate_raw or detection.plate,
            plausibility=plausibility,
            plausibility_reason=reason,
            status="new",
        )
        db.add(alert)
        created.append(alert)

    audit_record(
        db, "watchlist_rescan", resolve_operator(request), commit=False,
        since_hours=since_hours, scanned=len(rows), created=len(created),
    )
    db.commit()

    for alert in created:
        db.refresh(alert)
        await manager.broadcast({"type": "alert", "alert": alert_to_dict(alert)})

    return {"created": len(created), "scanned": len(rows), "since_hours": since_hours}


@router.get("", response_model=list[WatchlistOut])
def list_watchlist(db: Session = Depends(get_db)):
    return db.query(WatchlistEntry).order_by(WatchlistEntry.created_at.desc(), WatchlistEntry.id.desc()).all()


@router.post("", response_model=WatchlistOut)
def create_entry(payload: WatchlistCreate, request: Request, db: Session = Depends(get_db),
                 _principal=Depends(require_role("operator"))):
    plate = normalize(payload.plate)
    if not plate:
        raise HTTPException(status_code=422, detail="plate must contain at least one alphanumeric character")
    entry = WatchlistEntry(
        plate=plate,
        label=payload.label,
        category=payload.category,
        priority=payload.priority,
        active=payload.active,
        notes=payload.notes,
    )
    db.add(entry)
    db.flush()
    audit_record(
        db, "watchlist_create", resolve_operator(request), plate=plate,
        entity_id=entry.id, commit=False, label=payload.label,
        category=payload.category, priority=payload.priority,
    )
    db.commit()
    db.refresh(entry)
    return entry


@router.patch("/{entry_id}", response_model=WatchlistOut)
def patch_entry(entry_id: int, payload: WatchlistPatch, request: Request, db: Session = Depends(get_db),
                _principal=Depends(require_role("operator"))):
    entry = db.get(WatchlistEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="watchlist entry not found")
    updates = payload.model_dump(exclude_unset=True)
    if "plate" in updates:
        plate = normalize(updates["plate"])
        if not plate:
            raise HTTPException(status_code=422, detail="plate must contain at least one alphanumeric character")
        updates["plate"] = plate
    for key, value in updates.items():
        setattr(entry, key, value)
    audit_record(
        db, "watchlist_update", resolve_operator(request), plate=entry.plate,
        entity_id=entry.id, commit=False, changed=sorted(updates.keys()),
    )
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/{entry_id}")
def delete_entry(entry_id: int, request: Request, db: Session = Depends(get_db),
                 _principal=Depends(require_role("operator"))):
    entry = db.get(WatchlistEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="watchlist entry not found")
    audit_record(
        db, "watchlist_delete", resolve_operator(request), plate=entry.plate,
        entity_id=entry.id, commit=False, label=entry.label,
    )
    db.delete(entry)
    db.commit()
    return {"deleted": True, "id": entry_id}
