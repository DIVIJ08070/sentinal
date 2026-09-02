import { useEffect, useRef, useState } from 'react';
import { api, dossierPdfUrl, formatLocal, snapshotSrc } from '../api.js';

function pct(v) {
  return v == null ? null : `${Math.round(v * 100)}%`;
}

/**
 * Route reconstruction (the hackathon test case): search a plate, render the
 * sightings table + stats, and lift the route to App so MapView can draw the
 * numbered markers and polyline.
 *
 * Physics filter (backend v0.2): rejected sightings are still returned in
 * `points` — rendered struck-through/greyed with the plain-language
 * `rejected_reason`; accepted legs carry `leg_km` / `implied_speed_kmh`
 * chips; fuzzy matches show `match_confidence` + the raw `matched_from` read.
 */
export default function RouteSearch({ onRoute, onLocate, initialPlate = '' }) {
  const [plate, setPlate] = useState(initialPlate);
  const [since, setSince] = useState('');
  const [until, setUntil] = useState('');
  const [route, setRoute] = useState(null);
  const [searchWindow, setSearchWindow] = useState({}); // {since, until} of the last search — reused for the dossier export
  const [status, setStatus] = useState('idle'); // idle | loading | done | empty | error
  const [error, setError] = useState(null);
  const autoTraced = useRef(false);

  const runTrace = async (p) => {
    if (!p) return;
    setStatus('loading');
    setError(null);
    try {
      const params = {};
      if (since) params.since = new Date(since).toISOString();
      if (until) params.until = new Date(until).toISOString();
      const data = await api.vehicleRoute(p, params);
      if (!data || !Array.isArray(data.points) || data.points.length === 0) {
        setRoute(null);
        onRoute(null);
        setStatus('empty');
      } else {
        setRoute(data);
        setSearchWindow(params);
        onRoute(data);
        setStatus('done');
      }
    } catch (err) {
      setRoute(null);
      onRoute(null);
      setError(err.message);
      setStatus('error');
    }
  };

  const search = (e) => {
    e.preventDefault();
    runTrace(plate.trim());
  };

  // Deep link (?tab=route&trace=PLATE): run the trace once on mount.
  useEffect(() => {
    if (initialPlate && !autoTraced.current) {
      autoTraced.current = true;
      runTrace(initialPlate.trim());
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const clear = () => {
    setPlate('');
    setSince('');
    setUntil('');
    setRoute(null);
    setSearchWindow({});
    setStatus('idle');
    setError(null);
    onRoute(null);
  };

  const stats = route ? route.stats : null;

  // W2 guard: every returned point is a fuzzy candidate — there is NO exact
  // sighting of the searched plate. Say so loudly before the table, so the
  // route reads as "confusion-tolerant candidates, ranked" and never as
  // "another vehicle's route presented as this plate's".
  const allFuzzy =
    route && route.points.length > 0 && route.points.every((p) => p.fuzzy);
  const bestFuzzy = allFuzzy
    ? Math.max(...route.points.map((p) => p.match_confidence || 0))
    : null;

  return (
    <div>
      <div className="panel-title">
        <span>Route reconstruction</span>
      </div>

      <form className="route-form" onSubmit={search}>
        <label className="field">
          Vehicle plate
          <input
            type="text"
            placeholder="GJ01AB1234"
            value={plate}
            onChange={(e) => setPlate(e.target.value)}
            required
          />
        </label>
        <div className="row">
          <label className="field">
            Since (optional)
            <input
              type="datetime-local"
              value={since}
              onChange={(e) => setSince(e.target.value)}
            />
          </label>
          <label className="field">
            Until (optional)
            <input
              type="datetime-local"
              value={until}
              onChange={(e) => setUntil(e.target.value)}
            />
          </label>
        </div>
        <div className="row">
          <button className="btn btn-amber" type="submit" disabled={status === 'loading'}>
            {status === 'loading' ? 'Tracing…' : 'Trace route'}
          </button>
          <button className="btn btn-ghost" type="button" onClick={clear}>
            Clear
          </button>
        </div>
      </form>

      {status === 'error' && (
        <div className="error-note">Route lookup failed: {error}</div>
      )}

      {status === 'empty' && (
        <div className="empty-state">
          <h3>No route found</h3>
          <p>
            No sightings of <code>{plate.trim().toUpperCase()}</code> in the
            selected time window. Widen the window or verify the plate.
          </p>
        </div>
      )}

      {status === 'idle' && (
        <div className="empty-state">
          <p>
            Enter a vehicle registration number to trace its complete,
            timestamped movement across the camera network.
          </p>
        </div>
      )}

      {route && stats && (
        <div>
          {allFuzzy && (
            <div className="all-fuzzy-banner">
              <strong>
                No exact sightings of <span className="mono">{route.plate}</span>.
              </strong>{' '}
              Showing {route.points.length} confusion-tolerant candidate
              sighting{route.points.length === 1 ? '' : 's'}
              {bestFuzzy ? ` (best match ${pct(bestFuzzy)})` : ''} — every row
              is flagged <span className="badge fuzzy">fuzzy</span> at its own
              confidence, ranked and never silently merged. Verify the raw OCR
              read on each row before treating this as the vehicle&apos;s route.
            </div>
          )}
          <div className="route-stats">
            <div className="route-stat">
              <div className="k">First seen</div>
              <div className="v" title={stats.first_seen}>
                {formatLocal(stats.first_seen)}
              </div>
            </div>
            <div className="route-stat">
              <div className="k">Last seen</div>
              <div className="v" title={stats.last_seen}>
                {formatLocal(stats.last_seen)}
              </div>
            </div>
            <div className="route-stat">
              <div className="k">Cameras</div>
              <div className="v">{stats.cameras_count}</div>
            </div>
            <div className="route-stat">
              <div className="k">Sightings</div>
              <div className="v">{stats.sightings_count}</div>
            </div>
            <div className="route-stat">
              <div className="k">Distance</div>
              <div className="v">
                {stats.distance_km != null ? `${Number(stats.distance_km).toFixed(1)} km` : '—'}
              </div>
            </div>
            <div className="route-stat">
              <div className="k">Plate</div>
              <div className="v plate-sm">{route.plate}</div>
            </div>
            {stats.rejected_count != null && (
              <div
                className={`route-stat${stats.rejected_count > 0 ? ' route-stat-rejected' : ''}`}
                title="Sightings discarded by the physics plausibility filter (impossible implied speed between cameras)"
              >
                <div className="k">Physics-rejected</div>
                <div className="v">{stats.rejected_count}</div>
              </div>
            )}
          </div>

          <a
            className="dossier-btn"
            href={dossierPdfUrl(route.plate, searchWindow)}
            target="_blank"
            rel="noreferrer"
            title="Court-ready PDF: hashed sightings, camera/GPS/timestamp table, chain-of-custody header"
          >
            Export Evidence Dossier (PDF)
            <span className="dossier-sub">SHA-256 chain-of-custody sealed</span>
          </a>

          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Camera</th>
                  <th>Time</th>
                  <th>Match</th>
                </tr>
              </thead>
              <tbody>
                {route.points.map((p, i) => {
                  const rejected = !!p.rejected;
                  const clickable = p.lat != null && p.lon != null;
                  const rowClass = [
                    clickable ? 'clickable' : '',
                    rejected ? 'row-rejected' : '',
                  ]
                    .filter(Boolean)
                    .join(' ');
                  return (
                    <tr
                      key={`${p.camera_id}-${p.captured_at}-${i}`}
                      className={rowClass}
                      onClick={() => {
                        if (clickable) onLocate(p.lat, p.lon);
                      }}
                      title={
                        rejected
                          ? p.rejected_reason || 'Rejected by the physics filter'
                          : clickable
                            ? 'Click to locate on map'
                            : undefined
                      }
                    >
                      <td>{i + 1}</td>
                      <td>
                        <span className={rejected ? 'strike' : ''}>{p.camera_name}</span>
                        <div className="cell-sub">{p.department || ''}</div>
                        {snapshotSrc(p.snapshot_b64) && (
                          <img
                            className={`route-snap${rejected ? ' route-snap-rejected' : ''}`}
                            src={snapshotSrc(p.snapshot_b64)}
                            alt={`Evidence snapshot, sighting ${i + 1}`}
                          />
                        )}
                        {rejected ? (
                          <div className="rejected-reason">
                            &#9888; {p.rejected_reason ||
                              'physically impossible hop — discarded as false ANPR match'}
                          </div>
                        ) : (
                          <>
                            {p.fuzzy && p.matched_from && (
                              <div className="match-note">
                                read <span className="mono">{p.matched_from}</span>
                                {' → matched '}
                                {pct(p.match_confidence) || 'fuzzy'}
                              </div>
                            )}
                            {(p.leg_km != null || p.implied_speed_kmh != null) && (
                              <div className="leg-chips">
                                {p.leg_km != null && (
                                  <span className="leg-chip" title="Haversine distance from the previous accepted sighting">
                                    {Number(p.leg_km).toFixed(1)} km
                                  </span>
                                )}
                                {p.implied_speed_kmh != null && (
                                  <span className="leg-chip speed" title="Implied speed over this leg">
                                    {Math.round(p.implied_speed_kmh)} km/h
                                  </span>
                                )}
                              </div>
                            )}
                          </>
                        )}
                      </td>
                      <td title={p.captured_at}>
                        <span className={rejected ? 'strike' : ''}>{formatLocal(p.captured_at)}</span>
                      </td>
                      <td title={p.confidence != null ? `OCR confidence ${pct(p.confidence)}` : undefined}>
                        {rejected ? (
                          <span className="badge rejected">rejected</span>
                        ) : (
                          <>
                            {pct(p.match_confidence != null ? p.match_confidence : p.confidence) || '—'}
                            {p.fuzzy && (
                              <div>
                                <span className="badge fuzzy">fuzzy</span>
                              </div>
                            )}
                          </>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
