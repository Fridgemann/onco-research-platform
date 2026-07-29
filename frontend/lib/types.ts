export interface User {
  id: string
  email: string
  full_name: string
  role: 'admin' | 'researcher' | 'collaborator'
  is_active: boolean
  is_verified: boolean
  created_at: string
  last_login: string | null
}

export interface Workspace {
  id: string
  name: string
  description: string | null
  owner_id: string
  created_at: string
}

export interface WorkspaceMember {
  id: string
  user_id: string
  email: string
  role: 'owner' | 'collaborator'
  invited_by: string
  joined_at: string
}

export interface WorkspaceInvite {
  id: string
  workspace_id: string
  invited_email: string
  status: 'pending' | 'accepted' | 'revoked'
  invited_by: string
  created_at: string
  expires_at: string
  accepted_at: string | null
}

export interface Dataset {
  id: string
  workspace_id: string
  filename: string
  content_type: string
  file_size: number
  description: string | null
  uploaded_by: string
  created_at: string
}

export interface AnalysisJob {
  id: string
  dataset_id: string
  workspace_id: string
  requested_by: string
  job_type: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  parameters: Record<string, unknown> | null
  result: Record<string, unknown> | null
  error_message: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
}

// ── Kaplan-Meier (Milestone 3) ──────────────────────────────────────────────
// Shapes mirror the backend result exactly. The frontend only displays these
// values; it never recomputes a statistic.

export type KMValueType = 'boolean' | 'number' | 'string'
export type KMMappingRole = 'event' | 'censored' | 'exclude'

/** Typed status value — `value` keeps its original JSON type (1 !== "1"). */
export type KMStatusRawValue = boolean | number | string | null

export interface KMEventMappingEntry {
  value: KMStatusRawValue
  value_type: KMValueType
  role: KMMappingRole
}

/** Role as reported by preflight, including auto-mapped and unmapped states. */
export type KMStatusValueRole =
  | KMMappingRole
  | 'auto_event'
  | 'auto_censored'
  | 'unmapped'

export interface KMStatusValue {
  value: KMStatusRawValue
  value_type: KMValueType | 'unsupported'
  count: number
  role: KMStatusValueRole
}

export interface KMExclusionCounts {
  missing_duration: number
  invalid_duration: number
  missing_status: number
  missing_group: number
  explicitly_excluded: number
}

export interface KMCounts {
  total_rows: number
  used_rows: number
  excluded_rows: number
  events: number
  censored: number
  censoring_percentage: number
  exclusions: KMExclusionCounts
  unmapped_values: number
}

export interface KMPreflightRequest {
  time_column: string
  event_column?: string | null
  group_column?: string | null
  has_censoring: boolean
  event_mapping: KMEventMappingEntry[]
  all_events_confirmed: boolean
}

export interface KMPreflightResponse {
  ready: boolean
  blockers: string[]
  counts: KMCounts
  status_values: KMStatusValue[]
}

export interface KMRiskTable {
  time: number[]
  at_risk: number[]
  events: number[]
  censored: number[]
}

export interface KMCensorMark {
  time: number
  survival_probability: number
  count: number
}

export interface KMCurve {
  timeline: number[]
  survival_probability: number[]
  ci_lower: number[]
  ci_upper: number[]
  /** null means "not reached" — never Infinity. */
  median_survival: number | null
  n: number
  n_events: number
  n_censored: number
  risk_table: KMRiskTable
  censor_marks: KMCensorMark[]
}

export interface KMGroup {
  label: KMStatusRawValue
  value_type: KMValueType | 'overall'
  curve: KMCurve
}

export type KMComparison =
  | null
  | { available: false; reason: string }
  | {
      available: true
      test: string
      chi_square: number
      degrees_of_freedom: number
      p_value: number
    }

export interface KMReproducibility {
  parameters: Record<string, unknown>
  library: string
  library_version: string
  ci_method: string
  ci_level: number
  at_risk_convention: string
}

export interface KMResultData {
  grouped: boolean
  groups: KMGroup[]
  comparison: KMComparison
  counts: KMCounts
  reproducibility: KMReproducibility
  assumptions: string[]
}
