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

# (city, code, [(landmark, lat, lon)]) — every named junction carries its REAL
# position (± street-level rounding), not a jittered city-centre offset. The
# jury is Gujarat-local and leg_km / implied speed derived from these points
# are shown on the map, in the route table, and printed in the dossier: the
# geometry between named landmarks must survive a judge with Google Maps open
# (e.g. Kalupur Railway Station -> Lal Darwaja is ~2 km, not ~7).
CITIES = [
    ("Ahmedabad", "AMD", [
        ("CG Road Junction", 23.0330, 72.5605),
        ("Ellisbridge", 23.0230, 72.5680),
        ("Kalupur Railway Station", 23.0262, 72.6013),
        ("Sabarmati Riverfront", 23.0275, 72.5735),
        ("ISKCON Cross Roads", 23.0290, 72.5070),
        ("SG Highway - Thaltej", 23.0500, 72.5150),
        ("Lal Darwaja", 23.0240, 72.5800),
        ("Naroda GIDC Gate", 23.0700, 72.6590),
        ("Kankaria Lake East Gate", 23.0070, 72.6070),
        ("Maninagar Char Rasta", 22.9970, 72.6030),
        ("Airport Circle", 23.0650, 72.6270),
    ]),
    ("Surat", "SRT", [
        ("Ring Road Flyover", 21.1930, 72.8180),
        ("Varachha Main Road", 21.2100, 72.8560),
        ("Adajan Patiya", 21.1910, 72.7930),
        ("Udhna Darwaja", 21.1830, 72.8330),
        ("Surat Railway Station", 21.2050, 72.8410),
        ("Dumas Road", 21.1500, 72.7700),
        ("Katargam Darwaja", 21.2160, 72.8230),
        ("Athwa Gate", 21.1850, 72.8080),
    ]),
    ("Vadodara", "VAD", [
        ("Alkapuri Circle", 22.3110, 73.1660),
        ("Fatehgunj", 22.3220, 73.1870),
        ("Mandvi Gate", 22.2990, 73.2070),
        ("Sayajigunj", 22.3130, 73.1900),
        ("Makarpura GIDC", 22.2440, 73.1890),
        ("Gotri Road", 22.3130, 73.1440),
        ("Nyay Mandir Square", 22.3010, 73.2020),
    ]),
    ("Rajkot", "RAJ", [
        ("Trikon Baug", 22.2970, 70.7930),
        ("Kalavad Road", 22.2820, 70.7680),
        ("Yagnik Road", 22.2930, 70.7830),
        ("Gondal Road Overbridge", 22.2750, 70.8000),
        ("Race Course Ring Road", 22.2950, 70.7970),
    ]),
    ("Gandhinagar", "GNR", [
        ("Sector 21 Circle", 23.2230, 72.6490),
        ("Akshardham Circle", 23.2260, 72.6720),
        ("CH Road", 23.2200, 72.6400),
        ("Infocity Gate", 23.1900, 72.6360),
        ("Sachivalaya Gate 1", 23.2320, 72.6510),
    ]),
    ("Jamnagar", "JAM", [
        ("Bedi Gate", 22.4740, 70.0680),
        ("Ranjit Sagar Road", 22.4610, 70.0330),
    ]),
    ("Dwarka", "DWK", [
        ("Dwarkadhish Temple Road", 22.2376, 68.9674),
        ("Gomti Ghat", 22.2360, 68.9660),
    ]),
    ("Somnath", "SOM", [
        ("Somnath Temple Gate", 20.8880, 70.4010),
        ("Triveni Sangam", 20.8890, 70.4090),
    ]),
    ("Dahod", "DHD", [
        ("Station Road", 22.8340, 74.2550),
        ("Godhra Chowkdi", 22.8440, 74.2500),
    ]),
    ("Valsad", "VLS", [
        ("Tithal Road", 20.6070, 72.9130),
        ("Halar Cross Road", 20.5960, 72.9260),
    ]),
    ("Bhuj", "BHJ", [
        ("Hamirsar Lake", 23.2510, 69.6620),
        ("Bhuj Station Road", 23.2540, 69.6770),
    ]),
    ("Mehsana", "MSN", [
        ("Modhera Cross Road", 23.5960, 72.3830),
        ("Radhanpur Circle", 23.5990, 72.3620),
    ]),
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
    for city, code, landmarks in CITIES:
        for index, (landmark, lat, lon) in enumerate(landmarks, 1):
            camera_id = f"{code}-{index:03d}"
            department = rng.choices(DEPARTMENTS, weights=DEPARTMENT_WEIGHTS, k=1)[0]
            width, height = rng.choice(RESOLUTIONS)
            cameras.append({
                "id": camera_id,
                "name": f"{DEPARTMENT_PREFIX[department]} - {landmark}, {city}",
                "department": department,
                # Real landmark coordinates — see the CITIES note above.
                "location": {"lat": lat, "lon": lon},
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
