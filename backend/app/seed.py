"""Idempotent watchlist seeding (cameras come from /api/cameras/sync).

Run from backend/:  python -m app.seed
"""
from .db import Base, SessionLocal, engine
from .matching import normalize
from .models import WatchlistEntry

SEED_ENTRIES = [
    {
        "plate": "GJ01AB1234",
        "label": "Stolen vehicle — FIR 123/2026 (demo)",
        "category": "stolen",
        "priority": "high",
        "notes": "Primary demo plate used by the simulator and route reconstruction.",
    },
    {
        # One OCR-confusion substitution (2<->Z) away from the demo plate.
        # The simulator posts one sighting of GJ01AB1Z39 every run — a plate
        # whose only watchlist match is this entry (fuzzy, distance 1.0) — so
        # this entry demonstrably fires in every demo.
        "plate": "GJ01AB1Z34",
        "label": "Suspect vehicle — burglary case, Ahmedabad (demo)",
        "category": "suspect",
        "priority": "medium",
        "notes": "Fires via the simulator's GJ01AB1Z39 sighting (fuzzy match on this entry only).",
    },
    {
        "plate": "GJ05CJ4455",
        "label": "Wanted — armed robbery case, Surat (demo)",
        "category": "wanted",
        "priority": "high",
        "notes": None,
    },
    {
        "plate": "GJ18AX7788",
        "label": "Blacklisted — repeated toll evasion (demo)",
        "category": "blacklisted",
        "priority": "medium",
        "notes": None,
    },
    {
        "plate": "GJ03KL9012",
        "label": "Suspect vehicle — Dwarka checkpoint report (demo)",
        "category": "suspect",
        "priority": "low",
        "notes": None,
    },
    {
        "plate": "GJ06RT3456",
        "label": "Stolen two-wheeler — FIR 88/2026, Vadodara (demo)",
        "category": "stolen",
        "priority": "medium",
        "notes": None,
    },
]


def seed(session) -> tuple[int, int]:
    """Insert missing seed entries; existing plates are left untouched."""
    created = skipped = 0
    for spec in SEED_ENTRIES:
        plate = normalize(spec["plate"])
        exists = session.query(WatchlistEntry).filter(WatchlistEntry.plate == plate).first()
        if exists is not None:
            skipped += 1
            continue
        session.add(WatchlistEntry(
            plate=plate,
            label=spec["label"],
            category=spec["category"],
            priority=spec["priority"],
            active=True,
            notes=spec["notes"],
        ))
        created += 1
    return created, skipped


def main() -> None:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as session:
        created, skipped = seed(session)
        session.commit()
    print(f"watchlist seed: {created} created, {skipped} already present")


if __name__ == "__main__":
    main()
