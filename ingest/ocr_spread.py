"""Diagnostic: OCR confidence spread (NO confidence/length gate) on real grid
cameras — BEFORE/AFTER comparison of the OCR input pipeline.

Run from ingest/:  python ocr_spread.py cam05,cam09 120

Runs the production CaptureLoop + AnprDetector with the emit gates opened and,
for every YOLO vehicle crop, OCRs it TWO ways:

  raw      — the whole vehicle crop straight into fast-plate-ocr
             (the pre-2026-09-02 pipeline; banked in docs/EVIDENCE.md §3);
  pipeline — the production path: plate localization (open-image-models,
             when installed) + grayscale/CLAHE + Lanczos upscaling
             (AnprDetector._ocr_input).

Prints both spreads per camera so the effect of the localizer/preprocessing
is measured on the same frames, not argued.
"""
import collections
import os
import sys
import threading
import time

from capture import CaptureLoop
from detectors.anpr import AnprDetector

CAMS = sys.argv[1].split(",") if len(sys.argv) > 1 else ["cam05", "cam09"]
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 120

stats = collections.defaultdict(
    lambda: {"frames": 0, "vehicles": 0, "localized": 0, "raw": [], "pipeline": []}
)


class Spy(AnprDetector):
    def __init__(self, cam):
        super().__init__(min_plate_len=3, min_plate_confidence=0.0,
                         dedup_window_ms=0.0, plateless_interval_ms=1e12)
        self.cam = cam

    def process(self, frame, pts_ms, captured_at):
        s = stats[self.cam]
        s["frames"] += 1
        pred = self._yolo.predict(frame, conf=self.vehicle_conf,
                                  classes=[2, 3, 5, 7], verbose=False)[0]
        h, w = frame.shape[:2]
        for box in pred.boxes:
            x1, y1, x2, y2 = (int(round(v)) for v in box.xyxy[0].tolist())
            x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
            if (x2 - x1) < 32 or (y2 - y1) < 32:
                continue
            s["vehicles"] += 1
            crop = frame[y1:y2, x1:x2]
            plate, conf = self._read_plate(crop)  # BEFORE: whole vehicle crop
            if plate:
                s["raw"].append((plate, conf))
            if self._localize_plate(crop) is not None:
                s["localized"] += 1
            plate, conf = self._read_plate(self._ocr_input(crop))  # AFTER
            if plate:
                s["pipeline"].append((plate, conf))
        return []


def spread(reads):
    confs = sorted(c for _, c in reads if c is not None)
    if not confs:
        return "no reads"
    n = len(confs)
    return (f"min/median/max = {confs[0]:.2f}/{confs[n // 2]:.2f}/{confs[-1]:.2f}"
            f"  (>=0.35: {sum(c >= 0.35 for c in confs)}, >=0.55: {sum(c >= 0.55 for c in confs)})")


stop = threading.Event()
threads = []
for cam in CAMS:
    camera = {"id": cam, "name": cam,
              "rtsp_url": f"rtsp://{os.environ.get('GRID_HOST', '103.250.160.189')}:8554/stream/{cam}"}
    loop = CaptureLoop(camera, Spy(cam), on_detection=lambda *a: None,
                       on_status=lambda *a: None, stop_event=stop)
    t = threading.Thread(target=loop.run, daemon=True)
    t.start()
    threads.append(t)

time.sleep(SECONDS)
stop.set()
for t in threads:
    t.join(timeout=10)

for cam, s in sorted(stats.items()):
    print(f"{cam}: frames={s['frames']} vehicle_crops={s['vehicles']} "
          f"plate_localized={s['localized']} "
          f"raw_reads={len(s['raw'])} pipeline_reads={len(s['pipeline'])}")
    print(f"  BEFORE (whole vehicle crop): {spread(s['raw'])}")
    print(f"  AFTER  (localize+CLAHE+upscale): {spread(s['pipeline'])}")
    for p, c in s["pipeline"][:12]:
        print(f"    {p} conf={None if c is None else round(c, 3)}")
