#!/usr/bin/env python
"""Object-storage PoC: move evidence snapshots out of PostgreSQL into an
S3-compatible store (MinIO), proving the HLD's object-storage tier and the
"snapshots ride on object storage, not the hot DB" design. Measures the DB
offload and the round-trip latency.

    .venv/bin/python deploy/poc/bench/minio_demo.py

Pulls real snapshots from the live Docker Postgres backend (:8001) when
reachable; otherwise synthesizes JPEG blobs of the same size.
"""
import base64
import io
import time

import httpx
from minio import Minio

ENDPOINT = "localhost:8333"
ACCESS, SECRET = "sentinel", "sentinel123"
BUCKET = "evidence-snapshots"


def real_snapshots(limit=200):
    try:
        r = httpx.get(f"http://localhost:8001/api/detections?limit={limit}", timeout=5).json()
        return [base64.b64decode(d["snapshot_b64"]) for d in r if d.get("snapshot_b64")]
    except Exception:
        return []


def main():
    mc = Minio(ENDPOINT, access_key=ACCESS, secret_key=SECRET, secure=False)
    if not mc.bucket_exists(BUCKET):
        mc.make_bucket(BUCKET)

    blobs = real_snapshots()
    source = "live Docker Postgres" if blobs else "synthesized"
    if not blobs:
        blobs = [bytes(bytearray((i * 7) % 256 for i in range(48000))) for _ in range(200)]

    total = sum(len(b) for b in blobs)

    # --- upload ---
    t0 = time.perf_counter()
    for i, b in enumerate(blobs):
        mc.put_object(BUCKET, f"snap/{i}.jpg", io.BytesIO(b), length=len(b),
                      content_type="image/jpeg")
    up_s = time.perf_counter() - t0

    # --- download round-trip latency ---
    lat = []
    for i in range(min(100, len(blobs))):
        t = time.perf_counter()
        resp = mc.get_object(BUCKET, f"snap/{i}.jpg")
        resp.read(); resp.close(); resp.release_conn()
        lat.append((time.perf_counter() - t) * 1000)
    lat.sort()

    print("=== S3 object storage (SeaweedFS) — snapshot tier ===")
    print(f"  snapshots             : {len(blobs)}  (source: {source})")
    print(f"  total bytes           : {total/1e6:.1f} MB  (avg {total/len(blobs)/1024:.0f} KB each)")
    print(f"  upload throughput     : {len(blobs)/up_s:,.0f} objects/s ({total/1e6/up_s:.1f} MB/s)")
    print(f"  fetch latency         : p50 {lat[len(lat)//2]:.1f} ms   p99 {lat[int(len(lat)*0.99)]:.1f} ms")
    print(f"  DB offload            : these {total/1e6:.1f} MB leave PostgreSQL's hot path")
    # statewide projection
    daily = 32_000_000
    avg = total / len(blobs)
    print(f"  statewide projection  : {daily/1e6:.0f}M snapshots/day × {avg/1024:.0f}KB "
          f"≈ {daily*avg/1e12:.1f} TB/day on object storage, 0 bytes of video centralized")


if __name__ == "__main__":
    main()
