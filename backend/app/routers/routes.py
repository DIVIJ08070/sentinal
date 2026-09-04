"""Route reconstruction — the hackathon test case.

Extends the base contract (docs/CONTRACT_ADDENDUM.md) with:
- confusion-tolerant matching: every point carries match_confidence (0-1,
  exact = 1.0) and matched_from (the raw OCR read);
- the physics plausibility filter: consecutive-sighting legs get leg_km
  (haversine) and implied_speed_kmh; a hop implying an impossible speed marks
  the LATER sighting rejected=true with a plain-language rejected_reason.
  Rejected points are still returned (the UI greys them) but are excluded
  from the accepted polyline geojson, distance_km, and stats — and the leg
  chain is recomputed skipping rejected points.
"""
import math
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..audit import record as audit_record, resolve_operator
from ..db import get_db
from ..matching import normalize, score_match
from ..models import Camera, Detection
from ..schemas import as_naive_utc, iso_z
from ..sources import visible_detection  # noqa: F401 (kept for parity; route sees all)

router = APIRouter(tags=["routes"])

_EARTH_RADIUS_KM = 6371.0088

# Physics plausibility thresholds (tuned for Indian road reality: 180 km/h is
# already beyond any sustained legal/practical speed; short gaps get extra
# slack because timestamp jitter dominates small denominators).
MAX_SPEED_KMH = 180.0
MAX_SPEED_SHORT_GAP_KMH = 250.0
SHORT_GAP_S = 60.0
# Two reads within ~50 m (same junction / same camera cluster) are never a
# physics violation regardless of timing.
SAME_LOCATION_KM = 0.05
_MIN_DT_S = 0.1  # divide-by-zero guard for identical timestamps


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * _EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial great-circle bearing from point 1 to point 2, degrees 0-360
    (0 = due north, 90 = due east)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def bearing_delta_deg(a: float, b: float) -> float:
    """Smallest absolute angle between two bearings (0-180 degrees)."""
    d = abs(a - b) % 360.0
    return d if d <= 180.0 else 360.0 - d


# Retro-rejection (first-sighting poisoning guard): when the CHAIN-START
# anchor causes this many consecutive, mutually consistent rejections, the
# anchor itself is the outlier — reject it and re-anchor on the chain.
RETRO_MIN_CONSISTENT = 2


def _leg(points: list[dict], captured: list[datetime], a: int, b: int) -> tuple[float, float, float]:
    """(leg_km, dt_s, implied_kmh) from point a to point b (both have coords)."""
    leg_km = haversine_km(points[a]["lat"], points[a]["lon"], points[b]["lat"], points[b]["lon"])
    dt_s = (captured[b] - captured[a]).total_seconds()
    implied_kmh = (leg_km / max(dt_s, _MIN_DT_S)) * 3600.0
    return leg_km, dt_s, implied_kmh


def _plausible(leg_km: float, dt_s: float, implied_kmh: float) -> bool:
    threshold = MAX_SPEED_SHORT_GAP_KMH if dt_s < SHORT_GAP_S else MAX_SPEED_KMH
    return leg_km <= SAME_LOCATION_KM or implied_kmh <= threshold


def _annotate(point: dict, leg_km: float, implied_kmh: float) -> None:
    point["leg_km"] = round(leg_km, 3)
    point["implied_speed_kmh"] = round(implied_kmh, 1)


