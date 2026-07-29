'use client'

import { useEffect, useState } from 'react'
import { ApiError } from '@/lib/api'
import {
  KM_BLOCKER_LABELS,
  effectiveRole,
  fetchKMPreflight,
  formatStatusValue,
  isAutoRole,
  setMappingRole,
} from '@/lib/km'
import type {
  KMEventMappingEntry,
  KMPreflightRequest,
  KMPreflightResponse,
  KMValueType,
} from '@/lib/types'

// Kaplan-Meier configuration flow (Milestone 3).
//
// Censoring is never assumed: the researcher states whether the dataset
// contains censored observations, and either maps every status value
// explicitly or confirms that all included rows are observed events. A
// Validate step calls the backend preflight (not fired on every keystroke)
// and submission is gated on its `ready` flag — the backend re-validates
// regardless, so this gating is UX only.

export type KMConfig = {
  time_column: string
  event_column: string
  group_column: string
  has_censoring: boolean
  event_mapping: KMEventMappingEntry[]
  all_events_confirmed: boolean
  max_groups: string
}

export const EMPTY_KM_CONFIG: KMConfig = {
  time_column: '',
  event_column: '',
  group_column: '',
  has_censoring: true,
  event_mapping: [],
  all_events_confirmed: false,
  max_groups: '',
}

export function kmConfigToParams(cfg: KMConfig): Record<string, unknown> {
  const params: Record<string, unknown> = {
    time_column: cfg.time_column,
    has_censoring: cfg.has_censoring,
  }
  if (cfg.group_column) params.group_column = cfg.group_column
  if (cfg.max_groups) params.max_groups = Number(cfg.max_groups)
  if (cfg.has_censoring) {
    params.event_column = cfg.event_column
    params.event_mapping = cfg.event_mapping
  } else {
    params.all_events_confirmed = cfg.all_events_confirmed
  }
  return params
}

function toPreflightRequest(cfg: KMConfig): KMPreflightRequest {
  return {
    time_column: cfg.time_column,
    event_column: cfg.has_censoring ? cfg.event_column || null : null,
    group_column: cfg.group_column || null,
    has_censoring: cfg.has_censoring,
    event_mapping: cfg.has_censoring ? cfg.event_mapping : [],
    all_events_confirmed: cfg.has_censoring ? false : cfg.all_events_confirmed,
  }
}

const ROLE_OPTIONS: { value: '' | 'event' | 'censored' | 'exclude'; label: string }[] = [
  { value: '', label: '— choose —' },
  { value: 'event', label: 'Event' },
  { value: 'censored', label: 'Censored' },
  { value: 'exclude', label: 'Exclude' },
]

const labelStyle: React.CSSProperties = {
  fontSize: '10px',
  letterSpacing: '0.06em',
  textTransform: 'uppercase',
  color: 'var(--text-secondary)',
  display: 'block',
  marginBottom: '4px',
}

