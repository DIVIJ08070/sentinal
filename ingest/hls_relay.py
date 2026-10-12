"""Local HLS relay: pull grid cameras over RTSP-TCP, serve as HLS for the dashboard.

Bridges the sandbox grid into the browser: ffmpeg pulls a camera's RTSP stream
into rolling HLS segments on disk, and a CORS-enabled HTTP server serves them
at http://localhost:<port>/<id>/index.m3u8 — the URL shape the dashboard's
hls.js player expects.

Connection-paced by design (gateway rule: every client gets its own stream
copy, open only what you are actively processing):

* --cams lists STANDING pullers (always on, e.g. the demo cameras).
* Every other catalogue camera is relayed ON DEMAND: the first request for its
  index.m3u8 spawns a puller (the HTTP response waits until the manifest
  exists, ~3-8 s), and pullers idle for --idle-timeout seconds are reaped.
* --max-pullers caps simultaneous grid connections; at the cap the
  longest-idle on-demand puller is evicted first.
* HEVC cameras (codec read from --catalogue) are transcoded to H.264/720p so
  Chrome can decode them; H.264 cameras are stream-copied (no CPU cost).

Usage:
    python hls_relay.py --cams cam01,cam02 --catalogue grid_catalogue.json [--port 8888]
"""

import argparse
import functools
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from grid_auth import with_rtsp_auth  # optional RTSP credentials via env

DEFAULT_HOST = "103.250.160.189"
CAM_RE = re.compile(r"^/([A-Za-z0-9_\-]{1,32})/")
MANIFEST_WAIT_S = 12.0


