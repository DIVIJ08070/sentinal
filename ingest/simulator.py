"""Scripted vehicle-journey simulator - end-to-end demo with zero ML/video deps.

Usage:
    python simulator.py [--plate GJ01AB1234] [--minutes 3] [--seed 7]

Replays a plausible journey for one plate through the backend REST API only
(no video, no ML):

    1. Fetch cameras from the backend (triggering /api/cameras/sync first if
       the backend knows none).
    2. Pick ~8 cameras inside one city cluster and order them by longitude -
       a geographically plausible west-to-east route.
    3. POST detections for the target plate with captured_at spread over the
       last --minutes, ending now. Watchlist matches raise live alerts.
    4. POST 5-8 decoy detections with random-looking non-watchlist plates on
       other cameras, so search results have realistic noise.

Deterministic camera/plate/ordering choices for a given --seed
(random.Random(seed)); only the wall-clock window is time-dependent.
Afterwards, search the printed plate in the UI or call
GET /api/vehicles/{plate}/route.
"""

import argparse
import math
import os
import random
import sys
from datetime import datetime, timedelta, timezone

import httpx

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

DEFAULT_PLATE = "GJ01AB1234"
DEFAULT_MINUTES = 3.0
DEFAULT_SEED = 7
ROUTE_LENGTH = 8
# ~0.15 deg (~15 km) box: big enough to span one city, small enough to never
# merge two Gujarat cities into one "route".
CLUSTER_RADIUS_DEG = 0.15
# Real Indian series skip I/O/Q in the letter block.
PLATE_LETTERS = "ABCDEFGHJKLMNPRSTUVWXYZ"
# Journey timestamps are spaced so per-leg implied speeds land in this urban
# band - the backend physics filter (>180 km/h) must never reject the scripted
# route, only genuinely impossible hops (see docs/CONTRACT_ADDENDUM.md).
SPEED_BAND_KMH = (35.0, 60.0)
MIN_LEG_SECONDS = 20.0
_EARTH_RADIUS_KM = 6371.0088


def iso_z(dt: datetime) -> str:
    """UTC ISO8601 with trailing Z (contract: all timestamps are UTC + Z)."""
    return (
        dt.astimezone(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def normalize(plate: str) -> str:
    """Mirror of the backend's canonical rule: uppercase, A-Z0-9 only."""
    return "".join(ch for ch in plate.upper() if ch.isalnum())


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb))
            )
        previous = current
    return previous[-1]


def fetch_cameras(client: httpx.Client) -> list:
    """All backend cameras with usable coordinates (sync first if empty)."""
    resp = client.get("/api/cameras")
    resp.raise_for_status()
    cameras = resp.json()
    if not cameras:
        print("Backend has no cameras yet - requesting /api/cameras/sync ...")
        try:
            sync = client.post("/api/cameras/sync")
            sync.raise_for_status()
            print(f"  sync result: {sync.json()}")
        except Exception as exc:
            print(f"  sync failed: {exc}")
        resp = client.get("/api/cameras")
        resp.raise_for_status()
        cameras = resp.json()

    with_coords = [
        c for c in cameras if c.get("lat") is not None and c.get("lon") is not None
    ]
    # Prefer live cameras for realism; fall back to any with coordinates.
    live = [c for c in with_coords if c.get("status") == "live"]
    chosen = live if len(live) >= 3 else with_coords
    # Deterministic base ordering before any seeded sampling.
    chosen.sort(key=lambda c: c.get("id") or 0)
    return chosen


def pick_route(cameras: list, rng: random.Random) -> list:
    """~8 cameras from the densest city cluster, ordered by longitude."""
    best_cluster = []
    for anchor in cameras:
        cluster = [
            c
            for c in cameras
            if abs(c["lat"] - anchor["lat"]) <= CLUSTER_RADIUS_DEG
            and abs(c["lon"] - anchor["lon"]) <= CLUSTER_RADIUS_DEG
        ]
        if len(cluster) > len(best_cluster):
            best_cluster = cluster

    if len(best_cluster) > ROUTE_LENGTH:
        route = rng.sample(best_cluster, ROUTE_LENGTH)
    else:
        route = list(best_cluster)
    # Geographically plausible ordering: sweep the city cluster by longitude.
    route.sort(key=lambda c: (c["lon"], c["lat"]))
    return route


