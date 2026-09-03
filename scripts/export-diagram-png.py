#!/usr/bin/env python3
"""Render each mermaid diagram in a Markdown file to a standalone PNG, and
capture dashboard tab screenshots — both via headless Chrome.

Reuses the mermaid renderer from export-hld-pdf.py (same pinned mermaid build,
same 'neutral' theme) so the PNGs match the PDF exactly.

Run:  .venv/bin/python scripts/export-diagram-png.py \
          --src docs/WORKFLOW_DIAGRAM.md --out-dir deliverables/diagrams
      .venv/bin/python scripts/export-diagram-png.py --shots deliverables/screenshots
"""
import argparse
import pathlib
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from importlib import import_module  # noqa: E402

hld = import_module("export-hld-pdf")  # find_chrome, mermaid_js

DIAGRAM_CSS = """
body { margin: 0; background: #fff; font-family: -apple-system, Helvetica, Arial, sans-serif; }
.wrap { padding: 28px 32px; display: inline-block; }
h2 { font-size: 18px; margin: 0 0 14px; color: #16181d; }
pre.mermaid { margin: 0; }
pre.mermaid svg { max-width: none !important; }
"""

# Dashboard deep links understood by the frontend (tab + optional trace).
DEFAULT_SHOTS = {
    "01_dashboard_alerts": "http://localhost:5173/?tab=alerts",
    "02_route_reconstruction": "http://localhost:5173/?tab=route&trace=GJ01AB1234",
    "03_cameras_registry": "http://localhost:5173/?tab=cameras",
    "04_watchlist": "http://localhost:5173/?tab=watchlist",
    "05_camera_health": "http://localhost:5173/?tab=health",
}


def diagram_blocks(md_text: str):
    """Yield (heading, mermaid_source) for each ```mermaid fence, using the
    nearest preceding '## ' heading as the diagram title."""
    heading = "Diagram"
    pos = 0
    for m in re.finditer(r"```mermaid\n(.*?)```", md_text, flags=re.S):
        before = md_text[pos:m.start()]
        heads = re.findall(r"^##\s+(.+)$", before, flags=re.M)
        if heads:
            heading = heads[-1].strip()
        yield heading, m.group(1)
        pos = m.end()


def trim_whitespace(png: pathlib.Path, pad: int = 40) -> None:
    """Crop a screenshot to its non-white content box (+padding). Diagrams are
    rendered in an oversized window so nothing clips; this removes the slack."""
    import cv2
    import numpy as np

    img = cv2.imread(str(png))
    if img is None:
        return
    mask = np.any(img < 245, axis=2)
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return
    x0, x1 = max(int(xs.min()) - pad, 0), min(int(xs.max()) + pad, img.shape[1])
    y0, y1 = max(int(ys.min()) - pad, 0), min(int(ys.max()) + pad, img.shape[0])
    cv2.imwrite(str(png), img[y0:y1, x0:x1])


def render_png(chrome: str, html: str, out: pathlib.Path, width: int, height: int):
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        path = f.name
    cmd = [
        chrome, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
        f"--window-size={width},{height}", "--virtual-time-budget=12000",
        "--run-all-compositor-stages-before-draw",
        f"--screenshot={out}", f"file://{path}",
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    ok = out.exists() and out.stat().st_size > 10_000
    if ok:
        trim_whitespace(out)
    return ok


def export_diagrams(chrome: str, src: pathlib.Path, out_dir: pathlib.Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    js = hld.mermaid_js()
    made = []
    for i, (title, code) in enumerate(diagram_blocks(src.read_text(encoding="utf-8")), 1):
        safe = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")[:48]
        out = out_dir / f"{i:02d}_{safe}.png"
        html = f"""<!doctype html><html><head><meta charset="utf-8">
<style>{DIAGRAM_CSS}</style><script>{js}</script></head><body>
<div class="wrap"><h2>{title}</h2><pre class="mermaid">{code}</pre></div>
<script>mermaid.initialize({{startOnLoad:true, theme:'neutral',
  flowchart:{{htmlLabels:true, useMaxWidth:false}}, sequence:{{useMaxWidth:false}}}});</script>
</body></html>"""
        # Oversized canvas so wide LR flowcharts never clip; trimmed afterwards.
        ok = render_png(chrome, html, out, 4200, 2400)
        print(("OK  " if ok else "FAIL") + f" {out}")
        if ok:
            made.append(out)
    return made


def export_shots(chrome: str, out_dir: pathlib.Path, shots: dict):
    out_dir.mkdir(parents=True, exist_ok=True)
    made = []
    for name, url in shots.items():
        out = out_dir / f"{name}.png"
        cmd = [
            chrome, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
            "--window-size=1720,940", "--virtual-time-budget=20000",
            "--run-all-compositor-stages-before-draw",
            f"--screenshot={out}", url,
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        ok = out.exists() and out.stat().st_size > 30_000
        print(("OK  " if ok else "FAIL") + f" {out}")
        if ok:
            made.append(out)
    return made


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", type=pathlib.Path, default=hld.ROOT / "docs" / "WORKFLOW_DIAGRAM.md")
    ap.add_argument("--out-dir", type=pathlib.Path, default=hld.ROOT / "deliverables" / "diagrams")
    ap.add_argument("--shots", type=pathlib.Path, help="capture dashboard tab screenshots into this dir")
    args = ap.parse_args()
    chrome = hld.find_chrome()
    if args.shots:
        export_shots(chrome, args.shots, DEFAULT_SHOTS)
    else:
        export_diagrams(chrome, args.src, args.out_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
