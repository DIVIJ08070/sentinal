"""RTSP/HLS capture loop for the Sentinel ingest pipeline.

Implements the official gateway integration rules (docs/INTEGRATION_NOTES.md).
Where a piece of code exists because of a numbered rule, the rule is cited:

* rule 1  - RTSP is forced over TCP via OPENCV_FFMPEG_CAPTURE_OPTIONS, set
            immediately below, BEFORE cv2 is imported anywhere in the process
            (cv2 is only imported lazily inside methods). If RTSP cannot be
            opened twice, the loop falls back to the camera's HLS URL.
* rule 2  - CAP_PROP_FPS and the catalogue-declared fps are logged as
            informational only; no timing logic ever reads them.
* rule 3  - every frame timestamp derives from stream PTS (CAP_PROP_POS_MSEC)
            offset against a wall-clock anchor taken once per (re)connection:
            captured_at = anchor_wall + (pts - anchor_pts). Frame arrival time
            is never used (the gateway replays the buffered GOP on connect, so
            arrival-time stamps would produce impossible velocities).
* rule 4  - no constant-frame-rate assumption: inter-frame PTS gaps below the
            discontinuity threshold are normal, and a failed/slow read is
            tolerated rather than treated as a disconnect.
* rule 5  - automatic reconnect with exponential backoff, 2 s doubling to a
            30 s cap; never a tight reconnect loop.
* rule 6  - decoder warnings on mid-stream join ("Error constructing the frame
            RPS", "Could not find ref with POC") are emitted by FFmpeg on
            stderr until the first IDR frame; this code never inspects or
            aborts on them - they are logged noise by design.
* rule 7  - per-camera properties (codec, resolution, URLs, declared fps) come
            from the camera record the backend synced from /api/ingest; no
            uniform-grid assumption is made anywhere.
* rule 8  - a PTS discontinuity (pts < last_pts, or a forward jump > 10 s,
            e.g. the loop point of a feed) re-anchors the clock and calls
            detector.reset() so background models / trackers recover.
* rule 11 - captures are released on disconnect and shutdown; concurrency is
            capped by the worker (--max-cameras, default 4).
"""

import os

# Rule 1: force RTSP over TCP. This MUST run before `import cv2` anywhere in
# the process - OpenCV's FFmpeg backend reads the variable at capture-open
# time, and every entry point imports this module before touching cv2.
os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Rule 8: forward PTS jump above this (or a large backward jump) is a scene
# discontinuity (feed loop point / source restart) -> re-anchor + reset.
DISCONTINUITY_GAP_MS = 10_000.0
# Backward PTS steps smaller than this are RTP / B-frame reordering jitter,
# not a loop point (cam27 on the live grid shows ~1.2 s backward steps many
# times a minute). Such frames are skipped WITHOUT re-anchoring or resetting
# the detector — treating them as cuts starved ANPR of every stable frame.
PTS_JITTER_TOLERANCE_MS = 3_000.0

# Rule 5: exponential backoff bounds for reconnect attempts.
BACKOFF_INITIAL_S = 2.0
BACKOFF_MAX_S = 30.0
BACKOFF_FACTOR = 2.0

# Fall back to the HLS URL after this many failed RTSP opens (rule 1: "if
# 8554 is blocked, fall back to HLS").
RTSP_FAILURES_BEFORE_HLS = 2

# Rule 4: individual failed reads are tolerated; only a sustained run of
# consecutive failures is treated as a lost stream.
MAX_CONSECUTIVE_READ_FAILURES = 30
READ_FAILURE_SLEEP_S = 0.1

# Health-metrics reporting cadence (wall time between on_metrics callbacks).
METRICS_INTERVAL_S = 10.0

# Bandwidth estimate: OpenCV hands us decoded frames, not the transport byte
# stream, so per-feed bandwidth is estimated from MEASURED resolution x
# MEASURED delivery fps x a codec bits-per-pixel factor (typical CCTV encoder
# rates). It is an estimate and is labeled as such on the health board.
BITS_PER_PIXEL_BY_CODEC = {"h264": 0.10, "avc": 0.10, "h265": 0.055, "hevc": 0.055}
DEFAULT_BITS_PER_PIXEL = 0.10


