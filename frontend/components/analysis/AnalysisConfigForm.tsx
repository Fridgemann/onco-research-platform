'use client'

import { useEffect, useRef, useState } from 'react'
import { ApiError } from '@/lib/api'
import { fetchAnalysisPreflight, serializeClassLabels, setClassLabel } from '@/lib/analysis'
import AnalysisPreflightSummary from './AnalysisPreflightSummary'
import OutcomeConfirm from './OutcomeConfirm'
import { ColumnMultiSelect, ColumnRoleSelect } from './ColumnRoleSelect'
import type {
  AnalysisClassLabel,
  AnalysisPreflightResponse,
  AnalysisTypedValue,
} from '@/lib/types'

// Configuration for descriptive statistics, linear regression, and logistic
// regression (Milestone 4, Slice 5). Kaplan-Meier keeps its own form.
//
// Column roles are chosen from the dataset's real columns instead of typed
// into free-text boxes, and submission is gated on a backend preflight the
// same way Kaplan-Meier is. The gate is UX only — the run re-validates.

export type AnalysisJobType = 'descriptive_stats' | 'regression' | 'logistic_regression'

export type AnalysisConfig = {
  columns: string[]            // descriptive
  target_column: string        // regression + logistic
  feature_columns: string[]    // regression + logistic
  positive_class: AnalysisTypedValue | null   // logistic, confirmed by the user
  class_labels: AnalysisClassLabel[]          // logistic, optional display names
}

export const EMPTY_ANALYSIS_CONFIG: AnalysisConfig = {
  columns: [],
  target_column: '',
  feature_columns: [],
  positive_class: null,
  class_labels: [],
}

export function analysisConfigToParams(
  jobType: AnalysisJobType,
  cfg: AnalysisConfig,
): Record<string, unknown> {
  if (jobType === 'descriptive_stats') {
    // An empty selection means "every numeric column", which is what the
    // backend already defaults to; the form says so next to the picker.
    return cfg.columns.length ? { columns: cfg.columns } : {}
  }

  const params: Record<string, unknown> = {
    target_column: cfg.target_column,
    feature_columns: cfg.feature_columns,
  }
  if (jobType === 'logistic_regression') {
    // Sent only once the researcher has chosen; the backend rejects a
    // submission without it rather than picking an orientation itself.
    if (cfg.positive_class) params.positive_class = cfg.positive_class
    // Trimming happens here, not while typing, so a label keeps its spaces
    // until it is actually sent.
    const labels = serializeClassLabels(cfg.class_labels)
    if (labels.length) params.class_labels = labels
  }
  return params
}

/** Whether the form has enough filled in to be worth validating. */
function canValidate(jobType: AnalysisJobType, cfg: AnalysisConfig): boolean {
  if (jobType === 'descriptive_stats') return true
  return !!cfg.target_column && cfg.feature_columns.length > 0
}

