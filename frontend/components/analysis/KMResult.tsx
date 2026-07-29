'use client'

import KMCurveChart from './KMCurveChart'
import type { KMCurve, KMGroup, KMResultData } from '@/lib/types'

// Structured Kaplan-Meier result display. Every number shown here is read
// directly from the backend result — no statistic is recomputed in the
// browser.

const COMPARISON_REASONS: Record<string, string> = {
  no_observed_events:
    'No events were observed, so a log-rank comparison is not defined for these data.',
  insufficient_groups: 'A comparison needs at least two groups.',
  undefined: 'A log-rank comparison could not be computed for these data.',
}

function fmtProb(v: number): string {
  return `${(v * 100).toFixed(1)}%`
}

function fmtMedian(v: number | null): string {
  return v === null ? 'not reached' : v.toFixed(2)
}

function fmtP(p: number): string {
  return p < 0.001 ? '< 0.001' : p.toFixed(4)
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <p style={{
      fontSize: '10px', letterSpacing: '0.07em', textTransform: 'uppercase',
      color: 'var(--text-secondary)', marginBottom: '8px',
    }}>
      {children}
    </p>
  )
}

const th: React.CSSProperties = {
  padding: '6px 10px', textAlign: 'right', color: '#7a8399',
  fontFamily: 'var(--font-mono)', fontSize: '10px', letterSpacing: '0.05em',
  textTransform: 'uppercase', borderBottom: '1px solid #1e2433', whiteSpace: 'nowrap',
}
const td: React.CSSProperties = {
  padding: '5px 10px', textAlign: 'right', fontFamily: 'var(--font-mono)',
  fontSize: '11px', color: '#b8a99a', borderBottom: '1px solid rgba(255,255,255,0.04)',
}