def random_decoy_plate(rng: random.Random, target_norm: str) -> str:
    """Random-looking plate guaranteed not to (even fuzzily) match target."""
    while True:
        plate = "GJ{:02d}{}{}{:04d}".format(
            rng.randint(1, 38),
            rng.choice(PLATE_LETTERS),
            rng.choice(PLATE_LETTERS),
            rng.randint(1, 9999),
        )
        # Backend fuzzy matching fires at edit distance 1 (incl. OCR-confusion
        # substitutions); distance >= 2 keeps decoys out of the target's route.
        if levenshtein(normalize(plate), target_norm) >= 2:
            return plate


def build_detections(route, decoy_cameras, args, rng: random.Random):
    """(payload, camera, kind, journey_s) - the journey plus its decoys.

    Timestamps are PHYSICALLY PLAUSIBLE: per-leg travel time comes from the
    haversine leg distance at an urban speed (35-60 km/h), so the backend's
    physics filter accepts every scripted sighting. --minutes acts as a floor:
    when the chosen cameras are too far apart to cover in that window at
    plausible speeds, the journey is stretched (slower never violates
    physics; faster would). The journey always ends now.
    """
    end = datetime.now(timezone.utc)
    target_norm = normalize(args.plate)

    # Per-leg seconds from real geometry at a plausible urban speed.
    leg_seconds = []
    for prev, cur in zip(route, route[1:]):
        leg_km = haversine_km(prev["lat"], prev["lon"], cur["lat"], cur["lon"])
        speed_kmh = rng.uniform(*SPEED_BAND_KMH)
        leg_seconds.append(max(leg_km / speed_kmh * 3600.0, MIN_LEG_SECONDS))
    journey_s = sum(leg_seconds)

    floor_s = args.minutes * 60.0
    if journey_s < floor_s:
        # Stretch to honour --minutes (uniformly slower = still plausible).
        scale = floor_s / journey_s if journey_s > 0 else 1.0
        leg_seconds = [leg * scale for leg in leg_seconds]
        journey_s = max(floor_s, sum(leg_seconds))

    start = end - timedelta(seconds=journey_s)
    span_s = journey_s

    detections = []

    # The scripted journey: cumulative leg offsets, ending now.
    offsets = [0.0]
    for leg in leg_seconds:
        offsets.append(offsets[-1] + leg)
    for camera, offset in zip(route, offsets):
        captured_at = start + timedelta(seconds=offset)
        detections.append(
            (
                {
                    "camera_id": camera["id"],
                    "object_type": "vehicle",
                    "plate": args.plate,
                    "plate_confidence": round(rng.uniform(0.78, 0.97), 2),
                    "captured_at": iso_z(captured_at),
                    "detector": "simulator",
                },
                camera,
                "route",
            )
        )

    # Decoys: 5-8 non-watchlist plates on cameras off the route.
    decoy_count = rng.randint(5, 8)
    for _ in range(decoy_count):
        camera = rng.choice(decoy_cameras)
        captured_at = start + timedelta(seconds=rng.uniform(0.0, span_s))
        detections.append(
            (
                {
                    "camera_id": camera["id"],
                    "object_type": "vehicle",
                    "plate": random_decoy_plate(rng, target_norm),
                    "plate_confidence": round(rng.uniform(0.60, 0.95), 2),
                    "captured_at": iso_z(captured_at),
                    "detector": "simulator",
                },
                camera,
                "decoy",
            )
        )

    # Post in chronological order, like a live system would have produced.
    detections.sort(key=lambda item: item[0]["captured_at"])
    return detections, journey_s


