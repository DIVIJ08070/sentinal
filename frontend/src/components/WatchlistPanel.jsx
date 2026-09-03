import { useEffect, useState } from 'react';
import { api, formatLocal } from '../api.js';

const CATEGORIES = ['stolen', 'wanted', 'suspect', 'blacklisted', 'other'];
const PRIORITIES = ['high', 'medium', 'low'];

const EMPTY_FORM = {
  plate: '',
  label: '',
  category: 'stolen',
  priority: 'high',
};

export default function WatchlistPanel({ onStatsChanged }) {
  const [entries, setEntries] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [rescanning, setRescanning] = useState(false);
  const [rescanNote, setRescanNote] = useState(null);

  // Retroactive matching: when a plate lands on the watchlist, the control
  // room wants to know at once whether it was already seen — not only from
  // the next frame onward. Raises alerts for unmatched recent sightings.
  const rescan = async () => {
    setRescanning(true);
    setRescanNote(null);
    try {
      const r = await api.rescanWatchlist(24);
      setRescanNote(
        r.created > 0
          ? `${r.created} alert${r.created === 1 ? '' : 's'} raised from ${r.scanned} sightings in the last 24 h — see ALERTS`
          : `No new matches in the last 24 h (${r.scanned} sightings checked)`
      );
      if (onStatsChanged) onStatsChanged();
    } catch (err) {
      setError(`Re-scan failed: ${err.message}`);
    } finally {
      setRescanning(false);
    }
  };

  const load = async () => {
    try {
      const data = await api.watchlist();
      setEntries(Array.isArray(data) ? data : []);
      setError(null);
    } catch (err) {
      setError(`Could not load watchlist: ${err.message}`);
    } finally {
      setLoaded(true);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const setField = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }));

  const submit = async (e) => {
    e.preventDefault();
    const plate = form.plate.trim();
    if (!plate) return;
    setSaving(true);
    try {
      await api.addWatchlistEntry({
        plate,
        label: form.label.trim(),
        category: form.category,
        priority: form.priority,
      });
      setForm(EMPTY_FORM);
      await load();
      if (onStatsChanged) onStatsChanged();
    } catch (err) {
      setError(`Could not add entry: ${err.message}`);
    } finally {
      setSaving(false);
    }
  };

  const toggleActive = async (entry) => {
    try {
      await api.updateWatchlistEntry(entry.id, { active: !entry.active });
      await load();
      if (onStatsChanged) onStatsChanged();
    } catch (err) {
      setError(`Update failed: ${err.message}`);
    }
  };

  const remove = async (entry) => {
    if (!window.confirm(`Delete watchlist entry ${entry.plate}?`)) return;
    try {
      await api.deleteWatchlistEntry(entry.id);
      await load();
      if (onStatsChanged) onStatsChanged();
    } catch (err) {
      setError(`Delete failed: ${err.message}`);
    }
  };

  return (
    <div>
      <div className="panel-title">
        <span>Watchlist ({entries.length})</span>
        <button
          className="btn btn-amber btn-small"
          onClick={rescan}
          disabled={rescanning}
          title="Retroactive matching: check the last 24 h of sightings against every active plate and raise alerts for matches"
        >
          {rescanning ? 'Re-scanning…' : 'Re-scan recent sightings'}
        </button>
      </div>
      {rescanNote && <div className="wl-label rescan-note">{rescanNote}</div>}

      {error && <div className="error-note">{error}</div>}

      {loaded && entries.length === 0 && (
        <div className="empty-state">
          <h3>Watchlist is empty</h3>
          <p>
            Add a plate below, or seed the demo entries with{' '}
            <code>python -m app.seed</code> in the backend.
          </p>
        </div>
      )}

      {entries.map((entry) => (
        <div key={entry.id} className={`wl-card${entry.active ? '' : ' inactive'}`}>
          <div className="wl-head">
            <span className="plate">{entry.plate}</span>
            <span className={`badge cat-${entry.category || 'other'}`}>
              {entry.category || 'other'}
            </span>
            <span className={`badge pri-${entry.priority || 'low'}`}>
              {entry.priority || 'low'}
            </span>
            {!entry.active && <span className="badge inactive">inactive</span>}
          </div>
          {entry.label && <div className="wl-label">{entry.label}</div>}
          <div className="wl-label" title={entry.created_at}>
            Added {formatLocal(entry.created_at)}
          </div>
          <div className="wl-actions">
            <button className="btn btn-ghost btn-small" onClick={() => toggleActive(entry)}>
              {entry.active ? 'Deactivate' : 'Activate'}
            </button>
            <button className="btn btn-danger btn-small" onClick={() => remove(entry)}>
              Delete
            </button>
          </div>
        </div>
      ))}

      <form className="wl-form" onSubmit={submit}>
        <div className="panel-title">
          <span>Add entry</span>
        </div>
        <label className="field">
          Plate number
          <input
            type="text"
            placeholder="GJ01AB1234"
            value={form.plate}
            onChange={setField('plate')}
            required
          />
        </label>
        <label className="field">
          Label
          <input
            type="text"
            placeholder="Stolen vehicle — FIR 123/2026"
            value={form.label}
            onChange={setField('label')}
          />
        </label>
        <div className="row">
          <label className="field">
            Category
            <select value={form.category} onChange={setField('category')}>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            Priority
            <select value={form.priority} onChange={setField('priority')}>
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          </label>
        </div>
        <button className="btn btn-amber" type="submit" disabled={saving}>
          {saving ? 'Adding…' : 'Add to watchlist'}
        </button>
      </form>
    </div>
  );
}
