from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..matching import normalize
from ..models import WatchlistEntry
from ..schemas import WatchlistCreate, WatchlistOut, WatchlistPatch

router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("", response_model=list[WatchlistOut])
def list_watchlist(db: Session = Depends(get_db)):
    return db.query(WatchlistEntry).order_by(WatchlistEntry.created_at.desc(), WatchlistEntry.id.desc()).all()


@router.post("", response_model=WatchlistOut)
def create_entry(payload: WatchlistCreate, db: Session = Depends(get_db)):
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
    db.commit()
    db.refresh(entry)
    return entry


@router.patch("/{entry_id}", response_model=WatchlistOut)
def patch_entry(entry_id: int, payload: WatchlistPatch, db: Session = Depends(get_db)):
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
    db.commit()
    db.refresh(entry)
    return entry


@router.delete("/{entry_id}")
def delete_entry(entry_id: int, db: Session = Depends(get_db)):
    entry = db.get(WatchlistEntry, entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="watchlist entry not found")
    db.delete(entry)
    db.commit()
    return {"deleted": True, "id": entry_id}