class CaptureLoop:
    """Capture thread body for one camera.

    Parameters
    ----------
    camera:
        Camera record as returned by the backend (``GET /api/cameras``); the
        catalogue is the source of truth for per-camera properties (rule 7).
    detector:
        Object with ``process(frame, pts_ms, captured_at) -> [DetectionResult]``
        and ``reset()`` (see detectors/base.py).
    on_detection:
        Callback ``(camera, result, pts_ms, captured_at)`` invoked for every
        DetectionResult. Exceptions are logged, never fatal.
    on_status:
        Optional callback ``(camera, "live"|"down")`` invoked on connect and
        disconnect (the worker turns these into backend heartbeats).
    stop_event:
        Shared ``threading.Event`` used for graceful shutdown.
    process_interval_ms:
        Minimum elapsed *PTS* between frames handed to the detector - load
        pacing driven by stream time, never by fps or frame counts (rule 2).
    """

    def __init__(
        self,
        camera,
        detector,
        on_detection,
        on_status=None,
        on_metrics=None,
        stop_event=None,
        process_interval_ms=200.0,
        metrics_interval_s=METRICS_INTERVAL_S,
    ):
        self.camera = camera
        self.detector = detector
        self.on_detection = on_detection
        self.on_status = on_status
        # Optional callback ``(camera, metrics_dict)`` invoked every
        # metrics_interval_s of wall time with measured health metrics:
        # fps_measured, last_frame_age_s, reconnects, bandwidth_kbps.
        self.on_metrics = on_metrics
        self.stop_event = stop_event if stop_event is not None else threading.Event()
        self.process_interval_ms = float(process_interval_ms)
        self.metrics_interval_s = float(metrics_interval_s)

        # Per-camera properties from the camera record (rule 7) - no
        # assumptions of uniform codec/resolution across the grid.
        self.camera_id = camera.get("id")
        self.name = camera.get("name") or f"camera-{self.camera_id}"
        self.rtsp_url = camera.get("rtsp_url")
        self.hls_url = camera.get("hls_url")
        self.codec = camera.get("codec")
        self.width = camera.get("width")
        self.height = camera.get("height")
        # Rule 2: declared fps is INFORMATIONAL ONLY - stored for logging,
        # never read by any timing code in this module.
        self.fps_declared = camera.get("fps_declared")

        self._rtsp_open_failures = 0
        self._last_status = None
        # Health metrics state. `reconnects` counts successful RE-connections
        # (the first connect of the session is not a reconnect).
        self.reconnects = 0
        self._ever_connected = False

    # ------------------------------------------------------------------ run

    def run(self):
        """Blocking capture loop; returns when stop_event is set (or the
        camera has no usable stream URL)."""
        logger.info(
            "[%s] starting capture: codec=%s res=%sx%s declared_fps=%s "
            "(declared fps is informational only - timing is PTS-driven)",
            self.name, self.codec, self.width, self.height, self.fps_declared,
        )
        if not self.rtsp_url and not self.hls_url:
            logger.error("[%s] camera record has neither rtsp_url nor hls_url - nothing to capture", self.name)
            return
        try:
            while not self.stop_event.is_set():
                cap = self._connect()
                if cap is None:
                    break  # stop requested during backoff
                self._notify_status("live")
                try:
                    self._consume(cap)
                finally:
                    # Rule 11: never leave a stream copy open.
                    cap.release()
                self._notify_status("down")
        finally:
            self._notify_status("down")
            logger.info("[%s] capture loop stopped", self.name)

    # -------------------------------------------------------------- connect

    def _candidate_urls(self):
        """Ordered (transport, url) candidates for the next open attempt.

        RTSP first (rule: RTSP is the AI-inference transport); once RTSP has
        failed RTSP_FAILURES_BEFORE_HLS times, HLS is tried first while RTSP
        is still retried as a secondary option.
        """
        candidates = []
        prefer_hls = self._rtsp_open_failures >= RTSP_FAILURES_BEFORE_HLS and self.hls_url
        if prefer_hls:
            candidates.append(("hls", self.hls_url))
        if self.rtsp_url:
            candidates.append(("rtsp", self.rtsp_url))
        if not prefer_hls and self.hls_url and not self.rtsp_url:
            candidates.append(("hls", self.hls_url))
        return candidates

    def _connect(self):
        """Open the stream, retrying with exponential backoff (rule 5).

        Returns an opened cv2.VideoCapture, or None if stop was requested.
        """
        import cv2  # lazy: the transport env var at module top is already set

        backoff = BACKOFF_INITIAL_S
        while not self.stop_event.is_set():
            for transport, url in self._candidate_urls():
                cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
                if cap.isOpened():
                    if self._ever_connected:
                        self.reconnects += 1
                    self._ever_connected = True
                    if transport == "rtsp":
                        self._rtsp_open_failures = 0
                    # Rule 2: reported fps is logged as informational only and
                    # never used for timing. Rule 6: mid-stream join produces
                    # FFmpeg decoder warnings until the first IDR - expected,
                    # non-fatal, and deliberately not inspected.
                    reported_fps = cap.get(cv2.CAP_PROP_FPS)
                    logger.info(
                        "[%s] connected via %s; reported fps=%.2f (informational "
                        "only, unused). Decoder warnings (frame RPS / POC refs) "
                        "until the first IDR frame are expected and non-fatal.",
                        self.name, transport, reported_fps,
                    )
                    return cap
                cap.release()
                if transport == "rtsp":
                    self._rtsp_open_failures += 1
                    logger.warning(
                        "[%s] RTSP open failed (attempt %d)%s",
                        self.name, self._rtsp_open_failures,
                        " - will try HLS fallback" if (
                            self._rtsp_open_failures >= RTSP_FAILURES_BEFORE_HLS and self.hls_url
                        ) else "",
                    )
                else:
                    logger.warning("[%s] HLS open failed", self.name)
            logger.info("[%s] reconnecting in %.1f s", self.name, backoff)
            if self.stop_event.wait(backoff):
                break
            backoff = min(backoff * BACKOFF_FACTOR, BACKOFF_MAX_S)
        return None

    # -------------------------------------------------------------- consume

    def _consume(self, cap):
        """Read frames until the stream is lost or stop is requested.

        All timing is PTS-anchored (rule 3):
            captured_at = anchor_wall + (pts - anchor_pts)
        with the anchor taken once on the first successfully read frame of the
        connection and re-taken on every discontinuity (rule 8).
        """
        import cv2

        # Each (re)connect replays the buffered GOP and may land anywhere in a
        # looping feed - treat it as a scene discontinuity (rules 3 & 8).
        self.detector.reset()

        anchor_wall = None
        anchor_pts = 0.0
        last_pts = None
        last_processed_pts = None
        read_failures = 0

        # Health metrics (wall-clock based; NEVER used for frame timing).
        # fps_measured = frame-count delta over wall time - a measurement of
        # actual frame DELIVERY, not a trusted metadata value (rule 2 only
        # forbids using declared/reported fps for timing logic).
        window_start = time.monotonic()
        window_frames = 0
        last_frame_monotonic = None
        last_metrics_emit = time.monotonic()
        frame_width = self.width
        frame_height = self.height

        while not self.stop_event.is_set():
            # Periodic health report - also during read-failure stretches, so
            # last_frame_age_s keeps growing while a feed is stalling.
            now_monotonic = time.monotonic()
            if (
                self.on_metrics is not None
                and (now_monotonic - last_metrics_emit) >= self.metrics_interval_s
            ):
                elapsed = now_monotonic - window_start
                fps_measured = (window_frames / elapsed) if elapsed > 0 else 0.0
                last_frame_age_s = (
                    (now_monotonic - last_frame_monotonic)
                    if last_frame_monotonic is not None
                    else None
                )
                metrics = {
                    "fps_measured": round(fps_measured, 2),
                    "last_frame_age_s": (
                        round(last_frame_age_s, 2) if last_frame_age_s is not None else None
                    ),
                    "reconnects": self.reconnects,
                    "bandwidth_kbps": self._estimate_bandwidth_kbps(
                        fps_measured, frame_width, frame_height
                    ),
                }
                try:
                    self.on_metrics(self.camera, metrics)
                except Exception:
                    logger.exception("[%s] metrics callback failed", self.name)
                window_start = now_monotonic
                window_frames = 0
                last_metrics_emit = now_monotonic

            ok, frame = cap.read()
            if not ok or frame is None:
                # Rule 4: a failed/slow read is not a disconnect by itself and
                # must never crash or stall the pipeline.
                read_failures += 1
                if read_failures > MAX_CONSECUTIVE_READ_FAILURES:
                    logger.warning(
                        "[%s] %d consecutive read failures - treating stream as lost",
                        self.name, read_failures,
                    )
                    return
                if self.stop_event.wait(READ_FAILURE_SLEEP_S):
                    return
                continue
            read_failures = 0
            window_frames += 1
            last_frame_monotonic = time.monotonic()
            if frame_width is None or frame_height is None:
                # Measured resolution from the actual decoded frame (rule 7:
                # per-camera properties, no uniform-grid assumption).
                frame_height, frame_width = frame.shape[:2]

            # Rule 3: PTS drives all timing; wall-clock arrival time is never
            # attached to a frame.
            pts = float(cap.get(cv2.CAP_PROP_POS_MSEC))

            if anchor_wall is None:
                # First successfully read frame of this connection: anchor.
                anchor_wall = datetime.now(timezone.utc)
                anchor_pts = pts
            elif last_pts is not None and (
                pts < last_pts - PTS_JITTER_TOLERANCE_MS
                or (pts - last_pts) > DISCONTINUITY_GAP_MS
            ):
                # Rule 8: loop point / hard cut. Re-anchor the clock and reset
                # stateful detector models (background, trackers, galleries).
                logger.info(
                    "[%s] PTS discontinuity (%.0f -> %.0f ms): re-anchoring and resetting detector",
                    self.name, last_pts, pts,
                )
                anchor_wall = datetime.now(timezone.utc)
                anchor_pts = pts
                last_processed_pts = None
                self.detector.reset()
            elif last_pts is not None and pts < last_pts:
                # Small backward step: reordering jitter, not a cut. Skip the
                # out-of-order frame; keep the anchor and detector state.
                continue

            captured_at = anchor_wall + timedelta(milliseconds=pts - anchor_pts)
            last_pts = pts

            # Load pacing by elapsed PTS - never by fps or frame counts.
            if (
                last_processed_pts is not None
                and (pts - last_processed_pts) < self.process_interval_ms
            ):
                continue
            last_processed_pts = pts

            try:
                results = self.detector.process(frame, pts, captured_at)
            except Exception:
                logger.exception("[%s] detector error - frame skipped", self.name)
                continue
            for result in results:
                try:
                    self.on_detection(self.camera, result, pts, captured_at)
                except Exception:
                    logger.exception("[%s] detection callback failed", self.name)

    # -------------------------------------------------------------- metrics

    def _estimate_bandwidth_kbps(self, fps_measured, width, height):
        """Estimated stream bandwidth in Kbps.

        OpenCV exposes decoded frames, not transport bytes, so this estimates
        from measured resolution x measured delivery fps x a codec
        bits-per-pixel factor (typical CCTV encoder rates). Returns None when
        nothing has been measured yet.
        """
        if not fps_measured or not width or not height:
            return None
        codec = (self.codec or "").lower()
        bpp = BITS_PER_PIXEL_BY_CODEC.get(codec, DEFAULT_BITS_PER_PIXEL)
        return round(width * height * fps_measured * bpp / 1000.0, 1)

    # --------------------------------------------------------------- status

    def _notify_status(self, status):
        """Report 'live'/'down' transitions once each (heartbeat source)."""
        if status == self._last_status:
            return
        self._last_status = status
        if self.on_status is None:
            return
        try:
            self.on_status(self.camera, status)
        except Exception:
            logger.exception("[%s] status callback failed (%s)", self.name, status)
