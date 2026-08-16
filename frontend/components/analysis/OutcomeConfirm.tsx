'use client'

import {
  CLASS_LABEL_MAX_LEN,
  classKey,
  formatClassValue,
  getClassLabel,
  outcomeName,
  sameClass,
} from '@/lib/analysis'
import { labelStyle } from './ColumnRoleSelect'
import type { AnalysisClassCount, AnalysisClassLabel, AnalysisTypedValue } from '@/lib/types'

// Which outcome the model predicts is a clinical decision, not a library
// detail. sklearn would silently treat classes_[1] as positive; here the
// researcher chooses, nothing is pre-confirmed, and the consequence is
// stated back before the run.
//
// The question deliberately does not lead with "positive class" — that term
// appears once, as secondary helper text, because "positive" means only "the
// selected outcome" and is routinely read as "the good outcome".

export default function OutcomeConfirm({
  classes,
  selected,
  labels,
  suggested,
  onSelect,
  onLabel,
}: {
  classes: AnalysisClassCount[]
  selected: AnalysisTypedValue | null
  labels: AnalysisClassLabel[]
  suggested: AnalysisTypedValue | null
  onSelect: (cls: AnalysisTypedValue) => void
  onLabel: (cls: AnalysisTypedValue, label: string) => void
}) {
  if (classes.length === 0) return null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
      <div>
        <span style={{ ...labelStyle, marginBottom: '6px' }}>
          Which outcome should the model predict?
        </span>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {classes.map((c) => {
            const isSuggested = sameClass(suggested, c)
            const unsupported = c.value_type === 'unsupported'
            return (
              <label
                key={classKey(c)}
                style={{
                  display: 'flex', alignItems: 'center', gap: '8px',
                  fontSize: '12px', cursor: unsupported ? 'not-allowed' : 'pointer',
                  color: unsupported ? 'var(--text-secondary)' : 'var(--text-primary)',
                }}
              >
                <input
                  type="radio"
                  name="positive-class"
                  disabled={unsupported}
                  checked={sameClass(selected, c)}
                  onChange={() => onSelect({ value: c.value, value_type: c.value_type })}
                />
                <span style={{ fontFamily: 'var(--font-mono)', minWidth: '110px' }}>
                  {formatClassValue(c.value, c.value_type)}
                </span>
                <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
                  {c.count} row{c.count === 1 ? '' : 's'}
                </span>
                {/* A suggestion is shown, never applied on the researcher's
                    behalf — nothing is pre-selected. */}
                {isSuggested && !sameClass(selected, c) && (
                  <span style={{ fontSize: '10px', color: 'var(--text-secondary)', opacity: 0.75 }}>
                    common coding for this kind of column
                  </span>
                )}
              </label>
            )
          })}
        </div>
      </div>

      {/* State the consequence back in the researcher's own words. */}
      {selected && (
        <p style={{ fontSize: '12px', color: 'var(--text-primary)' }}>
          The model will estimate the probability of{' '}
          <strong>{outcomeName(selected, labels)}</strong>.
        </p>
      )}

      <p style={{ fontSize: '10px', color: 'var(--text-secondary)', opacity: 0.85, lineHeight: 1.6 }}>
        Statisticians call this the positive class. &quot;Positive&quot; means the selected
        outcome — not necessarily a good outcome. Changing it after a run has finished
        configures a new analysis; an existing result is never re-oriented.
      </p>

      <div>
        <span style={{ ...labelStyle, marginBottom: '6px' }}>
          Outcome names <span style={{ opacity: 0.6, textTransform: 'none' }}>(optional)</span>
        </span>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {classes.filter((c) => c.value_type !== 'unsupported').map((c) => (
            <div key={classKey(c)} style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span style={{
                fontFamily: 'var(--font-mono)', fontSize: '11px',
                color: 'var(--text-secondary)', minWidth: '110px',
              }}>
                {formatClassValue(c.value, c.value_type)}
              </span>
              <input
                className="field-input"
                style={{ maxWidth: '260px' }}
                maxLength={CLASS_LABEL_MAX_LEN}
                value={getClassLabel(labels, c)}
                onChange={(e) => onLabel({ value: c.value, value_type: c.value_type }, e.target.value)}
                placeholder="e.g. recurrence"
              />
            </div>
          ))}
        </div>
        <p style={{ fontSize: '10px', color: 'var(--text-secondary)', marginTop: '4px', opacity: 0.8 }}>
          Names are shown alongside the results. They label the values; they do not
          change the fit.
        </p>
      </div>
    </div>
  )
}
