import { useEffect, useMemo, useState } from 'react';
import {
  MapContainer,
  TileLayer,
  CircleMarker,
  Marker,
  Polyline,
  Popup,
  Tooltip,
  useMap,
} from 'react-leaflet';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { formatLocal } from '../api.js';

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

function numberIcon(n) {
  return L.divIcon({
    className: 'route-num-wrap',
    html: `<div class="route-num">${n}</div>`,
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

  const departments = useMemo(
    () =>
      [...new Set(cameras.map((c) => c.department).filter(Boolean))].sort(),
    [cameras]
  );

  const visible = useMemo(
    () =>
      cameras.filter(
        (c) =>
          c.lat != null &&
          c.lon != null &&
          (department === 'all' || c.department === department)
      ),
    [cameras, department]
  );

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
            icon={numberIcon(p.seq)}
          >
            <Popup>
              <div className="popup-title">
                Sighting #{p.seq} — {p.camera_name}
              </div>
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
