"""Evidence Dossier — "plate to court" export (docs/CONTRACT_ADDENDUM.md).

GET /api/vehicles/{plate}/dossier.pdf   -> chain-of-custody PDF
GET /api/vehicles/{plate}/dossier.json  -> same data incl. hashes (this is
                                           also the mandatory timestamped
                                           location-wise movement report)

Both derive from the same route payload as GET /api/vehicles/{plate}/route,
so matching + physics decisions can never disagree between screen and export.

Hash chain (tamper evidence):
- genesis  = sha256(canonical_json({plate, generated_at, operator}))
- row N    = sha256(canonical_json(row-fields + prev_hash))   (prev of row 1
             is the genesis hash; snapshots are bound via snapshot_sha256 —
             the sha256 of the decoded JPEG bytes — not the base64 text)
- final    = hash of the last row (or the genesis hash for an empty route)
canonical_json = JSON with sorted keys, separators (",", ":"), UTF-8.
Any post-export edit to any sighting, its snapshot, or the case metadata
changes every subsequent hash — tampering is detectable by recomputation.
"""
import base64
import hashlib
import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from ..db import get_db
from ..matching import find_watchlist_match, normalize
from ..models import WatchlistEntry, utcnow
from ..schemas import iso_z
from .routes import build_route_payload

router = APIRouter(tags=["dossier"])

OPERATOR = "demo-operator"
HASH_ALGORITHM = "sha256"
CUSTODY_STATEMENT = (
    "CHAIN OF CUSTODY: Every sighting row above is sealed into a SHA-256 hash "
    "chain — each row's hash covers its own canonical content plus the hash of "
    "the previous row, anchored in the case metadata (genesis hash). Snapshot "
    "images are bound by the SHA-256 of their raw JPEG bytes. Any modification "
    "to any row, image, or the case metadata after export changes every "
    "subsequent hash and the final chain hash, making post-export tampering "
    "detectable by recomputation. Verify by recomputing the chain from the "
    "matching dossier.json export."
)