function GroupSummary({ groups }: { groups: KMGroup[] }) {
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={{ ...th, textAlign: 'left' }}>Group</th>
            <th style={th}>N</th>
            <th style={th}>Events</th>
            <th style={th}>Censored</th>
            <th style={th}>Median survival</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((g) => (
            <tr key={String(g.label)}>
              <td style={{ ...td, textAlign: 'left', color: '#c88828' }}>{String(g.label)}</td>
              <td style={td}>{g.curve.n}</td>
              <td style={td}>{g.curve.n_events}</td>
              <td style={td}>{g.curve.n_censored}</td>
              <td style={td}>{fmtMedian(g.curve.median_survival)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SurvivalTable({ label, curve }: { label: string; curve: KMCurve }) {
  return (
    <div style={{ overflowX: 'auto', maxHeight: '260px', overflowY: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={{ ...th, textAlign: 'left' }}>Time</th>
            <th style={th}>Survival</th>
            <th style={th}>95% CI lower</th>
            <th style={th}>95% CI upper</th>
          </tr>
        </thead>
        <tbody>
          {curve.timeline.map((t, i) => (
            <tr key={`${label}-${t}-${i}`}>
              <td style={{ ...td, textAlign: 'left' }}>{t}</td>
              <td style={td}>{fmtProb(curve.survival_probability[i])}</td>
              <td style={td}>{fmtProb(curve.ci_lower[i])}</td>
              <td style={td}>{fmtProb(curve.ci_upper[i])}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function RiskTable({ label, curve }: { label: string; curve: KMCurve }) {
  const rt = curve.risk_table
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={{ ...th, textAlign: 'left' }}>Time</th>
            {rt.time.map((t, i) => <th key={`${label}-h-${t}-${i}`} style={th}>{t}</th>)}
          </tr>
        </thead>
        <tbody>
          <tr>
            <td style={{ ...td, textAlign: 'left' }}>At risk</td>
            {rt.at_risk.map((v, i) => <td key={`${label}-r-${i}`} style={td}>{v}</td>)}
          </tr>
          <tr>
            <td style={{ ...td, textAlign: 'left' }}>Events</td>
            {rt.events.map((v, i) => <td key={`${label}-e-${i}`} style={td}>{v}</td>)}
          </tr>
          <tr>
            <td style={{ ...td, textAlign: 'left' }}>Censored</td>
            {rt.censored.map((v, i) => <td key={`${label}-c-${i}`} style={td}>{v}</td>)}
          </tr>
        </tbody>
      </table>
    </div>
  )
}

export default function KMResult({ data }: { data: KMResultData }) {
  if (!data?.groups?.length) {
    return (
      <p style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
        This result contains no survival curves to display.
      </p>
    )
  }

  const c = data.counts
  const comparison = data.comparison

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '22px' }}>
      <KMCurveChart groups={data.groups} />

      <p style={{ fontSize: '10px', color: 'var(--text-secondary)', opacity: 0.85, lineHeight: 1.6 }}>
        The curve steps down at each observed event. A censor mark (✚) means the subject
        was event-free up to that time and their status afterward is unknown — it is not
        an event. The shaded band is the pointwise 95% confidence interval.
      </p>

      {/* Cohort counts */}
      {c && (
        <div>
          <SectionTitle>Rows used</SectionTitle>
          <p style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
            {c.used_rows} of {c.total_rows} rows included · {c.events} events ·{' '}
            {c.censored} censored ({c.censoring_percentage.toFixed(1)}% censored)
            {c.excluded_rows > 0 ? ` · ${c.excluded_rows} excluded` : ''}
          </p>
        </div>
      )}

      <div>
        <SectionTitle>Groups</SectionTitle>
        <GroupSummary groups={data.groups} />
      </div>

      {/* Group comparison */}
      {comparison && (
        <div>
          <SectionTitle>Group comparison</SectionTitle>
          {comparison.available ? (
            <>
              <p style={{ fontSize: '12px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
                Log-rank χ² = {comparison.chi_square.toFixed(3)} · df ={' '}
                {comparison.degrees_of_freedom} · p = {fmtP(comparison.p_value)}
              </p>
              <p style={{ fontSize: '10px', color: 'var(--text-secondary)', marginTop: '4px', opacity: 0.85 }}>
                The log-rank test asks whether the survival curves differ. It does not
                say which group is better, by how much, or why.
              </p>
            </>
          ) : (
            <p style={{ fontSize: '11px', color: '#c8a44a' }}>
              {COMPARISON_REASONS[comparison.reason] ?? 'Comparison unavailable.'}
            </p>
          )}
        </div>
      )}

      {/* Per-group tables */}
      {data.groups.map((g) => (
        <div key={`tables-${String(g.label)}`} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <SectionTitle>{String(g.label)} — survival estimates</SectionTitle>
          <SurvivalTable label={String(g.label)} curve={g.curve} />
          <div>
            <SectionTitle>{String(g.label)} — number at risk</SectionTitle>
            <RiskTable label={String(g.label)} curve={g.curve} />
          </div>
        </div>
      ))}

      {/* Assumptions */}
      {data.assumptions?.length > 0 && (
        <div>
          <SectionTitle>Assumptions and limitations</SectionTitle>
          <ul style={{ margin: 0, paddingLeft: '16px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {data.assumptions.map((a, i) => (
              <li key={i} style={{ fontSize: '11px', color: 'var(--text-secondary)', lineHeight: 1.5 }}>{a}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Reproducibility */}
      {data.reproducibility && (
        <details>
          <summary style={{ fontSize: '10px', letterSpacing: '0.07em', textTransform: 'uppercase', color: 'var(--text-secondary)', cursor: 'pointer' }}>
            Reproducibility
          </summary>
          <div style={{ marginTop: '8px', fontSize: '11px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', display: 'flex', flexDirection: 'column', gap: '3px' }}>
            <span>library: {data.reproducibility.library} {data.reproducibility.library_version}</span>
            <span>CI method: {data.reproducibility.ci_method} at {(data.reproducibility.ci_level * 100).toFixed(0)}%</span>
            <span>at-risk convention: {data.reproducibility.at_risk_convention.replace(/_/g, ' ')}</span>
            <details style={{ marginTop: '4px' }}>
              <summary style={{ cursor: 'pointer' }}>parameters</summary>
              <pre style={{ fontSize: '10px', overflowX: 'auto', marginTop: '4px' }}>
                {JSON.stringify(data.reproducibility.parameters, null, 2)}
              </pre>
            </details>
          </div>
        </details>
      )}
    </div>
  )
}
