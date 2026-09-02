import { useEffect, useState } from 'react';
import { api } from '../api.js';

const REFRESH_MS = 5000;

// A feed is DEGRADED when it claims to be live but frames have stopped
// arriving (stale last-frame age) or delivery has collapsed to under 1 fps.
const STALE_FRAME_S = 10;

function fmtFps(v) {
  return v == null ? '—' : Number(v).toFixed(1);
}

function fmtAge(s) {
  if (s == null) return '—';
  if (s < 10) return `${Number(s).toFixed(1)}s`;
  if (s < 120) return `${Math.round(s)}s`;
  return `${Math.round(s / 60)}m`;
}

function fmtBandwidth(kbps) {
  if (kbps == null) return '—';
  if (kbps >= 1000) return `${(kbps / 1000).toFixed(1)} Mbps`;
  return `${Math.round(kbps)} Kbps`;
}

/**
 * ok | degraded | reconnecting | unknown.
 * "down" means the capture worker lost the feed and is in its backoff
 * reconnect loop — the kill-a-feed demo beat renders as amber "reconnecting"
 * here until the heartbeat flips the camera live again.
 */
function feedState(c) {
  if (c.status === 'down') return 'reconnecting';
  if (c.status !== 'live') return 'unknown';
  if (
    (c.last_frame_age_s != null && c.last_frame_age_s > STALE_FRAME_S) ||
    (c.fps_measured != null && c.fps_measured < 1)
  ) {
    return 'degraded';
  }
  return 'ok';
}

const STATE_RANK = { reconnecting: 0, degraded: 1, ok: 2, unknown: 3 };

/**
 * Camera health board (GET /api/health/summary, auto-refresh every 5 s):
 * measured delivery FPS, last-frame age, reconnect count and bandwidth per
 * feed, with the totals pinned on top. Problem feeds (amber) sort first so
 * the kill-a-feed moment is impossible to miss.
 */
export default function HealthPanel() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const summary = await api.healthSummary();
        if (!cancelled) {
          setData(summary);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) setError(err.message);
      }
    };

    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  const cameras = data && Array.isArray(data.per_camera) ? data.per_camera : [];
  const totals = (data && data.totals) || {};

  const rows = [...cameras].sort((a, b) => {
    const rank = STATE_RANK[feedState(a)] - STATE_RANK[feedState(b)];
    return rank !== 0 ? rank : a.camera_id - b.camera_id;
  });

  const perCamKbps =
    totals.total_bandwidth_kbps != null && totals.streams_up > 0
      ? Math.round(totals.total_bandwidth_kbps / totals.streams_up)
      : null;

  // Measured upstream metadata rate (detection POST bytes over the rolling
  // window) — the live counterpart of the video figure: the 1000x edge story
  // as two numbers on one board instead of a caption.
  const metaKbps = totals.metadata_kbps_upstream;
  const metaPerCam =
    metaKbps != null && totals.streams_up > 0
      ? metaKbps / totals.streams_up
      : null;
  const fmtMetaKbps = (v) =>
    v == null ? '—' : v >= 10 ? `${Math.round(v)} Kbps` : `${Number(v).toFixed(1)} Kbps`;

  return (
    <div>
      <div className="panel-title">
        <span>Camera health</span>
        <span className="ws-status">auto-refresh {REFRESH_MS / 1000}s</span>
      </div>

      {error && (
        <div className="error-note">Health summary unavailable: {error}</div>
      )}

      {data && (
        <div className="health-totals">
          <div className="health-chips">
            <div className="stat-chip">
              <span className="stat-label">Streams up</span>
              <span className="stat-value ok">
                {totals.streams_up ?? '—'}
                <span className="stat-denom">/{cameras.length}</span>
              </span>
            </div>
            <div className="stat-chip">
              <span className="stat-label">Avg FPS</span>
              <span className="stat-value">{fmtFps(totals.avg_fps)}</span>
            </div>
            <div className="stat-chip">
              <span className="stat-label">Reconnects 1h</span>
              <span className="stat-value">{totals.reconnects_1h ?? '—'}</span>
            </div>
            <div className="stat-chip" title="Sum of measured stream bandwidth over live cameras — this video never leaves the edge">
              <span className="stat-label">Video (edge)</span>
              <span className="stat-value">
                {fmtBandwidth(totals.total_bandwidth_kbps)}
              </span>
            </div>
            <div
              className="stat-chip"
              title={`Measured from actual detection POST payload bytes over the last ${
                totals.metadata_window_s ? Math.round(totals.metadata_window_s / 60) : 10
              } min (${totals.detections_window ?? 0} detections) — the only traffic that goes upstream`}
            >
              <span className="stat-label">Metadata upstream</span>
              <span className="stat-value ok">{fmtMetaKbps(metaKbps)}</span>
            </div>
          </div>
          <div className="health-caption">
            {perCamKbps != null
              ? `Video at the edge: ~${fmtBandwidth(perCamKbps)}/camera. `
              : 'Video stays at the edge. '}
            {metaPerCam != null
              ? `Metadata upstream: ~${fmtMetaKbps(metaPerCam)}/camera, measured live — `
              : 'Metadata upstream: ~1–3 Kbps/camera — '}
            the ratio that makes 80,000 cameras a metadata problem, not a
            160 Gbps video problem.
          </div>
        </div>
      )}

      {data && cameras.length === 0 && (
        <div className="empty-state">
          <h3>No cameras onboarded</h3>
          <p>
            Sync the gateway catalogue first (<code>POST /api/cameras/sync</code>);
            per-feed metrics arrive with ingest heartbeats.
          </p>
        </div>
      )}

      {!data && !error && (
        <div className="empty-state">
          <p>Loading health summary…</p>
        </div>
      )}

      {rows.length > 0 && (
        <div className="table-wrap">
          <table className="data-table health-table">
            <thead>
              <tr>
                <th>Camera</th>
                <th title="Measured delivery FPS (frame-count delta / wall time)">FPS</th>
                <th title="Seconds since the last decoded frame">Age</th>
                <th title="Successful reconnects this worker session">Rec</th>
                <th title="Measured/estimated stream bandwidth">BW</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => {
                const state = feedState(c);
                const amber = state === 'reconnecting' || state === 'degraded';
                return (
                  <tr
                    key={c.camera_id}
                    className={amber ? 'row-amber' : ''}
                    title={c.last_seen_at ? `Last seen ${c.last_seen_at}` : undefined}
                  >
                    <td>
                      <div className="health-cam">
                        <span className={`dot status-${c.status || 'unknown'}`} />
                        <span className="health-cam-name">{c.name}</span>
                      </div>
                      <div className="cell-sub">
                        {c.department || 'Unassigned'}
                        {amber && (
                          <span className={`health-state ${state}`}>
                            {state === 'reconnecting' ? 'reconnecting…' : 'degraded'}
                          </span>
                        )}
                      </div>
                    </td>
                    <td>{fmtFps(c.fps_measured)}</td>
                    <td>{fmtAge(c.last_frame_age_s)}</td>
                    <td>{c.reconnects ?? '—'}</td>
                    <td>{fmtBandwidth(c.bandwidth_kbps)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
