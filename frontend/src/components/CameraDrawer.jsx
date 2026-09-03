import { useEffect, useRef, useState } from 'react';
import Hls from 'hls.js';
import { AI_VIEW_BASE, aiViewKey, aiViewList, aiViewStreamUrl, formatLocal } from '../api.js';

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

// ---- AI view ---------------------------------------------------------------

const AI_PROBE_INTERVAL_MS = 10000;
const VIEW_STORAGE_PREFIX = 'sentinel.streamView.';

function readStoredMode(scope) {
  try {
    const v = sessionStorage.getItem(VIEW_STORAGE_PREFIX + scope);
    return v === 'ai' ? 'ai' : 'live';
  } catch {
    return 'live';
  }
}

function storeMode(scope, mode) {
  try {
    sessionStorage.setItem(VIEW_STORAGE_PREFIX + scope, mode);
  } catch {
    // Storage blocked (private mode / quota) — the toggle still works, it
    // simply is not remembered.
  }
}

/**
 * Availability of the AI (annotated MJPEG) view for one camera.
 * Probes `${AI_VIEW_BASE}/ai` when `active` becomes true and every 10 s while
 * it stays true. Result:
 *   status: 'idle' | 'probing' | 'ready' | 'missing' | 'offline'
 *   key:    the stream key to use (external_id preferred, registry id accepted
 *           when that is what the server lists)
 */
function useAiViewAvailability(camera, active) {
  const preferredKey = aiViewKey(camera);
  const registryKey = camera ? String(camera.id) : null;
  const [state, setState] = useState({ status: 'idle', key: preferredKey });

  useEffect(() => {
    if (!active || !camera) {
      setState({ status: 'idle', key: preferredKey });
      return undefined;
    }
    let cancelled = false;
    setState((prev) =>
      prev.status === 'ready' && (prev.key === preferredKey || prev.key === registryKey)
        ? prev
        : { status: 'probing', key: preferredKey }
    );

    const probe = async () => {
      try {
        const keys = await aiViewList();
        if (cancelled) return;
        const key = keys.has(preferredKey)
          ? preferredKey
          : registryKey && keys.has(registryKey)
            ? registryKey
            : null;
        setState(key ? { status: 'ready', key } : { status: 'missing', key: preferredKey });
      } catch {
        if (!cancelled) setState({ status: 'offline', key: preferredKey });
      }
    };
    probe();
    const timer = setInterval(probe, AI_PROBE_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
    // camera identity, not the object, drives re-probing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, preferredKey, registryKey]);

  return state;
}

function AiViewUnavailable({ status }) {
  return (
    <div className="stream-fallback ai-view-fallback">
      <div className="ai-view-fallback-title">AI view not available for this camera</div>
      <div>
        AI view is available only for cameras under live ANPR analysis (start
        scripts/live-with-auth.sh with this camera in DEMO_CAMS)
      </div>
      <div className="ai-view-fallback-sub">
        {status === 'offline'
          ? `AI-view server not reachable at ${AI_VIEW_BASE} · re-checking every 10 s`
          : status === 'probing'
            ? 'checking live analysis…'
            : 're-checking every 10 s'}
      </div>
    </div>
  );
}

function AiView({ camera, active }) {
  const avail = useAiViewAvailability(camera, active);
  // A nonce forces the browser to open a fresh multipart connection when the
  // stream becomes ready again after an error or a camera switch.
  const [nonce, setNonce] = useState(0);
  const [imgFailed, setImgFailed] = useState(false);

  useEffect(() => {
    setImgFailed(false);
    setNonce((n) => n + 1);
  }, [avail.status, avail.key]);

  // Fullscreen: an <img> has no native fullscreen control (unlike <video>),
  // so offer one via the Fullscreen API on the wrapper. Double-click toggles
  // too; Esc exits (browser default).
  const wrapRef = useRef(null);
  const [fullscreen, setFullscreen] = useState(false);
  useEffect(() => {
    const onChange = () => setFullscreen(document.fullscreenElement === wrapRef.current);
    document.addEventListener('fullscreenchange', onChange);
    document.addEventListener('webkitfullscreenchange', onChange);
    return () => {
      document.removeEventListener('fullscreenchange', onChange);
      document.removeEventListener('webkitfullscreenchange', onChange);
    };
  }, []);
  const toggleFullscreen = () => {
    const el = wrapRef.current;
    if (!el) return;
    if (document.fullscreenElement || document.webkitFullscreenElement) {
      const exit = document.exitFullscreen || document.webkitExitFullscreen;
      try { const p = exit.call(document); if (p && p.catch) p.catch(() => {}); } catch (_e) { /* noop */ }
      return;
    }
    const req = el.requestFullscreen || el.webkitRequestFullscreen;
    if (!req) return;
    try { const p = req.call(el); if (p && p.catch) p.catch(() => {}); } catch (_e) { /* noop */ }
  };

  if (avail.status !== 'ready' || imgFailed) {
    return <AiViewUnavailable status={imgFailed ? 'offline' : avail.status} />;
  }
  return (
    <div
      ref={wrapRef}
      className={`ai-view-wrap${fullscreen ? ' fullscreen' : ''}`}
      onDoubleClick={toggleFullscreen}
      title="Double-click for fullscreen · Esc to exit"
    >
      <img
        className="ai-view-img"
        src={`${aiViewStreamUrl(avail.key)}?t=${nonce}`}
        alt={`AI view — ${camera.name}`}
        onError={() => setImgFailed(true)}
      />
      <div className="ai-view-controls">
        <button
          type="button"
          className="ai-view-btn"
          onClick={toggleFullscreen}
          title={fullscreen ? 'Exit fullscreen (Esc)' : 'Fullscreen (or double-click)'}
        >
          {fullscreen ? '⤡ Exit' : '⛶ Fullscreen'}
        </button>
        <a
          className="ai-view-btn"
          href={aiViewStreamUrl(avail.key)}
          target="_blank"
          rel="noreferrer"
          title="Open the AI stream in its own tab"
        >
          ↗ New tab
        </a>
      </div>
    </div>
  );
}

/**
 * Stream area with a "Live video | AI view" segmented toggle.
 * Live video = HlsPlayer (unchanged); AI view = annotated MJPEG from the ANPR
 * worker. The last choice is remembered per browser session (per `scope`).
 * `compact` = video-wall tile layout (fills its parent instead of 16:9 box).
 */
export function StreamView({ camera, scope = 'drawer', compact = false }) {
  const [mode, setMode] = useState(() => readStoredMode(scope));
  const choose = (next) => {
    setMode(next);
    storeMode(scope, next);
  };
  const ai = mode === 'ai';

  return (
    <div className={`stream-view${compact ? ' compact' : ''}`}>
      <div className="stream-view-bar">
        <div className="seg-toggle" role="group" aria-label="Stream view">
          <button
            type="button"
            className={`seg-btn${!ai ? ' active' : ''}`}
            aria-pressed={!ai}
            onClick={() => choose('live')}
          >
            Live video
          </button>
          <button
            type="button"
            className={`seg-btn${ai ? ' active' : ''}`}
            aria-pressed={ai}
            onClick={() => choose('ai')}
          >
            AI view
          </button>
        </div>
        {ai && (
          <span className="ai-view-caption">
            <span className="ai-view-caption-dot" />
            AI VIEW · live ANPR overlay
          </span>
        )}
      </div>
      <div className={compact ? 'stream-view-body' : 'stream-box'}>
        {ai ? <AiView camera={camera} active={ai} /> : <HlsPlayer src={camera.hls_url} />}
      </div>
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
        <StreamView key={camera.id} camera={camera} scope="drawer" />

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
