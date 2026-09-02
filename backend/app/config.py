"""Environment-driven configuration (all optional, contract defaults)."""
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./sentinel.db")
SENTINEL_HOST = os.getenv("SENTINEL_HOST", "http://localhost:8890").rstrip("/")

# Catalogue endpoint is always {SENTINEL_HOST}/api/ingest per the contract.
CATALOGUE_URL = f"{SENTINEL_HOST}/api/ingest"