export default function KMConfigForm({
  workspaceId,
  datasetId,
  columns,
  config,
  setConfig,
  preflight,
  setPreflight,
}: {
  workspaceId: string
  datasetId: string
  columns: string[]
  config: KMConfig
  setConfig: (c: KMConfig) => void
  preflight: KMPreflightResponse | null
  setPreflight: (p: KMPreflightResponse | null) => void
}) {
  const [validating, setValidating] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // `shown` is the display copy of the last preflight — it survives a mapping
  // edit so the mapping controls stay usable. The parent's `preflight` is the
  // submission gate and is cleared the moment anything changes, so stale
  // counts can never authorize a run.
  const [shown, setShown] = useState<KMPreflightResponse | null>(null)
  const stale = !!shown && !preflight

  // Changing a column or the censoring branch invalidates the status values
  // themselves — drop the whole panel.
  const columnStamp = JSON.stringify([
    config.time_column,
    config.event_column,
    config.group_column,
    config.has_censoring,
  ])
  useEffect(() => {
    setPreflight(null)
    setShown(null)
    setError(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [columnStamp])

  // Changing only the mapping or the all-events confirmation keeps the same
  // status values: keep the panel visible, but re-gate submission.
  const answerStamp = JSON.stringify([config.event_mapping, config.all_events_confirmed])
  useEffect(() => {
    setPreflight(null)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [answerStamp])

  const canValidate =
    !!config.time_column && (!config.has_censoring || !!config.event_column)

  async function handleValidate() {
    setValidating(true)
    setError(null)
    try {
      const res = await fetchKMPreflight(workspaceId, datasetId, toPreflightRequest(config))
      setShown(res)
      setPreflight(res)
    } catch (err) {
      setPreflight(null)
      setError(err instanceof ApiError ? err.message : 'Validation failed.')
    } finally {
      setValidating(false)
    }
  }

  function update(patch: Partial<KMConfig>) {
    setConfig({ ...config, ...patch })
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
      {/* Column selection — dropdowns, not free text */}
      <div>
        <label style={labelStyle} htmlFor="km-time">Time / duration column</label>
        <select
          id="km-time"
          className="field-select"
          value={config.time_column}
          onChange={(e) => update({ time_column: e.target.value })}
        >
          <option value="">— select a column —</option>
          {columns.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>

      {/* Censoring question — never assumed */}
      <div>
        <span style={labelStyle}>Does this dataset contain censored observations?</span>
        <div style={{ display: 'flex', gap: '16px', fontSize: '12px' }}>
          <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
            <input
              type="radio"
              name="km-censoring"
              checked={config.has_censoring}
              onChange={() => update({ has_censoring: true, all_events_confirmed: false })}
            />
            Yes — some subjects were event-free at last follow-up
          </label>
          <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
            <input
              type="radio"
              name="km-censoring"
              checked={!config.has_censoring}
              onChange={() => update({ has_censoring: false, event_mapping: [] })}
            />
            No
          </label>
        </div>
      </div>

      {config.has_censoring ? (
        <div>
          <label style={labelStyle} htmlFor="km-status">Status column</label>
          <select
            id="km-status"
            className="field-select"
            value={config.event_column}
            onChange={(e) => update({ event_column: e.target.value, event_mapping: [] })}
          >
            <option value="">— select a column —</option>
            {columns.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
          <p style={{ fontSize: '10px', color: 'var(--text-secondary)', marginTop: '4px', opacity: 0.8 }}>
            1 / true map to Event and 0 / false to Censored automatically. Any other
            value must be mapped explicitly below.
          </p>
        </div>
      ) : (
        <label style={{
          display: 'flex', alignItems: 'flex-start', gap: '8px',
          fontSize: '12px', color: 'var(--text-primary)', cursor: 'pointer',
          border: '1px solid var(--border-strong)', borderRadius: 'var(--radius)', padding: '10px 12px',
        }}>
          <input
            type="checkbox"
            checked={config.all_events_confirmed}
            onChange={(e) => update({ all_events_confirmed: e.target.checked })}
            style={{ marginTop: '2px' }}
          />
          I confirm every included row represents an observed event.
        </label>
      )}

      <div>
        <label style={labelStyle} htmlFor="km-group">
          Group column <span style={{ opacity: 0.6 }}>(optional)</span>
        </label>
        <select
          id="km-group"
          className="field-select"
          value={config.group_column}
          onChange={(e) => update({ group_column: e.target.value })}
        >
          <option value="">— none —</option>
          {columns.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>

      {/* Validate step — explicit, so preflight isn't called on every keystroke */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <button
          type="button"
          className="btn btn-outline btn-sm"
          disabled={!canValidate || validating}
          onClick={handleValidate}
        >
          {validating ? <><span className="spinner" /> Validating…</> : 'Validate configuration'}
        </button>
        {!canValidate && (
          <span style={{ fontSize: '10px', color: 'var(--text-secondary)' }}>
            Select the required columns first.
          </span>
        )}
      </div>

      {error && <div className="alert-error">{error}</div>}

      {shown && (
        <PreflightSummary
          preflight={shown}
          config={config}
          stale={stale}
          onRoleChange={(value, valueType, role) =>
            update({ event_mapping: setMappingRole(config.event_mapping, value, valueType, role) })
          }
        />
      )}
    </div>
  )
}

function PreflightSummary({
  preflight,
  config,
  stale,
  onRoleChange,
}: {
  preflight: KMPreflightResponse
  config: KMConfig
  stale: boolean
  onRoleChange: (
    value: boolean | number | string | null,
    valueType: KMValueType,
    role: '' | 'event' | 'censored' | 'exclude',
  ) => void
}) {
  const c = preflight.counts
  const stat = (label: string, value: string) => (
    <div>
      <p style={{ fontSize: '9px', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-secondary)' }}>
        {label}
      </p>
      <p style={{ fontSize: '15px', fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>{value}</p>
    </div>
  )

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
          ? '⟳ Configuration changed — validate again to refresh these counts'
          : preflight.ready ? '✓ Ready to run' : '⚠ Not ready yet'}
      </p>

      <div style={{ display: 'flex', gap: '20px', flexWrap: 'wrap', opacity: stale ? 0.5 : 1 }}>
        {stat('Total rows', String(c.total_rows))}
        {stat('Included', String(c.used_rows))}
        {stat('Events', String(c.events))}
        {stat('Censored', String(c.censored))}
        {stat('Excluded', String(c.excluded_rows))}
        {stat('Unmapped', String(c.unmapped_values))}
        {stat('Censoring', `${c.censoring_percentage.toFixed(1)}%`)}
      </div>

      {c.excluded_rows > 0 && (
        <p style={{ fontSize: '10px', color: 'var(--text-secondary)' }}>
          Excluded rows by reason (a row can have more than one reason):{' '}
          {Object.entries(c.exclusions)
            .filter(([, n]) => n > 0)
            .map(([k, n]) => `${k.replace(/_/g, ' ')}: ${n}`)
            .join(' · ') || 'none'}
        </p>
      )}

      {preflight.blockers.length > 0 && (
        <ul style={{ margin: 0, paddingLeft: '16px', display: 'flex', flexDirection: 'column', gap: '3px' }}>
          {preflight.blockers.map((b) => (
            <li key={b} style={{ fontSize: '11px', color: '#c8a44a' }}>
              {KM_BLOCKER_LABELS[b] ?? b}
            </li>
          ))}
        </ul>
      )}

      {/* Typed status-value mapping */}
      {config.has_censoring && preflight.status_values.length > 0 && (
        <div>
          <p style={{ ...labelStyle, marginBottom: '6px' }}>Status value mapping</p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {preflight.status_values.map((sv) => {
              const key = `${sv.value_type}:${String(sv.value)}`
              const unsupported = sv.value_type === 'unsupported'
              return (
                <div key={key} style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <span style={{
                    fontFamily: 'var(--font-mono)', fontSize: '11px',
                    color: sv.role === 'unmapped' ? '#c8a44a' : 'var(--text-primary)',
                    minWidth: '120px',
                  }}>
                    {formatStatusValue(sv.value, sv.value_type)}
                  </span>
                  <span style={{ fontSize: '10px', color: 'var(--text-secondary)', minWidth: '96px' }}>
                    {sv.value_type} · {sv.count} row{sv.count === 1 ? '' : 's'}
                  </span>
                  <select
                    className="field-select"
                    style={{ maxWidth: '160px' }}
                    disabled={unsupported}
                    value={effectiveRole(sv)}
                    onChange={(e) =>
                      onRoleChange(
                        sv.value,
                        sv.value_type as KMValueType,
                        e.target.value as '' | 'event' | 'censored' | 'exclude',
                      )
                    }
                  >
                    {ROLE_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                  </select>
                  {isAutoRole(sv.role) && (
                    <span style={{ fontSize: '10px', color: 'var(--text-secondary)', opacity: 0.75 }}>
                      auto
                    </span>
                  )}
                  {unsupported && (
                    <span style={{ fontSize: '10px', color: '#c8a44a' }}>unsupported type — excluded</span>
                  )}
                </div>
              )
            })}
          </div>
          <p style={{ fontSize: '10px', color: 'var(--text-secondary)', marginTop: '6px', opacity: 0.8 }}>
            Changing a mapping clears these counts — validate again to refresh them.
          </p>
        </div>
      )}
    </div>
  )
}
