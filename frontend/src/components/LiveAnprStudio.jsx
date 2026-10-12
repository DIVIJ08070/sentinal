import { useState, useEffect, useRef } from 'react';
import { api, vehicleIcon } from '../api.js';

const VIDEO_ANPR_BASE = 'http://localhost:8895';

export default function LiveAnprStudio({ onClose, onTraceRoute }) {
  const [status, setStatus] = useState(null);
  const [detections, setDetections] = useState([]);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadMessage, setUploadMessage] = useState('');
  const [watchlistSuccess, setWatchlistSuccess] = useState(null);
  const fileInputRef = useRef(null);

  // Poll status and recent detections
  useEffect(() => {
    let active = true;

    const fetchStatusAndDetections = async () => {
      try {
        const [resStatus, resDets] = await Promise.all([
          fetch(`${VIDEO_ANPR_BASE}/api/video-anpr/status`).then((r) => r.json()),
          fetch(`${VIDEO_ANPR_BASE}/api/video-anpr/detections`).then((r) => r.json()),
        ]);
        if (active) {
          setStatus(resStatus);
          setDetections(resDets);
        }
      } catch (err) {
        console.warn('Video ANPR service not reachable:', err);
      }
    };

    fetchStatusAndDetections();
    const interval = setInterval(fetchStatusAndDetections, 1200);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, []);

  const handleControl = async (action) => {
    try {
      const res = await fetch(`${VIDEO_ANPR_BASE}/api/video-anpr/control`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action }),
      });
      const data = await res.json();
      setStatus(data);
    } catch (err) {
      console.error('Control action failed:', err);
    }
  };

  const handleLoadDaytime = async () => {
    try {
      await fetch(`${VIDEO_ANPR_BASE}/api/video-anpr/play`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          video_path: 'cam06_daytime.mp4',
          camera_id: 6,
          camera_name: 'Madhuram Bypass Road Fix-2 (cam06 daytime)',
          loop: true,
        }),
      });
      setUploadMessage('Loaded: Cam06 Daytime Ground Truth');
      setTimeout(() => setUploadMessage(''), 4000);
    } catch (err) {
      console.error('Load video failed:', err);
    }
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    setUploadMessage(`Uploading ${file.name}…`);
    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch(`${VIDEO_ANPR_BASE}/api/video-anpr/upload`, {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();
      if (res.ok) {
        setUploadMessage(`Analyzing ${file.name} live!`);
      } else {
        setUploadMessage(`Error: ${data.detail || 'Upload failed'}`);
      }
    } catch (err) {
      setUploadMessage(`Upload error: ${err.message}`);
    } finally {
      setIsUploading(false);
      setTimeout(() => setUploadMessage(''), 5000);
    }
  };

  const handleAddToWatchlist = async (plate) => {
    try {
      await api.addWatchlistEntry({
        plate,
        label: `Flagged from Live ANPR Studio`,
        category: 'suspect',
        priority: 'high',
        active: true,
      });
      setWatchlistSuccess(plate);
      setTimeout(() => setWatchlistSuccess(null), 3000);
    } catch (err) {
      console.error('Failed to add to watchlist:', err);
    }
  };

  return (
    <div className="anpr-studio-backdrop">
      <div className="anpr-studio-modal">
        {/* Studio Header */}
        <div className="anpr-studio-head">
          <div className="anpr-studio-title-group">
            <span className="live-pulse-dot" />
            <h2 className="anpr-studio-title">LIVE VIDEO ANPR STUDIO</h2>
            <span className="anpr-studio-badge">YOLOv8 + RapidOCR</span>
          </div>

          <div className="anpr-studio-head-actions">
            <span className="hud-metric">
              FPS: <b>25</b>
            </span>
            <span className="hud-metric">
              Vehicles: <b>{status?.vehicles_in_frame ?? 0}</b>
            </span>
            <span className="hud-metric">
              Plates in frame: <b>{status?.plates_in_frame ?? 0}</b>
            </span>
            <button className="btn btn-ghost btn-small" onClick={onClose}>
              ✕ Close
            </button>
          </div>
        </div>

        {/* Toolbar */}
        <div className="anpr-studio-toolbar">
          <div className="toolbar-left">
            <button
              className="btn btn-primary btn-small"
              onClick={handleLoadDaytime}
              title="Switch to Cam06 Daytime Ground Truth clip"
            >
              ☀️ Cam06 Daylight HD
            </button>

            <button
              className="btn btn-ghost btn-small"
              onClick={() => fileInputRef.current?.click()}
              disabled={isUploading}
            >
              {isUploading ? 'Uploading…' : '📁 Upload Any Video'}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".mp4,.avi,.mov,.mkv,.ts"
              style={{ display: 'none' }}
              onChange={handleFileUpload}
            />

            <button
              className="btn btn-ghost btn-small"
              onClick={() => handleControl('toggle_pause')}
            >
              {status?.is_paused ? '▶ Resume' : '⏸ Pause'}
            </button>

            <button
              className="btn btn-ghost btn-small"
              onClick={() => handleControl('restart')}
            >
              ↺ Restart Clip
            </button>

            <label className="checkbox-toggle">
              <input
                type="checkbox"
                checked={status?.sync_backend ?? true}
                onChange={() => handleControl('toggle_sync')}
              />
              <span>Sync to Sentinel Live Alerts</span>
            </label>
          </div>

          <div className="toolbar-right">
            {uploadMessage && <span className="upload-notice">{uploadMessage}</span>}
            <span className="active-video-label">
              Feed: <b>{status?.video_path || 'cam06_daytime.mp4'}</b>
            </span>
          </div>
        </div>

        {/* Studio Body: Split View */}
        <div className="anpr-studio-body">
          {/* Main Video Stage */}
          <div className="anpr-video-stage">
            <div className="anpr-stream-wrapper">
              <img
                src={`${VIDEO_ANPR_BASE}/api/video-anpr/stream.mjpg`}
                alt="Live ANPR Stream"
                className="anpr-stream-img"
                onError={(e) => {
                  e.target.style.display = 'none';
                  e.target.nextSibling.style.display = 'flex';
                }}
              />
              <div className="anpr-stream-fallback" style={{ display: 'none' }}>
                <h3>Video ANPR Engine Connecting…</h3>
                <p>Starting background detector and stream at {VIDEO_ANPR_BASE}</p>
              </div>

              {/* HUD Overlay Pill */}
              <div className="stream-hud-pill">
                <span className="live-dot" />
                <span>{status?.camera_name || 'Camera Feed'}</span>
                <span className="hud-sep">•</span>
                <span>{status?.frame_count || 0} frames</span>
              </div>
            </div>
          </div>

          {/* Detections Feed Sidebar */}
          <div className="anpr-detections-sidebar">
            <div className="sidebar-head">
              <h3>REAL-TIME DETECTIONS</h3>
              <span className="count-badge">{detections.length} reads</span>
            </div>

            <div className="detections-scroll">
              {detections.length === 0 ? (
                <div className="empty-detections">
                  <p>Awaiting passing vehicles…</p>
                  <span className="dim-sub">Plates will appear here with instant OCR validation</span>
                </div>
              ) : (
                detections.map((det, idx) => (
                  <div key={`${det.plate}-${idx}`} className="detection-card">
                    <div className="card-top">
                      <span className="plate-badge">{det.plate}</span>
                      <span className="vtype-pill">
                        {vehicleIcon(det.vehicle_type)} {det.vehicle_type}
                      </span>
                    </div>

                    <div className="card-meta">
                      <div className="conf-bar-group">
                        <span className="conf-lbl">OCR Confidence:</span>
                        <div className="conf-bar-track">
                          <div
                            className="conf-bar-fill"
                            style={{
                              width: `${Math.round(det.confidence * 100)}%`,
                              background:
                                det.confidence >= 0.85
                                  ? 'var(--green)'
                                  : det.confidence >= 0.6
                                  ? 'var(--amber)'
                                  : 'var(--red)',
                            }}
                          />
                        </div>
                        <span className="conf-pct">
                          {Math.round(det.confidence * 100)}%
                        </span>
                      </div>

                      <span className="time-lbl">
                        {new Date(det.detected_at).toLocaleTimeString()}
                      </span>
                    </div>

                    {det.snapshot_b64 && (
                      <div className="card-snapshot">
                        <img
                          src={`data:image/jpeg;base64,${det.snapshot_b64}`}
                          alt="Plate crop"
                          className="snapshot-thumb"
                        />
                      </div>
                    )}

                    <div className="card-actions">
                      {onTraceRoute && (
                        <button
                          className="btn btn-ghost btn-xs"
                          onClick={() => {
                            onTraceRoute(det.plate);
                            onClose();
                          }}
                          title="Trace vehicle trajectory across all 30 cameras"
                        >
                          🎯 Trace Route
                        </button>
                      )}

                      <button
                        className="btn btn-ghost btn-xs"
                        onClick={() => handleAddToWatchlist(det.plate)}
                        disabled={watchlistSuccess === det.plate}
                      >
                        {watchlistSuccess === det.plate
                          ? '✓ Added'
                          : '+ Watchlist'}
                      </button>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
