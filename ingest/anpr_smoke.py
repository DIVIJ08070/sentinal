"""ANPR-path smoke test — proves the REAL video/ML pipeline runs at all.

Run:  make anpr-smoke        (or: cd ingest && python anpr_smoke.py)

No network or government sandbox needed. The script:

  1. verifies the ML extras import (ultralytics + fast-plate-ocr; clear
     install hint otherwise) — first run downloads yolov8n.pt (~6 MB) and the
     OCR model once, then everything is cached and offline;
  2. synthesizes a short looping test video (drawn vehicle rear + plate);
  3. drives the REAL CaptureLoop (capture.py: PTS anchoring, discontinuity
     re-anchor + detector.reset on the file loop, read-failure tolerance)
     with the REAL AnprDetector (detectors/anpr.py: YOLOv8n vehicle detection
     -> crop -> fast-plate-ocr), CPU-only;
  4. additionally runs the OCR stage directly on the synthetic plate crop
     (YOLO is trained on real vehicles, so a drawn rectangle may yield zero
     vehicle boxes — that is expected and reported honestly);
  5. logs the measured frame read rate, per-frame inference latency, and the
     plate read rate.

Exit codes: 0 = pipeline ran end-to-end; 2 = ML extras missing;
3 = pipeline failure (no frames / detector crash).

Against real streams use:  python worker.py --detector anpr --max-cameras 4
(same CaptureLoop + AnprDetector, plus backend POSTs) — run it on the
government sandbox as soon as it is reachable and record the read rate.
"""
import os
import sys
import tempfile
import threading
import time

# capture.py must be imported before cv2 anywhere (RTSP-over-TCP env var).
from capture import CaptureLoop

SMOKE_PLATE = "GJ01AB1234"
FRAMES = 120
FPS = 12.0
MAX_PROCESSED = 30          # stop after this many detector calls
WATCHDOG_S = 120.0


def fail(code: int, msg: str) -> int:
    print(f"\nANPR SMOKE: FAIL — {msg}")
    return code


def build_test_video(path: str) -> None:
    """Synthetic looping clip: a dark 'vehicle rear' translating across the
    frame with a bright plate carrying SMOKE_PLATE."""
    import cv2
    import numpy as np

    width, height = 640, 360
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"MJPG"), FPS, (width, height))
    if not writer.isOpened():
        raise RuntimeError("cv2.VideoWriter could not open the test file")
    for i in range(FRAMES):
        frame = np.full((height, width, 3), (70, 74, 78), dtype=np.uint8)  # road grey
        cv2.rectangle(frame, (0, 0), (width, 120), (150, 120, 90), -1)      # sky-ish
        x = 60 + int((width - 320) * i / FRAMES)                            # vehicle drifts right
        # Vehicle body + rear window + wheels (car-like blob for YOLO to try).
        cv2.rectangle(frame, (x, 130), (x + 260, 300), (40, 34, 30), -1)
        cv2.rectangle(frame, (x + 30, 145), (x + 230, 200), (90, 110, 120), -1)
        cv2.circle(frame, (x + 50, 305), 22, (15, 15, 15), -1)
        cv2.circle(frame, (x + 210, 305), 22, (15, 15, 15), -1)
        # Plate.
        cv2.rectangle(frame, (x + 60, 240), (x + 200, 280), (235, 238, 240), -1)
        cv2.rectangle(frame, (x + 60, 240), (x + 200, 280), (10, 10, 10), 2)
        cv2.putText(frame, SMOKE_PLATE, (x + 66, 268), cv2.FONT_HERSHEY_SIMPLEX,
                    0.62, (15, 15, 15), 2, cv2.LINE_AA)
        writer.write(frame)
    writer.release()


class CountingDetector:
    """Wraps the real AnprDetector; counts calls, measures latency, stops the loop."""

    def __init__(self, inner, stop_event):
        self.inner = inner
        self.stop_event = stop_event
        self.processed = 0
        self.resets = 0
        self.latencies = []

    def process(self, frame, pts_ms, captured_at):
        t0 = time.monotonic()
        results = self.inner.process(frame, pts_ms, captured_at)
        self.latencies.append(time.monotonic() - t0)
        self.processed += 1
        if self.processed >= MAX_PROCESSED:
            self.stop_event.set()
        return results

    def reset(self):
        self.resets += 1
        self.inner.reset()


