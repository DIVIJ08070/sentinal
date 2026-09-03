"""Pydantic schemas, UTC ISO8601-Z serialization helpers, and response builders."""
from datetime import datetime, timezone
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, model_validator


# ---------------------------------------------------------------------------
# UTC datetime helpers — everything is stored naive-UTC, returned as ...Z.
# ---------------------------------------------------------------------------

def as_naive_utc(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def iso_z(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return as_naive_utc(dt).isoformat(timespec="milliseconds") + "Z"


UTCDateTime = Annotated[datetime, PlainSerializer(iso_z, return_type=str)]

Category = Literal["stolen", "wanted", "suspect", "blacklisted", "other"]
Priority = Literal["high", "medium", "low"]
CameraStatus = Literal["live", "down", "unknown"]


# ---------------------------------------------------------------------------
# Cameras
# ---------------------------------------------------------------------------

class CameraCreate(BaseModel):
    name: str
    department: str
    lat: float
    lon: float
    external_id: Optional[str] = None
    codec: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    fps_declared: Optional[float] = None
    status: CameraStatus = "unknown"
    rtsp_url: Optional[str] = None
    hls_url: Optional[str] = None
    whep_url: Optional[str] = None
    storage_type: Optional[str] = None
    retention_days: Optional[int] = None


class CameraOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_id: Optional[str]
    source: str
    name: str
    department: Optional[str]
    lat: Optional[float]
    lon: Optional[float]
    codec: Optional[str]
    width: Optional[int]
    height: Optional[int]
    fps_declared: Optional[float]
    status: str
    rtsp_url: Optional[str]
    hls_url: Optional[str]
    whep_url: Optional[str]
    storage_type: Optional[str]
    retention_days: Optional[int]
    last_seen_at: Optional[UTCDateTime]
    fps_measured: Optional[float]
    last_frame_age_s: Optional[float]
    reconnects: Optional[int]
    bandwidth_kbps: Optional[float]
    created_at: UTCDateTime


class HeartbeatIn(BaseModel):
    status: CameraStatus
    # Optional health metrics (docs/CONTRACT_ADDENDUM.md): omitted fields keep
    # the camera's previously reported values.
    fps_measured: Optional[float] = Field(default=None, ge=0.0)
    last_frame_age_s: Optional[float] = Field(default=None, ge=0.0)
    reconnects: Optional[int] = Field(default=None, ge=0)
    bandwidth_kbps: Optional[float] = Field(default=None, ge=0.0)


# ---------------------------------------------------------------------------
# Watchlist
# ---------------------------------------------------------------------------

class WatchlistCreate(BaseModel):
    plate: str = Field(min_length=1)
    label: str
    category: Category = "other"
    priority: Priority = "medium"
    active: bool = True
    notes: Optional[str] = None


class WatchlistPatch(BaseModel):
    plate: Optional[str] = None
    label: Optional[str] = None
    category: Optional[Category] = None
    priority: Optional[Priority] = None
    active: Optional[bool] = None
    notes: Optional[str] = None


class WatchlistOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    plate: str
    label: str
    category: str
    priority: str
    active: bool
    notes: Optional[str]
    created_at: UTCDateTime


# ---------------------------------------------------------------------------
# Detections
# ---------------------------------------------------------------------------

class DetectionCreate(BaseModel):
    camera_id: Optional[int] = None
    camera_external_id: Optional[str] = None
    object_type: str = "vehicle"
    vehicle_type: Optional[str] = None  # car|motorcycle|bus|truck (from ingest)
    plate: Optional[str] = None
    plate_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    pts_ms: Optional[float] = None
    captured_at: datetime
    snapshot_b64: Optional[str] = None
    bbox: Optional[Any] = None  # JSON string, list, or object — stored as a JSON string
    detector: Optional[str] = None

    @model_validator(mode="after")
    def _require_camera_reference(self):
        if self.camera_id is None and self.camera_external_id is None:
            raise ValueError("either camera_id or camera_external_id is required")
        return self


class DetectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    camera_id: int
    object_type: str
    vehicle_type: Optional[str]
    plate: Optional[str]
    plate_raw: Optional[str]
    plate_confidence: Optional[float]
    pts_ms: Optional[float]
    captured_at: UTCDateTime
    snapshot_b64: Optional[str]
    bbox: Optional[str]
    detector: Optional[str]
    created_at: UTCDateTime


# ---------------------------------------------------------------------------
# Alerts — embedded shape shared by GET /api/alerts and WS broadcasts
# ---------------------------------------------------------------------------

def alert_to_dict(alert) -> dict:
    """Serialize an Alert ORM row (with loaded relationships) to the embedded
    shape the contract specifies for GET /api/alerts and WS 'alert' messages."""
    camera = alert.camera
    entry = alert.watchlist_entry
    detection = alert.detection
    return {
        "id": alert.id,
        "detection_id": alert.detection_id,
        "watchlist_id": alert.watchlist_id,
        "camera_id": alert.camera_id,
        "plate": alert.plate,
        "match_type": alert.match_type,
        "match_confidence": alert.match_confidence,
        "matched_from": alert.matched_from,
        "plausibility": alert.plausibility,
        "plausibility_reason": alert.plausibility_reason,
        "status": alert.status,
        "created_at": iso_z(alert.created_at),
        "acknowledged_at": iso_z(alert.acknowledged_at),
        "camera": {
            "id": camera.id,
            "name": camera.name,
            "lat": camera.lat,
            "lon": camera.lon,
            "department": camera.department,
        } if camera is not None else None,
        "watchlist": {
            "label": entry.label,
            "category": entry.category,
            "priority": entry.priority,
        } if entry is not None else None,
        "detection": {
            "captured_at": iso_z(detection.captured_at),
            "plate_confidence": detection.plate_confidence,
            "vehicle_type": detection.vehicle_type,
            "snapshot_b64": detection.snapshot_b64,
        } if detection is not None else None,
    }
