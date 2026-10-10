#!/usr/bin/env bash
# One-shot switch of SENTINEL from SQLite to PostgreSQL.
#
# It prompts YOU for your Postgres password (never echoed, never stored, never
# seen by anyone but your shell), creates the database if needed, copies all
# your data across, then restarts the backend against Postgres. The ingest
# worker and relay are untouched — they talk to the API, not the DB.
#
#   scripts/switch-to-postgres.sh
#
# Override defaults with env vars: PGUSER (default postgres), PGHOST (localhost),
# PGPORT (5432), PGDB (sentinel), PGBIN (/Library/PostgreSQL/17/bin).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PGBIN="${PGBIN:-/Library/PostgreSQL/17/bin}"
PGUSER="${PGUSER:-postgres}"
PGHOST="${PGHOST:-localhost}"
PGPORT="${PGPORT:-5432}"
PGDB="${PGDB:-sentinel}"
VENV="$ROOT/.venv/bin"

command -v "$PGBIN/psql" >/dev/null || { echo "psql not found at $PGBIN — set PGBIN" >&2; exit 1; }

# --- password: read once, into this process only ---
read -r -s -p "Postgres password for role '$PGUSER': " PGPASSWORD; echo
export PGPASSWORD

echo "→ checking connection..."
"$PGBIN/psql" -w -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d postgres -c "select version();" >/dev/null \
  || { echo "✗ could not connect — wrong password or role?" >&2; exit 1; }
echo "✓ connected"

# --- create the database if it does not exist ---
if "$PGBIN/psql" -w -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d postgres -tAc \
     "select 1 from pg_database where datname='$PGDB'" | grep -q 1; then
  echo "→ database '$PGDB' already exists"
else
  "$PGBIN/createdb" -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" "$PGDB"
  echo "✓ created database '$PGDB'"
fi

URL="postgresql+psycopg2://$PGUSER:$PGPASSWORD@$PGHOST:$PGPORT/$PGDB"

# --- copy the data ---
echo "→ migrating data from SQLite..."
DATABASE_URL="$URL" "$VENV/python" "$ROOT/scripts/migrate_sqlite_to_pg.py"

# --- restart the backend against Postgres ---
echo "→ restarting backend on PostgreSQL..."
pkill -f "uvicorn app.main:app --port 8000" 2>/dev/null || true
sleep 2
cd "$ROOT/backend"
SENTINEL_HOST="${SENTINEL_HOST:-http://localhost:8890}" DATABASE_URL="$URL" \
  nohup "$VENV/uvicorn" app.main:app --port 8000 >/tmp/sentinel-backend-pg.log 2>&1 &
sleep 4
if curl -s -o /dev/null -w "%{http_code}" localhost:8000/api/stats | grep -q 200; then
  echo "✓ backend is live on PostgreSQL (db '$PGDB'). Log: /tmp/sentinel-backend-pg.log"
  echo
  echo "To start the backend on Postgres in future, export this before launching it:"
  echo "  export DATABASE_URL=\"postgresql+psycopg2://$PGUSER:<password>@$PGHOST:$PGPORT/$PGDB\""
  echo "(Your SQLite file backend/sentinel.db is untouched — unset DATABASE_URL to fall back.)"
else
  echo "✗ backend did not come up — check /tmp/sentinel-backend-pg.log" >&2
  exit 1
fi
unset PGPASSWORD
