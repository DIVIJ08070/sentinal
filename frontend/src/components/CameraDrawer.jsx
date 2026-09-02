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
  const [connecting, setConnecting] = useState(true);

  useEffect(() => {
    setFailed(false);
    setConnecting(true);
    if (!src) return undefined;
    const video = videoRef.current;
    if (!video) return undefined;
    const onPlaying = () => setConnecting(false);
    video.addEventListener('playing', onPlaying);

    if (Hls.isSupported()) {
      // On-demand relay streams spin up when first requested: the manifest can
      // 503 for up to a minute while ffmpeg connects to the camera and waits
      // for a keyframe. During a startup grace window we treat fatal errors as
      // "not ready yet" — tear down and rebuild the hls instance — and only
      // surface "unavailable" once the grace window has elapsed.
      const GRACE_MS = 90000;
      const startedAt = Date.now();
      let hls = null;
      let retryTimer = null;
      let disposed = false;

      const patient = {
        default: {
          maxTimeToFirstByteMs: 20000,
          maxLoadTimeMs: 40000,
          timeoutRetry: { maxNumRetry: 6, retryDelayMs: 2000, maxRetryDelayMs: 5000 },
          errorRetry: { maxNumRetry: 8, retryDelayMs: 2000, maxRetryDelayMs: 4000 },
        },
      };

      const build = () => {
        if (disposed) return;
        hls = new Hls({
          liveDurationInfinity: true,
          manifestLoadPolicy: patient,
          playlistLoadPolicy: patient,
        });
        hls.on(Hls.Events.ERROR, (_event, data) => {
          if (!data || !data.fatal) return;
          if (Date.now() - startedAt < GRACE_MS) {
            // Still warming up — rebuild and try again shortly.
            try { hls.destroy(); } catch (_e) { /* noop */ }
            hls = null;
            retryTimer = setTimeout(build, 3000);
          } else {
            setFailed(true);
            try { if (hls) hls.destroy(); } catch (_e) { /* noop */ }
            hls = null;
          }
        });
        hls.on(Hls.Events.MANIFEST_PARSED, () => {
          // Autoplay attribute alone doesn't fire when the source attaches
          // after mount; muted play() is allowed by browser autoplay policy.
          video.play().catch(() => {});
        });
        hls.loadSource(src);
        hls.attachMedia(video);
      };
      build();

      return () => {
        disposed = true;
        video.removeEventListener('playing', onPlaying);
        if (retryTimer) clearTimeout(retryTimer);
        if (hls) { try { hls.destroy(); } catch (_e) { /* noop */ } }
      };
    }

    if (video.canPlayType('application/vnd.apple.mpegurl')) {
      const onError = () => setFailed(true);
      video.addEventListener('error', onError);
      video.src = src;
      return () => {
        video.removeEventListener('playing', onPlaying);
        video.removeEventListener('error', onError);
        video.removeAttribute('src');
        video.load();
      };
    }

    setFailed(true);
    return () => video.removeEventListener('playing', onPlaying);
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
    <div style={{ position: 'relative' }}>
      <video
        ref={videoRef}
        className="stream-video"
        autoPlay
        muted
        playsInline
        controls
      />
      {connecting && (
        <div
          className="stream-fallback"
          style={{
            position: 'absolute',
            inset: 0,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            textAlign: 'center',
            pointerEvents: 'none',
          }}
        >
          Connecting to live camera…
          <br />
          first open can take up to a minute
        </div>
      )}
    </div>
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
