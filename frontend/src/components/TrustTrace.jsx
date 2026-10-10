import { useEffect, useState } from 'react';
import { api } from '../api.js';

/**
 * TrustTrace — an explainable, evidence-first assessment of a plate result.
 *
 * It renders ONLY the real, measured signals the backend already computes
 * (OCR confidence + spread, cross-read agreement, the confusion-tolerant
 * recoveries, route plausibility with a possible-cloned-plate flag, and the
 * hash-chained evidence-integrity status). The overall band is a deterministic
 * heuristic over those measured values — an evidence-quality indicator for a
 * human to verify, never a claim of identity or guilt.
 */
const BAND = {
  high: { label: 'HIGH CONFIDENCE', fg: '#1E7A52', bg: 'rgba(30,122,82,0.14)', bd: '#2E9D6E' },
  medium: { label: 'MEDIUM — VERIFY', fg: '#9A6A08', bg: 'rgba(200,134,11,0.15)', bd: '#C8860B' },
  low: { label: 'LOW — LEAD ONLY', fg: '#B4431A', bg: 'rgba(180,67,26,0.15)', bd: '#D1662F' },
  'no-evidence': { label: 'NO EVIDENCE', fg: '#5A6B7B', bg: 'rgba(90,107,123,0.14)', bd: '#7D8EA0' },
};

const pct = (v) => (v == null ? '—' : `${Math.round(v * 100)}%`);

