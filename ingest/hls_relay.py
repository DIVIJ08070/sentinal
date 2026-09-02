"""Local HLS relay: pull grid cameras over RTSP-TCP, serve as HLS for the dashboard.

Bridges the sandbox grid into the browser: ffmpeg copies (no transcode) each
requested camera's RTSP stream into rolling HLS segments on disk, and a small
CORS-enabled HTTP server serves them at http://localhost:<port>/<id>/index.m3u8
— the URL shape the dashboard's hls.js player expects.

Only H.264 cameras are worth relaying for Chrome (hls.js cannot decode HEVC
there); pass those via --cams. Consume-only, paced: one RTSP connection per
relayed camera, all torn down on Ctrl-C.

Usage:
    python hls_relay.py --cams cam01,cam04,cam16,cam23 [--port 8888]
"""

import argparse
import functools
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_HOST = "103.250.160.189"


class CorsHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".m3u8": "application/vnd.apple.mpegurl",
        ".ts": "video/mp2t",
    }

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


def spawn_ffmpeg(host, cam, out_root):
    out_dir = os.path.join(out_root, cam)
    os.makedirs(out_dir, exist_ok=True)
    cmd = [
        "ffmpeg", "-nostdin", "-v", "error",
        "-rtsp_transport", "tcp", "-timeout", "8000000",
        "-i", f"rtsp://{host}:8554/stream/{cam}",
        "-c", "copy", "-an",
        "-f", "hls", "-hls_time", "2", "-hls_list_size", "6",
        "-hls_flags", "delete_segments+append_list+omit_endlist",
        os.path.join(out_dir, "index.m3u8"),
    ]
    log = open(os.path.join(out_dir, "ffmpeg.log"), "w")
    return subprocess.Popen(cmd, stdout=log, stderr=log)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cams", required=True, help="comma-separated camera ids (H.264 ones)")
    ap.add_argument("--host", default=os.environ.get("GRID_HOST", DEFAULT_HOST))
    ap.add_argument("--port", type=int, default=8888)
    ap.add_argument("--dir", default=os.path.join(os.path.dirname(__file__), ".hls_relay"))
    args = ap.parse_args()

    cams = [c.strip() for c in args.cams.split(",") if c.strip()]
    shutil.rmtree(args.dir, ignore_errors=True)
    os.makedirs(args.dir, exist_ok=True)

    procs = {cam: spawn_ffmpeg(args.host, cam, args.dir) for cam in cams}
    backoff = {cam: 2.0 for cam in cams}
    stopping = threading.Event()
    print(f"hls_relay: {len(procs)} ffmpeg pullers up; serving :{args.port}", file=sys.stderr)

    def watchdog():
        # A puller that dies (feed restart, demux error) is respawned with
        # exponential backoff 2s -> 30s, per the gateway reconnect rule.
        while not stopping.wait(5.0):
            for cam, proc in list(procs.items()):
                if proc.poll() is None:
                    backoff[cam] = 2.0
                    continue
                wait = backoff[cam]
                backoff[cam] = min(wait * 2.0, 30.0)
                print(f"hls_relay: {cam} puller exited (rc={proc.returncode}); "
                      f"respawn in {wait:.0f}s", file=sys.stderr)
                if stopping.wait(wait):
                    return
                procs[cam] = spawn_ffmpeg(args.host, cam, args.dir)

    threading.Thread(target=watchdog, daemon=True).start()

    def shutdown(*_):
        stopping.set()
        for p in procs.values():
            p.terminate()
        for p in procs.values():
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    handler = functools.partial(CorsHandler, directory=args.dir)
    ThreadingHTTPServer(("127.0.0.1", args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
