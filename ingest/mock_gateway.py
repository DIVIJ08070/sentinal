"""Mock of the government CCTV gateway catalogue endpoint.

Serves GET /api/ingest on port 8890 (stdlib http.server only - no deps),
returning ~50 realistic Gujarat cameras in the official catalogue shape:

    {id, name, department, location: {lat, lon}, codec, width, height, fps,
     live, urls: {rtsp, hls, whep}}

Properties are heterogeneous on purpose (mixed h264/h265, mixed resolutions
and frame rates, ~90% live) so every consumer honours gateway rule 7 - no
uniform-grid assumption. The catalogue is built ONCE at import time from a
fixed seed: content is fully deterministic, with no randomness at request
time, and identical across restarts.

RTSP URLs point at rtsp://localhost:8554/stream/<id> (meaningful only if a
local MediaMTX instance is running - fine for the demo, where the simulator
covers the end-to-end flow without video).
"""

import argparse
import json
import logging
import random
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger("ingest.mock_gateway")

DEFAULT_PORT = 8890
CATALOGUE_SEED = 2026  # fixed: the catalogue must be deterministic

# (city, code, lat, lon, [landmarks]) - real-ish coordinates across Gujarat.
CITIES = [
    ("Ahmedabad", "AMD", 23.0225, 72.5714, [
        "CG Road Junction", "Ellisbridge", "Kalupur Railway Station",
        "Sabarmati Riverfront", "ISKCON Cross Roads", "SG Highway - Thaltej",
        "Lal Darwaja", "Naroda GIDC Gate", "Kankaria Lake East Gate",
        "Maninagar Char Rasta", "Airport Circle",
    ]),
    ("Surat", "SRT", 21.1702, 72.8311, [
        "Ring Road Flyover", "Varachha Main Road", "Adajan Patiya",
        "Udhna Darwaja", "Surat Railway Station", "Dumas Road",
        "Katargam Darwaja", "Athwa Gate",
    ]),
    ("Vadodara", "VAD", 22.3072, 73.1812, [
        "Alkapuri Circle", "Fatehgunj", "Mandvi Gate", "Sayajigunj",
        "Makarpura GIDC", "Gotri Road", "Nyay Mandir Square",
    ]),
    ("Rajkot", "RAJ", 22.3039, 70.8022, [
        "Trikon Baug", "Kalavad Road", "Yagnik Road",
        "Gondal Road Overbridge", "Race Course Ring Road",
    ]),
    ("Gandhinagar", "GNR", 23.2156, 72.6369, [
        "Sector 21 Circle", "Akshardham Circle", "CH Road",
        "Infocity Gate", "Sachivalaya Gate 1",
    ]),
    ("Jamnagar", "JAM", 22.4707, 70.0577, ["Bedi Gate", "Ranjit Sagar Road"]),
    ("Dwarka", "DWK", 22.2442, 68.9685, ["Dwarkadhish Temple Road", "Gomti Ghat"]),
    ("Somnath", "SOM", 20.8880, 70.4013, ["Somnath Temple Gate", "Triveni Sangam"]),
    ("Dahod", "DHD", 22.8382, 74.2592, ["Station Road", "Godhra Chowkdi"]),
    ("Valsad", "VLS", 20.5992, 72.9342, ["Tithal Road", "Halar Cross Road"]),
    ("Bhuj", "BHJ", 23.2420, 69.6669, ["Hamirsar Lake", "Bhuj Station Road"]),
    ("Mehsana", "MSN", 23.5880, 72.3693, ["Modhera Cross Road", "Radhanpur Circle"]),
]

DEPARTMENTS = [
    "Home/Police",
    "GSRTC",
    "Municipal Corporation",
    "Panchayat",
    "Health",
    "RTO",
    "Food & Civil Supplies",
]
DEPARTMENT_WEIGHTS = [30, 10, 25, 8, 7, 10, 10]
DEPARTMENT_PREFIX = {
    "Home/Police": "Police Surveillance",
    "GSRTC": "GSRTC Bus Stand Cam",
    "Municipal Corporation": "Municipal CCTV",
    "Panchayat": "Gram Panchayat Cam",
    "Health": "Civil Hospital Cam",
    "RTO": "RTO Checkpost Cam",
    "Food & Civil Supplies": "FCS Godown Cam",
}

# Heterogeneous grid on purpose (gateway rule 7).
CODECS = ["h264", "h265"]
CODEC_WEIGHTS = [65, 35]
RESOLUTIONS = [(1920, 1080), (1280, 720), (2560, 1440), (704, 576), (640, 360)]
FPS_CHOICES = [12, 15, 20, 25, 30]
LIVE_RATIO = 0.9


def _build_catalogue() -> list:
    """Build the ~50-camera catalogue deterministically (fixed seed)."""
    rng = random.Random(CATALOGUE_SEED)
    cameras = []
    for city, code, base_lat, base_lon, landmarks in CITIES:
        for index, landmark in enumerate(landmarks, 1):
            camera_id = f"{code}-{index:03d}"
            department = rng.choices(DEPARTMENTS, weights=DEPARTMENT_WEIGHTS, k=1)[0]
            width, height = rng.choice(RESOLUTIONS)
            cameras.append({
                "id": camera_id,
                "name": f"{DEPARTMENT_PREFIX[department]} - {landmark}, {city}",
                "department": department,
                "location": {
                    "lat": round(base_lat + rng.uniform(-0.035, 0.035), 6),
                    "lon": round(base_lon + rng.uniform(-0.035, 0.035), 6),
                },
                "codec": rng.choices(CODECS, weights=CODEC_WEIGHTS, k=1)[0],
                "width": width,
                "height": height,
                # Declared fps: informational; consumers must never use it for
                # timing (gateway rule 2).
                "fps": rng.choice(FPS_CHOICES),
                "live": rng.random() < LIVE_RATIO,
                "urls": {
                    "rtsp": f"rtsp://localhost:8554/stream/{camera_id}",
                    "hls": f"http://localhost:8888/stream/{camera_id}/index.m3u8",
                    "whep": f"http://localhost:8889/stream/{camera_id}/whep",
                },
            })
    return cameras


# Built once at import time -> identical payload for every request.
CATALOGUE = _build_catalogue()
_CATALOGUE_BYTES = json.dumps(CATALOGUE, indent=2).encode("utf-8")


class GatewayHandler(BaseHTTPRequestHandler):
    server_version = "SentinelMockGateway/1.0"

    def do_GET(self):
        path = self.path.split("?", 1)[0].rstrip("/")
        if path == "/api/ingest":
            self._send(200, _CATALOGUE_BYTES)
        elif path == "":
            info = json.dumps({
                "service": "sentinel mock CCTV gateway",
                "catalogue": "/api/ingest",
                "cameras": len(CATALOGUE),
            }).encode("utf-8")
            self._send(200, info)
        else:
            self._send(404, json.dumps({"error": "not found"}).encode("utf-8"))

    def _send(self, status: int, body: bytes):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        logger.info("%s - %s", self.address_string(), fmt % args)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s")
    parser = argparse.ArgumentParser(description="Mock CCTV gateway catalogue (GET /api/ingest).")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args(argv)

    live = sum(1 for c in CATALOGUE if c["live"])
    server = ThreadingHTTPServer((args.host, args.port), GatewayHandler)
    print(
        f"Mock CCTV gateway on http://{args.host}:{args.port}/api/ingest - "
        f"{len(CATALOGUE)} cameras ({live} live, {len(CATALOGUE) - live} down), "
        f"deterministic seed {CATALOGUE_SEED}."
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("mock gateway stopped")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
