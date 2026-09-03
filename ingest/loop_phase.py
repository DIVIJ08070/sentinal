"""Pre-flight for the live demo: which demo cameras are readable RIGHT NOW?

The sandbox feeds are day-long recordings that loop, so a camera that read
2 plates/min this morning may be on an empty 2 AM road an hour later. This
grabs one frame per camera and reports brightness + vehicles in frame, so you
start recording on a camera that is in a daylight, traffic phase.

Usage:  python loop_phase.py [--cams cam06,cam23,cam16,cam27]
"""
import argparse
import subprocess
import sys

import cv2
import numpy as np

from grid_auth import with_rtsp_auth  # optional RTSP credentials via env

HOST = "103.250.160.189"

# Measured plate read-rate per camera (reads/min) from the live soak in
# docs/CAMERA_RANKING.md. Busy is not the same as readable: wide junction
# views detect many vehicles but plates are too small to OCR, while a
# close stop-line camera reads several per minute. Used to rank READY cams.
KNOWN_READ_RATE = {
    "cam06": 2.25, "cam23": 0.58, "cam16": 0.38, "cam27": 0.33,
    "cam01": 0.25, "cam05": 0.25, "cam04": 0.25,
}


def grab(cam):
    # A slow RTSP handshake (the grid can take 30s+ when many streams are
    # open) must mark this camera "no frame", never abort the whole report.
    try:
        out = subprocess.run(
            ["ffmpeg", "-v", "error", "-rtsp_transport", "tcp", "-timeout", "8000000",
             "-i", with_rtsp_auth(f"rtsp://{HOST}:8554/stream/{cam}"), "-frames:v", "1", "-f", "image2pipe",
             "-vcodec", "mjpeg", "-q:v", "4", "-"],
            capture_output=True, timeout=40,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if not out.stdout:
        return None
    return cv2.imdecode(np.frombuffer(out.stdout, np.uint8), cv2.IMREAD_COLOR)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cams", default="cam06,cam23,cam16,cam27,cam01,cam04")
    args = ap.parse_args()
    from ultralytics import YOLO
    yolo = YOLO("yolov8n.pt")

    rows = []
    for cam in [c.strip() for c in args.cams.split(",") if c.strip()]:
        img = grab(cam)
        if img is None:
            rows.append((cam, None, None, KNOWN_READ_RATE.get(cam, 0.0),
                         "no frame (handshake slow — stream busy serving the worker/relay)"))
            continue
        bright = float(img.mean())
        n = len(yolo.predict(img, conf=0.35, classes=[2, 3, 5, 7], verbose=False)[0].boxes)
        rate = KNOWN_READ_RATE.get(cam, 0.0)
        if bright < 40:
            verdict = "NIGHT / dark — wait"
        elif n == 0:
            verdict = "empty road — wait"
        elif rate >= 0.5 and n >= 1:
            verdict = "READY — daylight + proven plate reader  <-- record on this one"
        elif n >= 3:
            verdict = "READY — traffic, daylight (wide view: reads are rarer)"
        else:
            verdict = "light traffic — usable"
        rows.append((cam, bright, n, rate, verdict))

    print(f"{'camera':8} {'bright':>6} {'vehicles':>8} {'reads/min':>9}  verdict")
    for cam, b, n, r, v in rows:
        print(f"{cam:8} {('—' if b is None else f'{b:6.0f}'):>6} {('—' if n is None else n):>8} "
              f"{r:>9.2f}  {v}")
    # Recommend READY cameras, best measured plate-read rate first.
    ready = sorted([(c, r) for c, b, n, r, v in rows if v.startswith("READY")],
                   key=lambda x: -x[1])
    print("\nstart with:", f"DEMO_CAMS={','.join(c for c, _ in ready[:3])} scripts/demo-live.sh"
          if ready else "no camera is in a traffic phase right now — re-run in a few minutes")


if __name__ == "__main__":
    sys.exit(main())
