from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    """Naive UTC now — all datetimes are stored naive-UTC and serialized with Z."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Camera(Base):
    __tablename__ = "cameras"
    # NULL external_ids are distinct, so the constraint only bites when external_id is set.
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_camera_source_external_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(16), default="manual")  # catalogue|manual|csv
    name: Mapped[str] = mapped_column(String(255))
    department: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    codec: Mapped[str | None] = mapped_column(String(16), nullable=True)  # h264/h265
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Informational only — never used for timing (see INTEGRATION_NOTES rule 2).
    fps_declared: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="unknown")  # live|down|unknown
    rtsp_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    hls_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    whep_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    storage_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    retention_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Health metrics — reported by ingest heartbeats (all optional/nullable).
    # fps_measured is a frame-delivery measurement (frame-count delta over wall
    # time), a health metric only — never used for timing (INTEGRATION_NOTES rule 2).
    fps_measured: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_frame_age_s: Mapped[float | None] = mapped_column(Float, nullable=True)
    reconnects: Mapped[int | None] = mapped_column(Integer, nullable=True)
    bandwidth_kbps: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WatchlistEntry(Base):
    __tablename__ = "watchlist_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plate: Mapped[str] = mapped_column(String(32), index=True)  # normalized: uppercase A-Z0-9
    label: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(16), default="other")  # stolen|wanted|suspect|blacklisted|other
    priority: Mapped[str] = mapped_column(String(8), default="medium")  # high|medium|low
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Detection(Base):
    __tablename__ = "detections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    object_type: Mapped[str] = mapped_column(String(32), default="vehicle")
    plate: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)  # normalized
    # The raw OCR read exactly as posted, before normalization — surfaced as
    # `matched_from` on alerts and route points (evidence transparency).
    plate_raw: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plate_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    pts_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    # REQUIRED — derived from stream PTS anchor by the ingest worker, never arrival time.
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    snapshot_b64: Mapped[str | None] = mapped_column(Text, nullable=True)
    bbox: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    detector: Mapped[str | None] = mapped_column(String(32), nullable=True)  # mock|anpr
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    camera: Mapped["Camera"] = relationship("Camera")


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    detection_id: Mapped[int] = mapped_column(ForeignKey("detections.id"), index=True)
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlist_entries.id"), index=True)
    camera_id: Mapped[int] = mapped_column(ForeignKey("cameras.id"), index=True)
    plate: Mapped[str] = mapped_column(String(32), index=True)
    match_type: Mapped[str] = mapped_column(String(8))  # exact|fuzzy
    # Confusion-tolerant matcher outputs: confidence 0-1 (exact = 1.0) and the
    # raw plate read that produced the match (never silently merged).
    match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    matched_from: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Physics plausibility at alert time (recall-first: the alert still fires;
    # 'suspect' means the sighting implies an impossible speed from the plate's
    # previous sighting — the route view's physics filter adjudicates fully).
    plausibility: Mapped[str | None] = mapped_column(String(16), nullable=True)  # confirmed|suspect|null
    plausibility_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="new", index=True)  # new|acknowledged
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    detection: Mapped["Detection"] = relationship("Detection")
    watchlist_entry: Mapped["WatchlistEntry"] = relationship("WatchlistEntry")
    camera: Mapped["Camera"] = relationship("Camera")


class AuditLog(Base):
    """Append-only audit trail (who / what / when / params).

    Written by app/audit.py on every route query, watchlist change, alert
    acknowledgment, and dossier export. There is no UPDATE or DELETE path for
    this table anywhere in the codebase — rows are only ever inserted, and the
    dossier cites its own export entry so query provenance is verifiable.
    """
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    action: Mapped[str] = mapped_column(String(48), index=True)  # e.g. route_query|dossier_export|alert_ack|watchlist_create
    actor: Mapped[str] = mapped_column(String(128), index=True)  # operator identity (X-Operator header or SENTINEL_OPERATOR)
    plate: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    entity_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # id of the touched row, when applicable
    params: Mapped[str | None] = mapped_column(Text, nullable=True)  # canonical JSON of request parameters
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
