import { useEffect, useMemo, useState } from 'react';
import {
  MapContainer,
  TileLayer,
  Circle,
  CircleMarker,
  Marker,
  Polyline,
  Popup,
  Tooltip,
  useMap,
} from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { api, formatLocal } from '../api.js';

const TYPE_NOT_RECORDED = '__none__';
// Coverage layer (registry gap analysis): camera reach + district HQ status.
const COVERAGE_COLOR = '#38bdf8';
const UNCOVERED_COLOR = '#ef4444';

const GUJARAT_CENTER = [22.6, 71.6];
const GUJARAT_ZOOM = 7;

// Leaflet paths take literal colors; keep them in sync with styles.css vars.
const STATUS_COLORS = {
  live: '#22c55e',
  down: '#ef4444',
  unknown: '#64748b',
};
const ROUTE_COLOR = '#fbbf24';

function statusColor(status) {
  return STATUS_COLORS[status] || STATUS_COLORS.unknown;
}

/** Simulated demo sightings get a dashed blue ring so they never read as camera evidence. */
function numberIcon(n, simulated = false) {
  return L.divIcon({
    className: 'route-num-wrap',
    html: `<div class="route-num${simulated ? ' simulated' : ''}">${n}</div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  });
}

/** Grey hollow marker for sightings discarded by the physics filter. */
function rejectedIcon(n) {
  return L.divIcon({
    className: 'route-num-wrap',
    html: `<div class="route-num rejected">${n}</div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  });
}

/** Imperative map reactions: pan-to requests and route bounds fitting. */
function MapController({ panTarget, route }) {
  const map = useMap();

  useEffect(() => {
    if (panTarget && panTarget.lat != null && panTarget.lon != null) {
      map.flyTo([panTarget.lat, panTarget.lon], Math.max(map.getZoom(), 12), {
        duration: 0.8,
      });
    }
  }, [panTarget, map]);

  useEffect(() => {
    if (!route || !Array.isArray(route.points)) return;
    const coords = route.points
      .filter((p) => p.lat != null && p.lon != null)
      .map((p) => [p.lat, p.lon]);
    if (coords.length > 0) {
      map.fitBounds(L.latLngBounds(coords), { padding: [50, 50], maxZoom: 13 });
    }
  }, [route, map]);

  return null;
}

