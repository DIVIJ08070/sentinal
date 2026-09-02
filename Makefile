# Sentinel Platform — developer entry points.
# All targets delegate to scripts/ so behaviour is identical with or without make.

VENV := .venv

.PHONY: backend frontend gateway demo seed test anpr-smoke

## Start the FastAPI backend on :8000 (creates .venv and installs deps if needed)
backend:
	./scripts/dev-backend.sh

## Start the Vite dev server on :5173 (npm install on first run)
frontend:
	./scripts/dev-frontend.sh

## Start the mock CCTV gateway on :8890 (stands in for the government host)
gateway:
	$(VENV)/bin/python ingest/mock_gateway.py

## Full scripted demo: gateway -> camera sync -> watchlist seed -> simulated journey
demo:
	./scripts/demo.sh

## Seed the watchlist only (idempotent; cameras come from /api/cameras/sync)
seed:
	cd backend && ../$(VENV)/bin/python -m app.seed

## Backend regression suite: journey/fuzzy/teleport route physics, retro-rejection,
## alert plausibility, dossier hash chain + tamper detection, audit trail
test:
	cd backend && ../$(VENV)/bin/python -m pytest tests -q

## Prove the REAL video/ML path runs CPU-only (no gov sandbox needed):
## CaptureLoop + YOLOv8n + fast-plate-ocr on a synthetic clip, read rate logged.
## Needs the ML extras once: .venv/bin/pip install -r ingest/requirements-ml.txt
anpr-smoke:
	cd ingest && ../$(VENV)/bin/python anpr_smoke.py