def post_heartbeats(client: httpx.Client, cameras: list, rng: random.Random) -> int:
    """POST plausible health metrics for every live camera so the camera-health
    board is populated in the no-video demo (docs/CONTRACT_ADDENDUM.md:
    extended heartbeat body)."""
    posted = 0
    for camera in cameras:
        if camera.get("status") != "live":
            continue
        width = camera.get("width") or 1280
        height = camera.get("height") or 720
        codec = (camera.get("codec") or "h264").lower()
        fps = round(rng.uniform(8.0, 25.0), 2)
        bits_per_pixel = 0.055 if codec in ("h265", "hevc") else 0.10
        payload = {
            "status": "live",
            "fps_measured": fps,
            "last_frame_age_s": round(rng.uniform(0.04, 1.2), 2),
            "reconnects": rng.choice([0, 0, 0, 0, 0, 0, 0, 0, 1, 2]),
            "bandwidth_kbps": round(width * height * fps * bits_per_pixel / 1000.0, 1),
        }
        try:
            resp = client.post(f"/api/cameras/{camera['id']}/heartbeat", json=payload)
            resp.raise_for_status()
            posted += 1
        except Exception as exc:
            print(f"  heartbeat failed for camera {camera.get('id')}: {exc}")
    return posted


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Replay a scripted vehicle journey through the backend REST "
        "API (no video/ML needed) for the end-to-end alert + route demo.",
    )
    parser.add_argument("--plate", default=DEFAULT_PLATE, help="target registration number")
    parser.add_argument(
        "--minutes",
        type=float,
        default=DEFAULT_MINUTES,
        help="minimum journey duration; the journey ends now and is stretched "
        "beyond N minutes when the cameras are too far apart to cover at "
        "plausible urban speeds (the backend physics filter would otherwise "
        "reject the legs)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="deterministic seed for camera/plate choices (default %(default)s)",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    rng = random.Random(args.seed)
    client = httpx.Client(base_url=BACKEND_URL, timeout=httpx.Timeout(10.0, connect=5.0))

    try:
        cameras = fetch_cameras(client)
    except Exception as exc:
        print(f"ERROR: cannot reach backend at {BACKEND_URL}: {exc}")
        client.close()
        return 1
    if len(cameras) < 2:
        print(
            "ERROR: need at least 2 cameras with coordinates. Start "
            "mock_gateway.py, then POST /api/cameras/sync (or rerun this script)."
        )
        client.close()
        return 1

    route = pick_route(cameras, rng)
    if len(route) < 2:
        print("ERROR: could not form a route (no city cluster with >= 2 cameras).")
        client.close()
        return 1

    route_ids = {c["id"] for c in route}
    decoy_cameras = [c for c in cameras if c["id"] not in route_ids] or cameras

    detections, journey_s = build_detections(route, decoy_cameras, args, rng)

    posted = {"route": 0, "decoy": 0}
    alerts = 0
    failures = 0
    decoy_plates = []
    for payload, camera, kind in detections:
        try:
            resp = client.post("/api/detections", json=payload)
            resp.raise_for_status()
            body = resp.json()
        except Exception as exc:
            failures += 1
            print(f"  POST failed for camera {camera['id']}: {exc}")
            continue
        posted[kind] += 1
        if body.get("alert_id"):
            alerts += 1
        if kind == "decoy":
            decoy_plates.append(payload["plate"])
        else:
            print(
                f"  {payload['captured_at']}  {camera.get('name', 'camera ' + str(camera['id']))}"
                f"  (conf {payload['plate_confidence']:.2f})"
            )
    heartbeats = post_heartbeats(client, cameras, rng)
    client.close()

    if posted["route"] == 0:
        print("ERROR: no route detections were accepted by the backend.")
        return 1

    print()
    print(
        f"Simulated journey for {args.plate}: {posted['route']} sightings across "
        f"{len(route)} cameras over the last {journey_s / 60.0:.1f} min "
        f"(physically plausible spacing; --minutes {args.minutes:g} is a floor; seed={args.seed})."
    )
    print(
        f"Health board: posted heartbeat metrics (fps/frame-age/reconnects/Kbps) "
        f"for {heartbeats} live cameras."
    )
    print(
        f"Decoys: {posted['decoy']} detections on other cameras "
        f"(plates: {', '.join(decoy_plates) if decoy_plates else 'none'})."
    )
    print(f"Alerts raised by the backend: {alerts} (plate must be on the watchlist - run `python -m app.seed` in backend/).")
    if failures:
        print(f"WARNING: {failures} POSTs failed.")
    print()
    print(f"Search this plate in the UI: {args.plate}")
    print(f"Route API: GET {BACKEND_URL}/api/vehicles/{normalize(args.plate)}/route")
    return 0


if __name__ == "__main__":
    sys.exit(main())
