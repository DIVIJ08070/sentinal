// Single fetch wrapper for the Sentinel backend REST API.
// All paths are relative (/api/...) — the Vite dev proxy forwards them to
// http://localhost:8000 (see vite.config.js).

const API_BASE = '/api';

async function request(path, { method = 'GET', body, params } = {}) {
  let url = API_BASE + path;
  if (params) {
    const qs = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null && value !== '') qs.set(key, value);
    }
    const encoded = qs.toString();
    if (encoded) url += `?${encoded}`;
  }

  const options = { method };
  if (body !== undefined) {
    options.headers = { 'Content-Type': 'application/json' };
    options.body = JSON.stringify(body);
  }

  const response = await fetch(url, options);
  if (!response.ok) {
    let detail = '';
    try {
      const data = await response.json();
      detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail ?? data);
    } catch {
      // Non-JSON error body; the status line is enough.
    }
    throw new Error(`${response.status} ${response.statusText}${detail ? `: ${detail}` : ''}`);
  }
  if (response.status === 204) return null;
  return response.json();
}

export const api = {
  // Cameras
  cameras: (params) => request('/cameras', { params }),
  syncCameras: () => request('/cameras/sync', { method: 'POST' }),
  camerasGeojson: () => request('/cameras/geojson'),

  // Stats
  stats: () => request('/stats'),

  // Alerts
  alerts: (params) => request('/alerts', { params }),
  ackAlert: (id) => request(`/alerts/${id}/ack`, { method: 'POST' }),

  // Watchlist
  watchlist: () => request('/watchlist'),
  addWatchlistEntry: (entry) => request('/watchlist', { method: 'POST', body: entry }),
  updateWatchlistEntry: (id, patch) => request(`/watchlist/${id}`, { method: 'PATCH', body: patch }),
  deleteWatchlistEntry: (id) => request(`/watchlist/${id}`, { method: 'DELETE' }),
  // Retroactive matching: raise alerts for recent sightings of watchlist plates.
  rescanWatchlist: (sinceHours = 24) =>
    request('/watchlist/rescan', { method: 'POST', params: { since_hours: sinceHours } }),

  // Detections & route reconstruction
  detections: (params) => request('/detections', { params }),
  vehicleRoute: (plate, params) => request(`/vehicles/${encodeURIComponent(plate)}/route`, { params }),

  // Camera health & bandwidth
  healthSummary: () => request('/health/summary'),
};

// URL of the evidence-dossier PDF for a plate (opened in a new tab — the
// backend serves it inline with content-disposition; no body parsing needed).
// `params` takes the same optional {since, until} as the route endpoint.
export function dossierPdfUrl(plate, params = {}) {
  const qs = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') qs.set(key, value);
  }
  const encoded = qs.toString();
  return `${API_BASE}/vehicles/${encodeURIComponent(plate)}/dossier.pdf${encoded ? `?${encoded}` : ''}`;
}

// ---- AI view (annotated MJPEG from the live ANPR worker) --------------------
// The ANPR worker publishes per-camera MJPEG streams with the detection
// overlay on a separate small HTTP server (default :8892). It is NOT proxied
// through Vite: the browser connects directly, so the base is absolute and
// overridable via VITE_AI_VIEW_BASE at build time.

export const AI_VIEW_BASE = (import.meta.env.VITE_AI_VIEW_BASE || 'http://localhost:8892').replace(
  /\/+$/,
  ''
);

// Key the AI-view server uses for a camera: the catalogue external id
// (cam06...) when present, else the registry id.
export function aiViewKey(camera) {
  if (!camera) return null;
  return String(camera.external_id || camera.id);
}

export function aiViewStreamUrl(key) {
  return `${AI_VIEW_BASE}/ai/${encodeURIComponent(key)}.mjpg`;
}

// Normalises whatever `GET {AI_VIEW_BASE}/ai` returns into a Set of camera
// keys. Tolerates: ["cam06", ...], [{key|camera|external_id|id|name|url}],
// {cameras|streams: [...]} or a plain {cam06: {...}} map.
function collectAiKeys(node, out) {
  if (node == null) return;
  if (typeof node === 'string' || typeof node === 'number') {
    const m = String(node).match(/\/ai\/([^/?#]+?)(?:\.mjpg)?(?:[?#].*)?$/);
    out.add(m ? decodeURIComponent(m[1]) : String(node));
    return;
  }
  if (Array.isArray(node)) {
    for (const item of node) collectAiKeys(item, out);
    return;
  }
  if (typeof node === 'object') {
    for (const listKey of ['cameras', 'streams', 'ai', 'items', 'keys']) {
      if (Array.isArray(node[listKey])) {
        collectAiKeys(node[listKey], out);
        return;
      }
    }
    let hit = false;
    for (const field of ['key', 'camera', 'external_id', 'cam', 'id', 'name', 'url', 'path']) {
      const v = node[field];
      if (typeof v === 'string' || typeof v === 'number') {
        collectAiKeys(v, out);
        hit = true;
      }
    }
    if (!hit) for (const k of Object.keys(node)) out.add(k);
  }
}

// Resolves to a Set of keys currently under live analysis; rejects when the
// AI-view server is unreachable or answers with something that is not JSON.
export async function aiViewList() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 4000);
  try {
    const response = await fetch(`${AI_VIEW_BASE}/ai`, {
      signal: controller.signal,
      headers: { Accept: 'application/json' },
    });
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    const data = await response.json();
    const keys = new Set();
    collectAiKeys(data, keys);
    return keys;
  } finally {
    clearTimeout(timer);
  }
}

// ---- Shared display helpers -------------------------------------------------
// All backend timestamps are UTC ISO8601 with Z. Display rule: render in the
// browser's local timezone, keep the raw ISO string in the title tooltip.

export function formatLocal(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString([], {
    year: 'numeric',
    month: 'short',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

export function formatTime(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

export function snapshotSrc(b64) {
  return b64 ? `data:image/jpeg;base64,${b64}` : null;
}