def _apply_physics_filter(points: list[dict], captured: list[datetime]) -> None:
    """Annotate points in place with leg_km / implied_speed_kmh / rejected.

    The leg chain always runs between consecutive ACCEPTED points with
    coordinates — rejecting a point leaves the anchor on the previous accepted
    sighting, so one false ANPR match cannot poison the legs around it.
    Points without coordinates cannot be physics-checked: they stay accepted
    (with null legs) and do not advance the anchor.

    First-sighting poisoning guard (retro-rejection): a false match that is
    chronologically FIRST would otherwise anchor the chain and reject every
    true sighting after it. So when the chain-start anchor (a point with no
    accepted predecessor) has produced RETRO_MIN_CONSISTENT consecutive
    rejections that are mutually consistent at plausible speeds among
    themselves, the anchor — not the chain — is the outlier: it is rejected
    retroactively, the chain points are re-accepted with their legs recomputed
    among themselves, and the chain re-anchors on them. Anchors that already
    have an accepted predecessor earned their place by passing physics and are
    never retro-rejected (a lone trailing teleport keeps its behaviour).
    """
    anchor: int | None = None
    anchor_has_predecessor = False
    rejected_run: list[int] = []  # consecutive rejections against the current anchor

    for i, point in enumerate(points):
        if point["lat"] is None or point["lon"] is None:
            continue
        if anchor is None:
            anchor = i  # first accepted point with coordinates: no leg
            anchor_has_predecessor = False
            rejected_run = []
            continue

        leg_km, dt_s, implied_kmh = _leg(points, captured, anchor, i)
        _annotate(point, leg_km, implied_kmh)
        if _plausible(leg_km, dt_s, implied_kmh):
            anchor = i
            anchor_has_predecessor = True
            rejected_run = []
            continue

        point["rejected"] = True
        point["rejected_reason"] = (
            f"implied speed {implied_kmh:.0f} km/h over {leg_km:.1f} km "
            f"in {dt_s:.0f}s — physically impossible, discarded as false ANPR match"
        )
        rejected_run.append(i)

        # Retro-rejection check: only a chain-start anchor can be the outlier.
        if anchor_has_predecessor or len(rejected_run) < RETRO_MIN_CONSISTENT:
            continue  # anchor stays on the previous accepted sighting
        if not _run_is_consistent(points, captured, rejected_run):
            continue

        # The rejected run is a mutually consistent journey — the lone anchor
        # is the false match. Flip the verdicts.
        bad = points[anchor]
        first, *rest = rejected_run
        first_leg, _, first_kmh = _leg(points, captured, anchor, first)
        bad["rejected"] = True
        bad["rejected_reason"] = (
            f"{len(rejected_run)} subsequent sightings form a mutually consistent "
            f"route at plausible speeds, but reaching them from here would imply "
            f"{first_kmh:.0f} km/h over {first_leg:.1f} km — this first sighting is "
            f"the outlier, discarded as false ANPR match"
        )
        points[first]["rejected"] = False
        points[first]["rejected_reason"] = None
        points[first]["leg_km"] = None  # new chain start: no leg
        points[first]["implied_speed_kmh"] = None
        prev = first
        for j in rest:
            points[j]["rejected"] = False
            points[j]["rejected_reason"] = None
            leg_km, _, implied_kmh = _leg(points, captured, prev, j)
            _annotate(points[j], leg_km, implied_kmh)
            prev = j
        anchor = rejected_run[-1]
        anchor_has_predecessor = True
        rejected_run = []


def _run_is_consistent(points: list[dict], captured: list[datetime], run: list[int]) -> bool:
    """True when every consecutive hop within the rejected run is itself
    physically plausible — i.e. the run reads as one coherent journey."""
    for a, b in zip(run, run[1:]):
        if not _plausible(*_leg(points, captured, a, b)):
            return False
    return True


