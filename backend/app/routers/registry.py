"""Registry gap analysis (Model 1): uncovered zones, ageing infrastructure,
maintenance and metadata gaps across the onboarded camera registry.

GET /api/registry/gap-analysis        -> JSON (drives the map coverage layer)
GET /api/registry/gap-analysis.html   -> printable report (browser: Print -> PDF)

Coverage is measured against fixed reference points - the 33 district
headquarters of Gujarat (approximate coordinates): a district HQ is "covered"
when at least one registry camera lies within `coverage_km` of it. This is a
planning indicator over the registry's own metadata, not a field survey.
Everything is computed from stored camera rows; nothing is estimated.
"""
import html
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ..audit import record as audit_record, resolve_operator
from ..auth import department_scope
from ..db import get_db
from ..models import Camera, utcnow
from ..schemas import MAINTENANCE_STATUSES, iso_z
from .routes import haversine_km

router = APIRouter(prefix="/registry", tags=["registry"])

# District headquarters of Gujarat (33 districts), approximate lat/lon.
GUJARAT_DISTRICT_HQS = (
    ("Ahmedabad", "Ahmedabad", 23.0225, 72.5714),
    ("Amreli", "Amreli", 21.6032, 71.2221),
    ("Anand", "Anand", 22.5645, 72.9289),
    ("Aravalli", "Modasa", 23.4624, 73.2988),
    ("Banaskantha", "Palanpur", 24.1725, 72.4380),
    ("Bharuch", "Bharuch", 21.7051, 72.9959),
    ("Bhavnagar", "Bhavnagar", 21.7645, 72.1519),
    ("Botad", "Botad", 22.1693, 71.6684),
    ("Chhota Udaipur", "Chhota Udaipur", 22.3047, 74.0118),
    ("Dahod", "Dahod", 22.8350, 74.2550),
    ("Dang", "Ahwa", 20.7576, 73.6866),
    ("Devbhumi Dwarka", "Khambhalia", 22.2047, 69.6553),
    ("Gandhinagar", "Gandhinagar", 23.2156, 72.6369),
    ("Gir Somnath", "Veraval", 20.9070, 70.3679),
    ("Jamnagar", "Jamnagar", 22.4707, 70.0577),
    ("Junagadh", "Junagadh", 21.5222, 70.4579),
    ("Kheda", "Nadiad", 22.6916, 72.8634),
    ("Kutch", "Bhuj", 23.2420, 69.6669),
    ("Mahisagar", "Lunawada", 23.1286, 73.6100),
    ("Mehsana", "Mehsana", 23.5880, 72.3693),
    ("Morbi", "Morbi", 22.8173, 70.8377),
    ("Narmada", "Rajpipla", 21.8706, 73.5025),
    ("Navsari", "Navsari", 20.9467, 72.9520),
    ("Panchmahal", "Godhra", 22.7788, 73.6143),
    ("Patan", "Patan", 23.8493, 72.1266),
    ("Porbandar", "Porbandar", 21.6417, 69.6293),
    ("Rajkot", "Rajkot", 22.3039, 70.8022),
    ("Sabarkantha", "Himmatnagar", 23.5986, 72.9661),
    ("Surat", "Surat", 21.1702, 72.8311),
    ("Surendranagar", "Surendranagar", 22.7271, 71.6486),
    ("Tapi", "Vyara", 21.1110, 73.3940),
    ("Vadodara", "Vadodara", 22.3072, 73.1812),
    ("Valsad", "Valsad", 20.5992, 72.9342),
)

# Metadata a complete registry record should carry (Model 1 field list).
REQUIRED_METADATA = (
    ("lat", "coordinates"), ("department", "department"), ("camera_type", "camera type"),
    ("ownership", "ownership"), ("storage_type", "storage type"),
    ("retention_days", "retention period"), ("installed_on", "installation date"),
)


def _cam_ref(c: Camera, **extra) -> dict:
    return {"id": c.id, "external_id": c.external_id, "name": c.name,
            "department": c.department, **extra}


