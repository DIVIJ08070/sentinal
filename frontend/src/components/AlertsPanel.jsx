import { useCallback, useEffect, useMemo, useState } from 'react';
import { api, formatLocal, formatTime, snapshotSrc, vehicleIcon } from '../api.js';
import { groupAlerts } from '../vehicleGroups.js';
import { useAlertsSocket } from '../ws.js';

const FLASH_MS = 3000;

export default function AlertsPanel({ onAlert, onCameraStatus, onLocate, onStatsChanged }) {
  const [alerts, setAlerts] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(null);
  const [flashIds, setFlashIds] = useState(() => new Set());
  const [lastDetection, setLastDetection] = useState(null);
  // 'all' | 'new' — lets an operator hide already-acknowledged alerts (e.g.
  // older demo alerts) so the feed shows only what still needs attention.
  const [statusFilter, setStatusFilter] = useState('all');
  // Vehicle threads: one card per vehicle (latest sighting on top); a thread
  // with several sightings expands on click to show the earlier ones.
  const [expanded, setExpanded] = useState(() => new Set());
  const toggleThread = (key) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  useEffect(() => {
    let cancelled = false;
    api
      .alerts({ limit: 50 })
      .then((data) => {
        if (!cancelled) {
          setAlerts(Array.isArray(data) ? data : []);
          setLoaded(true);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(`Could not load alerts: ${err.message}`);
          setLoaded(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleMessage = useCallback(
    (msg) => {
      if (!msg || typeof msg !== 'object') return;

      if (msg.type === 'alert' && msg.alert) {
        const alert = msg.alert;
        setAlerts((prev) =>
          [alert, ...prev.filter((a) => a.id !== alert.id)].slice(0, 100)
        );
        setFlashIds((prev) => new Set(prev).add(alert.id));
        setTimeout(() => {
          setFlashIds((prev) => {
            const next = new Set(prev);
            next.delete(alert.id);
            return next;
          });
        }, FLASH_MS);
        if (onAlert) onAlert(alert);
      } else if (msg.type === 'camera_status') {
        if (onCameraStatus) onCameraStatus(msg.camera_id, msg.status);
      } else if (msg.type === 'detection' && msg.detection) {
        setLastDetection(msg.detection);
      }
    },
    [onAlert, onCameraStatus]
  );

  const { connected } = useAlertsSocket(handleMessage);

  const ack = async (id) => {
    try {
      await api.ackAlert(id);
      setAlerts((prev) =>
        prev.map((a) =>
          a.id === id
            ? { ...a, status: 'acknowledged', acknowledged_at: new Date().toISOString() }
            : a
        )
      );
      setError(null);
      if (onStatsChanged) onStatsChanged();
    } catch (err) {
      setError(`Acknowledge failed: ${err.message}`);
    }
  };

  // Acknowledge every still-new alert of a vehicle thread in one click.
  const ackThread = async (thread) => {
    for (const a of thread.alerts) {
      if (a.status === 'new') await ack(a.id);
    }
  };

  const visibleAlerts = statusFilter === 'new' ? alerts.filter((a) => a.status === 'new') : alerts;
  const threads = useMemo(() => groupAlerts(visibleAlerts), [visibleAlerts]);

  return (
    <div>
      <div className="panel-title">
        <span>Live alerts</span>
        <span className="ws-status">
          <span className={`dot status-${connected ? 'live' : 'down'}`} />
          {connected ? 'stream connected' : 'reconnecting…'}
        </span>
      </div>

      {lastDetection && (
        <div className="ticker" title={lastDetection.captured_at}>
          Last detection:{' '}
          <span className="plate-sm">{lastDetection.plate || 'vehicle'}</span>
          {' at '}
          {lastDetection.camera_name} · {formatTime(lastDetection.captured_at)}
        </div>
      )}

      {error && <div className="error-note">{error}</div>}

      {alerts.length > 0 && (
        <div className="alert-filter">
          {['all', 'new'].map((f) => (
            <button
              key={f}
              className={`btn btn-ghost btn-small${
                statusFilter === f ? ' filter-active' : ''
              }`}
              onClick={() => setStatusFilter(f)}
            >
              {f === 'all' ? `All (${alerts.length})` : `New (${alerts.filter((a) => a.status === 'new').length})`}
            </button>
          ))}
        </div>
      )}

      {loaded && alerts.length > 0 &&
        statusFilter === 'new' &&
        alerts.every((a) => a.status !== 'new') && (
          <div className="empty-state">
            <h3>No new alerts</h3>
            <p>Every alert has been acknowledged. New ones appear here in real time.</p>
          </div>
        )}

      {loaded && alerts.length === 0 && (
        <div className="empty-state">
          <h3>No alerts yet</h3>
          <p>
            Alerts appear here in real time when a watchlist vehicle is sighted
            on a live feed. Run the simulator (<code>python simulator.py</code>)
            for a full demo.
          </p>
        </div>
      )}

      {threads.map((thread) => {
        const a = thread.latest;
        const wl = a.watchlist || {};
        const cam = a.camera || {};
        const det = a.detection || {};
        const shot = snapshotSrc(det.snapshot_b64);
        const when = det.captured_at || a.created_at;
        const isOpen = expanded.has(thread.key);
        const flashing = thread.ids.some((id) => flashIds.has(id));
        return (
          <div
            key={thread.key}
            className={`alert-card${flashing ? ' flash' : ''}${
              !thread.hasNew ? ' acked' : ''
            }`}
          >
            <div className="alert-head">
              <span className="plate">{a.plate}</span>
              <span className={`badge cat-${wl.category || 'other'}`}>
                {wl.category || 'other'}
              </span>
              <span className={`badge pri-${wl.priority || 'low'}`}>
                {wl.priority || 'low'}
              </span>
              {det.vehicle_type && (
                <span
                  className="badge vehicle"
                  title={`Vehicle type classified by ANPR: ${det.vehicle_type}`}
                >
                  <span className="vehicle-ico" aria-hidden="true">
                    {vehicleIcon(det.vehicle_type)}
                  </span>
                  {det.vehicle_type}
                </span>
              )}
              {thread.count > 1 && (
                <button
                  type="button"
                  className={`badge thread-badge${isOpen ? ' open' : ''}`}
                  onClick={() => toggleThread(thread.key)}
                  title="Same vehicle: OCR variants within one pass and returns on later passes are threaded together — click to see every sighting"
                >
                  {thread.count} sightings · {thread.passes} pass{thread.passes === 1 ? '' : 'es'}{' '}
                  {isOpen ? '▴' : '▾'}
                </button>
              )}
              {a.match_type === 'fuzzy' && (
                <span className="badge fuzzy">
                  fuzzy
                  {a.match_confidence != null
                    ? ` ${Math.round(a.match_confidence * 100)}%`
                    : ''}
                </span>
              )}
              {a.plausibility === 'suspect' && (
                <span
                  className="badge physics-suspect"
                  title={
                    a.plausibility_reason ||
                    'Implied speed from the previous sighting is physically implausible'
                  }
                >
                  &#9888; physics-suspect
                </span>
              )}
            </div>

            {a.plausibility === 'suspect' && a.plausibility_reason && (
              <div className="plausibility-note">
                {a.plausibility_reason} — recall-first: alert kept, the route
                view adjudicates.
              </div>
            )}

            {a.match_type === 'fuzzy' && a.matched_from && (
              <div className="match-note">
                read <span className="mono">{a.matched_from}</span>
                {' → matched '}
                {a.match_confidence != null
                  ? `${Math.round(a.match_confidence * 100)}%`
                  : 'fuzzy'}
              </div>
            )}

            <div className="alert-meta">
              <span>{cam.name || `Camera #${a.camera_id}`}</span>
              <span title={when}>{formatLocal(when)}</span>
            </div>

            {wl.label && <div className="alert-label">{wl.label}</div>}

            {shot && (
              <figure className="snapshot-fig">
                <img className="snapshot" src={shot} alt={`Snapshot of ${a.plate}`} />
                {a.plate && (
                  <figcaption className="snapshot-caption">
                    Enhanced plate close-up
                  </figcaption>
                )}
              </figure>
            )}

            <div className="alert-actions">
              {thread.hasNew ? (
                <button className="btn btn-amber btn-small" onClick={() => ackThread(thread)}>
                  Acknowledge{thread.count > 1 ? ` (${thread.alerts.filter((x) => x.status === 'new').length})` : ''}
                </button>
              ) : (
                <span className="acked-tag">Acknowledged</span>
              )}
              {cam.lat != null && cam.lon != null && (
                <button
                  className="btn btn-ghost btn-small"
                  onClick={() => onLocate(cam.lat, cam.lon)}
                >
                  Locate
                </button>
              )}
            </div>

            {isOpen && thread.count > 1 && (
              <div className="thread-list">
                <div className="thread-list-title">
                  All sightings of this vehicle — newest first
                </div>
                {thread.alerts.map((s) => {
                  const sdet = s.detection || {};
                  const sshot = snapshotSrc(sdet.snapshot_b64);
                  const swhen = sdet.captured_at || s.created_at;
                  const conf = sdet.plate_confidence != null ? sdet.plate_confidence : s.match_confidence;
                  return (
                    <div key={s.id} className={`thread-row${s.status === 'acknowledged' ? ' acked' : ''}`}>
                      {sshot ? (
                        <img className="thread-thumb" src={sshot} alt={`Sighting ${s.plate}`} />
                      ) : (
                        <div className="thread-thumb empty" />
                      )}
                      <div className="thread-info">
                        <div>
                          <span className="plate-sm">{s.plate}</span>
                          {s.match_type === 'fuzzy' && <span className="badge fuzzy">fuzzy</span>}
                          {sdet.vehicle_type && (
                            <span
                              className="badge vehicle"
                              title={`Vehicle type: ${sdet.vehicle_type}`}
                            >
                              <span className="vehicle-ico" aria-hidden="true">
                                {vehicleIcon(sdet.vehicle_type)}
                              </span>
                              {sdet.vehicle_type}
                            </span>
                          )}
                          {conf != null && (
                            <span className="thread-conf">{Math.round(conf * 100)}%</span>
                          )}
                        </div>
                        <div className="thread-when" title={swhen}>
                          {(s.camera || {}).name || `Camera #${s.camera_id}`} · {formatLocal(swhen)}
                        </div>
                      </div>
                      {s.status === 'new' ? (
                        <button className="btn btn-ghost btn-small" onClick={() => ack(s.id)}>
                          Ack
                        </button>
                      ) : (
                        <span className="acked-tag">acked</span>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
