import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from './api.js';
import MapView from './components/MapView.jsx';
import StatsBar from './components/StatsBar.jsx';
import AlertsPanel from './components/AlertsPanel.jsx';
import WatchlistPanel from './components/WatchlistPanel.jsx';
import RouteSearch from './components/RouteSearch.jsx';
import CameraDrawer from './components/CameraDrawer.jsx';
import VideoWall from './components/VideoWall.jsx';
import HealthPanel from './components/HealthPanel.jsx';

const TABS = [
  { id: 'alerts', label: 'Alerts' },
  { id: 'watchlist', label: 'Watchlist' },
  { id: 'route', label: 'Route' },
  { id: 'cameras', label: 'Cameras' },
  { id: 'health', label: 'Health' },
];

function CamerasTab({ cameras, onSelect, onSync, syncing }) {
  const [filter, setFilter] = useState('');

  const shown = useMemo(() => {
    const needle = filter.trim().toLowerCase();
    if (!needle) return cameras;
    return cameras.filter((c) =>
      `${c.name || ''} ${c.department || ''}`.toLowerCase().includes(needle)
    );
  }, [cameras, filter]);

  return (
    <div>
      <div className="panel-title">
        <span>Cameras ({cameras.length})</span>
      </div>
      <div className="cam-toolbar">
        <input
          type="text"
          placeholder="Filter by name or department"
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <button className="btn btn-small" onClick={onSync} disabled={syncing}>
          {syncing ? 'Syncing…' : 'Sync'}
        </button>
      </div>

      {cameras.length === 0 && (
        <div className="empty-state">
          <h3>No cameras onboarded</h3>
          <p>
            Pull the gateway catalogue with the Sync button above
            (<code>POST /api/cameras/sync</code>).
          </p>
        </div>
      )}

      {cameras.length > 0 && shown.length === 0 && (
        <div className="empty-state">
          <p>No cameras match &quot;{filter}&quot;.</p>
        </div>
      )}

      {shown.map((c) => (
        <div key={c.id} className="cam-row" onClick={() => onSelect(c)}>
          <span className={`dot status-${c.status || 'unknown'}`} />
          <div className="cam-info">
            <div className="cam-name">{c.name}</div>
            <div className="cam-meta">
              {c.department || 'Unassigned'}
              {c.lat == null || c.lon == null ? ' · no coordinates' : ''}
            </div>
          </div>
          <span className="cam-codec">
            {(c.codec || '').toUpperCase()}
            {c.width && c.height ? ` ${c.width}x${c.height}` : ''}
          </span>
        </div>
      ))}
    </div>
  );
}

export default function App() {
  const [cameras, setCameras] = useState([]);
  const [stats, setStats] = useState(null);
  const [route, setRoute] = useState(null);
  const [selectedCameraId, setSelectedCameraId] = useState(null);
  const [panTarget, setPanTarget] = useState(null);
  const [activeTab, setActiveTab] = useState('alerts');
  const [wallOpen, setWallOpen] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const loadCameras = useCallback(async () => {
    try {
      setCameras(await api.cameras());
    } catch (err) {
      console.error('Failed to load cameras:', err);
    }
  }, []);

  const loadStats = useCallback(async () => {
    try {
      setStats(await api.stats());
    } catch (err) {
      console.error('Failed to load stats:', err);
    }
  }, []);

  useEffect(() => {
    loadCameras();
    loadStats();
    const statsTimer = setInterval(loadStats, 15000);
    const cameraTimer = setInterval(loadCameras, 60000);
    return () => {
      clearInterval(statsTimer);
      clearInterval(cameraTimer);
    };
  }, [loadCameras, loadStats]);

  const panTo = useCallback((lat, lon) => {
    if (lat == null || lon == null) return;
    setPanTarget({ lat, lon, ts: Date.now() });
  }, []);

  const handleSync = useCallback(async () => {
    setSyncing(true);
    try {
      await api.syncCameras();
      await loadCameras();
      await loadStats();
    } catch (err) {
      console.error('Camera sync failed:', err);
    } finally {
      setSyncing(false);
    }
  }, [loadCameras, loadStats]);

  // A new alert arrived over the WebSocket: pan the map to the sighting
  // camera and refresh the headline counters.
  const handleAlert = useCallback(
    (alert) => {
      const cam = alert && alert.camera;
      if (cam && cam.lat != null && cam.lon != null) panTo(cam.lat, cam.lon);
      loadStats();
    },
    [panTo, loadStats]
  );

  const handleCameraStatus = useCallback((cameraId, status) => {
    setCameras((prev) =>
      prev.map((c) => (c.id === cameraId ? { ...c, status } : c))
    );
  }, []);

  const handleSelectCamera = useCallback(
    (camera) => {
      setSelectedCameraId(camera.id);
      if (camera.lat != null && camera.lon != null) panTo(camera.lat, camera.lon);
    },
    [panTo]
  );

  // Keep the drawer bound to the freshest copy of the camera (WS status
  // updates and periodic refreshes replace the list objects).
  const selectedCamera = useMemo(() => {
    if (selectedCameraId == null) return null;
    return cameras.find((c) => c.id === selectedCameraId) || null;
  }, [cameras, selectedCameraId]);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" />
          <h1>
            SENTINEL <span className="brand-sub">— Unified CCTV Command</span>
          </h1>
        </div>
        <StatsBar stats={stats} />
        <button className="btn btn-ghost" onClick={() => setWallOpen(true)}>
          Video Wall
        </button>
      </header>

      <div className="main">
        <div className="map-area">
          <MapView
            cameras={cameras}
            route={route}
            panTarget={panTarget}
            onSelectCamera={handleSelectCamera}
            onSync={handleSync}
            syncing={syncing}
          />
          {selectedCamera && (
            <CameraDrawer
              camera={selectedCamera}
              onClose={() => setSelectedCameraId(null)}
            />
          )}
        </div>

        <aside className="side-panel">
          <nav className="tabs">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                className={`tab-btn${activeTab === tab.id ? ' active' : ''}`}
                onClick={() => setActiveTab(tab.id)}
              >
                {tab.label}
                {tab.id === 'alerts' && stats && stats.alerts_new > 0 && (
                  <span className="tab-badge">{stats.alerts_new}</span>
                )}
              </button>
            ))}
          </nav>

          {/* Panels stay mounted (hidden via CSS) so the alerts WebSocket
              keeps streaming while other tabs are open. */}
          <div className={`tab-page${activeTab === 'alerts' ? ' active' : ''}`}>
            <AlertsPanel
              onAlert={handleAlert}
              onCameraStatus={handleCameraStatus}
              onLocate={panTo}
              onStatsChanged={loadStats}
            />
          </div>
          <div className={`tab-page${activeTab === 'watchlist' ? ' active' : ''}`}>
            <WatchlistPanel onStatsChanged={loadStats} />
          </div>
          <div className={`tab-page${activeTab === 'route' ? ' active' : ''}`}>
            <RouteSearch onRoute={setRoute} onLocate={panTo} />
          </div>
          <div className={`tab-page${activeTab === 'cameras' ? ' active' : ''}`}>
            <CamerasTab
              cameras={cameras}
              onSelect={handleSelectCamera}
              onSync={handleSync}
              syncing={syncing}
            />
          </div>
          <div className={`tab-page${activeTab === 'health' ? ' active' : ''}`}>
            <HealthPanel />
          </div>
        </aside>
      </div>

      {wallOpen && <VideoWall cameras={cameras} onClose={() => setWallOpen(false)} />}
    </div>
  );
}
