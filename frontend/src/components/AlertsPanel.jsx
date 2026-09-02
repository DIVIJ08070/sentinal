import { useCallback, useEffect, useState } from 'react';
import { api, formatLocal, formatTime, snapshotSrc } from '../api.js';
import { useAlertsSocket } from '../ws.js';

const FLASH_MS = 3000;

export default function AlertsPanel({ onAlert, onCameraStatus, onLocate, onStatsChanged }) {
  const [alerts, setAlerts] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(null);
  const [flashIds, setFlashIds] = useState(() => new Set());
  const [lastDetection, setLastDetection] = useState(null);

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

      {alerts.map((a) => {
        const wl = a.watchlist || {};
        const cam = a.camera || {};
        const det = a.detection || {};
        const shot = snapshotSrc(det.snapshot_b64);
        const when = det.captured_at || a.created_at;
        return (
          <div
            key={a.id}
            className={`alert-card${flashIds.has(a.id) ? ' flash' : ''}${
              a.status === 'acknowledged' ? ' acked' : ''
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
              {a.match_type === 'fuzzy' && (
                <span className="badge fuzzy">
                  fuzzy
                  {a.match_confidence != null
                    ? ` ${Math.round(a.match_confidence * 100)}%`
                    : ''}
                </span>
              )}
            </div>

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
              <img className="snapshot" src={shot} alt={`Snapshot of ${a.plate}`} />
            )}

            <div className="alert-actions">
              {a.status === 'new' ? (
                <button className="btn btn-amber btn-small" onClick={() => ack(a.id)}>
                  Acknowledge
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
          </div>
        );
      })}
    </div>
  );
}
