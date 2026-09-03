"""Optional RTSP credentials for the camera grid — supplied ONLY via environment.

If the gateway starts answering `401 Unauthorized` on RTSP DESCRIBE, set, in the
terminal that runs the worker / relay / probe (never in the catalogue, never in
chat, never in a committed file):

    export GRID_RTSP_AUTH='user:password'

Every grid client calls `with_rtsp_auth()` at connect time, so the catalogue,
the registry and the dashboard keep credential-free URLs.

Caveat: FFmpeg echoes the input URL in its own error lines, so the relay's
per-camera `ffmpeg.log` files (gitignored, local) may contain the credential.
"""
import os
from urllib.parse import quote, urlsplit, urlunsplit

ENV_VAR = "GRID_RTSP_AUTH"


def with_rtsp_auth(url: str) -> str:
    """Return `url` with user:password injected, if configured and absent."""
    auth = os.environ.get(ENV_VAR, "").strip()
    if not auth or not url or not url.lower().startswith("rtsp://"):
        return url
    parts = urlsplit(url)
    if "@" in parts.netloc:  # already carries credentials
        return url
    user, _, password = auth.partition(":")
    netloc = f"{quote(user, safe='')}:{quote(password, safe='')}@{parts.netloc}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def redact(url: str) -> str:
    """Mask credentials in a URL for logging."""
    parts = urlsplit(url)
    if "@" not in parts.netloc:
        return url
    return urlunsplit((parts.scheme, "***@" + parts.netloc.rsplit("@", 1)[1],
                       parts.path, parts.query, parts.fragment))