def _canonical_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_dossier(
    db: Session,
    plate: str,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict:
    route = build_route_payload(db, plate, since, until)
    generated_at = iso_z(utcnow())

    entries = db.query(WatchlistEntry).filter(WatchlistEntry.active.is_(True)).all()
    entry, match_type, match_confidence = find_watchlist_match(route["plate"], entries)
    watchlist = None
    if entry is not None:
        watchlist = {
            "id": entry.id,
            "plate": entry.plate,
            "label": entry.label,
            "category": entry.category,
            "priority": entry.priority,
            "match_type": match_type,
            "match_confidence": match_confidence,
        }

    metadata = {"plate": route["plate"], "generated_at": generated_at, "operator": OPERATOR}
    genesis_hash = _sha256_hex(_canonical_json(metadata))

    sightings = []
    prev_hash = genesis_hash
    for seq, point in enumerate(route["points"], start=1):
        snapshot_b64 = point.get("snapshot_b64")
        snapshot_sha256 = None
        if snapshot_b64:
            try:
                snapshot_sha256 = hashlib.sha256(base64.b64decode(snapshot_b64)).hexdigest()
            except Exception:
                snapshot_sha256 = _sha256_hex(snapshot_b64)  # unparseable b64: hash the text
        row = {
            "seq": seq,
            "camera_id": point["camera_id"],
            "camera_name": point["camera_name"],
            "department": point["department"],
            "lat": point["lat"],
            "lon": point["lon"],
            "captured_at": point["captured_at"],
            "pts_ms": point["pts_ms"],
            "confidence": point["confidence"],
            "fuzzy": point["fuzzy"],
            "match_confidence": point["match_confidence"],
            "matched_from": point["matched_from"],
            "leg_km": point["leg_km"],
            "implied_speed_kmh": point["implied_speed_kmh"],
            "accepted": not point["rejected"],
            "rejected_reason": point["rejected_reason"],
            "snapshot_sha256": snapshot_sha256,
            "prev_hash": prev_hash,
        }
        row_hash = _sha256_hex(_canonical_json(row))
        sightings.append({**row, "row_hash": row_hash, "snapshot_b64": snapshot_b64})
        prev_hash = row_hash

    return {
        **metadata,
        "watchlist": watchlist,
        "stats": route["stats"],
        "sightings": sightings,
        "hash_chain": {
            "algorithm": HASH_ALGORITHM,
            "canonicalization": (
                "JSON with sorted keys, separators (\",\", \":\"), UTF-8; row "
                "fields exclude row_hash and snapshot_b64 (snapshots bound via "
                "snapshot_sha256 of the decoded JPEG bytes); genesis = "
                "sha256(canonical {plate, generated_at, operator})"
            ),
            "genesis_hash": genesis_hash,
            "final_hash": prev_hash,
            "row_count": len(sightings),
        },
        "chain_of_custody": CUSTODY_STATEMENT,
    }


# ---------------------------------------------------------------------------
# PDF rendering (fpdf2)
# ---------------------------------------------------------------------------

def _txt(value) -> str:
    """Latin-1-safe text for core PDF fonts (em/en dashes transliterated)."""
    text = "" if value is None else str(value)
    text = text.replace("—", "-").replace("–", "-").replace("→", "->")
    return text.encode("latin-1", "replace").decode("latin-1")


def _fit(text: str, limit: int) -> str:
    text = _txt(text)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _render_pdf(dossier: dict) -> bytes:
    from fpdf import FPDF

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.add_page()

    # -- Header -------------------------------------------------------------
    pdf.set_font("Helvetica", "B", 15)
    pdf.set_text_color(20, 20, 20)
    pdf.cell(0, 9, _txt("GUJARAT POLICE — VEHICLE MOVEMENT EVIDENCE DOSSIER"),
             new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 5, _txt("SENTINEL prototype — Gujarat Police CCTV Hackathon 2026 — "
                        "generated demo artifact"),
             new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(3)

    # -- Case metadata ------------------------------------------------------
    pdf.set_text_color(20, 20, 20)
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "CASE METADATA", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    meta_lines = [
        ("Registration number (normalized)", dossier["plate"]),
        ("Generated at (UTC)", dossier["generated_at"]),
        ("Operator", dossier["operator"]),
    ]
    watchlist = dossier["watchlist"]
    if watchlist is not None:
        meta_lines.append((
            "Watchlist entry",
            f"{watchlist['label']} [{watchlist['category']}/{watchlist['priority']}] "
            f"(match: {watchlist['match_type']}, confidence {watchlist['match_confidence']})",
        ))
    else:
        meta_lines.append(("Watchlist entry", "none (plate not on the active watchlist)"))
    for label, value in meta_lines:
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(62, 5, _txt(label))
        pdf.set_font("Helvetica", "", 9)
        pdf.multi_cell(0, 5, _txt(value), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    # -- Route stats --------------------------------------------------------
    stats = dossier["stats"]
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "ROUTE STATISTICS (accepted sightings only)", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.multi_cell(0, 5, _txt(
        f"First seen: {stats['first_seen']}   Last seen: {stats['last_seen']}\n"
        f"Cameras: {stats['cameras_count']}   Accepted sightings: {stats['sightings_count']}   "
        f"Rejected (physics filter): {stats['rejected_count']}   "
        f"Route distance: {stats['distance_km']} km"
    ), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    # -- Sightings table ----------------------------------------------------
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "SIGHTINGS (chronological; every row hash-sealed)", new_x="LMARGIN", new_y="NEXT")
    widths = (8, 52, 30, 34, 13, 18, 35)
    headers = ("#", "Camera / Department", "Lat, Lon", "Captured (UTC)", "OCR", "Match", "Status")
    pdf.set_font("Helvetica", "B", 7.5)
    pdf.set_fill_color(230, 230, 230)
    for width, header in zip(widths, headers):
        pdf.cell(width, 5.5, header, border=1, fill=True)
    pdf.ln()

    for row in dossier["sightings"]:
        pdf.set_font("Helvetica", "", 7.5)
        pdf.set_text_color(20, 20, 20)
        camera = _fit(f"{row['camera_name']} / {row['department'] or '-'}", 40)
        latlon = ("-" if row["lat"] is None else f"{row['lat']:.4f}, {row['lon']:.4f}")
        ocr = "-" if row["confidence"] is None else f"{row['confidence']:.2f}"
        match = f"{'fuzzy' if row['fuzzy'] else 'exact'} {row['match_confidence']:.2f}"
        status = "ACCEPTED" if row["accepted"] else "REJECTED"
        if row["accepted"] and row["implied_speed_kmh"] is not None:
            status += f" ({row['leg_km']:.1f} km @ {row['implied_speed_kmh']:.0f} km/h)"
        cells = (str(row["seq"]), camera, latlon, row["captured_at"], ocr, match, _fit(status, 30))
        if not row["accepted"]:
            pdf.set_text_color(180, 30, 30)
        for width, cell in zip(widths, cells):
            pdf.cell(width, 5, _txt(cell), border=1)
        pdf.ln()
        # Sub-row: hash (+ matched_from when fuzzy, + rejection reason).
        pdf.set_font("Helvetica", "", 6.5)
        pdf.set_text_color(120, 120, 120)
        sub = f"row hash {row['row_hash'][:16]}...  prev {row['prev_hash'][:16]}..."
        if row["fuzzy"]:
            sub += f"  |  matched from raw read: {row['matched_from']}"
        if row["snapshot_sha256"]:
            sub += f"  |  snapshot sha256 {row['snapshot_sha256'][:16]}..."
        pdf.cell(widths[0], 4, "", border="LB")
        pdf.cell(sum(widths[1:]), 4, _txt(_fit(sub, 150)), border="RB")
        pdf.ln()
        if not row["accepted"] and row["rejected_reason"]:
            pdf.set_text_color(180, 30, 30)
            pdf.cell(widths[0], 4, "", border="LB")
            pdf.cell(sum(widths[1:]), 4, _txt(_fit("REASON: " + row["rejected_reason"], 150)), border="RB")
            pdf.ln()
    pdf.set_text_color(20, 20, 20)
    pdf.ln(3)

    # -- Hash chain ---------------------------------------------------------
    chain = dossier["hash_chain"]
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(0, 6, "SHA-256 HASH CHAIN", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Courier", "", 7.5)
    pdf.cell(0, 4.5, _txt(f"genesis  {chain['genesis_hash']}"), new_x="LMARGIN", new_y="NEXT")
    for row in dossier["sightings"]:
        pdf.cell(0, 4.5, _txt(f"row {row['seq']:>3}  {row['row_hash']}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    pdf.set_font("Courier", "B", 10)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(0, 8, _txt(f"FINAL CHAIN HASH  {chain['final_hash']}"),
             border=1, fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 7.5)
    pdf.set_text_color(90, 90, 90)
    pdf.multi_cell(0, 4, _txt("Canonicalization: " + chain["canonicalization"]),
                   new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(20, 20, 20)
    pdf.ln(2)

    # -- Snapshot appendix ---------------------------------------------------
    with_snapshots = [r for r in dossier["sightings"] if r["snapshot_b64"]]
    if with_snapshots:
        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(0, 6, _txt("APPENDIX A — SNAPSHOT EVIDENCE"), new_x="LMARGIN", new_y="NEXT")
        for row in with_snapshots:
            try:
                image = io.BytesIO(base64.b64decode(row["snapshot_b64"]))
                pdf.set_font("Helvetica", "B", 8)
                pdf.cell(0, 5, _txt(
                    f"Sighting #{row['seq']} — {row['camera_name']} — {row['captured_at']}"
                ), new_x="LMARGIN", new_y="NEXT")
                pdf.image(image, w=70)
                pdf.set_font("Courier", "", 6.5)
                pdf.set_text_color(120, 120, 120)
                pdf.cell(0, 4, _txt(f"sha256 {row['snapshot_sha256']}"),
                         new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(20, 20, 20)
                pdf.ln(2)
            except Exception:
                pdf.set_font("Helvetica", "I", 7.5)
                pdf.cell(0, 4, _txt(f"Sighting #{row['seq']}: snapshot could not be rendered"),
                         new_x="LMARGIN", new_y="NEXT")

    # -- Chain-of-custody footer --------------------------------------------
    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(0, 5, "CHAIN-OF-CUSTODY STATEMENT", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 8)
    pdf.multi_cell(0, 4.2, _txt(dossier["chain_of_custody"]), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)
    pdf.set_font("Helvetica", "I", 7.5)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 4, _txt(
        f"Generated by SENTINEL — operator {dossier['operator']} — {dossier['generated_at']} "
        f"— verify against dossier.json (final hash {dossier['hash_chain']['final_hash'][:16]}...)"
    ), new_x="LMARGIN", new_y="NEXT")

    output = pdf.output()
    return bytes(output)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/vehicles/{plate}/dossier.json")
def dossier_json(
    plate: str,
    since: datetime | None = None,
    until: datetime | None = None,
    db: Session = Depends(get_db),
):
    """Timestamped movement report incl. the full hash chain (machine-verifiable)."""
    return build_dossier(db, plate, since, until)


@router.get("/vehicles/{plate}/dossier.pdf")
def dossier_pdf(
    plate: str,
    since: datetime | None = None,
    until: datetime | None = None,
    db: Session = Depends(get_db),
):
    dossier = build_dossier(db, plate, since, until)
    content = _render_pdf(dossier)
    filename = f"dossier-{normalize(plate) or 'unknown'}.pdf"
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )
