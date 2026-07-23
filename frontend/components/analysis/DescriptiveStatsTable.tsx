'use client'

type BinaryCode = { count: number; percent: number }

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
  is_binary?: boolean
  binary_counts?: { coded_0: BinaryCode; coded_1: BinaryCode } | null
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

function BinaryColumnCard({ col, stats }: { col: string; stats: ColumnStats }) {
  const bc = stats.binary_counts
  if (!bc) return null
  return (
    <div style={{
      border: '1px solid var(--border)',
      borderRadius: 'var(--radius)',
      padding: '12px 14px',
      background: 'var(--bg-surface)',
    }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px', marginBottom: '10px' }}>
        <p style={{ fontSize: '12px', color: '#c88828' }}>{col}</p>
        <p style={{ fontSize: '10px', color: 'var(--text-secondary)' }}>
          {stats.count} used
          {stats.missing > 0 && <> · <span style={{ color: '#e06c75' }}>{stats.missing} missing</span></>}
          {!!stats.non_numeric && stats.non_numeric > 0 && <> · <span style={{ color: '#e06c75' }}>{stats.non_numeric} non-numeric</span></>}
        </p>
      </div>
      <div style={{ display: 'flex', gap: '28px' }}>
        <div>
          <p style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-secondary)', marginBottom: '3px' }}>
            Coded 0
          </p>
          <p style={{ fontSize: '17px', fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
            {bc.coded_0.count}
            <span style={{ fontSize: '11px', color: 'var(--text-secondary)', marginLeft: '6px' }}>
              ({bc.coded_0.percent.toFixed(1)}%)
            </span>
          </p>
        </div>
        <div>
          <p style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-secondary)', marginBottom: '3px' }}>
            Coded 1
          </p>
          <p style={{ fontSize: '17px', fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
            {bc.coded_1.count}
            <span style={{ fontSize: '11px', color: 'var(--text-secondary)', marginLeft: '6px' }}>
              ({bc.coded_1.percent.toFixed(1)}%)
            </span>
          </p>
        </div>
      </div>
      <p style={{ fontSize: '10px', color: 'var(--text-secondary)', marginTop: '10px', opacity: 0.75 }}>
        Binary-coded column — what 0 and 1 represent (e.g. yes/no, male/female) is not inferred from the column name. Check your dataset documentation.
      </p>
    </div>
  )
}

export default function DescriptiveStatsTable({ data }: { data: Record<string, ColumnStats> }) {
  const columns = Object.keys(data)
  if (columns.length === 0) return null

  const binaryColumns = columns.filter((col) => data[col].is_binary)
  const otherColumns = columns.filter((col) => !data[col].is_binary)

  const codeEntries = columns
    .map((col) => [col, data[col].top_non_numeric_codes] as const)
    .filter(([, codes]) => codes && Object.keys(codes).length > 0)

  const normalizedEntries = columns
    .map((col) => [col, data[col]] as const)
    .filter(([, stats]) => (stats.normalized ?? 0) > 0)

  return (
    <div>
      {binaryColumns.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: otherColumns.length > 0 ? '20px' : 0 }}>
          {binaryColumns.map((col) => (
            <BinaryColumnCard key={col} col={col} stats={data[col]} />
          ))}
        </div>
      )}

      {otherColumns.length > 0 && (
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '12px' }}>
            <thead>
              <tr>
                <th style={thStyle({ left: true })}>Column</th>
                {COLS.map(c => <th key={c} style={thStyle({})}>{COL_LABELS[c]}</th>)}
              </tr>
            </thead>
            <tbody>
              {otherColumns.map((col, i) => (
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
      )}

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
