"""Catalogue adapter for the Sentinel sandbox camera grid.

Serves GET /api/ingest on :8891 in the exact shape backend `POST
/api/cameras/sync` consumes, translating the real grid's catalogue. Point the
backend at it with:  SENTINEL_HOST=http://localhost:8891

Catalogue sources, in priority order (the catalogue is the contract — the URL
patterns below are documented fallbacks used only when a source lacks fields):

1. --file / GRID_CAMERAS_FILE : a locally saved cameras.json (save it from your
   authenticated browser session; no credentials ever touch this code).
2. GRID_CAMERAS_URL (+ optional GRID_COOKIE header or GRID_BASIC_AUTH
   "user:pass" — set these yourself in your shell; never share them in chat).
3. --probe : scan cam01..camNN over direct RTSP with ffprobe and build a
   provisional catalogue from what actually answers (codec, resolution,
   declared fps). Slower, but needs no password at all.

Real-grid coordinates: the sandbox catalogue may not carry GIS positions. Any
camera without lat/lon gets a deterministic placeholder position on a ring
around Gandhinagar so the GIS map and route logic stay demonstrable; these are
clearly marked in the camera name suffix " [sandbox]". On hackathon day the
official gateway's /api/ingest carries real metadata and this adapter is not
needed (set SENTINEL_HOST to the government host directly).
"""

import argparse
import base64
import concurrent.futures
import json
import math
import os
import subprocess
import sys
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DEFAULT_HOST = "103.250.160.189"
DEFAULT_CDN = "https://cctv.corp8.cloud"
RTSP_TEMPLATE = os.environ.get("GRID_RTSP_TEMPLATE", "rtsp://{host}:8554/stream/{id}")
HLS_TEMPLATE = os.environ.get("GRID_HLS_TEMPLATE", "{cdn}/{id}/index.m3u8")
WHEP_TEMPLATE = os.environ.get("GRID_WHEP_TEMPLATE", "http://{host}:8889/stream/{id}/whep")

# Gandhinagar ring for cameras lacking real coordinates (placeholders).
RING_CENTER = (23.2156, 72.6369)
RING_RADIUS_DEG = 0.045


def _placeholder_coords(index, total):
    angle = 2.0 * math.pi * index / max(total, 1)
    return (
        round(RING_CENTER[0] + RING_RADIUS_DEG * math.sin(angle), 6),
        round(RING_CENTER[1] + RING_RADIUS_DEG * 1.4 * math.cos(angle), 6),
    )


def _get(entry, *names):
    for n in names:
        if isinstance(entry, dict) and entry.get(n) is not None:
            return entry[n]
    return None


def normalize_entry(entry, index, total, host, cdn):
    """Map one raw catalogue entry (tolerant of shape) to /api/ingest form."""
    cam_id = str(_get(entry, "id", "camera_id", "cam", "name") or f"cam{index + 1:02d}")
    loc = entry.get("location") if isinstance(entry.get("location"), dict) else {}
    lat = _get(loc, "lat", "latitude") or _get(entry, "lat", "latitude")
    lon = _get(loc, "lon", "lng", "longitude") or _get(entry, "lon", "lng", "longitude")
    placeholder = lat is None or lon is None
    if placeholder:
        lat, lon = _placeholder_coords(index, total)
    urls = entry.get("urls") if isinstance(entry.get("urls"), dict) else {}
    live = _get(entry, "live", "online")
    status = _get(entry, "status")
    if live is None and status is not None:
        live = str(status).lower() in ("live", "up", "online", "ok")
    name = _get(entry, "name", "label", "title") or cam_id
    return {
        "id": cam_id,
        "name": f"{name} [sandbox]" if placeholder else str(name),
        "department": _get(entry, "department", "dept") or "Sandbox Grid",
        "location": {"lat": lat, "lon": lon},
        "codec": (_get(entry, "codec", "video_codec") or "h264").lower(),
        "width": _get(entry, "width", "w"),
        "height": _get(entry, "height", "h"),
        "fps": _get(entry, "fps", "framerate", "frame_rate"),
        "live": True if live is None else bool(live),
        "urls": {
            "rtsp": _get(urls, "rtsp") or _get(entry, "rtsp", "rtsp_url")
            or RTSP_TEMPLATE.format(host=host, id=cam_id),
            "hls": _get(urls, "hls") or _get(entry, "hls", "hls_url")
            or HLS_TEMPLATE.format(cdn=cdn, id=cam_id),
            "whep": _get(urls, "whep") or _get(entry, "whep", "whep_url")
            or WHEP_TEMPLATE.format(host=host, id=cam_id),
        },
    }


