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

HOST = "103.250.160.189"


def grab(cam):
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-rtsp_transport", "tcp", "-timeout", "8000000",
         "-i", f"rtsp://{HOST}:8554/stream/{cam}", "-frames:v", "1", "-f", "image2pipe",
         "-vcodec", "mjpeg", "-q:v", "4", "-"],
        capture_output=True, timeout=30,
    )
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
            rows.append((cam, None, None, "no frame (stream busy?)"))
            continue
        bright = float(img.mean())
        n = len(yolo.predict(img, conf=0.35, classes=[2, 3, 5, 7], verbose=False)[0].boxes)
        if bright < 40:
            verdict = "NIGHT / dark — wait"
        elif n == 0:
            verdict = "empty road — wait"
        elif n >= 3:
            verdict = "READY — traffic, daylight  <-- record on this one"
        else:
            verdict = "light traffic — usable"
        rows.append((cam, bright, n, verdict))

    print(f"{'camera':8} {'bright':>6} {'vehicles':>8}  verdict")
    for cam, b, n, v in rows:
        print(f"{cam:8} {('—' if b is None else f'{b:6.0f}'):>6} {('—' if n is None else n):>8}  {v}")
    ready = [c for c, b, n, v in rows if v.startswith("READY")]
    print("\nstart with:", f"DEMO_CAMS={','.join(ready)} scripts/demo-live.sh" if ready
          else "no camera is in a traffic phase right now — re-run in a few minutes")


if __name__ == "__main__":
    sys.exit(main())