def build_gap_analysis(
    db: Session,
    scope: str | None = None,
    coverage_km: float = 25.0,
    ageing_years: float = 5.0,
    amc_warn_days: int = 60,
    stale_hours: float = 24.0,
) -> dict:
    query = db.query(Camera)
    if scope:
        query = query.filter(Camera.department == scope)
    cameras = query.order_by(Camera.id.asc()).all()
    today = utcnow().date()
    now = utcnow()
    located = [c for c in cameras if c.lat is not None and c.lon is not None]

    # --- coverage: nearest registry camera to every district HQ -------------
    districts = []
    for district, hq, lat, lon in GUJARAT_DISTRICT_HQS:
        nearest, nearest_km = None, None
        for c in located:
            d = haversine_km(lat, lon, c.lat, c.lon)
            if nearest_km is None or d < nearest_km:
                nearest, nearest_km = c, d
        cams_within = sum(1 for c in located if haversine_km(lat, lon, c.lat, c.lon) <= coverage_km)
        districts.append({
            "district": district, "hq": hq, "lat": lat, "lon": lon,
            "covered": cams_within > 0,
            "cameras_within_radius": cams_within,
            "nearest_camera": nearest.name if nearest else None,
            "nearest_km": round(nearest_km, 1) if nearest_km is not None else None,
        })
    uncovered = [d for d in districts if not d["covered"]]

    # --- ageing infrastructure ----------------------------------------------
    age_cutoff = today - timedelta(days=round(ageing_years * 365.25))
    aged = [_cam_ref(c, installed_on=c.installed_on.isoformat(),
                     age_years=round((today - c.installed_on).days / 365.25, 1))
            for c in cameras if c.installed_on and c.installed_on <= age_cutoff]
    amc_expired = [_cam_ref(c, amc_expiry=c.amc_expiry.isoformat())
                   for c in cameras if c.amc_expiry and c.amc_expiry < today]
    amc_expiring = [_cam_ref(c, amc_expiry=c.amc_expiry.isoformat(),
                             days_left=(c.amc_expiry - today).days)
                    for c in cameras if c.amc_expiry
                    and today <= c.amc_expiry <= today + timedelta(days=amc_warn_days)]

    # --- maintenance + health ------------------------------------------------
    maintenance_counts = {s: 0 for s in MAINTENANCE_STATUSES}
    maintenance_counts["not_recorded"] = 0
    for c in cameras:
        maintenance_counts[c.maintenance_status if c.maintenance_status in maintenance_counts
                           else "not_recorded"] += 1
    needs_attention = [_cam_ref(c, maintenance_status=c.maintenance_status,
                                last_maintenance_on=c.last_maintenance_on.isoformat()
                                if c.last_maintenance_on else None)
                       for c in cameras if c.maintenance_status in ("due", "under_repair", "faulty")]
    stale_cutoff = now - timedelta(hours=stale_hours)
    down = [_cam_ref(c, status=c.status) for c in cameras if c.status == "down"]
    stale = [_cam_ref(c, last_seen_at=iso_z(c.last_seen_at)) for c in cameras
             if c.status != "down" and c.last_seen_at is not None and c.last_seen_at < stale_cutoff]
    never_seen = [_cam_ref(c) for c in cameras if c.last_seen_at is None]

    # --- metadata completeness -----------------------------------------------
    missing = {label: [] for _, label in REQUIRED_METADATA}
    for c in cameras:
        for field, label in REQUIRED_METADATA:
            if getattr(c, field) in (None, ""):
                missing[label].append(c.external_id or str(c.id))
    complete = sum(1 for c in cameras
                   if all(getattr(c, f) not in (None, "") for f, _ in REQUIRED_METADATA))

    # --- per department --------------------------------------------------------
    aged_ids = {a["id"] for a in aged}
    attention_ids = {a["id"] for a in needs_attention} | {a["id"] for a in amc_expired}
    by_department = {}
    for c in cameras:
        d = by_department.setdefault(c.department or "Unassigned", {
            "total": 0, "live": 0, "down": 0, "no_coordinates": 0, "aged": 0,
            "maintenance_or_amc_issues": 0})
        d["total"] += 1
        d["live"] += c.status == "live"
        d["down"] += c.status == "down"
        d["no_coordinates"] += c.lat is None or c.lon is None
        d["aged"] += c.id in aged_ids
        d["maintenance_or_amc_issues"] += c.id in attention_ids

    # --- plain-language findings ---------------------------------------------
    findings = []
    if uncovered:
        findings.append(f"{len(uncovered)} of {len(districts)} district HQs have no registry camera within "
                        f"{coverage_km:g} km: {', '.join(d['district'] for d in uncovered)}.")
    if aged:
        findings.append(f"{len(aged)} camera(s) are {ageing_years:g}+ years old - candidates for replacement.")
    if amc_expired:
        findings.append(f"{len(amc_expired)} camera(s) are out of AMC; {len(amc_expiring)} more expire "
                        f"within {amc_warn_days} days.")
    elif amc_expiring:
        findings.append(f"{len(amc_expiring)} AMC(s) expire within {amc_warn_days} days.")
    if needs_attention:
        findings.append(f"{len(needs_attention)} camera(s) are due for maintenance, under repair or faulty.")
    if down or stale:
        findings.append(f"{len(down)} camera(s) are down and {len(stale)} have not reported for "
                        f"{stale_hours:g}+ hours.")
    if cameras and complete < len(cameras):
        worst = max(missing.items(), key=lambda kv: len(kv[1]))
        findings.append(f"{len(cameras) - complete} of {len(cameras)} record(s) are incomplete; most often "
                        f"missing: {worst[0]} ({len(worst[1])}). Request it from the owning department.")
    if not cameras:
        findings.append("The registry is empty - onboard cameras (sync, CSV import or manual entry) first.")

    return {
        "generated_at": iso_z(now),
        "scope": scope or "all departments",
        "parameters": {"coverage_km": coverage_km, "ageing_years": ageing_years,
                       "amc_warn_days": amc_warn_days, "stale_hours": stale_hours},
        "summary": {
            "cameras": len(cameras),
            "live": sum(1 for c in cameras if c.status == "live"),
            "down": len(down),
            "unknown": sum(1 for c in cameras if c.status not in ("live", "down")),
            "with_coordinates": len(located),
            "complete_records": complete,
            "districts_covered": len(districts) - len(uncovered),
            "districts_total": len(districts),
        },
        "findings": findings,
        "coverage": {"reference": "district headquarters of Gujarat (approximate)",
                     "radius_km": coverage_km, "districts": districts, "uncovered": uncovered},
        "ageing": {"older_than_years": ageing_years, "aged": aged, "unknown_install_date":
                   sum(1 for c in cameras if c.installed_on is None),
                   "amc_expired": amc_expired, "amc_expiring": amc_expiring},
        "maintenance": {"counts": maintenance_counts, "needs_attention": needs_attention},
        "health": {"down": down, "stale": stale, "never_seen": never_seen},
        "metadata_gaps": {label: ids for label, ids in missing.items()},
        "by_department": by_department,
    }


