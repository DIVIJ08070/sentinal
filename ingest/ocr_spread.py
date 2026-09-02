"""Diagnostic: raw OCR reads (NO confidence/length gate) on real grid cameras.

Run from ingest/:  python ocr_spread.py cam05,cam09 120

Runs the production CaptureLoop + AnprDetector with the emit gates opened, so
every OCR attempt on a YOLO vehicle crop is logged — measures the true
confidence spread behind the worker's 0-read result.
"""
import os, sys, threading, time, collections

from capture import CaptureLoop
from detectors.anpr import AnprDetector

CAMS = sys.argv[1].split(",") if len(sys.argv) > 1 else ["cam05", "cam09"]
SECONDS = float(sys.argv[2]) if len(sys.argv) > 2 else 120

stats = collections.defaultdict(lambda: {"frames": 0, "vehicles": 0, "reads": []})


class Spy(AnprDetector):
    def __init__(self, cam):
        super().__init__(min_plate_len=3, min_plate_confidence=0.0,
                         dedup_window_ms=0.0, plateless_interval_ms=1e12)
        self.cam = cam

    def process(self, frame, pts_ms, captured_at):
        stats[self.cam]["frames"] += 1
        pred = self._yolo.predict(frame, conf=self.vehicle_conf,
                                  classes=[2, 3, 5, 7], verbose=False)[0]
        h, w = frame.shape[:2]
        for box in pred.boxes:
            x1, y1, x2, y2 = (int(round(v)) for v in box.xyxy[0].tolist())
            x1, y1, x2, y2 = max(0, x1), max(0, y1), min(w, x2), min(h, y2)
            if (x2 - x1) < 32 or (y2 - y1) < 32:
                continue
            stats[self.cam]["vehicles"] += 1
            plate, conf = self._read_plate(frame[y1:y2, x1:x2])
            if plate:
                stats[self.cam]["reads"].append((plate, conf))
        return []


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
    confs = [c for _, c in s["reads"] if c is not None]
    print(f"{cam}: frames={s['frames']} vehicle_crops={s['vehicles']} "
          f"raw_ocr_reads={len(s['reads'])}")
    if confs:
        confs.sort()
        print(f"  conf min/median/max = {confs[0]:.2f}/{confs[len(confs)//2]:.2f}/{confs[-1]:.2f}")
    for p, c in s["reads"][:12]:
        print(f"    {p} conf={None if c is None else round(c, 3)}")
