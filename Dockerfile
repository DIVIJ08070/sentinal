# Base image for the backend API, the catalogue adapter and the HLS relay.
# All three run the same Python code + ffmpeg; docker-compose overrides the
# command per service. The ANPR worker has its own heavier image (ML deps):
# see Dockerfile.worker.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# ffmpeg: HLS relay + stream probing. libglib2.0-0: opencv-python-headless.
# curl: container healthchecks.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libglib2.0-0 curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first for layer caching. psycopg2-binary adds the Postgres driver.
COPY backend/requirements.txt backend/requirements.txt
COPY ingest/requirements.txt ingest/requirements.txt
RUN pip install -r backend/requirements.txt -r ingest/requirements.txt "psycopg2-binary>=2.9,<3.0"

COPY backend/ backend/
COPY ingest/ ingest/

EXPOSE 8000
# Default command = the backend API. Adapter/relay override `command:` in compose.
CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
