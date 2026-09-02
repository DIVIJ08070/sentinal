function Stat({ label, value, dot, accent }) {
  return (
    <div className={`stat-chip${accent ? ' accent' : ''}`}>
      {dot && <span className={`dot status-${dot}`} />}
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value ?? '—'}</span>
    </div>
  );
}

export default function StatsBar({ stats }) {
  const cams = stats ? stats.cameras : null;
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
    </div>
  );
}
