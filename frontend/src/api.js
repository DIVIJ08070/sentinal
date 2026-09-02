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