export default function AnalysisConfigForm({
  workspaceId,
  datasetId,
  jobType,
  columns,
  config,
  setConfig,
  preflight,
  setPreflight,
}: {
  workspaceId: string
  datasetId: string
  jobType: AnalysisJobType
  columns: string[]
  config: AnalysisConfig
  setConfig: (c: AnalysisConfig) => void
  preflight: AnalysisPreflightResponse | null
  setPreflight: (p: AnalysisPreflightResponse | null) => void
}) {
  const [validating, setValidating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // `shown` is the display copy of the last preflight. It survives an outcome
  // or label edit so those controls stay on screen; the parent's `preflight`
  // is the submission gate and is cleared the moment anything changes, so
  // stale counts can never authorize a run. (The M3 lesson: clearing both
  // unmounted the controls the researcher was in the middle of using.)
  const [shown, setShown] = useState<AnalysisPreflightResponse | null>(null)
  const stale = !!shown && !preflight

  // Only the newest validation may touch state. Two independent guards,
  // because neither alone is enough: the abort ends the request, and the
  // sequence number plus a fingerprint of what was actually validated reject
  // a response that resolved before its abort landed. Without them a slow
  // preflight for setup A could enable Run — and display A's classes and
  // counts — while setup B is on screen.
  const inFlightRef = useRef<AbortController | null>(null)
  const requestSeqRef = useRef(0)

  const fingerprint = JSON.stringify([
    datasetId, jobType, analysisConfigToParams(jobType, config),
  ])
  const fingerprintRef = useRef(fingerprint)
  fingerprintRef.current = fingerprint

  // Backstop invalidation. `update` already closes the gate synchronously;
  // these also drop the displayed panel when the columns change, because a
  // different column means different classes and different counts entirely.
  // Includes datasetId: switching datasets keeps this component mounted, and
  // a validation for the previous dataset must not survive the switch.
  const columnStamp = JSON.stringify([
    datasetId, jobType, config.columns, config.target_column, config.feature_columns,
  ])
  useEffect(() => {
    cancelInFlight()
    setPreflight(null)
    setShown(null)
    setError(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [columnStamp])

  // Changing only the outcome or its labels keeps the same classes: keep the
  // panel visible, but re-gate submission.
  const answerStamp = JSON.stringify([config.positive_class, config.class_labels])
  useEffect(() => {
    setPreflight(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [answerStamp])

  // Unmount: nothing left running, nothing left to settle.
  useEffect(() => () => cancelInFlight(), [])

  /** Abandon any validation in flight and stop it from settling into state. */
  function cancelInFlight() {
    inFlightRef.current?.abort()
    inFlightRef.current = null
    // Bumping the sequence retires the outstanding request even if its abort
    // arrives after the response, and releases the spinner that request owns.
    requestSeqRef.current++
    setValidating(false)
  }

  function update(patch: Partial<AnalysisConfig>) {
    // Close the gate in the SAME event as the edit, and drop any validation
    // still running for the previous setup. The effects below are a backstop
    // for state changes that do not come through here; relying on them alone
    // leaves the Run button enabled until React commits, which is a window
    // where a validated-looking button no longer matches what is on screen.
    cancelInFlight()
    setPreflight(null)
    setConfig({ ...config, ...patch })
  }

  async function handleValidate() {
    inFlightRef.current?.abort()
    const controller = new AbortController()
    inFlightRef.current = controller

    const seq = ++requestSeqRef.current
    const sentFor = fingerprint
    // Current means: newest request, not aborted, and the setup on screen is
    // still the one that was sent.
    const current = () =>
      seq === requestSeqRef.current
      && !controller.signal.aborted
      && fingerprintRef.current === sentFor

    setValidating(true)
    setError(null)
    try {
      const res = await fetchAnalysisPreflight(
        workspaceId, datasetId, jobType, analysisConfigToParams(jobType, config),
        controller.signal,
      )
      if (!current()) return
      setShown(res)
      setPreflight(res)
    } catch (err) {
      if (!current()) return   // superseded, not a failure
      setPreflight(null)
      setError(err instanceof ApiError ? err.message : 'Validation failed.')
    } finally {
      if (current()) setValidating(false)
    }
  }

  const ready = canValidate(jobType, config)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      {jobType === 'descriptive_stats' ? (
        <ColumnMultiSelect
          label="Columns to summarise"
          hint="Leave empty to summarise every numeric column."
          columns={columns}
          selected={config.columns}
          onChange={(next) => update({ columns: next })}
        />
      ) : (
        <>
          <ColumnRoleSelect
            id="analysis-target"
            label={jobType === 'logistic_regression' ? 'Outcome column' : 'Outcome (target) column'}
            hint={jobType === 'logistic_regression'
              ? 'The column recording what happened. It must hold exactly two values among the usable rows.'
              : 'The numeric column being predicted.'}
            columns={columns}
            value={config.target_column}
            onChange={(v) => update({
              target_column: v,
              // A new outcome column means new classes; a selection made for
              // the previous column must not silently carry over.
              feature_columns: config.feature_columns.filter((c) => c !== v),
              positive_class: null,
              class_labels: [],
            })}
          />
          <ColumnMultiSelect
            label="Predictor columns"
            hint="Numeric columns used to predict the outcome."
            columns={columns}
            selected={config.feature_columns}
            onChange={(next) => update({ feature_columns: next })}
            exclude={config.target_column ? [config.target_column] : []}
          />
        </>
      )}

      {/* Explicit Validate step, so preflight is not fired on every keystroke */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <button
          type="button"
          className="btn btn-outline btn-sm"
          disabled={!ready || validating}
          onClick={handleValidate}
        >
          {validating ? <><span className="spinner" /> Validating…</> : 'Validate configuration'}
        </button>
        {!ready && (
          <span style={{ fontSize: '10px', color: 'var(--text-secondary)' }}>
            Select an outcome column and at least one predictor first.
          </span>
        )}
      </div>

      {error && <div className="alert-error">{error}</div>}

      {shown && (
        <AnalysisPreflightSummary preflight={shown} stale={stale}>
          {jobType === 'logistic_regression' && shown.target_classes && (
            <div style={{ borderTop: '1px solid var(--border)', paddingTop: '12px' }}>
              <OutcomeConfirm
                classes={shown.target_classes}
                selected={config.positive_class}
                labels={config.class_labels}
                suggested={shown.suggested_positive_class}
                onSelect={(cls) => update({ positive_class: cls })}
                onLabel={(cls, label) =>
                  update({ class_labels: setClassLabel(config.class_labels, cls, label) })
                }
              />
              <p style={{ fontSize: '10px', color: 'var(--text-secondary)', marginTop: '8px', opacity: 0.8 }}>
                You changed the model setup. Validate again before running.
              </p>
            </div>
          )}
        </AnalysisPreflightSummary>
      )}
    </div>
  )
}
