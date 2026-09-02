import { useEffect, useRef, useState } from 'react';
import Hls from 'hls.js';
import { formatLocal } from '../api.js';

/**
 * Shared HLS player. Attaches hls.js when supported (falls back to native HLS
 * on Safari), destroys the instance on unmount/src change, and degrades to a
 * "stream unavailable" message on fatal errors. Also used by VideoWall.
 */
export function HlsPlayer({ src }) {
  const videoRef = useRef(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setFailed(false);
    if (!src) return undefined;
    const video = videoRef.current;
    if (!video) return undefined;

    if (Hls.isSupported()) {
      let hls = new Hls({ liveDurationInfinity: true });
      hls.on(Hls.Events.ERROR, (_event, data) => {
        if (data && data.fatal) {
          setFailed(true);
          if (hls) {
            hls.destroy();
            hls = null;
          }
        }
      });
      hls.on(Hls.Events.MANIFEST_PARSED, () => {
        // Autoplay attribute alone doesn't fire when the source attaches
        // after mount; muted play() is allowed by browser autoplay policy.
        video.play().catch(() => {});
      });
      hls.loadSource(src);
      hls.attachMedia(video);
      return () => {
        if (hls) hls.destroy();
      };
    }

    if (video.canPlayType('application/vnd.apple.mpegurl')) {
      const onError = () => setFailed(true);
      video.addEventListener('error', onError);
      video.src = src;
      return () => {
        video.removeEventListener('error', onError);
        video.removeAttribute('src');
        video.load();
      };
    }

    setFailed(true);
    return undefined;
  }, [src]);

  if (!src) {
    return (
      <div className="stream-fallback">
        No HLS stream URL published for this camera.
      </div>
    );
  }
  if (failed) {
    return <div className="stream-fallback">Stream unavailable.</div>;
  }
  return (
    <video
      ref={videoRef}
      className="stream-video"
      autoPlay
      muted
      playsInline
      controls
    />
  );
}

function MetaRow({ k, v, mono, title }) {
  return (
    <>
      <div className="k">{k}</div>
      <div className={`v${mono ? ' mono' : ''}`} title={title}>
        {v ?? '—'}
      </div>
    </>
  );
}

export default function CameraDrawer({ camera, onClose }) {
  if (!camera) return null;

  return (
    <div className="camera-drawer">
      <div className="drawer-head">
        <span className={`dot status-${camera.status || 'unknown'}`} />
        <div className="drawer-title">{camera.name}</div>
        <button className="btn btn-ghost btn-small" onClick={onClose}>
          Close
        </button>
      </div>

      <div className="drawer-body">
        <div className="stream-box">
          <HlsPlayer src={camera.hls_url} />
        </div>

        <div className="meta-grid">
          <MetaRow
            k="Camera ID"
            v={camera.external_id ? `${camera.id} (ext ${camera.external_id})` : camera.id}
          />
          <MetaRow k="Source" v={camera.source} />
          <MetaRow k="Department" v={camera.department} />
          <MetaRow k="Status" v={camera.status || 'unknown'} />
          <MetaRow
            k="Coordinates"
            v={
              camera.lat != null && camera.lon != null
                ? `${Number(camera.lat).toFixed(5)}, ${Number(camera.lon).toFixed(5)}`
                : 'not set'
            }
          />
          <MetaRow k="Codec" v={camera.codec ? String(camera.codec).toUpperCase() : null} />
          <MetaRow
            k="Resolution"
            v={camera.width && camera.height ? `${camera.width} x ${camera.height}` : null}
          />
          <MetaRow
            k="Declared FPS"
            v={
              camera.fps_declared != null
                ? `${camera.fps_declared} (informational only)`
                : null
            }
          />
          <MetaRow
            k="Storage"
            v={
              camera.storage_type
                ? `${camera.storage_type}${
                    camera.retention_days != null ? ` · ${camera.retention_days} days` : ''
                  }`
                : null
            }
          />
          <MetaRow
            k="Last seen"
            v={camera.last_seen_at ? formatLocal(camera.last_seen_at) : 'never'}
            title={camera.last_seen_at || undefined}
          />
          <MetaRow k="RTSP" v={camera.rtsp_url} mono />
          <MetaRow k="HLS" v={camera.hls_url} mono />
          <MetaRow k="WHEP" v={camera.whep_url} mono />
        </div>
      </div>
    </div>
  );
}
