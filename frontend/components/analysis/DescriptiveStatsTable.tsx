'use client'

const COLS = ['count', 'mean', 'std', 'min', 'p25', 'median', 'p75', 'max', 'missing'] as const
const COL_LABELS: Record<typeof COLS[number], string> = {
  count: 'N', mean: 'Mean', std: 'Std', min: 'Min',
  p25: 'P25', median: 'Median', p75: 'P75', max: 'Max', missing: 'Missing',
}

function fmt(v: number, key: string): string {
  if (key === 'count' || key === 'missing') return String(v)
  return v.toFixed(3)
}

export default function DescriptiveStatsTable({ data }: { data: Record<string, Record<string, number>> }) {
  const columns = Object.keys(data)
  if (columns.length === 0) return null

  return (
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
              {COLS.map(c => (
                <td key={c} style={tdStyle({ warn: c === 'missing' && data[col][c] > 0 })}>
                  {fmt(data[col][c] ?? 0, c)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function thStyle({ left }: { left?: boolean }) {
  return {
    padding: '8px 12px',
    textAlign: (left ? 'left' : 'right') as const,
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
