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
        # One OCR-confusion substitution (2<->Z) away from the demo plate —
        # exercises the fuzzy-match path without ever matching exactly.
        "plate": "GJ01AB1Z34",
        "label": "Fuzzy-bait plate (OCR 2/Z confusion of demo plate)",
        "category": "suspect",
        "priority": "medium",
        "notes": "Demonstrates fuzzy watchlist matching (match_type=fuzzy).",
    },
    {
        "plate": "GJ05CJ4455",
        "label": "Wanted — armed robbery case, Surat",
        "category": "wanted",
        "priority": "high",
        "notes": None,
    },
    {
        "plate": "GJ18AX7788",
        "label": "Blacklisted — repeated toll evasion",
        "category": "blacklisted",
        "priority": "medium",
        "notes": None,
    },
    {
        "plate": "GJ03KL9012",
        "label": "Suspect vehicle — Dwarka checkpoint report",
        "category": "suspect",
        "priority": "low",
        "notes": None,
    },
    {
        "plate": "GJ06RT3456",
        "label": "Stolen two-wheeler — FIR 88/2026, Vadodara",
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
