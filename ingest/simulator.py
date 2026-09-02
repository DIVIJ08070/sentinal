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
import base64
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
# One decoy every run reads GJ01AB1Z39 — its ONLY watchlist match is the
# seeded GJ01AB1Z34 entry (fuzzy, distance 1.0, confidence 0.72), so that
# entry demonstrably fires; it is >1 edit from the demo plate, so it never
# pollutes the target route.
BAIT_TRIGGER_PLATE = "GJ01AB1Z39"
# --inject-teleport: minimum distance of the "impossible" camera from the route.
TELEPORT_MIN_KM = 150.0


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


def plate_snapshot_b64(raw_plate: str, captured_at_iso: str, camera_name: str) -> str | None:
    """Small synthetic plate-crop JPEG (~5-10 KB): dark vehicle rectangle with
    a white Indian-style plate carrying the RAW read, plus a camera/timestamp
    strip — clearly synthetic, but it populates alert cards, route evidence
    cards, and dossier Appendix A exactly like a real ANPR crop would
    (detectors/anpr.py attaches real vehicle crops the same way).

    Returns None if OpenCV/numpy are unavailable (simulator still works).
    """
    try:
        import cv2
        import numpy as np
    except ImportError:
        return None

    width, height = 288, 132
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:] = (34, 30, 26)  # dark vehicle body (BGR)
    # Subtle body shading + a bumper line so it reads as a vehicle rear.
    cv2.rectangle(img, (0, 0), (width, 34), (52, 46, 40), -1)
    cv2.line(img, (0, 96), (width, 96), (20, 18, 16), 3)
    # White plate with a black border, centered.
    px1, py1, px2, py2 = 34, 44, width - 34, 88
    cv2.rectangle(img, (px1, py1), (px2, py2), (235, 238, 240), -1)
    cv2.rectangle(img, (px1, py1), (px2, py2), (10, 10, 10), 2)
    # Raw plate read, fitted to the plate box.
    text = raw_plate.upper()
    scale, thickness = 0.9, 2
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
    if tw > (px2 - px1 - 12):
        scale *= (px2 - px1 - 12) / float(tw)
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
    tx = px1 + ((px2 - px1) - tw) // 2
    ty = py1 + ((py2 - py1) + th) // 2
    cv2.putText(img, text, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, scale, (15, 15, 15), thickness, cv2.LINE_AA)
    # Camera + UTC timestamp strip (like a CCTV overlay), bottom-left.
    stamp = f"{camera_name[:24]}  {captured_at_iso[:19]}Z"
    cv2.putText(img, stamp, (6, height - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (140, 200, 235), 1, cv2.LINE_AA)
    cv2.putText(img, "SIMULATED FEED", (6, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (90, 90, 200), 1, cv2.LINE_AA)

    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 72])
    if not ok:
        return None
    return base64.b64encode(buf.tobytes()).decode("ascii")


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
    def payload_for(camera, plate, captured_at, conf_lo, conf_hi):
        captured_iso = iso_z(captured_at)
        return {
            "camera_id": camera["id"],
            "object_type": "vehicle",
            "plate": plate,
            "plate_confidence": round(rng.uniform(conf_lo, conf_hi), 2),
            "captured_at": captured_iso,
            "snapshot_b64": plate_snapshot_b64(
                plate, captured_iso, camera.get("name") or f"camera {camera['id']}"
            ),
            "detector": "simulator",
        }

    for camera, offset in zip(route, offsets):
        captured_at = start + timedelta(seconds=offset)
        detections.append((payload_for(camera, args.plate, captured_at, 0.78, 0.97), camera, "route"))

    # Decoys: 5-8 non-watchlist plates on cameras off the route.
    decoy_count = rng.randint(5, 8)
    for _ in range(decoy_count):
        camera = rng.choice(decoy_cameras)
        captured_at = start + timedelta(seconds=rng.uniform(0.0, span_s))
        plate = random_decoy_plate(rng, target_norm)
        detections.append((payload_for(camera, plate, captured_at, 0.60, 0.95), camera, "decoy"))

    # Bait trigger: one sighting of GJ01AB1Z39, whose only watchlist match is
    # the seeded fuzzy entry GJ01AB1Z34 — so that entry fires every run.
    bait_camera = rng.choice(decoy_cameras)
    bait_at = start + timedelta(seconds=rng.uniform(0.2, 0.8) * span_s)
    detections.append((payload_for(bait_camera, BAIT_TRIGGER_PLATE, bait_at, 0.70, 0.90), bait_camera, "bait"))

    # Optional physics-filter showcase: one impossible sighting of the TARGET
    # plate on a far-away camera (>= TELEPORT_MIN_KM from the route).
    #   trailing — injected mid-journey between the last two true sightings:
    #              the classic greyed-out rejected hop.
    #   leading  — injected BEFORE the first true sighting: the hostile
    #              variant, proving the retro-rejection guard (the chain
    #              re-anchors on the consistent route instead of letting the
    #              false first sighting poison it).
    teleport_camera = None
    if args.inject_teleport != "none":
        far = [
            c for c in decoy_cameras
            if haversine_km(route[0]["lat"], route[0]["lon"], c["lat"], c["lon"]) >= TELEPORT_MIN_KM
        ]
        if far:
            teleport_camera = max(
                far, key=lambda c: haversine_km(route[0]["lat"], route[0]["lon"], c["lat"], c["lon"])
            )
            if args.inject_teleport == "leading":
                teleport_at = start - timedelta(seconds=45.0)
            else:  # trailing: between the last two true sightings
                teleport_at = start + timedelta(seconds=offsets[-2] + leg_seconds[-1] * 0.5)
            detections.append(
                (payload_for(teleport_camera, args.plate, teleport_at, 0.80, 0.95), teleport_camera, "teleport")
            )
        else:
            print("WARNING: no camera far enough for --inject-teleport; skipping injection.")

    # Post in chronological order, like a live system would have produced.
    detections.sort(key=lambda item: item[0]["captured_at"])
    return detections, journey_s, teleport_camera


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
    parser.add_argument(
        "--inject-teleport",
        choices=["none", "trailing", "leading"],
        default="none",
        help="inject one physically impossible sighting of the target plate on "
        "a far-away camera: 'trailing' (mid-journey — the classic rejected "
        "hop) or 'leading' (BEFORE the first true sighting — exercises the "
        "route engine's retro-rejection guard against first-sighting "
        "poisoning). Default: %(default)s",
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

    detections, journey_s, teleport_camera = build_detections(route, decoy_cameras, args, rng)

    posted = {"route": 0, "decoy": 0, "bait": 0, "teleport": 0}
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
        elif kind == "bait":
            print(
                f"  {payload['captured_at']}  {camera.get('name', 'camera ' + str(camera['id']))}"
                f"  [bait-trigger {payload['plate']} -> fuzzy watchlist entry GJ01AB1Z34]"
            )
        elif kind == "teleport":
            print(
                f"  {payload['captured_at']}  {camera.get('name', 'camera ' + str(camera['id']))}"
                f"  [INJECTED {args.inject_teleport} teleport — expect physics rejection]"
            )
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
    print(
        f"Bait trigger: {posted['bait']} sighting of {BAIT_TRIGGER_PLATE} "
        f"(fires the fuzzy watchlist entry GJ01AB1Z34 at 0.72)."
    )
    if teleport_camera is not None:
        print(
            f"Teleport injection ({args.inject_teleport}): 1 impossible sighting at "
            f"{teleport_camera.get('name')} — the route view must reject exactly this one."
        )
    print("Snapshots: every sighting carries a synthetic plate-crop JPEG (evidence cards + dossier Appendix A).")
    print(f"Alerts raised by the backend: {alerts} (plate must be on the watchlist - run `python -m app.seed` in backend/).")
    if failures:
        print(f"WARNING: {failures} POSTs failed.")
    print()
    print(f"Search this plate in the UI: {args.plate}")
    print(f"Route API: GET {BACKEND_URL}/api/vehicles/{normalize(args.plate)}/route")
    return 0


if __name__ == "__main__":
    sys.exit(main())