def _params(coverage_km, ageing_years, amc_warn_days, stale_hours):
    return dict(coverage_km=coverage_km, ageing_years=ageing_years,
                amc_warn_days=amc_warn_days, stale_hours=stale_hours)


@router.get("/gap-analysis")
def gap_analysis(
    request: Request,
    coverage_km: float = Query(default=25.0, gt=0, le=500),
    ageing_years: float = Query(default=5.0, gt=0, le=50),
    amc_warn_days: int = Query(default=60, ge=0, le=3650),
    stale_hours: float = Query(default=24.0, gt=0),
    db: Session = Depends(get_db),
):
    return build_gap_analysis(db, department_scope(request),
                              **_params(coverage_km, ageing_years, amc_warn_days, stale_hours))


@router.get("/gap-analysis.html", response_class=HTMLResponse)
def gap_analysis_report(
    request: Request,
    coverage_km: float = Query(default=25.0, gt=0, le=500),
    ageing_years: float = Query(default=5.0, gt=0, le=50),
    amc_warn_days: int = Query(default=60, ge=0, le=3650),
    stale_hours: float = Query(default=24.0, gt=0),
    db: Session = Depends(get_db),
):
    report = build_gap_analysis(db, department_scope(request),
                                **_params(coverage_km, ageing_years, amc_warn_days, stale_hours))
    entry = audit_record(db, "gap_analysis_report", resolve_operator(request),
                         scope=report["scope"], cameras=report["summary"]["cameras"],
                         **report["parameters"])
    return HTMLResponse(render_report_html(report, entry.id))


# ------------------------------------------------------------------- HTML

def _e(value) -> str:
    return html.escape("" if value is None else str(value))


def _table(headers, rows) -> str:
    if not rows:
        return '<p class="none">None.</p>'
    head = "".join(f"<th>{_e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{_e(v)}</td>" for v in row) + "</tr>" for row in rows)
    return f'<div class="tw"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def render_report_html(r: dict, audit_entry_id: int | None = None) -> str:
    s = r["summary"]
    p = r["parameters"]
    cov = r["coverage"]
    age = r["ageing"]
    tiles = [
        ("Cameras in registry", s["cameras"]),
        ("Live / down / unknown", f'{s["live"]} / {s["down"]} / {s["unknown"]}'),
        ("Mapped (have coordinates)", f'{s["with_coordinates"]} / {s["cameras"]}'),
        ("Complete records", f'{s["complete_records"]} / {s["cameras"]}'),
        (f'District HQs covered ({p["coverage_km"]:g} km)', f'{s["districts_covered"]} / {s["districts_total"]}'),
        ("Need maintenance", len(r["maintenance"]["needs_attention"])),
    ]
    tiles_html = "".join(f'<div class="tile"><div class="v">{_e(v)}</div><div class="k">{_e(k)}</div></div>'
                         for k, v in tiles)
    findings = "".join(f"<li>{_e(f)}</li>" for f in r["findings"]) or "<li>No gaps found.</li>"
    dept_rows = [(d, v["total"], v["live"], v["down"], v["no_coordinates"], v["aged"],
                  v["maintenance_or_amc_issues"]) for d, v in sorted(r["by_department"].items())]
    district_rows = [(d["district"], d["hq"], "yes" if d["covered"] else "NO", d["cameras_within_radius"],
                      d["nearest_camera"] or "-", "-" if d["nearest_km"] is None else f'{d["nearest_km"]} km')
                     for d in sorted(cov["districts"], key=lambda d: (d["covered"], d["district"]))]
    gap_rows = [(label, len(ids), ", ".join(ids[:12]) + (" ..." if len(ids) > 12 else ""))
                for label, ids in r["metadata_gaps"].items()]
    mc = r["maintenance"]["counts"]
    provenance = (f"Generation recorded as entry {audit_entry_id} of the hash-chained audit log."
                  if audit_entry_id else "")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SENTINEL - Registry gap analysis</title>