def load_from_file(path):
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return data.get("cameras", data) if isinstance(data, dict) else data


def load_from_url(url):
    req = urllib.request.Request(url)
    cookie = os.environ.get("GRID_COOKIE")
    basic = os.environ.get("GRID_BASIC_AUTH")
    if cookie:
        req.add_header("Cookie", cookie)
    if basic:
        req.add_header(
            "Authorization",
            "Basic " + base64.b64encode(basic.encode()).decode(),
        )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("cameras", data) if isinstance(data, dict) else data


def _ffprobe_one(host, cam_id):
    url = RTSP_TEMPLATE.format(host=host, id=cam_id)
    try:
        out = subprocess.run(
            [
                "ffprobe", "-v", "error", "-rtsp_transport", "tcp",
                "-timeout", "6000000", "-select_streams", "v:0",
                "-show_entries", "stream=codec_name,width,height,avg_frame_rate",
                "-of", "json", url,
            ],
            capture_output=True, timeout=25, text=True,
        )
        streams = json.loads(out.stdout or "{}").get("streams") or []
        if not streams:
            return None
        s = streams[0]
        fps = None
        raw = s.get("avg_frame_rate") or ""
        if "/" in raw:
            num, den = raw.split("/", 1)
            if float(den or 1) > 0:
                fps = round(float(num) / float(den), 2)
        return {
            "id": cam_id,
            "codec": s.get("codec_name"),
            "width": s.get("width"),
            "height": s.get("height"),
            "fps": fps,
            "live": True,
        }
    except Exception:
        return None


def load_by_probe(host, count, workers=4):
    """Provisional catalogue from a direct RTSP sweep (no password needed)."""
    ids = [f"cam{i:02d}" for i in range(1, count + 1)]
    entries = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for res in pool.map(lambda c: _ffprobe_one(host, c), ids):
            if res:
                entries.append(res)
    return entries


def build_catalogue(args):
    src_file = args.file or os.environ.get("GRID_CAMERAS_FILE")
    src_url = os.environ.get("GRID_CAMERAS_URL")
    if src_file and os.path.exists(src_file):
        raw, source = load_from_file(src_file), f"file:{src_file}"
    elif src_url:
        raw, source = load_from_url(src_url), src_url
    elif args.probe:
        raw, source = load_by_probe(args.host, args.probe_count), "rtsp-probe"
    else:
        sys.exit(
            "No catalogue source: pass --file cameras.json, set GRID_CAMERAS_URL, "
            "or use --probe for a direct RTSP sweep."
        )
    total = len(raw)
    cams = [normalize_entry(e, i, total, args.host, args.cdn) for i, e in enumerate(raw)]
    return {"cameras": cams, "_source": source}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--file", help="locally saved cameras.json")
    ap.add_argument("--probe", action="store_true", help="build catalogue by RTSP sweep")
    ap.add_argument("--probe-count", type=int, default=30)
    ap.add_argument("--host", default=os.environ.get("GRID_HOST", DEFAULT_HOST))
    ap.add_argument("--cdn", default=os.environ.get("GRID_CDN", DEFAULT_CDN))
    ap.add_argument("--port", type=int, default=8891)
    ap.add_argument("--once", action="store_true", help="print catalogue JSON and exit")
    args = ap.parse_args()

    catalogue = build_catalogue(args)
    print(
        f"grid_adapter: {len(catalogue['cameras'])} cameras from {catalogue['_source']}",
        file=sys.stderr,
    )
    if args.once:
        json.dump(catalogue, sys.stdout, indent=2)
        print()
        return

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.rstrip("/") == "/api/ingest":
                body = json.dumps(catalogue).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(404)

        def log_message(self, fmt, *a):
            pass

    print(f"grid_adapter: serving /api/ingest on :{args.port}", file=sys.stderr)
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
