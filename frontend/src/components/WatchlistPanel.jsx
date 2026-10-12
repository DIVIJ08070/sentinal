import { useEffect, useRef, useState } from 'react';
import { api, formatLocal } from '../api.js';

const CATEGORIES = ['stolen', 'wanted', 'suspect', 'blacklisted', 'other'];
const PRIORITIES = ['high', 'medium', 'low'];

const EMPTY_FORM = {
  plate: '',
  label: '',
  category: 'stolen',
  priority: 'high',
};

const normalizePlate = (str) => (str || '').toUpperCase().replace(/[^A-Z0-9]/g, '');

const downloadBlob = (content, filename, contentType) => {
  const blob = new Blob([content], { type: contentType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};

export default function WatchlistPanel({ onStatsChanged }) {
  const [entries, setEntries] = useState([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState(null);
  const [successNote, setSuccessNote] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [showAddForm, setShowAddForm] = useState(false);
  const [filterQuery, setFilterQuery] = useState('');
  const [saving, setSaving] = useState(false);
  const [rescanning, setRescanning] = useState(false);
  const [rescanNote, setRescanNote] = useState(null);

  // Export & Import states
  const [showExportMenu, setShowExportMenu] = useState(false);
  const [showImportCard, setShowImportCard] = useState(false);
  const [importMode, setImportMode] = useState('text'); // 'text' | 'file'
  const [importText, setImportText] = useState('');
  const [importFileName, setImportFileName] = useState('');
  const [importLabel, setImportLabel] = useState('Bulk import');
  const [importCategory, setImportCategory] = useState('stolen');
  const [importPriority, setImportPriority] = useState('high');
  const [importAutoRescan, setImportAutoRescan] = useState(true);
  const [importing, setImporting] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const exportMenuRef = useRef(null);

  // Close export dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (e) => {
      if (exportMenuRef.current && !exportMenuRef.current.contains(e.target)) {
        setShowExportMenu(false);
      }
    };
    if (showExportMenu) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [showExportMenu]);

  // Check in real-time if entered plate already exists in the watchlist
  const enteredClean = normalizePlate(form.plate);
  const duplicateEntry = enteredClean
    ? entries.find((e) => normalizePlate(e.plate) === enteredClean)
    : null;

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

  const setField = (key) => (e) => {
    setForm((f) => ({ ...f, [key]: e.target.value }));
    if (error) setError(null);
  };

  const submit = async (e) => {
    e.preventDefault();
    const plate = normalizePlate(form.plate);
    if (!plate) {
      setError('Please enter a valid registration plate number.');
      return;
    }
    if (duplicateEntry) {
      setError(
        `Duplicate Plate: "${duplicateEntry.plate}" is already in the watchlist (${
          duplicateEntry.active ? 'Active' : 'Inactive'
        } · ${duplicateEntry.category.toUpperCase()})`
      );
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.addWatchlistEntry({
        plate,
        label: form.label.trim(),
        category: form.category,
        priority: form.priority,
      });
      setForm(EMPTY_FORM);
      setSuccessNote(`Added plate ${plate} to watchlist`);
      setShowAddForm(false);
      setTimeout(() => setSuccessNote(null), 5000);
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

  // --- Export Actions ---
  const exportCSV = () => {
    if (entries.length === 0) return;
    const header = ['Plate', 'Label', 'Category', 'Priority', 'Active', 'Notes', 'Created_At'];
    const rows = entries.map((e) => [
      `"${(e.plate || '').replace(/"/g, '""')}"`,
      `"${(e.label || '').replace(/"/g, '""')}"`,
      `"${(e.category || '').replace(/"/g, '""')}"`,
      `"${(e.priority || '').replace(/"/g, '""')}"`,
      e.active ? 'true' : 'false',
      `"${(e.notes || '').replace(/"/g, '""')}"`,
      `"${e.created_at || ''}"`,
    ]);
    const csvContent = [header.join(','), ...rows.map((r) => r.join(','))].join('\r\n');
    downloadBlob(csvContent, 'watchlist_export.csv', 'text/csv;charset=utf-8;');
    setShowExportMenu(false);
    setSuccessNote(`✓ Exported ${entries.length} watchlist plates to CSV`);
    setTimeout(() => setSuccessNote(null), 4000);
  };

  const exportPlatesTxt = () => {
    if (entries.length === 0) return;
    const txtContent = entries.map((e) => e.plate).join('\n') + '\n';
    downloadBlob(txtContent, 'watchlist_plates.txt', 'text/plain;charset=utf-8;');
    setShowExportMenu(false);
    setSuccessNote(`✓ Exported ${entries.length} number plates as text list`);
    setTimeout(() => setSuccessNote(null), 4000);
  };

  const exportJSON = () => {
    if (entries.length === 0) return;
    const jsonContent = JSON.stringify(entries, null, 2);
    downloadBlob(jsonContent, 'watchlist_export.json', 'application/json');
    setShowExportMenu(false);
    setSuccessNote(`✓ Exported ${entries.length} watchlist records as JSON`);
    setTimeout(() => setSuccessNote(null), 4000);
  };

  const copyPlates = async () => {
    if (entries.length === 0) return;
    const txt = entries.map((e) => e.plate).join('\n');
    try {
      await navigator.clipboard.writeText(txt);
      setShowExportMenu(false);
      setSuccessNote(`✓ Copied ${entries.length} number plates to clipboard!`);
      setTimeout(() => setSuccessNote(null), 4000);
    } catch (err) {
      setError(`Could not copy to clipboard: ${err.message}`);
    }
  };

  // --- Import Parsing Logic ---
  const parseRawPlates = (raw) => {
    if (!raw || !raw.trim()) return [];
    const lines = raw.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
    if (lines.length === 0) return [];

    let items = [];
    if (lines[0].includes(',') || lines[0].includes('\t')) {
      const delimiter = lines[0].includes('\t') ? '\t' : ',';
      const parseLine = (line) => {
        const parts = [];
        let cur = '';
        let inQuotes = false;
        for (let i = 0; i < line.length; i++) {
          const c = line[i];
          if (c === '"') {
            inQuotes = !inQuotes;
          } else if (c === delimiter && !inQuotes) {
            parts.push(cur.trim());
            cur = '';
          } else {
            cur += c;
          }
        }
        parts.push(cur.trim());
        return parts;
      };

      const rows = lines.map(parseLine);
      const firstRow = rows[0].map((c) => c.toLowerCase().replace(/[^a-z_]/g, ''));
      let headerCols = null;
      let startIdx = 0;
      if (firstRow.some((c) => ['plate', 'registration', 'number_plate', 'vehicleno', 'regno'].includes(c))) {
        headerCols = firstRow;
        startIdx = 1;
      }

      for (let i = startIdx; i < rows.length; i++) {
        const row = rows[i];
        if (!row || row.length === 0 || (row.length === 1 && !row[0])) continue;
        if (headerCols) {
          const d = {};
          headerCols.forEach((col, idx) => {
            d[col] = row[idx] || '';
          });
          const plate = d.plate || d.registration || d.number_plate || d.vehicleno || d.regno || '';
          const clean = normalizePlate(plate);
          if (clean) {
            items.push({
              plate: clean,
              label: d.label || d.reason || importLabel || 'Bulk import',
              category: d.category || importCategory,
              priority: d.priority || importPriority,
              active: d.active ? !['false', '0', 'no'].includes(d.active.toLowerCase()) : true,
              notes: d.notes || '',
            });
          }
        } else {
          const clean = normalizePlate(row[0]);
          if (clean) {
            items.push({
              plate: clean,
              label: row[1] || importLabel || 'Bulk import',
              category: row[2] || importCategory,
              priority: row[3] || importPriority,
              active: row[4] ? !['false', '0', 'no'].includes(row[4].toLowerCase()) : true,
              notes: row[5] || '',
            });
          }
        }
      }
    } else {
      for (const line of lines) {
        const tokens = line.split(/[,;\s]+/).filter(Boolean);
        for (const tok of tokens) {
          const clean = normalizePlate(tok);
          if (clean) {
            items.push({
              plate: clean,
              label: importLabel || 'Bulk import',
              category: importCategory,
              priority: importPriority,
              active: true,
              notes: '',
            });
          }
        }
      }
    }
    return items;
  };

  const parsedItems = parseRawPlates(importText);
  const existingPlatesSet = new Set(entries.map((e) => normalizePlate(e.plate)));
  const seenBatch = new Set();
  const readyToImport = [];
  const duplicateBatch = [];

  parsedItems.forEach((item) => {
    if (existingPlatesSet.has(item.plate) || seenBatch.has(item.plate)) {
      duplicateBatch.push(item);
    } else {
      seenBatch.add(item.plate);
      readyToImport.push(item);
    }
  });

  const handleFileUpload = (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    setImportFileName(file.name);
    const reader = new FileReader();
    reader.onload = (evt) => {
      setImportText(evt.target.result || '');
    };
    reader.readAsText(file);
  };

  const handleFileDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    const file = e.dataTransfer.files && e.dataTransfer.files[0];
    if (!file) return;
    setImportFileName(file.name);
    setImportMode('file');
    const reader = new FileReader();
    reader.onload = (evt) => {
      setImportText(evt.target.result || '');
    };
    reader.readAsText(file);
  };

  const submitImport = async () => {
    if (readyToImport.length === 0) {
      setError('No new plates to import (all detected plates are duplicates or invalid).');
      return;
    }
    setImporting(true);
    setError(null);
    try {
      const res = await api.importWatchlist({
        items: readyToImport,
        rescan: importAutoRescan,
      });
      setSuccessNote(
        `✓ Successfully imported ${res.imported} plate${res.imported === 1 ? '' : 's'}${
          res.skipped > 0 ? ` (${res.skipped} duplicate${res.skipped === 1 ? '' : 's'} skipped)` : ''
        }`
      );
      if (res.rescan && res.rescan.created > 0) {
        setRescanNote(
          `⚡ Retroactive match: ${res.rescan.created} alert${res.rescan.created === 1 ? '' : 's'} raised from past 24h sightings!`
        );
      }
      setTimeout(() => setSuccessNote(null), 6000);
      setShowImportCard(false);
      setImportText('');
      setImportFileName('');
      await load();
      if (onStatsChanged) onStatsChanged();
    } catch (err) {
      setError(`Import failed: ${err.message}`);
    } finally {
      setImporting(false);
    }
  };

  const filteredEntries = entries.filter((e) => {
    if (!filterQuery) return true;
    const q = filterQuery.toLowerCase();
    return (
      (e.plate && e.plate.toLowerCase().includes(q)) ||
      (e.label && e.label.toLowerCase().includes(q)) ||
      (e.category && e.category.toLowerCase().includes(q))
    );
  });

  return (
    <div>
      {/* Sticky Top Header: Stays fixed when scrolling through watchlist cards */}
      <div className="wl-sticky-header">
        <div className="wl-panel-title">
          <span style={{ fontWeight: 600, fontSize: '13.5px' }}>
            Watchlist ({entries.length})
          </span>
          <div className="wl-header-actions">
            <button
              className={`btn ${showAddForm ? 'btn-ghost' : 'btn-amber'} btn-small`}
              onClick={() => {
                setShowAddForm(!showAddForm);
                if (!showAddForm) setShowImportCard(false);
                setError(null);
              }}
            >
              {showAddForm ? '✕ Close' : '+ Add Plate'}
            </button>

            <button
              className={`btn ${showImportCard ? 'btn-ghost' : 'btn-ghost'} btn-small`}
              style={showImportCard ? { borderColor: '#38bdf8', color: '#38bdf8' } : {}}
              onClick={() => {
                setShowImportCard(!showImportCard);
                if (!showImportCard) setShowAddForm(false);
                setError(null);
              }}
            >
              {showImportCard ? '✕ Close' : '⭱ Import'}
            </button>

            {/* Export Dropdown */}
            <div className="wl-dropdown-container" ref={exportMenuRef}>
              <button
                className="btn btn-ghost btn-small"
                onClick={() => setShowExportMenu(!showExportMenu)}
                disabled={entries.length === 0}
                title="Export full list of number plates"
              >
                ⭳ Export ▾
              </button>
              {showExportMenu && (
                <div className="wl-dropdown-menu">
                  <button className="wl-dropdown-item" onClick={exportCSV}>
                    <span>📄 Export CSV</span>
                    <span className="wl-drop-hint">Full details</span>
                  </button>
                  <button className="wl-dropdown-item" onClick={exportPlatesTxt}>
                    <span>📝 Export Plates (.txt)</span>
                    <span className="wl-drop-hint">Plates only</span>
                  </button>
                  <button className="wl-dropdown-item" onClick={copyPlates}>
                    <span>📋 Copy All Plates</span>
                    <span className="wl-drop-hint">Clipboard</span>
                  </button>
                  <button className="wl-dropdown-item" onClick={exportJSON}>
                    <span>{'{ }'} Export JSON</span>
                    <span className="wl-drop-hint">Raw data</span>
                  </button>
                </div>
              )}
            </div>

            <button
              className="btn btn-ghost btn-small"
              onClick={rescan}
              disabled={rescanning}
              title="Retroactive matching: check the last 24 h of sightings against every active plate and raise alerts for matches"
            >
              {rescanning ? 'Re-scanning…' : 'Re-scan 24h'}
            </button>
          </div>
        </div>

        {successNote && <div className="success-note">{successNote}</div>}
        {rescanNote && <div className="wl-label rescan-note">{rescanNote}</div>}
        {error && <div className="error-note">{error}</div>}

        {/* Top Add Entry Form Card */}
        {showAddForm && (
          <form className="wl-add-card" onSubmit={submit}>
            <div className="wl-add-card-header">
              <span>Add Vehicle to Watchlist</span>
              <button
                type="button"
                className="btn btn-ghost btn-small"
                style={{ padding: '2px 8px' }}
                onClick={() => setShowAddForm(false)}
              >
                ✕
              </button>
            </div>
            <div className="row">
              <label className="field" style={{ flex: '1.4' }}>
                Plate number
                <input
                  type="text"
                  placeholder="GJ01AB1234"
                  maxLength={12}
                  value={form.plate}
                  onChange={(e) => {
                    setForm((f) => ({ ...f, plate: e.target.value.toUpperCase() }));
                    if (error) setError(null);
                  }}
                  autoFocus
                  required
                  style={duplicateEntry ? { borderColor: 'var(--red)', color: '#fca5a5' } : {}}
                />
                {duplicateEntry && (
                  <div
                    className="wl-dup-warning"
                    style={{
                      color: '#f87171',
                      background: 'rgba(239, 68, 68, 0.18)',
                      border: '1px solid #ef4444',
                    }}
                  >
                    ⛔ Already in watchlist ({duplicateEntry.active ? 'Active' : 'Inactive'} ·{' '}
                    {duplicateEntry.category.toUpperCase()})
                  </div>
                )}
              </label>
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
            <label className="field">
              Label / Reason
              <input
                type="text"
                placeholder="e.g. Stolen vehicle — FIR 123/2026"
                value={form.label}
                onChange={setField('label')}
              />
            </label>
            <div className="wl-add-card-actions">
              <button
                className="btn btn-amber"
                type="submit"
                disabled={saving || Boolean(duplicateEntry) || !enteredClean}
                title={duplicateEntry ? `Plate ${duplicateEntry.plate} is already registered` : ''}
              >
                {saving ? 'Adding…' : '✓ Save to Watchlist'}
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => {
                  setShowAddForm(false);
                  setForm(EMPTY_FORM);
                }}
              >
                Cancel
              </button>
            </div>
          </form>
        )}

        {/* Bulk Import Card */}
        {showImportCard && (
          <div className="wl-import-card">
            <div className="wl-import-header">
              <span>⭱ Import Number Plates to Watchlist</span>
              <button
                type="button"
                className="btn btn-ghost btn-small"
                style={{ padding: '2px 8px' }}
                onClick={() => setShowImportCard(false)}
              >
                ✕
              </button>
            </div>

            <div className="wl-import-modes">
              <button
                type="button"
                className={`wl-import-mode-btn ${importMode === 'text' ? 'active' : ''}`}
                onClick={() => setImportMode('text')}
              >
                📝 Paste Plates / CSV Text
              </button>
              <button
                type="button"
                className={`wl-import-mode-btn ${importMode === 'file' ? 'active' : ''}`}
                onClick={() => setImportMode('file')}
              >
                📁 Upload CSV / Text File
              </button>
            </div>

            {importMode === 'text' ? (
              <textarea
                className="wl-import-textarea"
                placeholder={`Paste plates (one per line, comma or space separated) or CSV:\nGJ01AB1234\nGJ01CD5678\nGJ27EF9999\n\nOr CSV format: plate,label,category,priority`}
                value={importText}
                onChange={(e) => setImportText(e.target.value)}
                autoFocus
              />
            ) : (
              <div
                className={`wl-dropzone ${isDragging ? 'dragging' : ''}`}
                onDragOver={(e) => {
                  e.preventDefault();
                  setIsDragging(true);
                }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={handleFileDrop}
                onClick={() => document.getElementById('wl-file-input')?.click()}
              >
                <input
                  id="wl-file-input"
                  type="file"
                  accept=".csv,.txt"
                  style={{ display: 'none' }}
                  onChange={handleFileUpload}
                />
                <div className="wl-dropzone-icon">📥</div>
                <div style={{ fontSize: '12.5px', fontWeight: 500, color: '#38bdf8' }}>
                  {importFileName ? `Selected: ${importFileName}` : 'Click to browse or drag & drop CSV / TXT file'}
                </div>
                <div style={{ fontSize: '11px', color: 'var(--text-dim)', marginTop: '4px' }}>
                  Supports CSV with headers (plate, label, category, priority) or plain plates list
                </div>
              </div>
            )}

            {/* Default Properties for imported entries */}
            <div className="row">
              <label className="field" style={{ flex: '1.4' }}>
                Default Reason / Label
                <input
                  type="text"
                  placeholder="e.g. Operation Hawk or FIR Batch"
                  value={importLabel}
                  onChange={(e) => setImportLabel(e.target.value)}
                />
              </label>
              <label className="field">
                Default Category
                <select value={importCategory} onChange={(e) => setImportCategory(e.target.value)}>
                  {CATEGORIES.map((c) => (
                    <option key={c} value={c}>
                      {c}
                    </option>
                  ))}
                </select>
              </label>
              <label className="field">
                Default Priority
                <select value={importPriority} onChange={(e) => setImportPriority(e.target.value)}>
                  {PRIORITIES.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            {/* Live Parsing Preview */}
            {parsedItems.length > 0 && (
              <>
                <div className="wl-preview-counts">
                  <span className="wl-preview-pill total">Detected: {parsedItems.length}</span>
                  <span className="wl-preview-pill new">✓ {readyToImport.length} New Plates</span>
                  {duplicateBatch.length > 0 && (
                    <span className="wl-preview-pill dup">
                      ⚠ {duplicateBatch.length} Duplicates (Skipped)
                    </span>
                  )}
                </div>

                <div className="wl-chips-preview">
                  {readyToImport.slice(0, 20).map((item, idx) => (
                    <span key={idx} className="wl-chip new" title={`${item.plate} · ${item.category}`}>
                      +{item.plate}
                    </span>
                  ))}
                  {readyToImport.length > 20 && (
                    <span className="wl-chip new" style={{ opacity: 0.8 }}>
                      +{readyToImport.length - 20} more
                    </span>
                  )}
                  {duplicateBatch.slice(0, 10).map((item, idx) => (
                    <span key={`dup-${idx}`} className="wl-chip dup" title={`Already in watchlist: ${item.plate}`}>
                      {item.plate}
                    </span>
                  ))}
                </div>
              </>
            )}

            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <label style={{ fontSize: '12px', display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={importAutoRescan}
                  onChange={(e) => setImportAutoRescan(e.target.checked)}
                />
                Run retroactive 24h search on imported plates immediately
              </label>
            </div>

            <div className="wl-import-actions">
              <button
                className="btn btn-amber"
                type="button"
                onClick={submitImport}
                disabled={importing || readyToImport.length === 0}
              >
                {importing ? 'Importing…' : `✓ Import ${readyToImport.length} Plates`}
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={() => {
                  setShowImportCard(false);
                  setImportText('');
                  setImportFileName('');
                }}
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        {/* Quick Search Filter */}
        {entries.length > 0 && (
          <div className="wl-search-bar" style={{ margin: 0 }}>
            <input
              type="text"
              placeholder="Filter watchlist by plate, reason, category…"
              value={filterQuery}
              onChange={(e) => setFilterQuery(e.target.value)}
            />
          </div>
        )}
      </div>

      {loaded && entries.length === 0 && (
        <div className="empty-state">
          <h3>Watchlist is empty</h3>
          <p>
            Click <strong>+ Add Plate</strong> or <strong>⭱ Import</strong> above to add vehicles, or seed demo entries with{' '}
            <code>python -m app.seed</code> in the backend.
          </p>
        </div>
      )}

      {filteredEntries.map((entry) => (
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
    </div>
  );
}