<style>
  body {{ font: 14px/1.45 system-ui, -apple-system, Segoe UI, sans-serif; color: #17202c; background: #fff;
         max-width: 1100px; margin: 24px auto; padding: 0 16px; }}
  h1 {{ font-size: 22px; margin: 0 0 4px; }} h2 {{ font-size: 16px; margin: 28px 0 8px;
  border-bottom: 2px solid #17202c; padding-bottom: 4px; }}
  .meta {{ color: #5a6675; font-size: 12px; }}
  .tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin: 16px 0; }}
  .tile {{ border: 1px solid #c9d1db; border-radius: 6px; padding: 10px; }}
  .tile .v {{ font-size: 20px; font-weight: 700; }} .tile .k {{ color: #5a6675; font-size: 12px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 12.5px; }}
  th, td {{ border: 1px solid #d5dbe3; padding: 4px 6px; text-align: left; vertical-align: top; }}
  th {{ background: #eef1f5; }} .none {{ color: #5a6675; }}
  ul {{ margin: 6px 0 0 18px; padding: 0; }} li {{ margin: 3px 0; }}
  .tw {{ overflow-x: auto; }}
  .print {{ margin-bottom: 10px; }} @media print {{ .print {{ display: none; }} body {{ margin: 0; }} }}
</style></head><body>
<button class="print" onclick="window.print()">Print / save as PDF</button>
<h1>SENTINEL - CCTV registry gap analysis</h1>
<div class="meta">Generated {_e(r["generated_at"])} - scope: {_e(r["scope"])} - coverage radius {p["coverage_km"]:g} km,
ageing threshold {p["ageing_years"]:g} years, AMC warning {p["amc_warn_days"]} days, stale after {p["stale_hours"]:g} h.
{_e(provenance)}</div>
<div class="tiles">{tiles_html}</div>
<h2>Key findings</h2><ul>{findings}</ul>
<h2>Uncovered zones - district HQ coverage</h2>
<p class="meta">Reference points: {_e(cov["reference"])}. A district HQ counts as covered when a registry camera lies within {p["coverage_km"]:g} km.</p>
{_table(("District", "HQ", "Covered", "Cameras within radius", "Nearest camera", "Distance"), district_rows)}
<h2>Ageing infrastructure</h2>
<p class="meta">{len(age["aged"])} camera(s) installed {p["ageing_years"]:g}+ years ago; installation date unknown for {age["unknown_install_date"]}.</p>
{_table(("Camera", "Department", "Installed", "Age (years)"), [(a["name"], a["department"], a["installed_on"], a["age_years"]) for a in age["aged"]])}
<h3>AMC expired</h3>
{_table(("Camera", "Department", "AMC expiry"), [(a["name"], a["department"], a["amc_expiry"]) for a in age["amc_expired"]])}
<h3>AMC expiring within {p["amc_warn_days"]} days</h3>
{_table(("Camera", "Department", "AMC expiry", "Days left"), [(a["name"], a["department"], a["amc_expiry"], a["days_left"]) for a in age["amc_expiring"]])}
<h2>Maintenance status</h2>
<p class="meta">ok {mc["ok"]} - due {mc["due"]} - under repair {mc["under_repair"]} - faulty {mc["faulty"]} - not recorded {mc["not_recorded"]}</p>
{_table(("Camera", "Department", "Status", "Last maintenance"), [(a["name"], a["department"], a["maintenance_status"], a["last_maintenance_on"] or "-") for a in r["maintenance"]["needs_attention"]])}
<h2>Connectivity</h2>
{_table(("Camera", "Department", "Issue"), [(a["name"], a["department"], "down") for a in r["health"]["down"]] + [(a["name"], a["department"], f'no report since {a["last_seen_at"]}') for a in r["health"]["stale"]])}
<h2>Metadata completeness</h2>
{_table(("Missing field", "Cameras", "Camera ids"), gap_rows)}
<h2>By department</h2>
{_table(("Department", "Total", "Live", "Down", "No coordinates", "Aged", "Maintenance/AMC issues"), dept_rows)}
</body></html>"""
