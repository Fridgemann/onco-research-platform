'use client'

// Shared per-analysis data-preparation report (Milestone 2). Renders the
// joint row-exclusion summary from _meta plus the per-column `processing`
// section that regression, logistic regression, and Kaplan-Meier all return
// in the same shape. Numeric roles (target/feature/duration) can report
// missing, non-numeric, and normalized values; categorical roles (a logistic
// target, a KM event/group) report only missing — valid categorical text is
// never described as "non-numeric".

export type Meta = { total_rows: number; used_rows: number; dropped_rows: number }

export type ColumnProcessing = {
  role: string
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

function hasAnythingToReport(p: ColumnProcessing): boolean {
  return (p.missing ?? 0) > 0 || (p.non_numeric ?? 0) > 0 || (p.normalized ?? 0) > 0
}

export default function ProcessingReport({
  meta,
  processing,
}: {
  meta: Meta | null
  processing: Record<string, ColumnProcessing> | null
}) {
  if (!meta && !processing) return null

  const columns = processing ? Object.keys(processing) : []
  const reportable = columns.filter((c) => hasAnythingToReport(processing![c]))

  // Nothing excluded and nothing transformed — still confirm the row count
  // so the researcher knows the full cohort was used.
  const nothingHappened = (!meta || meta.dropped_rows === 0) && reportable.length === 0

  return (
    <div style={{ marginBottom: '16px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
      {meta && (
        <p style={{ fontSize: '11px', color: meta.dropped_rows > 0 ? '#c8a44a' : 'var(--text-secondary)' }}>
          {meta.dropped_rows > 0 ? '⚠ ' : ''}
          {meta.used_rows} of {meta.total_rows} rows used
          {meta.dropped_rows > 0 ? ` · ${meta.dropped_rows} excluded` : ''}.
        </p>
      )}

      {reportable.map((col) => {
        const p = processing![col]
        const parts: string[] = []
        if ((p.missing ?? 0) > 0) parts.push(`${p.missing} missing`)
        if ((p.non_numeric ?? 0) > 0) parts.push(`${p.non_numeric} non-numeric/coded`)
        if ((p.normalized ?? 0) > 0) {
          const ruleLabel = p.normalized_rule
            ? NORMALIZED_RULE_LABELS[p.normalized_rule] ?? p.normalized_rule
            : null
          parts.push(`${p.normalized} normalized${ruleLabel ? ` (${ruleLabel})` : ''}`)
        }
        const codes = p.top_non_numeric_codes && Object.keys(p.top_non_numeric_codes).length > 0
          ? p.top_non_numeric_codes
          : null

        return (
          <div key={col}>
            <p style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
              <span style={{ color: '#c88828' }}>{col}</span>
              <span style={{ opacity: 0.6 }}> ({p.role})</span>: {parts.join(', ')}.
            </p>
            {codes && (
              <p style={{ fontSize: '10px', color: 'var(--text-secondary)', paddingLeft: '4px', opacity: 0.85 }}>
                excluded codes: {Object.entries(codes).map(([code, count]) => `"${code}" ×${count}`).join(', ')}
              </p>
            )}
            {p.normalized_examples && p.normalized_examples.length > 0 && (
              <details style={{ marginTop: '2px', paddingLeft: '4px' }}>
                <summary style={{ fontSize: '10px', color: 'var(--text-secondary)', cursor: 'pointer' }}>
                  Data processing details
                </summary>
                <p style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '4px' }}>
                  {p.normalized_examples.map((ex) => `"${ex.raw}" → ${ex.parsed}`).join(', ')}
                </p>
              </details>
            )}
          </div>
        )
      })}

      {nothingHappened && processing && (
        <p style={{ fontSize: '10px', color: 'var(--text-secondary)', opacity: 0.7 }}>
          No values were excluded or transformed.
        </p>
      )}
    </div>
  )
}
