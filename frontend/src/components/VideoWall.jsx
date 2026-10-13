import { useEffect, useMemo, useState } from 'react';
import { StreamView } from './CameraDrawer.jsx';

const TILE_COUNT = 4;
const DEFAULT_CAM_TARGETS = [
  { ext: 'cam01', id: 1 },
  { ext: 'cam02', id: 2 },
  { ext: 'cam03', id: 3 },
  { ext: 'cam05', id: 5 },
];

function pickDefaultCams(candidates) {
  const chosen = [];
  for (const target of DEFAULT_CAM_TARGETS) {
    const match = candidates.find(
      (c) => c.external_id === target.ext || c.id === target.id
    );
    if (match && !chosen.includes(match.id)) {
      chosen.push(match.id);
    }
  }
  for (const c of candidates) {
    if (chosen.length >= TILE_COUNT) break;
    if (!chosen.includes(c.id)) chosen.push(c.id);
  }
  return Array.from({ length: TILE_COUNT }, (_, i) => chosen[i] ?? '');
}

/**
 * 2x2 wall of live HLS previews. Defaults to cam 1, 2, 3 and 5; each tile
 * can be retargeted with its dropdown.
 */
export default function VideoWall({ cameras, onClose }) {
  const candidates = useMemo(
    () => cameras.filter((c) => Boolean(c.hls_url)),
    [cameras]
  );

  const [selection, setSelection] = useState(() => pickDefaultCams(candidates));

  useEffect(() => {
    if (selection.every((id) => id === '') && candidates.length > 0) {
      setSelection(pickDefaultCams(candidates));
    }
  }, [candidates, selection]);

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
                      <StreamView key={camera.id} camera={camera} scope={`wall.${i}`} compact />
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
