'use client'

import { useCallback, useEffect, useState, use, useRef } from 'react'
import Link from 'next/link'
import { apiFetch, ApiError } from '@/lib/api'
import { getToken } from '@/lib/auth'
import { useUser } from '@/lib/user-context'
import type {
  Dataset, AnalysisJob, Workspace, WorkspaceInvite, WorkspaceMember, KMPreflightResponse,
  DatasetInspect, AnalysisPreflightResponse,
} from '@/lib/types'
import ResultPanel from '@/components/analysis/ResultPanel'
import DatasetInspector from '@/components/analysis/DatasetInspector'
import {
  fetchDatasetInspect, checkUploadFile, UPLOAD_ACCEPT, UPLOAD_MAX_LABEL,
} from '@/lib/datasets'
import KMConfigForm, {
  EMPTY_KM_CONFIG, kmConfigToParams, type KMConfig,
} from '@/components/analysis/KMConfigForm'
import AnalysisConfigForm, {
  EMPTY_ANALYSIS_CONFIG, analysisConfigToParams,
  type AnalysisConfig, type AnalysisJobType,
} from '@/components/analysis/AnalysisConfigForm'

type JobType = 'kaplan_meier' | 'descriptive_stats' | 'regression' | 'logistic_regression'

// Polling for in-flight analysis jobs. Polling gives up after this much
// elapsed wall time so a job stuck in "running" can't poll forever; the
// researcher is told it is still processing and can check again.
const JOB_POLL_INTERVAL_MS = 2500
const JOB_POLL_TIMEOUT_MS = 10 * 60 * 1000

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
  const [inspect, setInspect] = useState<DatasetInspect | null>(null)
  const [inspectError, setInspectError] = useState<string | null>(null)
  const [columnsLoading, setColumnsLoading] = useState(false)
  // Column names still drive the role dropdowns; they now come from the
  // inspect payload rather than a separate unaudited endpoint.
  const inspectAbortRef = useRef<AbortController | null>(null)

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
  // Kaplan-Meier uses a dedicated censoring-aware flow with a preflight gate.
  const [kmConfig, setKmConfig] = useState<KMConfig>(EMPTY_KM_CONFIG)
  const [kmPreflight, setKmPreflight] = useState<KMPreflightResponse | null>(null)
  // The other three analyses share one role-selection flow, also gated on a
  // backend preflight rather than submitted blind from free-text boxes.
  const [analysisConfig, setAnalysisConfig] = useState<AnalysisConfig>(EMPTY_ANALYSIS_CONFIG)
  const [analysisPreflight, setAnalysisPreflight] = useState<AnalysisPreflightResponse | null>(null)
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
    setKmConfig(EMPTY_KM_CONFIG)
    setKmPreflight(null)
    setAnalysisConfig(EMPTY_ANALYSIS_CONFIG)
    setAnalysisPreflight(null)
    setRightJobId(null)
  }, [selectedTest])

  useEffect(() => {
    // A different dataset invalidates any column selection and preflight.
    setKmConfig(EMPTY_KM_CONFIG)
    setKmPreflight(null)
    setAnalysisConfig(EMPTY_ANALYSIS_CONFIG)
    setAnalysisPreflight(null)
    setRightJobId(null)
  }, [selectedDatasetId])

  const loadInspect = useCallback(() => {
    if (!selectedDatasetId) return

    // One inspection in flight at a time. Switching datasets quickly would
    // otherwise let a slow response for the previous dataset land last and
    // display dataset A's rows while dataset B is selected. Aborting first
    // and then ignoring every settlement of an aborted controller means only
    // the current selection can touch inspect / error / loading state.
    inspectAbortRef.current?.abort()
    const controller = new AbortController()
    inspectAbortRef.current = controller

    setColumnsLoading(true)
    setInspectError(null)
    fetchDatasetInspect(id, selectedDatasetId, controller.signal)
      .then((data) => {
        if (controller.signal.aborted) return
        setInspect(data)
      })
      .catch((err) => {
        // A superseded request is not a failure — say nothing about it.
        if (controller.signal.aborted) return
        // Previously this failed silently: no columns appeared and no reason
        // was given. A dataset that cannot be read is worth saying out loud.
        setInspect(null)
        setInspectError(
          err instanceof ApiError
            ? err.message
            : 'Could not read this dataset.',
        )
      })
      .finally(() => {
        // The request that replaced this one owns the loading state now.
        if (controller.signal.aborted) return
        setColumnsLoading(false)
      })
  }, [id, selectedDatasetId])

  useEffect(() => {
    setInspect(null)
    loadInspect()
    return () => inspectAbortRef.current?.abort()
  }, [loadInspect])

  // Role dropdowns need plain names. Use column_names, not the profiled
  // subset: detailed profiles are capped at 200 columns, so deriving the
  // dropdown list from them would make every later column unselectable.
  const datasetColumns = inspect ? inspect.column_names : []

  // Analyses run asynchronously on Celery, so a submitted job stays "pending"
  // until something refetches it. Poll only the jobs that are still running,
  // and stop as soon as they all reach a terminal state.
  const activeJobIds = jobs
    .filter((j) => j.status === 'pending' || j.status === 'running')
    .map((j) => j.id)
    .sort()
    .join(',')

  // Which active-job set polling gave up on, and a manual "check again"
  // trigger. Keying the flag to the id set means a new set clears it without
  // a reset effect.
  const [timedOutFor, setTimedOutFor] = useState<string | null>(null)
  const [pollAttempt, setPollAttempt] = useState(0)
  const pollTimedOut = !!activeJobIds && timedOutFor === activeJobIds

  useEffect(() => {
    if (!activeJobIds) return
    const ids = activeJobIds.split(',')
    const controller = new AbortController()
    const startedAt = Date.now()
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined

    const poll = async () => {
      if (stopped) return

      // Elapsed wall time, not tick count: a slow network makes each round
      // trip longer, so counting ticks would silently stretch the cap.
      if (Date.now() - startedAt > JOB_POLL_TIMEOUT_MS) {
        setTimedOutFor(activeJobIds)
        return
      }

      const settled = await Promise.all(
        ids.map((jobId) =>
          apiFetch<AnalysisJob>(`/api/analysis/${jobId}`, { signal: controller.signal })
            .catch(() => null),
        ),
      )
      if (stopped) return

      // Transient failures (offline, 5xx, aborted) yield null — keep the job
      // as-is and try again on the next pass rather than surfacing an error.
      const fresh = settled.filter((j): j is AnalysisJob => j !== null)
      if (fresh.length > 0) {
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
          // Returning `prev` unchanged avoids a re-render that would otherwise
          // tear down and restart this poller on every pass.
          return changed ? next : prev
        })
      }

      // Scheduled only after the batch settles, so requests can never overlap
      // even when a round trip takes longer than the interval.
      timer = setTimeout(poll, JOB_POLL_INTERVAL_MS)
    }

    timer = setTimeout(poll, JOB_POLL_INTERVAL_MS)

    return () => {
      stopped = true
      controller.abort()
      if (timer) clearTimeout(timer)
    }
  }, [activeJobIds, pollAttempt])

  async function handleUpload(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault()
    if (!uploadFile) return
    // Re-check at submit: the picker's check can be bypassed by dropping a
    // file or by changing it after selection. The backend is still the
    // authority — this only avoids a pointless round trip.
    const problem = checkUploadFile(uploadFile)
    if (problem) {
      setUploadError(problem)
      return
    }
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
        // `HTTP 413` tells a clinician nothing. Say what happened and what to
        // do about it; fall back to the server's own message when it has one.
        if (res.status === 413) {
          throw new Error(`This file exceeds the ${UPLOAD_MAX_LABEL} limit.`)
        }
        if (res.status === 401 || res.status === 403) {
          throw new Error('You are not allowed to upload to this workspace.')
        }
        throw new Error(
          typeof body.detail === 'string'
            ? body.detail
            : 'Upload failed. Check the file and try again.',
        )
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
    // A disabled button is not the gate — Enter in a text field and any
    // programmatic submit reach this handler directly. Refuse here too, so a
    // configuration that has not been validated since its last edit cannot be
    // submitted by a route that skips the button.
    if (!runGate.ready) {
      setSubmitError(runGate.reason ?? 'Validate the configuration first.')
      return
    }
    setSubmitting(true)
    setSubmitError(null)
    try {
      // Both paths send typed parameters built from real column names. The
      // old free-text path split strings on commas, so a typo or a stray
      // space reached the backend as a validation error after submission.
      const parameters = selectedTest === 'kaplan_meier'
        ? kmConfigToParams(kmConfig)
        : analysisConfigToParams(selectedTest as AnalysisJobType, analysisConfig)
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

  // Every analysis is now gated on a backend preflight, not just Kaplan-Meier.
  // The gate is UX: it stops a submission the backend would reject anyway, and
  // the run re-validates the same configuration regardless. For logistic
  // regression `ready` is also false until the outcome has been confirmed,
  // because the backend reports that as a blocker.
  const runGate: { ready: boolean; reason?: string } = !selectedTest
    ? { ready: false, reason: 'Select an analysis type' }
    : (selectedTest === 'kaplan_meier' ? kmPreflight?.ready : analysisPreflight?.ready)
      ? { ready: true }
      : { ready: false, reason: 'Validate the configuration first' }
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
          {/* Data first, analysis second: the researcher sees what they
              uploaded before being asked what any column means. */}
          {selectedDatasetId && (
            <DatasetInspector
              inspect={inspect}
              loading={columnsLoading}
              error={inspectError}
              onRetry={loadInspect}
            />
          )}

          {!selectedTest ? (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '48px 0', flexDirection: 'column', gap: '10px' }}>
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
                  <AnalysisConfigForm
                    workspaceId={id}
                    datasetId={selectedDatasetId}
                    jobType={selectedTest as AnalysisJobType}
                    columns={datasetColumns}
                    config={analysisConfig}
                    setConfig={setAnalysisConfig}
                    preflight={analysisPreflight}
                    setPreflight={setAnalysisPreflight}
                  />
                )}
                {submitError && <div className="alert-error">{submitError}</div>}
                <div>
                  <button
                    type="submit"
                    disabled={submitting || !runGate.ready}
                    className="btn btn-primary"
                    title={runGate.ready ? undefined : runGate.reason}
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
                        pollTimedOut ? (
                          // Polling gave up waiting — the job is NOT marked
                          // failed, it may still be running on the worker.
                          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', color: 'var(--text-secondary)', fontSize: '12px' }}>
                            <span>Analysis is still processing. You can refresh later.</span>
                            <button
                              type="button"
                              className="btn btn-outline btn-sm"
                              onClick={() => {
                                setTimedOutFor(null)
                                setPollAttempt((n) => n + 1)
                              }}
                            >
                              Check again
                            </button>
                          </div>
                        ) : (
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--text-secondary)', fontSize: '12px' }}>
                            <span className="spinner" /> Processing…
                          </div>
                        )
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
        <div
          className="modal-overlay"
          onClick={(e) => {
            // Closing mid-upload would leave the request running with nothing
            // reporting its outcome.
            if (e.target === e.currentTarget && !uploading) setShowUpload(false)
          }}
        >
          <div className="modal">
            <p className="modal-title">Upload dataset</p>
            {/* Format and limit stated before the file picker opens, not
                discovered from a rejection afterwards. */}
            <p style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
              CSV files only, up to {UPLOAD_MAX_LABEL}. The first row must contain
              column names. All data is encrypted at rest.
            </p>
            <hr className="modal-divider" />
            <form onSubmit={handleUpload} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div>
                <label className="field-label">File</label>
                <input
                  ref={fileInputRef}
                  type="file"
                  required
                  accept={UPLOAD_ACCEPT}
                  onChange={(e) => {
                    const file = e.target.files?.[0] ?? null
                    // Reject an unusable file at selection time. The backend
                    // enforces the same rules — this only saves the researcher
                    // a failed upload.
                    const problem = file ? checkUploadFile(file) : null
                    setUploadError(problem)
                    setUploadFile(problem ? null : file)
                  }}
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
                    {uploadFile ? uploadFile.name : `No file chosen — .csv, up to ${UPLOAD_MAX_LABEL}`}
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
              {/* Encryption and storage happen before the response, so a large
                  file can sit here for a while. Say so instead of leaving a
                  spinner to be read as a hang. */}
              {uploading && (
                <p style={{ fontSize: '11px', color: 'var(--text-secondary)' }}>
                  Encrypting and storing your file. This can take a moment for large
                  files — keep this window open.
                </p>
              )}
              <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
                <button
                  type="button"
                  className="btn btn-outline"
                  disabled={uploading}
                  onClick={() => setShowUpload(false)}
                >
                  Cancel
                </button>
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
