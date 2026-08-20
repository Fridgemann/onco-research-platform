'use client'

import {
  ASSUMPTIONS_NOT_CHECKED,
  GLOSSARY,
  NO_CAUSAL_CLAIM,
  WHAT_WAS_CALCULATED,
  assumptionsFor,
  termsFor,
} from '@/lib/glossary'
import { formatClassValue } from '@/lib/analysis'
import type { AnalysisClassLabel, AnalysisTypedValue } from '@/lib/types'

// The "understand" layer (Milestone 4, Slice 6): what was calculated, what
// the numbers mean, and what the analysis is taking on faith.
//
// Every sentence describes a figure the analysis already produced — no new
// statistic is computed or implied here, and Kaplan-Meier is untouched: it
// carries its own guide, assumptions, and reproducibility block from M3.

const sectionTitle: React.CSSProperties = {
  fontSize: '10px',
  letterSpacing: '0.07em',
  textTransform: 'uppercase',
  color: 'var(--text-secondary)',
  marginBottom: '6px',
}

const body: React.CSSProperties = {
  fontSize: '11.5px',
  color: 'var(--text-secondary)',
  lineHeight: 1.65,
}

/**
 * For logistic regression, say which outcome the model was oriented to, using
 * the researcher's own label when they gave one. This reads the selection the
 * run already recorded; it never re-derives or re-orients anything.
 */
function OutcomeSentence({
  positiveClass,
  labels,
  confirmed,
}: {
  positiveClass: AnalysisTypedValue | null
  labels: AnalysisClassLabel[]
  confirmed: boolean
}) {
  if (!positiveClass || !confirmed) return null
  const named = labels.find(
    (l) => l.value_type === positiveClass.value_type && Object.is(l.value, positiveClass.value),
  )?.label
  const outcome = named || formatClassValue(positiveClass.value, positiveClass.value_type)

  return (
    <p style={{ ...body, color: 'var(--text-primary)' }}>
      Every probability, coefficient direction and AUC below refers to one outcome:{' '}
      <strong>{outcome}</strong>. A positive coefficient means a higher estimated
      probability of {outcome} as that predictor increases.
    </p>
  )
}

export default function MethodExplainer({
  jobType,
  resultType = null,
  positiveClass = null,
  classLabels = [],
  positiveClassConfirmed = false,
}: {
  jobType: string
  /** The `type` field of the stored result (e.g. "linear" vs
   *  "multiple_linear"). Which numbers exist depends on this, not on the job
   *  type alone, so it decides which terms and assumptions are shown. */
  resultType?: string | null
  positiveClass?: AnalysisTypedValue | null
  classLabels?: AnalysisClassLabel[]
  positiveClassConfirmed?: boolean
}) {
  const what = WHAT_WAS_CALCULATED[jobType]
  const terms = termsFor(jobType, resultType)
  const assumptions = assumptionsFor(jobType, resultType)
  if (!what && terms.length === 0 && assumptions.length === 0) return null

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', gap: '16px',
      border: '1px solid var(--border)', borderRadius: 'var(--radius)',
      background: 'var(--bg-surface)', padding: '14px 16px', marginTop: '22px',
    }}>
      {what && (
        <div>
          <p style={sectionTitle}>What was calculated</p>
          <p style={body}>{what}</p>
        </div>
      )}

      {jobType === 'logistic_regression' && (
        <OutcomeSentence
          positiveClass={positiveClass}
          labels={classLabels}
          confirmed={positiveClassConfirmed}
        />
      )}

      {terms.length > 0 && (
        <details>
          <summary style={{ ...sectionTitle, cursor: 'pointer', marginBottom: 0 }}>
            What these numbers mean
          </summary>
          <dl style={{ margin: '10px 0 0', display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {terms.map((key) => {
              const entry = GLOSSARY[key]
              if (!entry) return null
              return (
                <div key={key}>
                  <dt style={{ fontSize: '11px', color: '#c88828', fontFamily: 'var(--font-mono)' }}>
                    {entry.term}
                  </dt>
                  <dd style={{ ...body, margin: '2px 0 0' }}>
                    {entry.definition}
                    {entry.caution && (
                      <>
                        {' '}
                        <span style={{ color: '#c8a44a' }}>{entry.caution}</span>
                      </>
                    )}
                  </dd>
                </div>
              )
            })}
          </dl>
        </details>
      )}

      {assumptions.length > 0 && (
        <div>
          <p style={sectionTitle}>Assumptions and limitations</p>
          <ul style={{ margin: 0, paddingLeft: '16px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {assumptions.map((a) => (
              <li key={a} style={body}>{a}</li>
            ))}
          </ul>
          {/* Stated plainly because the platform will report numbers whether
              or not the assumptions above hold. */}
          <p style={{ ...body, color: '#c8a44a', marginTop: '8px' }}>
            {ASSUMPTIONS_NOT_CHECKED}
          </p>
        </div>
      )}

      <p style={{ ...body, opacity: 0.9 }}>{NO_CAUSAL_CLAIM}</p>
    </div>
  )
}
