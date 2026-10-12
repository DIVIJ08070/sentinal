from datetime import timedelta
import csv
import io
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy.orm import Session

from ..audit import record as audit_record, resolve_operator
from ..auth import require_role
from ..db import get_db
from ..matching import canonicalize, find_watchlist_match, normalize
from ..models import Alert, Camera, Detection, WatchlistEntry, utcnow
from ..schemas import (
    WatchlistBulkImportIn,
    WatchlistBulkImportItem,
    WatchlistCreate,
    WatchlistOut,
    WatchlistPatch,
    alert_to_dict,
)
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
    existing = db.query(WatchlistEntry).filter(WatchlistEntry.plate == plate).first()
    if existing:
        status_str = "Active" if existing.active else "Inactive"
        raise HTTPException(
            status_code=409,
            detail=f"Plate '{plate}' is already on the watchlist ({status_str}, ID #{existing.id})"
        )
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


def _parse_raw_text(
    raw_text: str,
    default_label: str = "Bulk imported",
    default_category: str = "stolen",
    default_priority: str = "high",
    default_active: bool = True,
) -> list[WatchlistBulkImportItem]:
    items: list[WatchlistBulkImportItem] = []
    lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
    if not lines:
        return items

    if "," in lines[0] or "\t" in lines[0]:
        delimiter = "\t" if "\t" in lines[0] else ","
        reader = csv.reader(lines, delimiter=delimiter)
        rows = list(reader)
        first_row = [c.strip().lower() for c in rows[0]]
        header_cols = None
        start_idx = 0
        if any(h in first_row for h in ("plate", "registration", "number_plate", "vehicle_no", "reg_no")):
            header_cols = first_row
            start_idx = 1

        for row in rows[start_idx:]:
            if not row or not any(row):
                continue
            if header_cols:
                row_dict = {header_cols[i]: row[i].strip() for i in range(min(len(header_cols), len(row)))}
                plate = (
                    row_dict.get("plate")
                    or row_dict.get("registration")
                    or row_dict.get("number_plate")
                    or row_dict.get("vehicle_no")
                    or row_dict.get("reg_no")
                    or ""
                )
                label = row_dict.get("label") or row_dict.get("reason") or default_label
                category = row_dict.get("category") or default_category
                priority = row_dict.get("priority") or default_priority
                active_str = row_dict.get("active")
                active = default_active if not active_str else active_str.lower() not in ("false", "0", "no")
                notes = row_dict.get("notes") or None
            else:
                plate = row[0].strip()
                label = row[1].strip() if len(row) > 1 and row[1].strip() else default_label
                category = row[2].strip() if len(row) > 2 and row[2].strip() else default_category
                priority = row[3].strip() if len(row) > 3 and row[3].strip() else default_priority
                active = (row[4].strip().lower() not in ("false", "0", "no")) if len(row) > 4 else default_active
                notes = row[5].strip() if len(row) > 5 and row[5].strip() else None

            if plate:
                items.append(WatchlistBulkImportItem(
                    plate=plate, label=label, category=category, priority=priority, active=active, notes=notes
                ))
    else:
        for line in lines:
            parts = [p.strip() for p in re.split(r'[,;\s]+', line) if p.strip()]
            for p in parts:
                items.append(WatchlistBulkImportItem(
                    plate=p, label=default_label, category=default_category, priority=default_priority, active=default_active
                ))
    return items


@router.get("/export")
def export_watchlist(
    format: str = Query("csv", pattern="^(csv|json|txt)$"),
    active_only: bool = Query(False),
    db: Session = Depends(get_db),
):
    query = db.query(WatchlistEntry).order_by(WatchlistEntry.created_at.desc(), WatchlistEntry.id.desc())
    if active_only:
        query = query.filter(WatchlistEntry.active.is_(True))
    entries = query.all()

    if format == "txt":
        content = "\n".join(e.plate for e in entries) + ("\n" if entries else "")
        return Response(
            content=content,
            media_type="text/plain; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="watchlist_plates.txt"'},
        )
    elif format == "json":
        data = [WatchlistOut.model_validate(e).model_dump(mode="json") for e in entries]
        return Response(
            content=json.dumps(data, indent=2),
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="watchlist_export.json"'},
        )
    else:  # csv
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["plate", "label", "category", "priority", "active", "notes", "created_at"])
        for e in entries:
            writer.writerow([
                e.plate,
                e.label or "",
                e.category or "other",
                e.priority or "medium",
                "true" if e.active else "false",
                e.notes or "",
                e.created_at.isoformat() if e.created_at else "",
            ])
        return Response(
            content=buf.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="watchlist_export.csv"'},
        )


@router.post("/import")
async def import_watchlist(
    payload: WatchlistBulkImportIn,
    request: Request,
    db: Session = Depends(get_db),
    _principal=Depends(require_role("operator")),
):
    raw_items = list(payload.items)
    if payload.raw_text:
        parsed = _parse_raw_text(
            payload.raw_text,
            default_label=payload.default_label or "Bulk imported",
            default_category=payload.default_category or "stolen",
            default_priority=payload.default_priority or "high",
            default_active=True if payload.default_active is None else payload.default_active,
        )
        raw_items.extend(parsed)

    if not raw_items:
        raise HTTPException(status_code=422, detail="No plates provided in import request")

    existing_rows = db.query(WatchlistEntry.plate).all()
    existing_plates = {p for (p,) in existing_rows}

    created: list[WatchlistEntry] = []
    duplicates: list[str] = []
    invalid: list[str] = []
    seen_in_batch: set[str] = set()

    for item in raw_items:
        clean = normalize(item.plate)
        if not clean:
            invalid.append(item.plate)
            continue
        if clean in existing_plates or clean in seen_in_batch:
            duplicates.append(clean)
            if payload.skip_duplicates:
                continue
            else:
                raise HTTPException(status_code=409, detail=f"Duplicate plate '{clean}' found during import")

        cat = item.category if item.category in ("stolen", "wanted", "suspect", "blacklisted", "other") else "other"
        pri = item.priority if item.priority in ("high", "medium", "low") else "medium"
        entry = WatchlistEntry(
            plate=clean,
            label=item.label or payload.default_label or "Bulk imported",
            category=cat,
            priority=pri,
            active=item.active if item.active is not None else (payload.default_active if payload.default_active is not None else True),
            notes=item.notes,
        )
        db.add(entry)
        created.append(entry)
        seen_in_batch.add(clean)

    db.flush()
    audit_record(
        db, "watchlist_import", resolve_operator(request), commit=False,
        imported=len(created), skipped=len(duplicates), invalid=len(invalid),
    )
    db.commit()

    for e in created:
        db.refresh(e)

    rescan_result = None
    if payload.rescan and created:
        rescan_result = await rescan_recent_sightings(request=request, since_hours=24.0, db=db, _principal=_principal)

    return {
        "imported": len(created),
        "skipped": len(duplicates),
        "invalid": len(invalid),
        "duplicates": duplicates,
        "plates_imported": [e.plate for e in created],
        "rescan": rescan_result,
    }


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
        existing = db.query(WatchlistEntry).filter(WatchlistEntry.plate == plate, WatchlistEntry.id != entry_id).first()
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Plate '{plate}' is already on the watchlist (ID #{existing.id})"
            )
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