def build_route_payload(
    db: Session,
    plate: str,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict:
    """Full route payload for a plate — shared by the route endpoint and the
    evidence dossier so both always agree on matching + physics decisions."""
    target = normalize(plate)

    # Candidate blocking: the fuzzy threshold (weighted distance <= 1.0) allows
    # at most one insertion/deletion, so any match is within +/-1 character of
    # the target's length (canonicalization never changes length). This SQL
    # pre-filter bounds the Python-side scoring loop; at production scale the
    # same idea extends to an indexed canonical-plate column + confusion-twin
    # candidate generation (HLD §6, "Matching at scale").
    # Route reconstruction is an investigator's tool: unlike the live ALERTS
    # feed and stats (which hide simulator/mock rows to stay genuine), a route
    # search must see EVERY stored sighting of the plate — including the
    # simulator's representative cross-camera journeys used to demonstrate the
    # engine. So no visible_detection() filter here.
    query = (
        db.query(Detection, Camera)
        .join(Camera, Detection.camera_id == Camera.id)
        .filter(Detection.plate.isnot(None))
        .filter(func.length(Detection.plate).between(len(target) - 1, len(target) + 1))
    )
    if since is not None:
        query = query.filter(Detection.captured_at >= as_naive_utc(since))
    if until is not None:
        query = query.filter(Detection.captured_at <= as_naive_utc(until))
    rows = query.order_by(Detection.captured_at.asc(), Detection.id.asc()).all()

    points: list[dict] = []
    captured: list[datetime] = []
    for detection, camera in rows:
        score = score_match(detection.plate, target)
        if score is None:
            continue
        points.append({
            "camera_id": camera.id,
            "camera_name": camera.name,
            "department": camera.department,
            "lat": camera.lat,
            "lon": camera.lon,
            "captured_at": iso_z(detection.captured_at),
            "pts_ms": detection.pts_ms,
            "confidence": detection.plate_confidence,
            "vehicle_type": detection.vehicle_type,
            "snapshot_b64": detection.snapshot_b64,
            "fuzzy": score.match_type == "fuzzy",
            "match_confidence": score.confidence,
            "matched_from": detection.plate_raw or detection.plate,
            "leg_km": None,
            "implied_speed_kmh": None,
            "rejected": False,
            "rejected_reason": None,
        })
        captured.append(detection.captured_at)

    _apply_physics_filter(points, captured)

    accepted = [p for p in points if not p["rejected"]]
    # LineString + distance + stats use only ACCEPTED points (with coordinates
    # for the geometry); rejected points remain visible in `points`.
    coordinates = [
        [p["lon"], p["lat"]] for p in accepted
        if p["lat"] is not None and p["lon"] is not None
    ]
    distance_km = sum(p["leg_km"] for p in accepted if p["leg_km"] is not None)

    return {
        "plate": target,
        "points": points,
        "geojson": {"type": "LineString", "coordinates": coordinates},
        "stats": {
            "first_seen": accepted[0]["captured_at"] if accepted else None,
            "last_seen": accepted[-1]["captured_at"] if accepted else None,
            "cameras_count": len({p["camera_id"] for p in accepted}),
            "sightings_count": len(accepted),
            "rejected_count": len(points) - len(accepted),
            "distance_km": round(distance_km, 3),
        },
    }


# Intercept-prediction heuristics (pure geometry — labeled heuristic, no ML).
PREDICT_MAX_BEARING_DELTA_DEG = 60.0  # a camera must lie within this of heading
PREDICT_MIN_SPEED_KMH = 3.0           # below this the vehicle is "stationary"
PREDICT_RECENT_LEGS = 3               # legs used for the mean-speed estimate
PREDICT_SOON_SECONDS = 1800.0         # "reachable soon" horizon for confidence
PREDICT_TOP_N = 3


def _parse_iso_z(s: str) -> datetime:
    """Parse an iso_z timestamp ('...Z') back to a naive-UTC datetime."""
    return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)


