'use client'

import { useState } from 'react'

// Column-role controls shared by the descriptive, linear, and logistic forms.
//
// "Role" here means the role a column plays in one analysis (outcome,
// predictor, summarised column) — never a platform permission. Roles are
// chosen from the dataset's real column list rather than typed by hand: a
// typo used to reach the backend as a validation error after submission.

export const labelStyle: React.CSSProperties = {
  fontSize: '10px',
  letterSpacing: '0.06em',
  textTransform: 'uppercase',
  color: 'var(--text-secondary)',
  display: 'block',
  marginBottom: '4px',
}

export function ColumnRoleSelect({
  id,
  label,
  hint,
  columns,
  value,
  onChange,
  placeholder = '— select a column —',
}: {
  id: string
  label: string
  hint?: string
  columns: string[]
  value: string
  onChange: (v: string) => void
  placeholder?: string
}) {
  return (
    <div>
      <label style={labelStyle} htmlFor={id}>{label}</label>
      <select
        id={id}
        className="field-select"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        <option value="">{placeholder}</option>
        {columns.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
      {hint && (
        <p style={{ fontSize: '10px', color: 'var(--text-secondary)', marginTop: '4px', opacity: 0.8 }}>
          {hint}
        </p>
      )}
    </div>
  )
}

/**
 * Multi-column picker. A checkbox list rather than a multi-select box: a
 * dataset can carry hundreds of columns, and a native multi-select hides the
 * current choice behind scrolling and loses it on a stray click. `exclude`
 * drops a column already used in another role, so the same column cannot be
 * both outcome and predictor.
 */
export function ColumnMultiSelect({
  label,
  hint,
  columns,
  selected,
  onChange,
  exclude = [],
}: {
  label: string
  hint?: string
  columns: string[]
  selected: string[]
  onChange: (next: string[]) => void
  exclude?: string[]
}) {
  const [filter, setFilter] = useState('')
  const available = columns.filter((c) => !exclude.includes(c))
  const needle = filter.trim().toLowerCase()
  const shown = needle
    ? available.filter((c) => c.toLowerCase().includes(needle))
    : available

  function toggle(col: string) {
    onChange(selected.includes(col) ? selected.filter((c) => c !== col) : [...selected, col])
  }

  return (
    <div>
      <span style={labelStyle}>{label}</span>

      {available.length > 12 && (
        <input
          className="field-input"
          style={{ marginBottom: '6px' }}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder={`Filter ${available.length} columns…`}
        />
      )}

      <div style={{
        maxHeight: '190px',
        overflowY: 'auto',
        border: '1px solid var(--border-strong)',
        borderRadius: 'var(--radius)',
        background: 'var(--bg-raised)',
        padding: '6px 8px',
        display: 'flex',
        flexDirection: 'column',
        gap: '2px',
      }}>
        {shown.length === 0 ? (
          <span style={{ fontSize: '11px', color: 'var(--text-secondary)', opacity: 0.7 }}>
            {available.length === 0 ? 'No columns available.' : 'No column matches that filter.'}
          </span>
        ) : shown.map((c) => (
          <label
            key={c}
            style={{
              display: 'flex', alignItems: 'center', gap: '7px',
              fontSize: '12px', fontFamily: 'var(--font-mono)', cursor: 'pointer',
              color: selected.includes(c) ? 'var(--text-primary)' : 'var(--text-secondary)',
            }}
          >
            <input type="checkbox" checked={selected.includes(c)} onChange={() => toggle(c)} />
            {c}
          </label>
        ))}
      </div>

      <div style={{
        display: 'flex', justifyContent: 'space-between', gap: '10px',
        fontSize: '10px', color: 'var(--text-secondary)', marginTop: '4px',
      }}>
        <span style={{ opacity: 0.8 }}>{hint}</span>
        <span>{selected.length} selected</span>
      </div>
    </div>
  )
}
