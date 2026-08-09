'use client'

import type { DatasetColumnProfile, DatasetInspect, DatasetDisplayType } from '@/lib/types'

// Shows the researcher what they actually uploaded, before they choose any
// analysis roles. Two things this deliberately never does: present a sampled
// figure as if it covered the whole file, or imply that a detected type is
// the column's real meaning.

const TYPE_LABELS: Record<DatasetDisplayType, string> = {
  numeric: 'Numeric',
  categorical: 'Categorical',
  binary: 'Binary (0/1)',
  empty: 'No values',
}

const TYPE_COLORS: Record<DatasetDisplayType, string> = {
  numeric: '#4a8fc1',
  categorical: '#c88828',
  binary: '#4ac17b',
  empty: '#7a8399',
}

function fmtCell(v: boolean | number | string | null): string {
  if (v === null) return '—'
  if (typeof v === 'boolean') return v ? 'true' : 'false'
  return String(v)
}

function TypeBadge({ type }: { type: DatasetDisplayType }) {
  return (
    <span style={{
      fontSize: '9px', letterSpacing: '0.05em', textTransform: 'uppercase',
      color: TYPE_COLORS[type], border: `1px solid ${TYPE_COLORS[type]}55`,
      borderRadius: '3px', padding: '1px 5px', whiteSpace: 'nowrap',
    }}>
      {TYPE_LABELS[type]}
    </span>
  )
}

const th: React.CSSProperties = {
  padding: '6px 10px', textAlign: 'left', color: '#7a8399',
  fontFamily: 'var(--font-mono)', fontSize: '10px', letterSpacing: '0.05em',
  textTransform: 'uppercase', borderBottom: '1px solid #1e2433', whiteSpace: 'nowrap',
}
const td: React.CSSProperties = {
  padding: '5px 10px', fontFamily: 'var(--font-mono)', fontSize: '11px',
  color: '#b8a99a', borderBottom: '1px solid rgba(255,255,255,0.04)', whiteSpace: 'nowrap',
}

function ScopeLine({ inspect }: { inspect: DatasetInspect }) {
  const { profiled_rows, profile_scope, total_rows } = inspect.profile
  const partial = profile_scope === 'partial'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
      <p style={{ fontSize: '11px', color: partial ? '#c8a44a' : 'var(--text-secondary)' }}>
        {partial
          ? `Based on the first ${profiled_rows.toLocaleString()} rows of this file — the full row count is not known here.`
          : `${total_rows?.toLocaleString()} rows · ${inspect.column_count} columns`}
      </p>
      {partial && (
        <p style={{ fontSize: '10px', color: 'var(--text-secondary)', opacity: 0.8 }}>
          Every count below describes those {profiled_rows.toLocaleString()} rows. Analyses still
          use the whole file.
        </p>
      )}
      {inspect.columns_truncated && (
        <p style={{ fontSize: '10px', color: '#c8a44a' }}>
          Detailed profiles shown for the first {inspect.columns_returned} of{' '}
          {inspect.column_count} columns. All {inspect.column_count} remain selectable
          when you set up an analysis.
        </p>
      )}
    </div>
  )
}

function ColumnTable({ columns, profiledRows }: { columns: DatasetColumnProfile[]; profiledRows: number }) {
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={th}>Column</th>
            <th style={th}>Detected type</th>
            <th style={{ ...th, textAlign: 'right' }}>Missing</th>
            <th style={{ ...th, textAlign: 'right' }}>Distinct</th>
            <th style={th}>Example values</th>
          </tr>
        </thead>
        <tbody>
          {columns.map((c) => (
            <tr key={c.name}>
              <td style={{ ...td, color: '#c88828' }}>{c.name}</td>
              <td style={td}><TypeBadge type={c.display_type} /></td>
              <td style={{ ...td, textAlign: 'right', color: c.missing > 0 ? '#e06c75' : '#b8a99a' }}>
                {c.missing > 0
                  ? `${c.missing} (${c.missing_percent.toFixed(1)}%)`
                  : '0'}
              </td>
              <td style={{ ...td, textAlign: 'right' }}>
                {c.distinct_count === null ? `> ${(c.distinct_values?.length ?? 20)}` : c.distinct_count}
              </td>
              <td style={{ ...td, color: 'var(--text-secondary)' }}>
                {c.example_values.length ? c.example_values.map(fmtCell).join(', ') : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p style={{ fontSize: '10px', color: 'var(--text-secondary)', marginTop: '6px', opacity: 0.85 }}>
        Missing and distinct counts describe the {profiledRows.toLocaleString()} rows profiled above.
      </p>
    </div>
  )
}

function SampleTable({ inspect }: { inspect: DatasetInspect }) {
  const names = inspect.columns.map((c) => c.name)
  if (!inspect.sample_rows.length) return null

  return (
    <div style={{ overflowX: 'auto', maxHeight: '260px', overflowY: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            {names.map((n) => <th key={n} style={th}>{n}</th>)}
          </tr>
        </thead>
        <tbody>
          {inspect.sample_rows.map((row, i) => (
            <tr key={i} style={{ background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)' }}>
              {names.map((n) => (
                <td key={n} style={{ ...td, color: row[n] === null ? '#5c6370' : '#b8a99a' }}>
                  {fmtCell(row[n] ?? null)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function DatasetInspector({
  inspect,
  loading,
  error,
  onRetry,
}: {
  inspect: DatasetInspect | null
  loading: boolean
  error: string | null
  onRetry?: () => void
}) {
  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '12px', color: 'var(--text-secondary)' }}>
        <span className="spinner" /> Reading dataset…
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <div className="alert-error" style={{ flex: 1 }}>{error}</div>
        {onRetry && (
          <button type="button" className="btn btn-outline btn-sm" onClick={onRetry}>
            Try again
          </button>
        )}
      </div>
    )
  }

  if (!inspect) return null

  return (
    <details open style={{ marginBottom: '20px' }}>
      <summary style={{
        fontSize: '10px', letterSpacing: '0.07em', textTransform: 'uppercase',
        color: 'var(--text-secondary)', cursor: 'pointer', marginBottom: '10px',
      }}>
        Your data
      </summary>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', marginTop: '10px' }}>
        <ScopeLine inspect={inspect} />

        {/* Header-only file. Every count below would be zero and every role
            dropdown empty; say why rather than showing a blank table. */}
        {inspect.profile.profiled_rows === 0 && (
          <div className="alert-error">
            This file has column names but no data rows, so nothing can be analysed.
            Upload a CSV that contains the patient rows as well.
          </div>
        )}

        <ColumnTable columns={inspect.columns} profiledRows={inspect.profile.profiled_rows} />

        {/* The single most important caveat on this screen: a detected type is
            a hint for narrowing choices, never a statement of clinical meaning. */}
        <p style={{ fontSize: '10px', color: 'var(--text-secondary)', opacity: 0.85, lineHeight: 1.6 }}>
          Detected type — verify against your dataset documentation. A column of 0/1/2 could be a
          count or a category such as low/medium/high; this platform cannot tell which. You choose
          what each column means when you set up the analysis.
        </p>

        <div>
          <p style={{
            fontSize: '10px', letterSpacing: '0.06em', textTransform: 'uppercase',
            color: 'var(--text-secondary)', marginBottom: '6px',
          }}>
            First {inspect.sample_rows.length} rows
          </p>
          <SampleTable inspect={inspect} />
        </div>
      </div>
    </details>
  )
}
