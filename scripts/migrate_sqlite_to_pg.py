#!/usr/bin/env python
"""Copy every row from the SQLite dev database into a PostgreSQL database.

The app is DB-agnostic (SQLAlchemy + an env-driven DATABASE_URL), so moving to
Postgres is a data copy plus a config switch — no schema rewrite. This script
copies the real data so you keep your cameras, watchlist, detections and alerts.

Usage (you supply the Postgres URL so your password never leaves your shell):

    # 1. create the database once (prompts for your postgres password):
    /Library/PostgreSQL/17/bin/createdb -h localhost -U postgres sentinel

    # 2. copy the data (SOURCE defaults to ./backend/sentinel.db):
    DATABASE_URL="postgresql+psycopg2://postgres:YOURPASS@localhost:5432/sentinel" \
      .venv/bin/python scripts/migrate_sqlite_to_pg.py

    # 3. run the backend against Postgres (same URL):
    cd backend && DATABASE_URL="postgresql+psycopg2://postgres:YOURPASS@localhost:5432/sentinel" \
      ../.venv/bin/uvicorn app.main:app --port 8000

Re-running is safe only on an empty target — it refuses to copy into tables that
already have rows, so you don't double-load. Drop/recreate the DB to redo.
"""
import os
import sys

# make `import app...` work from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import create_engine, func, insert, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import Base  # noqa: E402
from app.models import Alert, AuditLog, Camera, Detection, WatchlistEntry  # noqa: E402

SOURCE_URL = os.getenv(
    "SOURCE_URL",
    "sqlite:///" + os.path.join(os.path.dirname(__file__), "..", "backend", "sentinel.db"),
)
TARGET_URL = os.getenv("DATABASE_URL", "")

# FK-safe order: parents before children.
ORDER = [Camera, WatchlistEntry, Detection, Alert, AuditLog]


def main() -> int:
    if not TARGET_URL or TARGET_URL.startswith("sqlite"):
        sys.exit("Set DATABASE_URL to your PostgreSQL URL (not sqlite). See the header.")
    if not TARGET_URL.startswith(("postgresql", "postgres")):
        sys.exit(f"DATABASE_URL must be a PostgreSQL URL, got: {TARGET_URL.split('://')[0]}")

    src = create_engine(SOURCE_URL, connect_args={"check_same_thread": False})
    dst = create_engine(TARGET_URL)

    # Create the schema on the target from the same models the app uses.
    Base.metadata.create_all(bind=dst)

    total = 0
    with Session(src) as s, Session(dst) as d:
        for model in ORDER:
            table = model.__table__
            existing = d.scalar(select(func.count()).select_from(table))
            if existing:
                print(f"  {table.name}: target already has {existing} rows — skipped")
                continue
            rows = [dict(r._mapping) for r in s.execute(select(table)).all()]
            if rows:
                d.execute(insert(table), rows)
                d.commit()
            print(f"  {table.name}: copied {len(rows)} rows")
            total += len(rows)

        # Reset each SERIAL/IDENTITY sequence so new inserts don't collide with
        # the ids we copied verbatim.
        for model in ORDER:
            t = model.__table__.name
            d.execute(
                __import__("sqlalchemy").text(
                    f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), "
                    f"COALESCE((SELECT MAX(id) FROM {t}), 1), "
                    f"(SELECT COUNT(*) FROM {t}) > 0)"
                )
            )
        d.commit()

    print(f"done — {total} rows copied into PostgreSQL. Sequences reset.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
