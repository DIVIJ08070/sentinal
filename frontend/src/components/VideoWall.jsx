import { useMemo, useState } from 'react';
import { HlsPlayer } from './CameraDrawer.jsx';

const TILE_COUNT = 4;

/**
 * 2x2 wall of live HLS previews. Defaults to the first four live cameras
 * that publish an HLS URL; each tile can be retargeted with its dropdown.
 */
export default function VideoWall({ cameras, onClose }) {
  const candidates = useMemo(
    () => cameras.filter((c) => c.hls_url && c.status === 'live'),
    [cameras]
  );

  const [selection, setSelection] = useState(() =>
    Array.from({ length: TILE_COUNT }, (_, i) =>
      candidates[i] ? candidates[i].id : ''
    )
  );

  const camById = useMemo(() => {
    const map = new Map();
    for (const c of candidates) map.set(c.id, c);
    return map;
  }, [candidates]);

  const setTile = (index, rawId) => {
    const id = rawId === '' ? '' : Number(rawId);
    setSelection((prev) => prev.map((v, i) => (i === index ? id : v)));
  };

  return (
    <div className="videowall-backdrop">
      <div className="videowall">
        <div className="videowall-head">
          <span className="title">Video wall — live cameras</span>
          <button className="btn btn-ghost btn-small" onClick={onClose}>
            Close
          </button>
        </div>

        {candidates.length === 0 ? (
          <div className="empty-state">
            <h3>No live streams available</h3>
            <p>
              No live cameras with an HLS URL were found. Sync the catalogue
              and make sure feeds are up, then reopen the wall.
            </p>
          </div>
        ) : (
          <div className="wall-grid">
            {selection.map((camId, i) => {
              const camera = camId === '' ? null : camById.get(camId) || null;
              return (
                <div key={i} className="wall-tile">
                  <div className="wall-tile-bar">
                    <span className={`dot status-${camera ? camera.status : 'unknown'}`} />
                    <select
                      value={camId === '' ? '' : String(camId)}
                      onChange={(e) => setTile(i, e.target.value)}
                    >
                      <option value="">— no camera —</option>
                      {candidates.map((c) => (
                        <option key={c.id} value={String(c.id)}>
                          {c.name}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="wall-tile-stream">
                    {camera ? (
                      <HlsPlayer key={camera.id} src={camera.hls_url} />
                    ) : (
                      <div className="stream-fallback">No camera selected.</div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
