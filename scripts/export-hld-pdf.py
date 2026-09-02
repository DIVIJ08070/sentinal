#!/usr/bin/env python3
"""Export docs/HLD.md to docs/HLD.pdf with mermaid diagrams RENDERED.

Toolchain (debugged ahead of submission day, per the battle plan):
  1. python-markdown renders the Markdown (tables + fenced code) to HTML;
     ```mermaid fences become <pre class="mermaid"> blocks;
  2. mermaid.js (CDN, pinned) renders the diagrams in the page;
  3. headless Google Chrome prints the page to PDF (A4, print CSS with
     sane page-break rules).

Run:  .venv/bin/python scripts/export-hld-pdf.py
Network is needed only ONCE, to cache the pinned mermaid UMD build into
scripts/vendor/ (gitignored); afterwards the export is fully offline.
"""
import pathlib
import re
import subprocess
import sys
import tempfile
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "HLD.md"
OUT = ROOT / "docs" / "HLD.pdf"

# v10.9.x is the last UMD (single-file <script>) build published on cdnjs;
# mermaid 11 ships ESM-only there, which headless print can't take inline.
MERMAID_VERSION = "10.9.1"
MERMAID_URL = f"https://cdnjs.cloudflare.com/ajax/libs/mermaid/{MERMAID_VERSION}/mermaid.min.js"
MERMAID_CACHE = ROOT / "scripts" / "vendor" / f"mermaid-{MERMAID_VERSION}.min.js"

CHROME_CANDIDATES = [
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
]

CSS = """
@page { size: A4; margin: 16mm 14mm; }
body { font: 10.5pt/1.5 -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif;
       color: #16181d; max-width: 100%; }
h1 { font-size: 19pt; border-bottom: 2px solid #16181d; padding-bottom: 4px; }
h2 { font-size: 14pt; margin-top: 1.6em; border-bottom: 1px solid #c5c9d3;
     padding-bottom: 3px; page-break-after: avoid; }
h3 { font-size: 11.5pt; page-break-after: avoid; }
table { border-collapse: collapse; width: 100%; font-size: 9pt; page-break-inside: avoid; }
th, td { border: 1px solid #b9bfcc; padding: 4px 7px; text-align: left; vertical-align: top; }
th { background: #eef0f5; }
code { font: 8.8pt/1.4 'SF Mono', Menlo, Consolas, monospace; background: #f1f3f7;
       padding: 1px 3px; border-radius: 3px; }
pre { background: #f1f3f7; border: 1px solid #d6dae3; border-radius: 4px;
      padding: 8px 10px; overflow-x: hidden; white-space: pre-wrap;
      page-break-inside: avoid; }
pre code { background: none; padding: 0; }
pre.mermaid { background: #fff; border: 1px solid #d6dae3; text-align: center;
              page-break-inside: avoid; }
pre.mermaid svg { max-width: 100%; height: auto; }
blockquote { border-left: 3px solid #c5c9d3; margin-left: 0; padding-left: 12px; color: #4a4f5c; }
"""


def find_chrome() -> str:
    for path in CHROME_CANDIDATES:
        if pathlib.Path(path).exists():
            return path
    sys.exit("ERROR: no Chrome/Chromium found; install one or adjust CHROME_CANDIDATES.")


def mermaid_js() -> str:
    if not MERMAID_CACHE.exists():
        MERMAID_CACHE.parent.mkdir(parents=True, exist_ok=True)
        print(f"caching mermaid {MERMAID_VERSION} from cdnjs (one-time)...")
        with urllib.request.urlopen(MERMAID_URL, timeout=60) as resp:
            data = resp.read()
        if resp.status != 200 or len(data) < 500_000:
            sys.exit(f"ERROR: mermaid download looks wrong ({resp.status}, {len(data)} bytes)")
        MERMAID_CACHE.write_bytes(data)
    return MERMAID_CACHE.read_text(encoding="utf-8")


def render_html(md_text: str) -> str:
    import markdown

    # Pull mermaid fences out before markdown processing, restore after.
    blocks: list[str] = []

    def stash(match) -> str:
        blocks.append(match.group(1))
        return f"\nMERMAIDBLOCK{len(blocks) - 1}MERMAIDBLOCK\n"

    md_text = re.sub(r"```mermaid\n(.*?)```", stash, md_text, flags=re.S)
    body = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
    for i, code in enumerate(blocks):
        pre = f'<pre class="mermaid">{code}</pre>'
        body = body.replace(f"<p>MERMAIDBLOCK{i}MERMAIDBLOCK</p>", pre)
        body = body.replace(f"MERMAIDBLOCK{i}MERMAIDBLOCK", pre)
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{CSS}</style>
<script>{mermaid_js()}</script>
</head><body>
{body}
<script>
  mermaid.initialize({{ startOnLoad: true, theme: 'neutral',
                        flowchart: {{ htmlLabels: true }} }});
</script>
</body></html>"""


def main() -> int:
    chrome = find_chrome()
    html = render_html(SRC.read_text(encoding="utf-8"))
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html)
        html_path = f.name
    cmd = [
        chrome, "--headless=new", "--disable-gpu", "--no-first-run",
        "--virtual-time-budget=15000", "--run-all-compositor-stages-before-draw",
        "--no-pdf-header-footer", f"--print-to-pdf={OUT}", f"file://{html_path}",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if not OUT.exists() or OUT.stat().st_size < 20_000:
        print(result.stderr[-2000:])
        sys.exit(f"ERROR: PDF export failed or suspiciously small ({OUT}).")
    print(f"OK: {OUT} ({OUT.stat().st_size / 1024:.0f} KB) — verify the mermaid "
          f"diagrams rendered (open it) before submission.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
