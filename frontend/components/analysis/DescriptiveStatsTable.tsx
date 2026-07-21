'use client'

type ColumnStats = {
  count: number
  mean: number
  std: number
  min: number
  p25: number
  median: number
  p75: number
  max: number
  missing: number
  non_numeric?: number
  top_non_numeric_codes?: Record<string, number>
  normalized?: number
  normalized_rule?: string | null
  normalized_examples?: { raw: string; parsed: number }[]
}

const NORMALIZED_RULE_LABELS: Record<string, string> = {
  english_thousands_grouping: 'English thousands formatting',
}

const COLS = ['count', 'mean', 'std', 'min', 'p25', 'median', 'p75', 'max', 'missing', 'non_numeric'] as const
const COL_LABELS: Record<typeof COLS[number], string> = {
  count: 'N', mean: 'Mean', std: 'Std', min: 'Min',
  p25: 'P25', median: 'Median', p75: 'P75', max: 'Max',
  missing: 'Missing', non_numeric: 'Non-numeric',
}

function fmt(v: number, key: string): string {
  if (key === 'count' || key === 'missing' || key === 'non_numeric') return String(v)
  return v.toFixed(3)
}

export default function DescriptiveStatsTable({ data }: { data: Record<string, ColumnStats> }) {
  const columns = Object.keys(data)
  if (columns.length === 0) return null

  const codeEntries = columns
    .map((col) => [col, data[col].top_non_numeric_codes] as const)
    .filter(([, codes]) => codes && Object.keys(codes).length > 0)

  const normalizedEntries = columns
    .map((col) => [col, data[col]] as const)
    .filter(([, stats]) => (stats.normalized ?? 0) > 0)

  return (
    <div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
          <thead>
            <tr>
              <th style={thStyle({ left: true })}>Column</th>
              {COLS.map(c => <th key={c} style={thStyle({})}>{COL_LABELS[c]}</th>)}
            </tr>
          </thead>
          <tbody>
            {columns.map((col, i) => (
              <tr key={col} style={{ background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.02)' }}>
                <td style={tdStyle({ accent: true })}>{col}</td>
                {COLS.map(c => {
                  const v = data[col][c]
                  return (
                    <td key={c} style={tdStyle({ warn: (c === 'missing' || c === 'non_numeric') && !!v && v > 0 })}>
                      {v === undefined ? '—' : fmt(v, c)}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {normalizedEntries.length > 0 && (
        <div style={{ marginTop: '10px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {normalizedEntries.map(([col, stats]) => {
            const ruleLabel = stats.normalized_rule ? NORMALIZED_RULE_LABELS[stats.normalized_rule] ?? stats.normalized_rule : null
            return (
              <div key={col}>
                <p style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
                  <span style={{ color: '#3d8f5e' }}>{col}</span>: {stats.normalized} value{stats.normalized === 1 ? '' : 's'} normalized
                  {ruleLabel ? ` using ${ruleLabel}` : ''} and included in the calculation.
                </p>
                {stats.normalized_examples && stats.normalized_examples.length > 0 && (
                  <details style={{ marginTop: '3px' }}>
                    <summary style={{ fontSize: '10px', color: 'var(--text-secondary)', cursor: 'pointer' }}>
                      Data processing details
                    </summary>
                    <p style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '4px', paddingLeft: '4px' }}>
                      {stats.normalized_examples.map((ex) => `"${ex.raw}" → ${ex.parsed}`).join(', ')}
                    </p>
                  </details>
                )}
              </div>
            )
          })}
        </div>
      )}

      {codeEntries.length > 0 && (
        <div style={{ marginTop: '10px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
          {codeEntries.map(([col, codes]) => (
            <p key={col} style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
              <span style={{ color: '#c88828' }}>{col}</span> non-numeric codes (excluded):{' '}
              {Object.entries(codes!).map(([code, count]) => `"${code}" ×${count}`).join(', ')}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

function thStyle({ left }: { left?: boolean }) {
  return {
    padding: '8px 12px',
    textAlign: (left ? 'left' : 'right') as 'left' | 'right',
    color: '#7a8399',
    fontFamily: 'var(--font-mono)',
    fontSize: '10px',
    letterSpacing: '0.06em',
    textTransform: 'uppercase' as const,
    borderBottom: '1px solid #1e2433',
    whiteSpace: 'nowrap' as const,
  }
}

function tdStyle({ accent, warn }: { accent?: boolean; warn?: boolean }) {
  return {
    padding: '7px 12px',
    textAlign: 'right' as const,
    fontFamily: 'var(--font-mono)',
    color: accent ? '#c88828' : warn ? '#e06c75' : '#b8a99a',
    borderBottom: '1px solid rgba(255,255,255,0.04)',
  }
}