export default function MapView({
  cameras,
  route,
  panTarget,
  onSelectCamera,
  onSync,
  syncing,
}) {
  const [department, setDepartment] = useState('all');
  const [cameraType, setCameraType] = useState('all');
  const [showCoverage, setShowCoverage] = useState(false);
  const [coverage, setCoverage] = useState(null);
  const [coverageError, setCoverageError] = useState(null);

  const departments = useMemo(
    () =>
      [...new Set(cameras.map((c) => c.department).filter(Boolean))].sort(),
    [cameras]
  );

  const cameraTypes = useMemo(
    () => [...new Set(cameras.map((c) => c.camera_type).filter(Boolean))].sort(),
    [cameras]
  );

  const visible = useMemo(
    () =>
      cameras.filter(
        (c) =>
          c.lat != null &&
          c.lon != null &&
          (department === 'all' || c.department === department) &&
          (cameraType === 'all' ||
            (cameraType === TYPE_NOT_RECORDED ? !c.camera_type : c.camera_type === cameraType))
      ),
    [cameras, department, cameraType]
  );

  // Coverage layer data comes from the registry gap analysis (district HQ
  // coverage); refreshed whenever the registry changes while it is shown.
  useEffect(() => {
    if (!showCoverage) return undefined;
    let cancelled = false;
    setCoverageError(null);
    api
      .gapAnalysis()
      .then((g) => !cancelled && setCoverage(g.coverage))
      .catch((err) => !cancelled && setCoverageError(err.message));
    return () => {
      cancelled = true;
    };
  }, [showCoverage, cameras]);

  const coverageRadiusM = coverage ? coverage.radius_km * 1000 : 0;

  // Sequence numbers follow the full table ordering (rejected rows included)
  // so map markers and table rows stay in correspondence.
  const routePoints = useMemo(
    () =>
      route && Array.isArray(route.points)
        ? route.points
            .map((p, i) => ({ ...p, seq: i + 1 }))
            .filter((p) => p.lat != null && p.lon != null)
        : [],
    [route]
  );

  // Physics filter: the polyline only ever runs through ACCEPTED sightings;
  // rejected ones render as grey hollow markers with the reason attached.
  const acceptedPoints = useMemo(
    () => routePoints.filter((p) => !p.rejected),
    [routePoints]
  );
  const rejectedPoints = useMemo(
    () => routePoints.filter((p) => p.rejected),
    [routePoints]
  );

  return (
    <div className="map-wrap">
      <MapContainer center={GUJARAT_CENTER} zoom={GUJARAT_ZOOM} className="map">
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <MapController panTarget={panTarget} route={route} />

        {showCoverage &&
          coverage &&
          visible.map((c) => (
            <Circle
              key={`cov-${c.id}`}
              center={[c.lat, c.lon]}
              radius={coverageRadiusM}
              interactive={false}
              pathOptions={{
                color: COVERAGE_COLOR,
                weight: 0.5,
                opacity: 0.35,
                fillColor: COVERAGE_COLOR,
                fillOpacity: 0.06,
              }}
            />
          ))}

        {showCoverage &&
          coverage &&
          coverage.districts.map((d) => (
            <CircleMarker
              key={`hq-${d.district}`}
              center={[d.lat, d.lon]}
              radius={6}
              pathOptions={{
                color: d.covered ? COVERAGE_COLOR : UNCOVERED_COLOR,
                fillColor: '#0b1220',
                fillOpacity: 0.9,
                weight: 2.5,
                dashArray: d.covered ? null : '3 3',
              }}
            >
              <Tooltip direction="top" offset={[0, -6]}>
                <strong>{d.district}</strong> ({d.hq}) —{' '}
                {d.covered
                  ? `covered: ${d.cameras_within_radius} camera(s) within ${coverage.radius_km} km`
                  : `NOT covered${
                      d.nearest_km != null ? `: nearest camera ${d.nearest_km} km away` : ''
                    }`}
              </Tooltip>
            </CircleMarker>
          ))}

        {visible.map((c) => (
          <CircleMarker
            key={c.id}
            center={[c.lat, c.lon]}
            radius={7}
            pathOptions={{
              color: statusColor(c.status),
              fillColor: statusColor(c.status),
              fillOpacity: 0.85,
              weight: 1.5,
            }}
          >
            <Popup>
              <div className="popup-title">{c.name}</div>
              <div className="popup-line">{c.department || 'Unassigned'}</div>
              <div className="popup-line">
                <span className={`dot status-${c.status || 'unknown'}`} />
                {c.status || 'unknown'}
                {c.codec ? ` · ${String(c.codec).toUpperCase()}` : ''}
                {c.width && c.height ? ` · ${c.width}x${c.height}` : ''}
              </div>
              {(c.camera_type || c.maintenance_status) && (
                <div className="popup-line">
                  {c.camera_type ? `Type: ${c.camera_type}` : ''}
                  {c.camera_type && c.maintenance_status ? ' · ' : ''}
                  {c.maintenance_status
                    ? `Maintenance: ${c.maintenance_status.replace('_', ' ')}`
                    : ''}
                </div>
              )}
              <div className="popup-actions">
                <button
                  className="btn btn-amber btn-small"
                  onClick={() => onSelectCamera(c)}
                >
                  Open camera
                </button>
              </div>
            </Popup>
          </CircleMarker>
        ))}

        {acceptedPoints.length > 1 && (
          <Polyline
            positions={acceptedPoints.map((p) => [p.lat, p.lon])}
            pathOptions={{ color: ROUTE_COLOR, weight: 3, opacity: 0.9 }}
          />
        )}

        {acceptedPoints.map((p) => (
          <Marker
            key={`route-${p.camera_id}-${p.captured_at}-${p.seq}`}
            position={[p.lat, p.lon]}
            icon={numberIcon(p.seq, p.simulated)}
          >
            <Popup>
              <div className="popup-title">
                Sighting #{p.seq} — {p.camera_name}
              </div>
              {p.simulated && (
                <div className="popup-line sim-line">
                  SIMULATED demo data — not a camera read
                </div>
              )}
              <div className="popup-line">{p.department || 'Unassigned'}</div>
              <div className="popup-line">
                <span title={p.captured_at}>{formatLocal(p.captured_at)}</span>
              </div>
              {(p.match_confidence != null || p.confidence != null) && (
                <div className="popup-line">
                  {p.match_confidence != null
                    ? `Match ${Math.round(p.match_confidence * 100)}%`
                    : `Confidence ${Math.round(p.confidence * 100)}%`}
                  {p.fuzzy ? ' · fuzzy' : ''}
                </div>
              )}
              {p.fuzzy && p.matched_from && (
                <div className="popup-line">
                  read <span className="mono">{p.matched_from}</span> →{' '}
                  {route ? route.plate : ''}
                </div>
              )}
              {p.leg_km != null && p.implied_speed_kmh != null && (
                <div className="popup-line">
                  {Number(p.leg_km).toFixed(1)} km leg ·{' '}
                  {Math.round(p.implied_speed_kmh)} km/h implied
                </div>
              )}
            </Popup>
          </Marker>
        ))}

        {rejectedPoints.map((p) => (
          <Marker
            key={`rejected-${p.camera_id}-${p.captured_at}-${p.seq}`}
            position={[p.lat, p.lon]}
            icon={rejectedIcon(p.seq)}
          >
            <Tooltip
              className="rejected-tooltip"
              direction="top"
              offset={[0, -14]}
              opacity={1}
            >
              <strong>REJECTED</strong> —{' '}
              {p.rejected_reason ||
                'physically impossible hop, discarded as false ANPR match'}
            </Tooltip>
            <Popup>
              <div className="popup-title">
                Sighting #{p.seq} — {p.camera_name}
              </div>
              <div className="popup-line">{p.department || 'Unassigned'}</div>
              <div className="popup-line">
                <span title={p.captured_at}>{formatLocal(p.captured_at)}</span>
              </div>
              <div className="popup-line rejected-line">
                &#9888;{' '}
                {p.rejected_reason ||
                  'physically impossible hop, discarded as false ANPR match'}
              </div>
            </Popup>
          </Marker>
        ))}
      </MapContainer>

      <div className="map-overlay top-left">
        <select
          value={department}
          onChange={(e) => setDepartment(e.target.value)}
          title="Filter cameras by department"
        >
          <option value="all">All departments</option>
          {departments.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
        <select
          value={cameraType}
          onChange={(e) => setCameraType(e.target.value)}
          title="Filter cameras by camera type"
        >
          <option value="all">All camera types</option>
          {cameraTypes.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
          <option value={TYPE_NOT_RECORDED}>Type not recorded</option>
        </select>
        <label className="map-toggle" title="Camera reach and district HQ coverage (registry gap analysis)">
          <input
            type="checkbox"
            checked={showCoverage}
            onChange={(e) => setShowCoverage(e.target.checked)}
          />
          Coverage
        </label>
        {showCoverage && coverage && (
          <span className="map-coverage-note">
            {coverage.districts.filter((d) => d.covered).length}/{coverage.districts.length}{' '}
            district HQs within {coverage.radius_km} km
          </span>
        )}
        {showCoverage && coverageError && (
          <span className="map-coverage-note error">coverage unavailable</span>
        )}
      </div>

      <div className="map-overlay bottom-left">
        <div className="map-legend">
          <div className="row">
            <span className="dot status-live" /> Live
          </div>
          <div className="row">
            <span className="dot status-down" /> Down
          </div>
          <div className="row">
            <span className="dot status-unknown" /> Unknown
          </div>
          <div className="row">
            <span className="legend-route" /> Vehicle route
          </div>
          <div className="row">
            <span className="legend-rejected" /> Physics-rejected sighting
          </div>
          {showCoverage && (
            <>
              <div className="row">
                <span className="legend-hq covered" /> District HQ covered
              </div>
              <div className="row">
                <span className="legend-hq uncovered" /> District HQ not covered
              </div>
            </>
          )}
        </div>
      </div>

      {cameras.length === 0 && (
        <div className="map-empty">
          <h3>No cameras onboarded yet</h3>
          <p>
            Sync the gateway catalogue to place cameras on the map
            (POST /api/cameras/sync).
          </p>
          <button className="btn btn-amber" onClick={onSync} disabled={syncing}>
            {syncing ? 'Syncing…' : 'Sync catalogue'}
          </button>
        </div>
      )}
    </div>
  );
}
