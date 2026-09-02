from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from ..audit import record as audit_record, resolve_operator
from ..db import get_db
from ..matching import normalize
from ..models import WatchlistEntry
from ..schemas import WatchlistCreate, WatchlistOut, WatchlistPatch

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("", response_model=list[WatchlistOut])
def list_watchlist(db: Session = Depends(get_db)):
    return db.query(WatchlistEntry).order_by(WatchlistEntry.created_at.desc(), WatchlistEntry.id.desc()).all()


@router.post("", response_model=WatchlistOut)
def create_entry(payload: WatchlistCreate, request: Request, db: Session = Depends(get_db)):
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
def patch_entry(entry_id: int, payload: WatchlistPatch, request: Request, db: Session = Depends(get_db)):
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
def delete_entry(entry_id: int, request: Request, db: Session = Depends(get_db)):
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