export default function TrustTrace({ plate }) {
  const [data, setData] = useState(null);
  const [status, setStatus] = useState('idle'); // idle | loading | done | error
  const [open, setOpen] = useState(true);

  useEffect(() => {
    if (!plate) return;
    let cancelled = false;
    setStatus('loading');
    api
      .assessment(plate)
      .then((d) => {
        if (cancelled) return;
        setData(d);
        setStatus('done');
      })
      .catch(() => {
        if (cancelled) return;
        setStatus('error');
      });
    return () => {
      cancelled = true;
    };
  }, [plate]);

  if (status === 'loading') {
    return <div className="trusttrace loading">Assessing evidence…</div>;
  }
  if (status === 'error' || !data) return null;

  const band = BAND[data.assessment.band] || BAND['no-evidence'];
  const ocr = data.ocr;
  const m = data.matching;
  const rp = data.route_plausibility;

  return (
    <section
      className="trusttrace"
      style={{
        marginTop: '1rem',
        border: '1px solid var(--rule, #2a3745)',
        borderRadius: '8px',
        overflow: 'hidden',
        fontSize: '0.9rem',
      }}
    >
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          gap: '0.6rem',
          padding: '0.7rem 0.9rem',
          background: band.bg,
          borderLeft: `4px solid ${band.bd}`,
          border: 'none',
          borderBottom: open ? `1px solid var(--rule, #2a3745)` : 'none',
          cursor: 'pointer',
          textAlign: 'left',
          color: 'inherit',
        }}
        aria-expanded={open}
      >
        <span style={{ fontWeight: 700, letterSpacing: '0.1em', fontSize: '0.72rem', color: band.fg }}>
          TRUSTTRACE
        </span>
        <span
          style={{
            fontFamily: 'ui-monospace, Menlo, monospace',
            fontWeight: 700,
            fontSize: '0.72rem',
            letterSpacing: '0.05em',
            color: band.fg,
            padding: '0.15em 0.5em',
            border: `1px solid ${band.bd}`,
            borderRadius: '999px',
          }}
        >
          {band.label}
        </span>
        <span style={{ marginLeft: 'auto', opacity: 0.6, fontSize: '0.8rem' }}>{open ? '▾' : '▸'}</span>
      </button>

      {open && (
        <div style={{ padding: '0.85rem 0.9rem', display: 'grid', gap: '0.85rem' }}>
          {/* measured signal tiles */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(6.5rem, 1fr))', gap: '0.5rem' }}>
            <Tile k="Best OCR" v={pct(ocr.best_confidence)} />
            <Tile k="Mean OCR" v={pct(ocr.mean_confidence)} />
            <Tile k="Reads" v={ocr.reads} sub={`${ocr.cameras} cam${ocr.cameras === 1 ? '' : 's'}`} />
            <Tile k="Accepted" v={rp.accepted_sightings} sub={rp.rejected_sightings ? `${rp.rejected_sightings} rejected` : 'no conflict'} />
          </div>

          {/* fuzzy recoveries */}
          {m.has_fuzzy && m.recovered_variants.length > 0 && (
            <Row title={`OCR misreads recovered (${m.fuzzy_reads} of ${ocr.reads})`}>
              {m.recovered_variants.map((v, i) => (
                <div key={i} style={{ fontFamily: 'ui-monospace, Menlo, monospace', fontSize: '0.84rem' }}>
                  <span style={{ opacity: 0.7 }}>{v.read}</span>
                  {' → '}
                  <strong>{v.recovered_as}</strong>
                  <span style={{ opacity: 0.7 }}>{' '}at {pct(v.match_confidence)}</span>
                </div>
              ))}
            </Row>
          )}

          {/* route plausibility / clone */}
          {(rp.rejected_sightings > 0 || rp.clone_suspected) && (
            <Row title="Route plausibility">
              {rp.clone_suspected && (
                <div style={{ color: '#B4431A', fontWeight: 600 }}>
                  ⚠ Possible cloned / duplicate plate — same registration seen in two places too fast. Verify before acting.
                </div>
              )}
              {rp.warnings.map((w, i) => (
                <div key={i} style={{ opacity: 0.85 }}>
                  {w.camera}: {w.reason}
                </div>
              ))}
            </Row>
          )}

          {/* flags */}
          {data.assessment.flags.length > 0 && (
            <Row title="Assessment">
              <ul style={{ margin: 0, paddingLeft: '1.1rem' }}>
                {data.assessment.flags.map((f, i) => (
                  <li key={i} style={{ margin: '0.15rem 0' }}>{f}</li>
                ))}
              </ul>
            </Row>
          )}

          {/* integrity */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', fontSize: '0.82rem', opacity: 0.85 }}>
            <span style={{ color: '#1E7A52', fontWeight: 700 }}>✓</span>
            <span>Evidence integrity: {data.evidence_integrity.method}.</span>
            <a href={data.evidence_integrity.dossier_url} target="_blank" rel="noreferrer" style={{ marginLeft: 'auto' }}>
              Open dossier
            </a>
          </div>

          <p style={{ margin: 0, fontSize: '0.74rem', opacity: 0.6, lineHeight: 1.4 }}>
            {data.assessment.basis}
          </p>
        </div>
      )}
    </section>
  );
}

function Tile({ k, v, sub }) {
  return (
    <div style={{ background: 'var(--surface-2, rgba(127,127,127,0.06))', borderRadius: '6px', padding: '0.5rem 0.6rem' }}>
      <div style={{ fontSize: '0.68rem', textTransform: 'uppercase', letterSpacing: '0.05em', opacity: 0.6 }}>{k}</div>
      <div style={{ fontSize: '1.25rem', fontWeight: 700, lineHeight: 1.1, fontVariantNumeric: 'tabular-nums' }}>{v}</div>
      {sub && <div style={{ fontSize: '0.7rem', opacity: 0.6, marginTop: '0.1rem' }}>{sub}</div>}
    </div>
  );
}

function Row({ title, children }) {
  return (
    <div>
      <div style={{ fontSize: '0.7rem', textTransform: 'uppercase', letterSpacing: '0.06em', opacity: 0.6, marginBottom: '0.3rem' }}>
        {title}
      </div>
      <div style={{ display: 'grid', gap: '0.2rem' }}>{children}</div>
    </div>
  );
}
