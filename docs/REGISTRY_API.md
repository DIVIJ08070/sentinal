# Camera Registry API (Model 1)

The registry is the common CCTV inventory and GIS layer. All endpoints are under
`/api`. Interactive OpenAPI docs are served by the running backend at
`http://localhost:8000/docs`.

## Camera record

Every onboarding path (catalogue sync, CSV import, manual entry) fills the same record.

| Field | Meaning |
|---|---|
| `external_id`, `name`, `department`, `lat`, `lon` | Identity, owner department, location |
| `status` | `live` / `down` / `unknown` (kept current by ingest heartbeats) |
| `camera_type` | e.g. `bullet`, `dome`, `ptz`, `anpr`, `analog` |
| `ownership` | Owning office or agency |
| `installed_on`, `amc_expiry`, `last_maintenance_on` | Dates (`YYYY-MM-DD`; CSV also accepts `DD-MM-YYYY`) |
| `maintenance_status` | `ok` / `due` / `under_repair` / `faulty` |
| `storage_type`, `retention_days` | Where footage is kept and for how long |
| `codec`, `width`, `height`, `rtsp_url`, `hls_url`, `whep_url` | Stream properties (URLs are stored without credentials) |

## Onboarding

| Method | Endpoint | Notes |
|---|---|---|
| API / catalogue sync | `POST /api/cameras/sync` | Pulls `{SENTINEL_HOST}/api/ingest`. Accepts aliases `type`, `owner`, `install_date`, `amc_end`. Never overwrites registry fields the catalogue leaves out. |
| Bulk import | `POST /api/cameras/bulk` (multipart `file`) | CSV with the columns above; missing columns tolerated; upserts on `external_id`. Returns `{imported, errors[]}` with a reason per rejected row. Sample: [sample_camera_registry.csv](sample_camera_registry.csv). |
| Manual entry | `POST /api/cameras` | JSON; `name`, `department`, `lat`, `lon` required. |
| Edit metadata | `PATCH /api/cameras/{id}` | Any subset of the record fields. |

## Search, export and reports

| Endpoint | Purpose |
|---|---|
| `GET /api/cameras?department=&status=&source=&camera_type=&maintenance_status=` | Filtered list |
| `GET /api/cameras/geojson` | Map layer (FeatureCollection) |
| `GET /api/cameras/export?format=csv\|json&<same filters>` | Download. The CSV re-imports through `/bulk` unchanged. |
| `GET /api/registry/gap-analysis?coverage_km=25&ageing_years=5&amc_warn_days=60&stale_hours=24` | JSON gap analysis: district-HQ coverage (33 Gujarat districts), aged cameras, AMC expired/expiring, maintenance, connectivity, missing metadata, per-department table |
| `GET /api/registry/gap-analysis.html` | Printable report (browser: Print → PDF). Sample: [../deliverables/SAMPLE_GAP_ANALYSIS_REPORT.html](../deliverables/SAMPLE_GAP_ANALYSIS_REPORT.html) |
| `GET /api/health/summary` | Per-camera health: fps, last-frame age, reconnects, bandwidth |

## Audit trail

Every camera create, bulk import, catalogue sync, metadata edit (with old → new
values), registry export and gap report is appended to the hash-chained audit
log: `GET /api/audit?action=camera_update`, verify the chain with `GET /api/audit?verify=1`.

## Department-wise access

Set `SENTINEL_TOKENS="token:name:role[:department],..."`, for example
`tok-rto:rto-desk:operator:RTO,tok-sp:sp-admin:admin`. Callers send
`Authorization: Bearer <token>`.

- Roles rank `viewer < operator < admin`. Editing, importing and creating need `operator`.
- A non-admin token with a department sees, exports, reports on and edits only that department's cameras. A CSV row for another department is rejected with a reason.
- With `SENTINEL_TOKENS` unset (demo mode), everything is open.
