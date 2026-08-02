'use client'

import { useEffect, useState, use, useRef } from 'react'
import Link from 'next/link'
import { apiFetch, ApiError } from '@/lib/api'
import { getToken } from '@/lib/auth'
import { useUser } from '@/lib/user-context'
import type {
  Dataset, AnalysisJob, Workspace, WorkspaceInvite, WorkspaceMember, KMPreflightResponse,
} from '@/lib/types'
import ResultPanel from '@/components/analysis/ResultPanel'
import KMConfigForm, {
  EMPTY_KM_CONFIG, kmConfigToParams, type KMConfig,
} from '@/components/analysis/KMConfigForm'

type JobType = 'kaplan_meier' | 'descriptive_stats' | 'regression' | 'logistic_regression'

// Polling for in-flight analysis jobs. The cap stops a job stuck in
// "running" from polling indefinitely (~10 minutes at this interval).
const JOB_POLL_INTERVAL_MS = 2500
const JOB_POLL_MAX_TICKS = 240

const JOB_TYPE_LABELS: Record<JobType, string> = {
  kaplan_meier: 'Kaplan–Meier Survival',
  descriptive_stats: 'Descriptive Statistics',
  regression: 'Linear Regression',
  logistic_regression: 'Logistic Regression',
}

const JOB_TYPE_DESCRIPTIONS: Record<JobType, string> = {
  kaplan_meier: 'Estimate survival function over time with optional group stratification',
  descriptive_stats: 'Summary statistics: mean, median, std, quartiles per column',
  regression: 'Ordinary least squares regression with feature coefficients and R²',
  logistic_regression: 'Binary outcome classification with odds ratios and confusion matrix',
}

const FIELD_CONFIG: Record<JobType, { key: string; label: string; placeholder: string; optional?: boolean }[]> = {
  kaplan_meier: [
    { key: 'time_column', label: 'Time Column', placeholder: 'e.g. survival_months' },
    { key: 'event_column', label: 'Event Column', placeholder: 'e.g. event_occurred' },
    { key: 'group_column', label: 'Group Column', placeholder: 'e.g. treatment_arm', optional: true },
    { key: 'max_groups', label: 'Max Groups', placeholder: 'e.g. 60 — leave blank for default (server max: 100)', optional: true },
  ],
  descriptive_stats: [{ key: 'columns', label: 'Columns', placeholder: 'e.g. age, stage', optional: true }],
  regression: [
    { key: 'target_column', label: 'Target Column', placeholder: 'e.g. survival_months' },
    { key: 'feature_columns', label: 'Feature Columns', placeholder: 'e.g. tumor_size' },
  ],
  logistic_regression: [
    { key: 'target_column', label: 'Target Column', placeholder: 'e.g. survival_status' },
    { key: 'feature_columns', label: 'Feature Columns', placeholder: 'e.g. age, tumor_size' },
  ],
}

function AnalysisParamFields({
  jobType,
  params,
  setParams,
}: {
  jobType: JobType
  params: Record<string, string>
  setParams: (p: Record<string, string>) => void
}) {
  return (
    <div className='flex flex-col gap-4'>
      {FIELD_CONFIG[jobType].map((f) => {
        if (f.key === 'max_groups' && !params['group_column']) return null
        return (
          <div key={f.key}>
            <label className='field-label'>
              {f.label}
              {f.optional && <span style={{ opacity: 0.5 }}> (optional)</span>}
            </label>
            <input
              className='field-input'
              value={params[f.key] ?? ''}
              onChange={(e) => setParams({ ...params, [f.key]: e.target.value })}
              placeholder={f.placeholder}
            />
          </div>
        )
      })}
    </div>
  )
}

function StatusBadge({ status }: { status: AnalysisJob['status'] }) {
  return (
    <span className={`badge badge-${status}`}>
      <span className="badge-dot" />
      {status}
    </span>
  )
}