class RelayManager:
    def __init__(self, host, out_root, standing, codecs, max_pullers, idle_timeout, reencode=False):
        self.host = host
        self.out_root = out_root
        self.codecs = codecs                  # cam id -> codec string
        self.standing = set(standing)
        self.max_pullers = max_pullers
        self.idle_timeout = idle_timeout
        self.reencode = reencode
        self.lock = threading.Lock()
        # cam -> {proc, last_access (monotonic), standing, backoff}
        self.pullers = {}
        self.stopping = threading.Event()

    # ------------------------------------------------------------- helpers

    def known(self, cam):
        return cam in self.codecs

    def _spawn(self, cam, fresh=True):
        if cam in self.pullers and self.pullers[cam]["proc"].poll() is None:
            try:
                self.pullers[cam]["proc"].kill()
                self.pullers[cam]["proc"].wait(timeout=1.0)
            except Exception:
                pass
        out_dir = os.path.join(self.out_root, cam)
        if fresh:
            shutil.rmtree(out_dir, ignore_errors=True)
        os.makedirs(out_dir, exist_ok=True)
        codec = (self.codecs.get(cam) or "h264").lower()
        transcode = codec in ("hevc", "h265") or self.reencode
        if transcode:
            video_args = ["-c:v", "libx264", "-preset", "ultrafast",
                          "-tune", "zerolatency", "-vf", "scale=-2:720,fps=10",
                          "-pix_fmt", "yuv420p",
                          "-force_key_frames", "expr:gte(t,n_forced*2)",
                          "-sc_threshold", "0"]
        else:
            video_args = ["-c", "copy"]
        cmd = ["ffmpeg", "-nostdin", "-v", "error",
               "-rtsp_transport", "tcp", "-timeout", "8000000",
               "-flags", "low_delay",
               "-fflags", "+discardcorrupt+nobuffer",
               "-i", with_rtsp_auth(f"rtsp://{self.host}:8554/stream/{cam}"),
               *video_args, "-an",
               "-f", "hls", "-hls_time", "2", "-hls_list_size", "6",
               "-hls_flags", "delete_segments+append_list+omit_endlist+discont_start+temp_file",
               os.path.join(out_dir, "index.m3u8")]
        log = open(os.path.join(out_dir, "ffmpeg.log"), "w")
        proc = subprocess.Popen(cmd, stdout=log, stderr=log)
        print(f"hls_relay: puller up for {cam} ({codec}"
              f"{', transcode' if transcode else ', copy'})",
              file=sys.stderr)
        return proc

    def _alive_count(self):
        return sum(1 for p in self.pullers.values() if p["proc"].poll() is None)

    def _evict_idle(self):
        now = time.monotonic()
        candidates = [(cam, p) for cam, p in self.pullers.items()
                      if not p["standing"] and p["proc"].poll() is None
                      and (now - p["last_access"]) > 30.0]
        if not candidates:
            return False
        cam, p = min(candidates, key=lambda cp: cp[1]["last_access"])
        self._kill(cam, "evicted (connection cap)")
        return True

    def _kill(self, cam, why):
        p = self.pullers.get(cam)
        if not p:
            return
        proc = p["proc"]
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(os.path.join(self.out_root, cam), ignore_errors=True)
        del self.pullers[cam]
        print(f"hls_relay: {cam} stopped — {why}", file=sys.stderr)

    # -------------------------------------------------------------- public

    def touch(self, cam):
        with self.lock:
            p = self.pullers.get(cam)
            if p:
                p["last_access"] = time.monotonic()

    def is_cam_healthy(self, cam):
        cam_dir = os.path.join(self.out_root, cam)
        m = os.path.join(cam_dir, "index.m3u8")
        if not (os.path.exists(m) and os.path.getsize(m) > 0):
            return False
        try:
            ts_files = [f for f in os.listdir(cam_dir) if f.endswith(".ts")]
            if not ts_files:
                return False
            latest_ts = max(ts_files, key=lambda f: os.path.getmtime(os.path.join(cam_dir, f)))
            return os.path.getsize(os.path.join(cam_dir, latest_ts)) > 1000
        except Exception:
            return False

    def ensure_async(self, cam):
        """Make sure a puller runs for cam without blocking the caller."""
        if not self.known(cam):
            return
        with self.lock:
            p = self.pullers.get(cam)
            if p:
                p["last_access"] = time.monotonic()
                return
            while self._alive_count() >= self.max_pullers:
                if not self._evict_idle():
                    return
            self.pullers[cam] = {
                "proc": self._spawn(cam, fresh=True),
                "last_access": time.monotonic(),
                "standing": cam in self.standing,
                "backoff": 1.0,
                "started": time.monotonic(),
                "respawn_at": None,
            }

    def ensure(self, cam):
        """Make sure a puller runs for cam; wait until its manifest exists."""
        self.ensure_async(cam)
        manifest = os.path.join(self.out_root, cam, "index.m3u8")
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline and not self.stopping.is_set():
            if os.path.exists(manifest) and os.path.getsize(manifest) > 0:
                return True
            time.sleep(0.2)
        return os.path.exists(manifest)

    def supervise(self):
        while not self.stopping.wait(1.0):
            now = time.monotonic()
            with self.lock:
                for cam in list(self.pullers):
                    p = self.pullers[cam]
                    alive = p["proc"].poll() is None
                    idle = now - p["last_access"]
                    if alive:
                        p["respawn_at"] = None
                        if not p["standing"] and idle > self.idle_timeout:
                            self._kill(cam, f"idle {idle:.0f}s")
                        elif now - p["started"] > 10.0:
                            p["backoff"] = 1.0  # stable run: forget past failures
                        continue
                    if not (p["standing"] or idle < 15.0):
                        self._kill(cam, "exited while unwatched")
                        continue
                    if p["respawn_at"] is None:
                        clean = p["proc"].returncode == 0 and now - p["started"] >= 10.0
                        wait = 1.0 if clean else p["backoff"]
                        if not clean:
                            p["backoff"] = min(wait * 1.5, 10.0)
                        p["respawn_at"] = now + wait
                        print(f"hls_relay: {cam} puller exited "
                              f"(rc={p['proc'].returncode}); respawn in {wait:.0f}s",
                              file=sys.stderr)
                    elif now >= p["respawn_at"]:
                        p["proc"] = self._spawn(cam, fresh=False)
                        p["started"] = now
                        p["respawn_at"] = None

    def shutdown(self):
        self.stopping.set()
        with self.lock:
            for cam in list(self.pullers):
                self._kill(cam, "shutdown")


