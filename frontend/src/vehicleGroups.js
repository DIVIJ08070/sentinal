// Alert threads: collapse many alerts about ONE vehicle into a single thread.
//
// Why: ANPR reads the same plate several times as a vehicle crosses the read
// zone, often with OCR variants (GJ39TB954 / GJ39T945 / GJ09TB955 for one
// truck), and the vehicle comes back on later passes. Each read that matches
// the watchlist raises its own alert — correct for the audit trail, noisy for
// an operator. Grouping is a VIEW concern, so it lives here in the client and
// never changes what the backend stored.
//
// Two rules decide "same vehicle":
//   1. same camera, sightings <= PASS_WINDOW_MS apart, plates >= PASS_SIMILARITY
//      similar -> one pass of one vehicle (OCR variants of consecutive frames);
//   2. plates within one edit of each other (any camera, any time)
//      -> the same vehicle identity (later passes, small misreads).
// Union-find merges transitively, so A~B and B~C thread A, B and C together —
// which is exactly why rule 1 must be tight: at a busy stop-line several
// DIFFERENT vehicles pass within ten seconds, and any two Gujarat plates share
// "GJ" plus a few digits, so a loose window/similarity chained a scooter to
// two cars. Real OCR variants of one vehicle come from consecutive frames
// within ~1-2 s and differ by only a character or two.

const PASS_WINDOW_MS = 3_000;
const PASS_SIMILARITY = 0.7;
const MIN_PLATE_LEN = 6;
const NEW_PASS_GAP_MS = 60_000;

export function editDistance(a, b) {
  const s = a || '';
  const t = b || '';
  if (s === t) return 0;
  const m = s.length;
  const n = t.length;
  if (!m) return n;
  if (!n) return m;
  let prev = Array.from({ length: n + 1 }, (_, j) => j);
  for (let i = 1; i <= m; i++) {
    const cur = [i];
    for (let j = 1; j <= n; j++) {
      const cost = s[i - 1] === t[j - 1] ? 0 : 1;
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost);
    }
    prev = cur;
  }
  return prev[n];
}

function similarity(a, b) {
  const len = Math.max((a || '').length, (b || '').length, 1);
  return 1 - editDistance(a, b) / len;
}

function timeOf(alert) {
  const iso = (alert.detection && alert.detection.captured_at) || alert.created_at;
  const t = new Date(iso).getTime();
  return Number.isNaN(t) ? 0 : t;
}

function confidenceOf(alert) {
  const det = alert.detection || {};
  if (det.plate_confidence != null) return det.plate_confidence;
  if (alert.match_confidence != null) return alert.match_confidence;
  return 0;
}

/**
 * Group alerts into vehicle threads.
 * Returns threads newest-first; each thread:
 *   { key, alerts (newest first), latest, bestPlate, count, passes, hasNew, ids }
 */
export function groupAlerts(alerts) {
  const n = alerts.length;
  if (n === 0) return [];
  const parent = Array.from({ length: n }, (_, i) => i);
  const find = (i) => (parent[i] === i ? i : (parent[i] = find(parent[i])));
  const union = (i, j) => {
    const ri = find(i);
    const rj = find(j);
    if (ri !== rj) parent[ri] = rj;
  };
  const times = alerts.map(timeOf);

  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const a = alerts[i];
      const b = alerts[j];
      const pa = a.plate || '';
      const pb = b.plate || '';
      if (pa.length < MIN_PLATE_LEN || pb.length < MIN_PLATE_LEN) continue;
      const sameCamera = a.camera_id != null && a.camera_id === b.camera_id;
      const dt = Math.abs(times[i] - times[j]);
      if (sameCamera && dt <= PASS_WINDOW_MS && similarity(pa, pb) >= PASS_SIMILARITY) union(i, j);
      else if (editDistance(pa, pb) <= 1) union(i, j);
    }
  }

  const buckets = new Map();
  alerts.forEach((a, i) => {
    const r = find(i);
    if (!buckets.has(r)) buckets.set(r, []);
    buckets.get(r).push(a);
  });

  const threads = [...buckets.values()].map((list) => {
    list.sort((x, y) => timeOf(y) - timeOf(x));
    const best = list.reduce((m, a) => (confidenceOf(a) > confidenceOf(m) ? a : m), list[0]);
    const sorted = list.map(timeOf).sort((x, y) => x - y);
    let passes = 1;
    for (let k = 1; k < sorted.length; k++) if (sorted[k] - sorted[k - 1] > NEW_PASS_GAP_MS) passes++;
    const ids = list.map((a) => a.id);
    return {
      key: `thread-${Math.min(...ids)}`,
      alerts: list,
      latest: list[0],
      bestPlate: best.plate,
      count: list.length,
      passes,
      hasNew: list.some((a) => a.status === 'new'),
      ids,
    };
  });

  threads.sort((g, h) => timeOf(h.latest) - timeOf(g.latest));
  return threads;
}