export default function WorkspacePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params)
  const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [jobs, setJobs] = useState<AnalysisJob[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Dataset selection (top bar)
  const [selectedDatasetId, setSelectedDatasetId] = useState('')
  const [datasetColumns, setDatasetColumns] = useState<string[]>([])
  const [columnsLoading, setColumnsLoading] = useState(false)
  const [deletingDataset, setDeletingDataset] = useState<string | null>(null)
  const [confirmDeleteDs, setConfirmDeleteDs] = useState<string | null>(null)

  // Upload modal
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [showUpload, setShowUpload] = useState(false)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadDesc, setUploadDesc] = useState('')
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)

  // Test selection (left panel)
  const [selectedTest, setSelectedTest] = useState<JobType | null>(null)
  const [jobParams, setJobParams] = useState<Record<string, string>>({})
  // Kaplan-Meier uses a dedicated censoring-aware flow with a preflight gate.
  const [kmConfig, setKmConfig] = useState<KMConfig>(EMPTY_KM_CONFIG)
  const [kmPreflight, setKmPreflight] = useState<KMPreflightResponse | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)

  // Right panel: which past run to show results for
  const [rightJobId, setRightJobId] = useState<string | null>(null)

  // Members modal
  const [showMembers, setShowMembers] = useState(false)
  const [members, setMembers] = useState<WorkspaceMember[]>([])
  const [invites, setInvites] = useState<WorkspaceInvite[]>([])
  const [invitesLoading, setInvitesLoading] = useState(false)
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviting, setInviting] = useState(false)
  const [inviteError, setInviteError] = useState<string | null>(null)
  const [newToken, setNewToken] = useState<string | null>(null)
  const [revoking, setRevoking] = useState<string | null>(null)
  const [removing, setRemoving] = useState<string | null>(null)
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null)
  const [leaving, setLeaving] = useState(false)
  const [confirmLeave, setConfirmLeave] = useState(false)

  const currentUser = useUser()

  useEffect(() => {
    async function load() {
      try {
        const [ws, ds, js] = await Promise.all([
          apiFetch<Workspace>(`/api/workspaces/${id}`),
          apiFetch<Dataset[]>(`/api/workspaces/${id}/datasets`),
          apiFetch<AnalysisJob[]>(`/api/analysis?workspace_id=${id}`),
        ])
        setWorkspace(ws)
        setDatasets(ds)
        setJobs(js)
        if (ds.length > 0) setSelectedDatasetId(ds[0].id)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Failed to load workspace')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [id])

  useEffect(() => {
    setJobParams({})
    setKmConfig(EMPTY_KM_CONFIG)
    setKmPreflight(null)
    setRightJobId(null)
  }, [selectedTest])

  useEffect(() => {
    // A different dataset invalidates any column selection and preflight.
    setKmConfig(EMPTY_KM_CONFIG)
    setKmPreflight(null)
    setRightJobId(null)
  }, [selectedDatasetId])

  useEffect(() => {
    if (!selectedDatasetId) return
    setColumnsLoading(true)
    apiFetch<{ columns: string[] }>(`/api/workspaces/${id}/datasets/${selectedDatasetId}/columns`)
      .then((data) => setDatasetColumns(data.columns))
      .catch(() => setDatasetColumns([]))
      .finally(() => setColumnsLoading(false))
  }, [selectedDatasetId, id])

  // Analyses run asynchronously on Celery, so a submitted job stays "pending"
  // until something refetches it. Poll only the jobs that are still running,
  // and stop as soon as they all reach a terminal state.
  const activeJobIds = jobs
    .filter((j) => j.status === 'pending' || j.status === 'running')
    .map((j) => j.id)
    .sort()
    .join(',')

  useEffect(() => {
    if (!activeJobIds) return
    const ids = activeJobIds.split(',')
    let cancelled = false
    let ticks = 0

    const timer = setInterval(async () => {
      // Safety cap: a job stuck in "running" (dead worker, lost broker
      // message) must not poll forever on a page left open.
      if (++ticks > JOB_POLL_MAX_TICKS) {
        clearInterval(timer)
        return
      }

      const settled = await Promise.all(
        ids.map((jobId) =>
          apiFetch<AnalysisJob>(`/api/analysis/${jobId}`).catch(() => null),
        ),
      )
      if (cancelled) return

      const fresh = settled.filter((j): j is AnalysisJob => j !== null)
      if (fresh.length === 0) return // transient failure — retry next tick

      setJobs((prev) => {
        let changed = false
        const next = prev.map((j) => {
          const updated = fresh.find((f) => f.id === j.id)
          if (updated && updated.status !== j.status) {
            changed = true
            return updated
          }
          return j
        })
        // Returning `prev` unchanged avoids a re-render, which would otherwise
        // restart this interval on every tick.
        return changed ? next : prev
      })
    }, JOB_POLL_INTERVAL_MS)

    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [activeJobIds])

  async function handleUpload(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault()
    if (!uploadFile) return
    setUploading(true)
    setUploadError(null)
    try {
      const formData = new FormData()
      formData.append('file', uploadFile)
      if (uploadDesc) formData.append('description', uploadDesc)
      const token = getToken()
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'}/api/workspaces/${id}/datasets`,
        {
          method: 'POST',
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          body: formData,
          credentials: 'include',
        },
      )
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail ?? `HTTP ${res.status}`)
      }
      const ds = await res.json() as Dataset
      setDatasets((prev) => [ds, ...prev])
      setSelectedDatasetId(ds.id)
      setShowUpload(false)
      setUploadFile(null)
      setUploadDesc('')
    } catch (err) {
      setUploadError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  async function handleRunAnalysis(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault()
    if (!selectedTest || !selectedDatasetId) return
    setSubmitting(true)
    setSubmitError(null)
    try {
      let parameters: Record<string, unknown> = {}
      if (selectedTest === 'kaplan_meier') {
        // Typed KM parameters (mapping values keep their original JSON types).
        parameters = kmConfigToParams(kmConfig)
      } else {
        for (const [k, v] of Object.entries(jobParams)) {
          if (k.endsWith('_columns') || k === 'columns') {
            parameters[k] = v.split(',').map((s) => s.trim()).filter(Boolean)
          } else {
            parameters[k] = v
          }
        }
      }
      const job = await apiFetch<AnalysisJob>(
        `/api/workspaces/${id}/datasets/${selectedDatasetId}/analysis`,
        { method: 'POST', body: JSON.stringify({ job_type: selectedTest, parameters }) },
      )
      setJobs((prev) => [job, ...prev])
      setRightJobId(job.id)
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : 'Failed to submit job')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleDeleteDataset(datasetId: string) {
    setDeletingDataset(datasetId)
    try {
      await apiFetch(`/api/workspaces/${id}/datasets/${datasetId}`, { method: 'DELETE' })
      setDatasets((prev) => {
        const next = prev.filter((d) => d.id !== datasetId)
        if (selectedDatasetId === datasetId) setSelectedDatasetId(next[0]?.id ?? '')
        return next
      })
      setConfirmDeleteDs(null)
    } catch {
      // ignore
    } finally {
      setDeletingDataset(null)
    }
  }

  async function loadInvites() {
    setInvitesLoading(true)
    try {
      const memberData = await apiFetch<WorkspaceMember[]>(`/api/workspaces/${id}/members`)
      setMembers(memberData)
      try {
        const inviteData = await apiFetch<WorkspaceInvite[]>(`/api/workspaces/${id}/invites`)
        setInvites(inviteData)
      } catch {
        // non-owners get 403
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load members')
    } finally {
      setInvitesLoading(false)
    }
  }

  async function handleInvite(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault()
    setInviting(true)
    setInviteError(null)
    setNewToken(null)
    try {
      const data = await apiFetch<{ invite_id: string; token: string; expires_at: string; message: string }>(
        `/api/workspaces/${id}/invites`,
        { method: 'POST', body: JSON.stringify({ email: inviteEmail }) },
      )
      setNewToken(data.token)
      setInviteEmail('')
      loadInvites()
    } catch (err) {
      setInviteError(err instanceof ApiError ? err.message : 'Failed to create invite')
    } finally {
      setInviting(false)
    }
  }

  async function handleLeave() {
    setLeaving(true)
    try {
      await apiFetch(`/api/workspaces/${id}/members/me`, { method: 'DELETE' })
      window.location.href = '/dashboard'
    } catch {
      setLeaving(false)
    }
  }

  async function handleRemoveMember(memberId: string, userId: string) {
    setRemoving(memberId)
    try {
      await apiFetch(`/api/workspaces/${id}/members/${userId}`, { method: 'DELETE' })
      setMembers((prev) => prev.filter((m) => m.id !== memberId))
    } catch {
      // ignore
    } finally {
      setRemoving(null)
    }
  }

  async function handleRevoke(inviteId: string) {
    setRevoking(inviteId)
    try {
      await apiFetch(`/api/workspaces/${id}/invites/${inviteId}`, { method: 'DELETE' })
      setInvites((prev) => prev.map((inv) => inv.id === inviteId ? { ...inv, status: 'revoked' as const } : inv))
    } catch {
      // ignore
    } finally {
      setRevoking(null)
    }
  }

  const selectedDataset = datasets.find((d) => d.id === selectedDatasetId) ?? null
  const testJobs = selectedTest && selectedDatasetId
    ? jobs.filter((j) => j.job_type === selectedTest && j.dataset_id === selectedDatasetId)
    : []
  const rightJob = rightJobId ? jobs.find((j) => j.id === rightJobId) ?? null : null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', background: 'var(--bg-base)' }}>

      {/* App header */}
      <header className="app-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <Link
            href="/dashboard"
            style={{
              fontSize: '11px',
              letterSpacing: '0.06em',
              textTransform: 'uppercase',
              color: 'var(--text-secondary)',
              textDecoration: 'none',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
              transition: 'color 0.15s',
            }}
            onMouseEnter={(e) => (e.currentTarget.style.color = 'var(--text-primary)')}
            onMouseLeave={(e) => (e.currentTarget.style.color = 'var(--text-secondary)')}
          >
            ← Workspaces
          </Link>
          {workspace && (
            <>
              <span style={{ color: 'var(--border-strong)' }}>|</span>
              <span style={{ fontSize: '13px', color: 'var(--text-primary)' }}>{workspace.name}</span>
            </>
          )}
        </div>
        <button
          className="btn btn-outline btn-sm"
          onClick={() => { setShowMembers(true); if (members.length === 0) loadInvites() }}
        >
          Members
        </button>
      </header>

      {/* Dataset bar */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        padding: '10px 24px',
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg-surface)',
        flexShrink: 0,
      }}>
        <span style={{
          fontSize: '10px',
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          color: 'var(--text-secondary)',
          flexShrink: 0,
        }}>
          Dataset
        </span>

        {loading ? (
          <div className="skeleton" style={{ width: '220px', height: '28px' }} />
        ) : datasets.length === 0 ? (
          <span style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
            No datasets — upload one to begin
          </span>
        ) : (
          <select
            value={selectedDatasetId}
            onChange={(e) => setSelectedDatasetId(e.target.value)}
            className="field-select"
            style={{ minWidth: '200px', maxWidth: '420px' }}
          >
            {datasets.map((ds) => (
              <option key={ds.id} value={ds.id}>{ds.filename}</option>
            ))}
          </select>
        )}

        <button className="btn btn-outline btn-sm" onClick={() => setShowUpload(true)}>
          + Upload
        </button>

        {workspace && currentUser?.id === workspace.owner_id && selectedDataset && (
          confirmDeleteDs === selectedDatasetId ? (
            <span style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
              <span style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
                Delete {selectedDataset.filename}?
              </span>
              <button
                className="btn btn-outline btn-sm"
                disabled={deletingDataset === selectedDatasetId}
                onClick={() => handleDeleteDataset(selectedDatasetId)}
                style={{ color: 'var(--status-failed-fg)' }}
              >
                {deletingDataset === selectedDatasetId ? 'Deleting…' : 'Yes'}
              </button>
              <button className="btn btn-outline btn-sm" onClick={() => setConfirmDeleteDs(null)}>No</button>
            </span>
          ) : (
            <button
              className="btn btn-ghost btn-sm"
              onClick={() => setConfirmDeleteDs(selectedDatasetId)}
              style={{ color: 'var(--status-failed-fg)', marginLeft: 'auto' }}
            >
              Delete dataset
            </button>
          )
        )}
      </div>

      {error && (
        <div className="alert-error" style={{ margin: '10px 24px', flexShrink: 0 }}>{error}</div>
      )}

      {/* Split pane */}
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>

        {/* Left: test list */}
        <aside style={{
          width: '220px',
          flexShrink: 0,
          borderRight: '1px solid var(--border)',
          background: 'var(--bg-surface)',
          overflowY: 'auto',
          paddingTop: '16px',
        }}>
          <p style={{
            fontSize: '10px',
            letterSpacing: '0.08em',
            textTransform: 'uppercase',
            color: 'var(--text-secondary)',
            padding: '0 16px 10px',
          }}>
            Analysis types
          </p>

          {(Object.entries(JOB_TYPE_LABELS) as [JobType, string][]).map(([k, v]) => {
            const active = selectedTest === k
            const latestStatus = jobs.find(
              (j) => j.job_type === k && j.dataset_id === selectedDatasetId,
            )?.status
            return (
              <button
                key={k}
                onClick={() => setSelectedTest(k)}
                style={{
                  display: 'block',
                  width: '100%',
                  textAlign: 'left',
                  padding: '10px 16px',
                  background: active ? 'var(--bg-raised)' : 'transparent',
                  color: active ? 'var(--text-primary)' : 'var(--text-secondary)',
                  border: 'none',
                  borderLeft: active ? '2px solid var(--accent)' : '2px solid transparent',
                  cursor: 'pointer',
                  fontSize: '12px',
                  transition: 'color 0.12s, background 0.12s',
                }}
                onMouseEnter={(e) => {
                  if (!active) {
                    e.currentTarget.style.color = 'var(--text-primary)'
                    e.currentTarget.style.background = 'var(--bg-raised)'
                  }
                }}
                onMouseLeave={(e) => {
                  if (!active) {
                    e.currentTarget.style.color = 'var(--text-secondary)'
                    e.currentTarget.style.background = 'transparent'
                  }
                }}
              >
                <span style={{ display: 'block' }}>{v}</span>
                {latestStatus && (
                  <span style={{ fontSize: '10px', opacity: 0.55, marginTop: '2px', display: 'block' }}>
                    {latestStatus}
                  </span>
                )}
              </button>
            )
          })}
        </aside>

        {/* Right: config + results */}
        <main style={{ flex: 1, overflowY: 'auto', padding: '28px 32px' }}>
          {!selectedTest ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', flexDirection: 'column', gap: '10px' }}>
              <p className="display" style={{ fontSize: '20px', color: 'var(--text-secondary)' }}>
                Select an analysis type
              </p>
              <p style={{ fontSize: '12px', color: 'var(--text-secondary)', opacity: 0.6 }}>
                Choose from the left panel to configure and run an analysis
              </p>
            </div>
          ) : !selectedDatasetId ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', flexDirection: 'column', gap: '12px' }}>
              <p className="display" style={{ fontSize: '20px', color: 'var(--text-secondary)' }}>
                No dataset selected
              </p>
              <button className="btn btn-outline" onClick={() => setShowUpload(true)}>Upload dataset</button>
            </div>
          ) : (
            <>
              {/* Test header */}
              <div style={{ marginBottom: '22px' }}>
                <h2 className="display" style={{ fontSize: '18px', marginBottom: '4px' }}>
                  {JOB_TYPE_LABELS[selectedTest]}
                </h2>
                <p style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
                  {JOB_TYPE_DESCRIPTIONS[selectedTest]}
                </p>
              </div>

              {/* Column chips */}
              {columnsLoading ? (
                <div className="skeleton" style={{ height: '28px', marginBottom: '20px' }} />
              ) : datasetColumns.length > 0 && (
                <div style={{ marginBottom: '20px' }}>
                  <p style={{
                    fontSize: '10px',
                    textTransform: 'uppercase',
                    letterSpacing: '0.06em',
                    color: 'var(--text-secondary)',
                    marginBottom: '6px',
                  }}>
                    Columns in {selectedDataset?.filename}
                  </p>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
                    {datasetColumns.map((col) => (
                      <span
                        key={col}
                        style={{
                          fontSize: '11px',
                          fontFamily: 'var(--font-mono)',
                          background: 'var(--bg-raised)',
                          border: '1px solid var(--border)',
                          borderRadius: '3px',
                          padding: '2px 7px',
                          color: 'var(--text-secondary)',
                        }}
                      >
                        {col}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Config form */}
              <form
                onSubmit={handleRunAnalysis}
                style={{ display: 'flex', flexDirection: 'column', gap: '14px', marginBottom: '28px' }}
              >
                {selectedTest === 'kaplan_meier' ? (
                  <KMConfigForm
                    workspaceId={id}
                    datasetId={selectedDatasetId}
                    columns={datasetColumns}
                    config={kmConfig}
                    setConfig={setKmConfig}
                    preflight={kmPreflight}
                    setPreflight={setKmPreflight}
                  />
                ) : (
                  <AnalysisParamFields jobType={selectedTest} params={jobParams} setParams={setJobParams} />
                )}
                {submitError && <div className="alert-error">{submitError}</div>}
                <div>
                  <button
                    type="submit"
                    disabled={submitting || (selectedTest === 'kaplan_meier' && !kmPreflight?.ready)}
                    className="btn btn-primary"
                    title={
                      selectedTest === 'kaplan_meier' && !kmPreflight?.ready
                        ? 'Validate the configuration first'
                        : undefined
                    }
                  >
                    {submitting ? <><span className="spinner" /> Running…</> : 'Run analysis'}
                  </button>
                </div>
              </form>

              {/* Past runs + results */}
              {testJobs.length > 0 && (
                <>
                  <hr style={{ border: 'none', borderTop: '1px solid var(--border)', marginBottom: '20px' }} />

                  {/* Expanded result */}
                  {rightJob && (
                    <div style={{ marginBottom: '24px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '14px' }}>
                        <p style={{
                          fontSize: '11px',
                          textTransform: 'uppercase',
                          letterSpacing: '0.06em',
                          color: 'var(--text-secondary)',
                        }}>
                          Result
                        </p>
                        <StatusBadge status={rightJob.status} />
                        <span className="mono-sm" style={{ marginLeft: 'auto' }}>
                          {new Date(rightJob.created_at).toLocaleString('en-GB', {
                            day: 'numeric', month: 'short',
                            hour: '2-digit', minute: '2-digit',
                          })}
                        </span>
                        {rightJob.status === 'completed' && rightJob.result && (
                          <button
                            className="btn btn-outline btn-sm"
                            onClick={() => {
                              const blob = new Blob([JSON.stringify(rightJob.result, null, 2)], { type: 'application/json' })
                              const url = URL.createObjectURL(blob)
                              const a = document.createElement('a')
                              a.href = url; a.download = `${rightJob.id}.json`; a.click()
                              URL.revokeObjectURL(url)
                            }}
                          >
                            ↓ JSON
                          </button>
                        )}
                      </div>

                      {rightJob.status === 'completed' && rightJob.result && (
                        <ResultPanel job={rightJob} />
                      )}
                      {rightJob.status === 'failed' && rightJob.error_message && (
                        <div className="alert-error">{rightJob.error_message}</div>
                      )}
                      {(rightJob.status === 'pending' || rightJob.status === 'running') && (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-secondary)', fontSize: '12px' }}>
                          <span className="spinner" /> Processing…
                        </div>
                      )}
                    </div>
                  )}

                  {/* Past runs list */}
                  <p style={{
                    fontSize: '10px',
                    textTransform: 'uppercase',
                    letterSpacing: '0.06em',
                    color: 'var(--text-secondary)',
                    marginBottom: '8px',
                  }}>
                    Past runs
                  </p>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    {testJobs.map((job) => (
                      <div
                        key={job.id}
                        onClick={() => setRightJobId(rightJobId === job.id ? null : job.id)}
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          gap: '10px',
                          padding: '8px 12px',
                          background: rightJobId === job.id ? 'var(--bg-raised)' : 'var(--bg-surface)',
                          border: `1px solid ${rightJobId === job.id ? 'var(--border-strong)' : 'var(--border)'}`,
                          borderRadius: 'var(--radius)',
                          cursor: 'pointer',
                          transition: 'background 0.12s',
                        }}
                      >
                        <StatusBadge status={job.status} />
                        <span className="mono-sm" style={{ flex: 1 }}>
                          {new Date(job.created_at).toLocaleString('en-GB', {
                            day: 'numeric', month: 'short', year: 'numeric',
                            hour: '2-digit', minute: '2-digit',
                          })}
                        </span>
                        {job.status === 'completed' && job.result && (
                          <span style={{ fontSize: '10px', color: 'var(--text-secondary)' }}>
                            {rightJobId === job.id ? 'showing ↑' : 'view'}
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                </>
              )}
            </>
          )}
        </main>
      </div>

      {/* Upload modal */}
      {showUpload && (
        <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && setShowUpload(false)}>
          <div className="modal">
            <p className="modal-title">Upload dataset</p>
            <p style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
              CSV or Excel files. All data is encrypted at rest.
            </p>
            <hr className="modal-divider" />
            <form onSubmit={handleUpload} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div>
                <label className="field-label">File</label>
                <input
                  ref={fileInputRef}
                  type="file"
                  required
                  accept=".csv,.xlsx,.xls"
                  onChange={(e) => setUploadFile(e.target.files?.[0] ?? null)}
                  style={{ display: 'none' }}
                />
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '10px',
                  background: 'var(--bg-raised)',
                  border: '1px solid var(--border-strong)',
                  borderRadius: 'var(--radius)',
                  padding: '8px 10px 8px 4px',
                }}>
                  <button
                    type="button"
                    className="btn btn-outline btn-sm"
                    style={{ flexShrink: 0 }}
                    onClick={() => fileInputRef.current?.click()}
                  >
                    Browse
                  </button>
                  <span style={{
                    fontSize: '12px',
                    color: uploadFile ? 'var(--text-primary)' : 'var(--text-secondary)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                    opacity: uploadFile ? 1 : 0.5,
                  }}>
                    {uploadFile ? uploadFile.name : 'No file chosen — .csv, .xlsx, .xls'}
                  </span>
                </div>
              </div>
              <div>
                <label className="field-label" htmlFor="upload-desc">
                  Description <span style={{ opacity: 0.5 }}>(optional)</span>
                </label>
                <input
                  id="upload-desc"
                  type="text"
                  value={uploadDesc}
                  onChange={(e) => setUploadDesc(e.target.value)}
                  className="field-input"
                  placeholder="e.g. Treatment arm A — 156 patients"
                />
              </div>
              {uploadError && <div className="alert-error">{uploadError}</div>}
              <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
                <button type="button" className="btn btn-outline" onClick={() => setShowUpload(false)}>Cancel</button>
                <button type="submit" disabled={uploading || !uploadFile} className="btn btn-primary">
                  {uploading ? <><span className="spinner" /> Uploading…</> : 'Upload'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Members modal */}
      {showMembers && (
        <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && setShowMembers(false)}>
          <div className="modal" style={{ maxWidth: '540px', maxHeight: '80vh', display: 'flex', flexDirection: 'column' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '4px' }}>
              <p className="modal-title" style={{ marginBottom: 0 }}>Members</p>
              <button className="btn btn-ghost btn-sm" onClick={() => setShowMembers(false)}>✕</button>
            </div>
            <hr className="modal-divider" />
            <div style={{ overflowY: 'auto', flex: 1 }}>
              {invitesLoading ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', padding: '8px 0' }}>
                  {[1, 2].map((i) => <div key={i} className="skeleton" style={{ height: '40px' }} />)}
                </div>
              ) : (
                <>
                  {members.map((m) => (
                    <div key={m.id} className="dataset-row">
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <span className="mono-sm" style={{ color: 'var(--text-primary)' }}>{m.email}</span>
                      </div>
                      <span style={{
                        fontSize: '11px',
                        letterSpacing: '0.05em',
                        textTransform: 'uppercase',
                        color: m.role === 'owner' ? 'var(--accent)' : 'var(--text-secondary)',
                        marginRight: '12px',
                      }}>
                        {m.role}
                      </span>
                      {workspace && currentUser?.id === workspace.owner_id && m.user_id !== currentUser.id && (
                        confirmRemove === m.id ? (
                          <span style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                            <span style={{ fontSize: '11px', color: 'var(--text-secondary)', marginRight: '4px' }}>Sure?</span>
                            <button className="btn btn-outline btn-sm" disabled={removing === m.id}
                              onClick={() => { setConfirmRemove(null); handleRemoveMember(m.id, m.user_id) }}>
                              {removing === m.id ? 'Removing…' : 'Yes'}
                            </button>
                            <button className="btn btn-outline btn-sm" onClick={() => setConfirmRemove(null)}>No</button>
                          </span>
                        ) : (
                          <button className="btn btn-outline btn-sm" disabled={removing === m.id}
                            onClick={() => setConfirmRemove(m.id)}>
                            Remove
                          </button>
                        )
                      )}
                      {workspace && currentUser?.id !== workspace.owner_id && m.user_id === currentUser?.id && (
                        confirmLeave ? (
                          <span style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                            <span style={{ fontSize: '11px', color: 'var(--text-secondary)', marginRight: '4px' }}>Sure?</span>
                            <button className="btn btn-outline btn-sm" disabled={leaving}
                              onClick={() => { setConfirmLeave(false); handleLeave() }}>
                              {leaving ? 'Leaving…' : 'Yes'}
                            </button>
                            <button className="btn btn-outline btn-sm" onClick={() => setConfirmLeave(false)}>No</button>
                          </span>
                        ) : (
                          <button className="btn btn-outline btn-sm" onClick={() => setConfirmLeave(true)}>Leave</button>
                        )
                      )}
                    </div>
                  ))}

                  {workspace && currentUser?.id === workspace.owner_id && (
                    <>
                      <div style={{ padding: '16px 24px', borderTop: '1px solid var(--border)' }}>
                        <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '12px', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                          Invite collaborator
                        </p>
                        <form onSubmit={handleInvite} style={{ display: 'flex', gap: '10px', alignItems: 'flex-end' }}>
                          <input
                            id="invite-email"
                            type="email"
                            required
                            value={inviteEmail}
                            onChange={(e) => setInviteEmail(e.target.value)}
                            className="field-input"
                            placeholder="collaborator@institution.org"
                            style={{ flex: 1 }}
                          />
                          <button type="submit" disabled={inviting} className="btn btn-primary btn-sm" style={{ flexShrink: 0 }}>
                            {inviting ? <><span className="spinner" /> Sending…</> : 'Send invite'}
                          </button>
                        </form>
                        {inviteError && <div className="alert-error" style={{ marginTop: '10px' }}>{inviteError}</div>}
                        {newToken && (
                          <div style={{ marginTop: '12px', padding: '10px 12px', background: 'var(--bg-raised)', border: '1px solid var(--border-strong)', borderRadius: 'var(--radius)', display: 'flex', gap: '8px', alignItems: 'center' }}>
                            <code style={{ fontSize: '11px', color: 'var(--accent)', flex: 1, wordBreak: 'break-all', fontFamily: 'var(--font-mono)' }}>
                              {`${process.env.NEXT_PUBLIC_FRONTEND_URL ?? 'http://localhost:3000'}/invites/accept?token=${newToken}`}
                            </code>
                            <button
                              type="button"
                              className="btn btn-outline btn-sm"
                              style={{ flexShrink: 0 }}
                              onClick={() => navigator.clipboard.writeText(`${process.env.NEXT_PUBLIC_FRONTEND_URL ?? 'http://localhost:3000'}/invites/accept?token=${newToken}`)}
                            >
                              Copy
                            </button>
                          </div>
                        )}
                      </div>

                      {invites.filter(inv => inv.status === 'pending').length > 0 && (
                        <div style={{ borderTop: '1px solid var(--border)' }}>
                          <p style={{ fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--text-secondary)', padding: '12px 24px 8px' }}>
                            Pending invites
                          </p>
                          {invites.filter(inv => inv.status === 'pending').map((inv) => (
                            <div key={inv.id} className="dataset-row">
                              <div style={{ flex: 1, minWidth: 0 }}>
                                <p style={{ fontSize: '13px', color: 'var(--text-primary)', marginBottom: '2px' }}>{inv.invited_email}</p>
                                <span className="mono-sm">expires {new Date(inv.expires_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}</span>
                              </div>
                              <button className="btn btn-outline btn-sm" disabled={revoking === inv.id} onClick={() => handleRevoke(inv.id)}>
                                {revoking === inv.id ? 'Revoking…' : 'Revoke'}
                              </button>
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
