import { useEffect, useState } from 'react';

function Stat({ label, value, dot, accent, title }) {
  return (
    <div className={`stat-chip${accent ? ' accent' : ''}`} title={title}>
      {dot && <span className={`dot status-${dot}`} />}
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value ?? '—'}</span>
    </div>
  );
}

/**
 * Liveness heartbeat: "N s ago" since the pipeline last delivered data,
 * ticking every second between stats polls. Green while fresh, grey once the
 * pipeline has been quiet for a minute, red after five — so anyone watching
 * can see the numbers are arriving now, not loaded from a file.
 */
function ageLabel(iso, now) {
  if (!iso) return { text: '—', dot: 'unknown' };
  const secs = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  const text = secs < 60 ? `${secs} s ago`
    : secs < 3600 ? `${Math.floor(secs / 60)} min ago`
    : `${Math.floor(secs / 3600)} h ago`;
  return { text, dot: secs < 60 ? 'live' : secs < 300 ? 'unknown' : 'down' };
}

export default function StatsBar({ stats }) {
  const cams = stats ? stats.cameras : null;
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  const lastRead = ageLabel(stats ? stats.last_detection_at : null, now);
  const lastAlert = ageLabel(stats ? stats.last_alert_at : null, now);
  return (
    <div className="stats-bar">
      <Stat label="Cameras" value={cams ? cams.total : null} />
      <Stat label="Live" value={cams ? cams.live : null} dot="live" />
      <Stat label="Down" value={cams ? cams.down : null} dot="down" />
      <Stat label="Unknown" value={cams ? cams.unknown : null} dot="unknown" />
      <div className="stats-sep" />
      <Stat label="Watchlist" value={stats ? stats.watchlist_active : null} />
      <Stat label="Detections 24h" value={stats ? stats.detections_24h : null} />
      <Stat
        label="New alerts"
        value={stats ? stats.alerts_new : null}
        accent={Boolean(stats && stats.alerts_new > 0)}
      />
      <Stat label="Total alerts" value={stats ? stats.alerts_total : null} />
      <div className="stats-sep" />
      <Stat
        label="Last read"
        value={lastRead.text}
        dot={lastRead.dot}
        title={stats && stats.last_detection_at ? `Last detection received ${stats.last_detection_at}` : 'No detections yet'}
      />
      <Stat
        label="Last alert"
        value={lastAlert.text}
        dot={lastAlert.dot}
        title={stats && stats.last_alert_at ? `Last alert raised ${stats.last_alert_at}` : 'No alerts yet'}
      />
    </div>
  );
}