def build_intercept_prediction(
    db: Session,
    plate: str,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict:
    """Predict where a vehicle is heading next from its accepted sightings.

    Pure geometry (haversine + bearings), no new deps and no ML: from the last
    accepted sightings compute the current heading and mean speed, then rank
    OTHER cameras that lie ahead (bearing within PREDICT_MAX_BEARING_DELTA_DEG
    of the heading) by how well they line up and how soon they are reachable.
    ETA is a heuristic (distance / recent mean speed, straight-line), not a
    routed drive time. Returns {predictions:[...], reason:str|None, heading_deg,
    mean_speed_kmh, from_camera_id}.
    """
    payload = build_route_payload(db, plate, since, until)
    target = payload["plate"]
    accepted = [
        p for p in payload["points"]
        if not p["rejected"] and p["lat"] is not None and p["lon"] is not None
    ]
    if len(accepted) < 2:
        return {
            "plate": target,
            "predictions": [],
            "reason": "need at least 2 accepted sightings with coordinates to "
                      "establish a heading",
        }

    # Mean speed over the most recent legs; heading from the final leg.
    recent = accepted[-(PREDICT_RECENT_LEGS + 1):]
    total_km = 0.0
    total_s = 0.0
    for a, b in zip(recent, recent[1:]):
        total_km += haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
        total_s += (_parse_iso_z(b["captured_at"]) - _parse_iso_z(a["captured_at"])).total_seconds()
    mean_kmh = (total_km / total_s * 3600.0) if total_s > 0 else 0.0

    last, prev = accepted[-1], accepted[-2]
    heading = initial_bearing_deg(prev["lat"], prev["lon"], last["lat"], last["lon"])

    if mean_kmh < PREDICT_MIN_SPEED_KMH:
        return {
            "plate": target,
            "predictions": [],
            "reason": f"vehicle effectively stationary (mean speed "
                      f"{mean_kmh:.1f} km/h) — no meaningful heading to project",
            "heading_deg": round(heading, 1),
            "mean_speed_kmh": round(mean_kmh, 1),
            "from_camera_id": last["camera_id"],
        }

    cameras = (
        db.query(Camera)
        .filter(Camera.lat.isnot(None), Camera.lon.isnot(None))
        .all()
    )
    candidates = []
    for cam in cameras:
        if cam.id == last["camera_id"]:
            continue
        dist_km = haversine_km(last["lat"], last["lon"], cam.lat, cam.lon)
        if dist_km <= SAME_LOCATION_KM:
            continue  # co-located with the last sighting — not "ahead"
        cam_bearing = initial_bearing_deg(last["lat"], last["lon"], cam.lat, cam.lon)
        delta = bearing_delta_deg(heading, cam_bearing)
        if delta > PREDICT_MAX_BEARING_DELTA_DEG:
            continue  # not in the direction of travel
        eta_s = dist_km / mean_kmh * 3600.0
        alignment = 1.0 - (delta / PREDICT_MAX_BEARING_DELTA_DEG)  # 1=dead ahead
        proximity = max(0.0, 1.0 - eta_s / PREDICT_SOON_SECONDS)   # 1=reachable now
        confidence = round(0.7 * alignment + 0.3 * proximity, 2)
        candidates.append({
            "camera_id": cam.id,
            "camera_name": cam.name,
            "lat": cam.lat,
            "lon": cam.lon,
            "distance_km": round(dist_km, 3),
            "bearing_deg": round(cam_bearing, 1),
            "eta_seconds": round(eta_s, 1),
            "confidence": confidence,
        })

    # Rank: best heading alignment + soonest reachable (both fold into
    # confidence); ties broken by nearer ETA.
    candidates.sort(key=lambda c: (-c["confidence"], c["eta_seconds"]))
    top = candidates[:PREDICT_TOP_N]
    return {
        "plate": target,
        "predictions": top,
        "reason": None if top else "no cameras lie ahead on the current heading",
        "heading_deg": round(heading, 1),
        "mean_speed_kmh": round(mean_kmh, 1),
        "from_camera_id": last["camera_id"],
        "eta_note": "eta_seconds is a heuristic: straight-line distance / recent "
                    "mean speed, not a routed drive time",
    }


@router.get("/vehicles/{plate}/predict")
def vehicle_predict(
    plate: str,
    request: Request,
    since: datetime | None = None,
    until: datetime | None = None,
    db: Session = Depends(get_db),
):
    payload = build_intercept_prediction(db, plate, since, until)
    audit_record(
        db, "intercept_predict", resolve_operator(request), plate=payload["plate"],
        since=iso_z(as_naive_utc(since)) if since else None,
        until=iso_z(as_naive_utc(until)) if until else None,
        predictions=len(payload["predictions"]),
        heading_deg=payload.get("heading_deg"),
        mean_speed_kmh=payload.get("mean_speed_kmh"),
    )
    return payload


@router.get("/vehicles/{plate}/route")
def vehicle_route(
    plate: str,
    request: Request,
    since: datetime | None = None,
    until: datetime | None = None,
    db: Session = Depends(get_db),
):
    payload = build_route_payload(db, plate, since, until)
    audit_record(
        db, "route_query", resolve_operator(request), plate=payload["plate"],
        since=iso_z(as_naive_utc(since)) if since else None,
        until=iso_z(as_naive_utc(until)) if until else None,
        sightings=payload["stats"]["sightings_count"],
        rejected=payload["stats"]["rejected_count"],
    )
    return payload
