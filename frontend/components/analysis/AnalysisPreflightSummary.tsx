'use client'

import { ANALYSIS_BLOCKER_LABELS } from '@/lib/analysis'
import type { AnalysisPreflightResponse } from '@/lib/types'

// What the run will actually use, shown before it is submitted. The counts
// come from the same preparation helpers the run uses, so they are not an
// estimate. Excluded rows are always visible: a result computed on 1,487 of
// 1,500 rows should never look like a result for all 1,500.

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p style={{
        fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.06em',
        color: 'var(--text-secondary)',
      }}>
        {label}
      </p>
      <p style={{ fontSize: '15px', fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
        {value}
      </p>
    </div>
  )
}

export default function AnalysisPreflightSummary({
  preflight,
  stale,
  children,
}: {
  preflight: AnalysisPreflightResponse
  stale: boolean
  children?: React.ReactNode
}) {
  const joint = preflight.counts
  const perColumn = preflight.counts_by_column

  return (
    <div style={{
      border: `1px solid ${preflight.ready ? 'var(--border)' : '#c8a44a55'}`,
      borderRadius: 'var(--radius)',
      background: 'var(--bg-surface)',
      padding: '12px 14px',
      display: 'flex', flexDirection: 'column', gap: '12px',
    }}>
      <p style={{ fontSize: '11px', color: stale ? '#c8a44a' : preflight.ready ? '#3d8f5e' : '#c8a44a' }}>
        {stale
          ? '⟳ Configuration changed — validate this setup again.'
          : preflight.ready ? '✓ Ready to run' : '⚠ Not ready yet'}
      </p>

      <div style={{ opacity: stale ? 0.5 : 1, display: 'flex', flexDirection: 'column', gap: '12px' }}>
        {joint && (
          <>
            <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap' }}>
              <Stat label="Total rows" value={String(joint.total_rows)} />
              <Stat label="Included" value={String(joint.used_rows)} />
              <Stat label="Excluded" value={String(joint.excluded_rows)} />
            </div>
            {joint.excluded_rows > 0 && (
              <p style={{ fontSize: '10px', color: 'var(--text-secondary)' }}>
                A row is used only when every selected column has a usable value on it.
                Excluded by reason (one row can have more than one reason):{' '}
                {Object.entries(joint.exclusions)
                  .filter(([, n]) => n > 0)
                  .map(([k, n]) => `${k.replace(/_/g, ' ')}: ${n}`)
                  .join(' · ') || 'none'}
              </p>
            )}
          </>
        )}

        {/* Descriptive statistics are computed per column, so a single
            included/excluded pair would misdescribe them. */}
        {perColumn && (
          <div style={{ overflowX: 'auto' }}>
            <p style={{ fontSize: '10px', color: 'var(--text-secondary)', marginBottom: '6px' }}>
              Each column is summarised over its own usable rows.
            </p>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  {['Column', 'Used', 'Excluded', 'Missing', 'Not numeric'].map((h, i) => (
                    <th key={h} style={{
                      padding: '4px 8px', textAlign: i === 0 ? 'left' : 'right',
                      fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.05em',
                      color: 'var(--text-secondary)', borderBottom: '1px solid var(--border)',
                    }}>
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {Object.entries(perColumn).map(([name, c]) => (
                  <tr key={name}>
                    <td style={{
                      padding: '3px 8px', fontFamily: 'var(--font-mono)', fontSize: '11px',
                      color: c.used_rows === 0 ? '#e06c75' : '#c88828',
                    }}>
                      {name}
                    </td>
                    {[c.used_rows, c.excluded_rows, c.missing_rows, c.non_numeric_rows].map((n, i) => (
                      <td key={i} style={{
                        padding: '3px 8px', textAlign: 'right', fontFamily: 'var(--font-mono)',
                        fontSize: '11px', color: 'var(--text-secondary)',
                      }}>
                        {n}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {preflight.blockers.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: '16px', display: 'flex', flexDirection: 'column', gap: '3px' }}>
          {preflight.blockers.map((b) => (
            <li key={b} style={{ fontSize: '11px', color: '#c8a44a' }}>
              {ANALYSIS_BLOCKER_LABELS[b] ?? b}
            </li>
          ))}
        </ul>
      )}

      {children}
    </div>
  )
}
