import { apiFetch } from './api'
import type {
  KMEventMappingEntry,
  KMPreflightRequest,
  KMPreflightResponse,
  KMStatusRawValue,
  KMStatusValue,
  KMValueType,
} from './types'

/**
 * Kaplan-Meier preflight: validate a censoring configuration against the
 * dataset and get row/event/censoring counts plus per-status-value roles.
 *
 * The backend is the final authority — `ready` here is advisory UX only; the
 * analysis run re-validates the same configuration server-side.
 */
export async function fetchKMPreflight(
  workspaceId: string,
  datasetId: string,
  body: KMPreflightRequest,
): Promise<KMPreflightResponse> {
  return apiFetch<KMPreflightResponse>(
    `/api/workspaces/${workspaceId}/datasets/${datasetId}/analysis/km-preflight`,
    { method: 'POST', body: JSON.stringify(body) },
  )
}

/** Human-readable label for a raw status value, preserving type distinctions. */
export function formatStatusValue(value: KMStatusRawValue, valueType: string): string {
  if (value === null || value === undefined) return '(unsupported)'
  if (valueType === 'string') return `"${value}"`
  return String(value)
}

/** Roles the backend resolved automatically (not user-chosen). */
export function isAutoRole(role: string): boolean {
  return role === 'auto_event' || role === 'auto_censored'
}

/** The effective mapping role implied by a preflight status value. */
export function effectiveRole(sv: KMStatusValue): '' | 'event' | 'censored' | 'exclude' {
  if (sv.role === 'auto_event') return 'event'
  if (sv.role === 'auto_censored') return 'censored'
  if (sv.role === 'unmapped') return ''
  return sv.role
}

/**
 * Merge a user's role choice into the mapping list, preserving the original
 * typed value (numeric 1 must never become string "1").
 */
export function setMappingRole(
  mapping: KMEventMappingEntry[],
  value: KMStatusRawValue,
  valueType: KMValueType,
  role: '' | 'event' | 'censored' | 'exclude',
): KMEventMappingEntry[] {
  const rest = mapping.filter(
    (m) => !(m.value_type === valueType && Object.is(m.value, value)),
  )
  if (!role) return rest // cleared -> fall back to auto/unmapped
  return [...rest, { value, value_type: valueType, role }]
}

/** Blocker code -> researcher-facing explanation. */
export const KM_BLOCKER_LABELS: Record<string, string> = {
  no_status_column: 'Select the column that records event or censoring status.',
  unmapped_values:
    'Some status values are not mapped yet. Map each one to Event, Censored, or Exclude.',
  needs_all_events_confirmation:
    'Confirm that every included row represents an observed event.',
  no_usable_rows: 'No rows remain usable with the current selection.',
}