class CorsHandler(SimpleHTTPRequestHandler):
    manager = None  # set via functools.partial
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".m3u8": "application/vnd.apple.mpegurl",
        ".ts": "video/mp2t",
    }

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self):
        m = CAM_RE.match(self.path)
        if m:
            cam = m.group(1)
            if not self.manager.known(cam):
                self.send_error(404, "unknown camera")
                return
            if self.path.endswith("index.m3u8"):
                self.manager.ensure(cam)
                self.manager.touch(cam)
            else:
                self.manager.touch(cam)
                filepath = os.path.join(self.manager.out_root, cam, os.path.basename(self.path))
                if filepath.endswith(".ts") and os.path.exists(filepath):
                    for _ in range(5):
                        if os.path.getsize(filepath) > 0:
                            break
                        time.sleep(0.1)
                    if os.path.getsize(filepath) == 0:
                        self.send_error(404, "segment not ready")
                        return
        super().do_GET()

    def log_message(self, fmt, *args):
        pass


class QuietServer(ThreadingHTTPServer):
    """A player closing its connection mid-segment raises BrokenPipe /
    ConnectionReset inside copyfile. That is routine, not an error, and must
    not dump tracebacks into the relay's terminal (socketserver reports
    handler exceptions via the SERVER's handle_error)."""

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError)):
            return
        super().handle_error(request, client_address)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cams", default="", help="comma-separated STANDING camera ids")
    ap.add_argument("--catalogue", default=os.path.join(os.path.dirname(__file__), "grid_catalogue.json"),
                    help="catalogue json (camera ids + codecs) — defines which cams exist")
    ap.add_argument("--host", default=os.environ.get("GRID_HOST", DEFAULT_HOST))
    ap.add_argument("--port", type=int, default=8888)
    ap.add_argument("--dir", default=os.path.join(os.path.dirname(__file__), ".hls_relay"))
    ap.add_argument("--reencode", action="store_true",
                    help="re-encode H.264 cameras too (steady 2 s segments)")
    ap.add_argument("--max-pullers", type=int, default=10,
                    help="max simultaneous grid connections (pacing cap)")
    ap.add_argument("--idle-timeout", type=float, default=90.0,
                    help="seconds after last request before an on-demand puller is reaped")
    args = ap.parse_args()

    with open(args.catalogue, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    entries = data.get("cameras", data) if isinstance(data, dict) else data
    codecs = {str(e["id"]): (e.get("codec") or "h264") for e in entries if e.get("id")}

    standing = [c.strip() for c in args.cams.split(",") if c.strip()]
    unknown = [c for c in standing if c not in codecs]
    if unknown:
        sys.exit(f"standing cams not in catalogue: {unknown}")

    shutil.rmtree(args.dir, ignore_errors=True)
    os.makedirs(args.dir, exist_ok=True)

    mgr = RelayManager(args.host, args.dir, standing, codecs,
                       args.max_pullers, args.idle_timeout, args.reencode)
    # Warm the standing pullers in the background — the HTTP server must
    # start listening immediately (ensure() blocks on manifest creation).
    threading.Thread(
        target=lambda: [mgr.ensure(cam) for cam in standing], daemon=True
    ).start()
    threading.Thread(target=mgr.supervise, daemon=True).start()
    print(f"hls_relay: {len(standing)} standing + on-demand for {len(codecs)} cams; "
          f"cap {args.max_pullers}, idle reap {args.idle_timeout:.0f}s; serving :{args.port}",
          file=sys.stderr)

    def shutdown(*_):
        mgr.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    handler = functools.partial(CorsHandler, directory=args.dir)
    handler.manager = mgr
    CorsHandler.manager = mgr
    bind_addr = os.environ.get("HLS_RELAY_BIND", "0.0.0.0")
    QuietServer((bind_addr, args.port), handler).serve_forever()


if __name__ == "__main__":
    main()