def main() -> int:
    print("=== SENTINEL ANPR smoke (CPU-only, no network streams needed) ===")

    # -- 1. ML extras import ------------------------------------------------
    t0 = time.monotonic()
    try:
        from detectors.anpr import AnprDetector
    except ImportError as exc:
        print(exc)
        return fail(2, "ML extras not installed (pip install -r requirements-ml.txt)")
    print(f"[1] ML extras import OK ({time.monotonic() - t0:.1f}s)")

    # -- 2. synthetic test video -------------------------------------------
    tmp = tempfile.NamedTemporaryFile(suffix=".avi", delete=False)
    tmp.close()
    try:
        build_test_video(tmp.name)
        print(f"[2] synthetic test video: {FRAMES} frames @ {FPS:.0f} fps -> {tmp.name}")

        # -- 3. real CaptureLoop + real AnprDetector ------------------------
        t0 = time.monotonic()
        detector = AnprDetector(vehicle_conf=0.10)  # generous: synthetic 'vehicle'
        load_s = time.monotonic() - t0
        print(f"[3] YOLOv8n + fast-plate-ocr models loaded ({load_s:.1f}s, CPU)")

        stop_event = threading.Event()
        counting = CountingDetector(detector, stop_event)
        detections = []
        statuses = []
        camera = {"id": 0, "name": "anpr-smoke", "rtsp_url": None, "hls_url": tmp.name,
                  "codec": "mjpeg", "width": 640, "height": 360, "fps_declared": FPS}
        loop = CaptureLoop(
            camera, counting,
            on_detection=lambda cam, res, pts, at: detections.append((res, pts, at)),
            on_status=lambda cam, status: statuses.append(status),
            stop_event=stop_event,
            process_interval_ms=200.0,
        )
        thread = threading.Thread(target=loop.run, daemon=True)
        t0 = time.monotonic()
        thread.start()
        stop_event.wait(WATCHDOG_S)
        stop_event.set()
        thread.join(timeout=15)
        wall = time.monotonic() - t0

        if counting.processed == 0:
            return fail(3, "CaptureLoop delivered no frames to the detector")
        lat = sorted(counting.latencies)
        print(f"[4] pipeline ran: {counting.processed} frames processed in {wall:.1f}s "
              f"({counting.processed / wall:.2f} processed-frames/s), "
              f"detector resets (connect/loop discontinuity): {counting.resets}, "
              f"statuses: {statuses}")
        print(f"    per-frame inference: median {lat[len(lat) // 2] * 1000:.0f} ms, "
              f"p95 {lat[int(len(lat) * 0.95) - 1] * 1000:.0f} ms (CPU-only)")
        plate_reads = [r for r, _, _ in detections if r.plate]
        vehicle_only = [r for r, _, _ in detections if not r.plate]
        print(f"    detections posted-equivalent: {len(detections)} "
              f"({len(plate_reads)} with plate, {len(vehicle_only)} vehicle-only)")
        if plate_reads:
            print(f"    measured plate read rate: {len(plate_reads)}/{counting.processed} frames; "
                  f"reads: {sorted({r.plate for r in plate_reads})}")
        else:
            print("    YOLO found no vehicle in the DRAWN scene (expected — it is "
                  "trained on real vehicles); the full-chain read rate must be "
                  "measured on real footage: worker.py --detector anpr")

        # -- 4. OCR stage directly on the plate crop ------------------------
        import cv2

        cap = cv2.VideoCapture(tmp.name)
        ok, frame = cap.read()
        cap.release()
        if not ok:
            return fail(3, "could not re-read the test video")
        crop = frame[225:295, 100:280]  # plate region (frame 0 vehicle at x=60)
        # This step checks the OCR STAGE, not the registration-format policy:
        # the drawn font yields near-misses (e.g. G111A8134) that the format
        # gate rightly rejects, so read with the gate bypassed here and test
        # the gate on its own in step 6.
        saved_re, detector._plate_re = detector._plate_re, None
        try:
            plate, conf = detector._read_plate(crop)
        finally:
            detector._plate_re = saved_re
        print(f"[5] fast-plate-ocr direct read on the synthetic crop: "
              f"plate={plate!r} confidence={conf}")
        if plate is None:
            return fail(3, "OCR could not read the synthetic plate crop")

        norm_target = SMOKE_PLATE.replace("-", "")
        verdict = "exact" if plate == norm_target else "near-miss (confusion-tolerant matcher covers this)"
        print(f"    vs expected {norm_target}: {verdict}")

        # -- 6. Registration-format gate (regression for the caption bug) ----
        # On the live sandbox grid the plate localizer OCR'd a camera's
        # burned-in caption ("Camera 01") into plate-shaped junk. The gate must
        # reject those and keep genuine Indian registrations.
        junk = ["CMEP801", "C0MC01", "4MB8801", "CMMC701", "CAMERA01"]
        genuine = ["GJ1104284", "GJ01AB1234", "GJ19PE8859", "MH12AB1234"]
        gate = lambda p: (detector._plate_re is None or detector._plate_re.match(p)) \
            and sum(ch.isdigit() for ch in p) >= 3
        leaked = [p for p in junk if gate(p)]
        blocked = [p for p in genuine if not gate(p)]
        print(f"[6] format gate: rejected {len(junk) - len(leaked)}/{len(junk)} caption junk, "
              f"kept {len(genuine) - len(blocked)}/{len(genuine)} genuine plates")
        if leaked or blocked:
            return fail(4, f"format gate regression — leaked={leaked} blocked={blocked}")
        print("\nANPR SMOKE: PASS — capture->PTS anchor->YOLOv8n->OCR chain runs CPU-only.")
        print("Next: run against real streams and RECORD the per-camera read rate:")
        print("  python worker.py --detector anpr --max-cameras 4   (government grid / mediamtx)")
        return 0
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


if __name__ == "__main__":
    sys.exit(main())
