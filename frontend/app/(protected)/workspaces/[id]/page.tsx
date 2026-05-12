'use client'

import { useEffect, useState, use, useRef } from 'react'
import Link from 'next/link'
import { apiFetch, ApiError } from '@/lib/api'
import { getToken } from '@/lib/auth'
import type { Dataset, AnalysisJob, Workspace, WorkspaceInvite, WorkspaceMember, User } from '@/lib/types'
import ResultPanel from '@/components/analysis/ResultPanel'

type Tab = 'datasets' | 'analysis' | 'members'

type JobType = 'kaplan_meier' | 'descriptive_stats' | 'regression' | 'logistic_regression'

const JOB_TYPE_LABELS: Record<JobType, string> = {
  kaplan_meier: 'Kaplan–Meier Survival',
  descriptive_stats: 'Descriptive Statistics',
  regression: 'Linear Regression',
  logistic_regression: 'Logistic Regression',
}

const FIELD_CONFIG: Record<JobType, { key: string; label: string; placeholder: string; optional?: boolean }[]> = {
  kaplan_meier: [
    { key: 'time_column', label: 'Time Column', placeholder: 'e.g. survival_months' },
    { key: 'event_column', label: 'Event Column', placeholder: 'e.g. event_occurred' },
    { key: 'group_column', label: 'Group Column', placeholder: 'e.g. treatment_arm', optional: true },
    { key: 'max_groups', label: 'Max Groups', placeholder: 'e.g. 60 — leave blank for default (server max: 100)', optional: true },
  ],
  descriptive_stats: [{ key: 'columns', label: 'Columns', placeholder: 'e.g. age, stage', optional: true }],
  regression: [{ key: 'target_column', label: 'Target Column', placeholder: 'e.g. survival_months' },
  { key: 'feature_columns', label: 'Feature Columns', placeholder: 'e.g. tumor_size' }],
  logistic_regression: [{ key: 'target_column', label: 'Target Column', placeholder: 'e.g. survival_status' },
  { key: 'feature_columns', label: 'Feature Columns', placeholder: 'e.g. age, tumor_size' }],
}

function AnalysisParamFields({
  jobType,
  params,
  setParams,
}: {
  jobType: JobType,
  params: Record<string, string>,
  setParams: (p: Record<string, string>) => void
}) {
  return (
    <div className='flex flex-col gap-4'>
      {FIELD_CONFIG[jobType].map((f) => {
        if (f.key === 'max_groups' && !params['group_column']) return null
        return (
          <div key={f.key}>
            <label className='field-label'>{f.label}{f.optional && <span style={{ opacity: 0.5 }}> (optional)</span>}</label>
            <input
              className='field-input'
              value={params[f.key] ?? ''}
              onChange={(e) => setParams({...params, [f.key]: e.target.value })}
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

export default function WorkspacePage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = use(params)
  const [workspace, setWorkspace] = useState<Workspace | null>(null)
  const [tab, setTab] = useState<Tab>('datasets')
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [jobs, setJobs] = useState<AnalysisJob[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Upload modal
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [showUpload, setShowUpload] = useState(false)
  const [uploadFile, setUploadFile] = useState<File | null>(null)
  const [uploadDesc, setUploadDesc] = useState('')
  const [uploading, setUploading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)

  // Current user (for owner check)
  const [currentUser, setCurrentUser] = useState<User | null>(null)

  // Members / invites tab
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

  // Run analysis modal
  const [showAnalysis, setShowAnalysis] = useState(false)
  const [jobType, setJobType] = useState<JobType>('kaplan_meier')
  const [jobDatasetId, setJobDatasetId] = useState('')
  const [jobParams, setJobParams] = useState<Record<string, string>>({})
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [expandedJobId, setExpandedJobId] = useState<string | null>(null)

  useEffect(() => {
    async function load() {
      try {
        const [ws, ds, js, me] = await Promise.all([
          apiFetch<Workspace>(`/api/workspaces/${id}`),
          apiFetch<Dataset[]>(`/api/workspaces/${id}/datasets`),
          apiFetch<AnalysisJob[]>(`/api/analysis?workspace_id=${id}`),
          apiFetch<User>('/api/auth/me'),
        ])
        setWorkspace(ws)
        setDatasets(ds)
        setJobs(js)
        setCurrentUser(me)
        if (ds.length > 0) setJobDatasetId(ds[0].id)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Failed to load workspace')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [id])

  // Reset params when job type changes
  useEffect(() => {
    setJobParams({})
  }, [jobType])

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
      if (!jobDatasetId) setJobDatasetId(ds.id)
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
    setSubmitting(true)
    setSubmitError(null)
    try {
      // Convert comma-separated string params to arrays where needed
      const parameters: Record<string, unknown> = {}
      for (const [k, v] of Object.entries(jobParams)) {
        if (k.endsWith('_columns') || k === 'columns') {
          parameters[k] = v.split(',').map((s) => s.trim()).filter(Boolean)
        } else {
          parameters[k] = v
        }
      }

      const job = await apiFetch<AnalysisJob>(
        `/api/workspaces/${id}/datasets/${jobDatasetId}/analysis`,
        {
          method: 'POST',
          body: JSON.stringify({ job_type: jobType, parameters }),
        },
      )
      setJobs((prev) => [job, ...prev])
      setShowAnalysis(false)
      setTab('analysis')
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : 'Failed to submit job')
    } finally {
      setSubmitting(false)
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
        // non-owners get 403 on invites — members list still shows
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
      // ignore — list stays stale but not harmful
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
      // ignore — list will be stale but not harmful
    } finally {
      setRevoking(null)
    }
  }

  return (
    <div className="min-h-screen" style={{ background: 'var(--bg-base)' }}>
      {/* Header */}
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
              <span style={{ fontSize: '13px', color: 'var(--text-primary)' }}>
                {workspace.name}
              </span>
            </>
          )}
        </div>

        <div style={{ display: 'flex', gap: '10px' }}>
          <button
            className="btn btn-outline btn-sm"
            onClick={() => setShowUpload(true)}
          >
            Upload dataset
          </button>
          <button
            className="btn btn-primary btn-sm"
            onClick={() => setShowAnalysis(true)}
            disabled={datasets.length === 0}
            title={datasets.length === 0 ? 'Upload a dataset first' : undefined}
          >
            Run analysis
          </button>
        </div>
      </header>

      {/* Main */}
      <main style={{ maxWidth: '920px', margin: '0 auto', padding: '32px 28px' }}>
        {error && (
          <div className="alert-error anim-fade-up" style={{ marginBottom: '24px' }}>
            {error}
          </div>
        )}

        {/* Tab nav */}
        <div className="tab-nav anim-fade-up" style={{ marginBottom: '24px' }}>
          <button onClick={() => setTab('datasets')} className={`tab-btn ${tab === 'datasets' ? 'active' : ''}`}>
            {`Datasets${datasets.length ? ` (${datasets.length})` : ''}`}
          </button>
          <button onClick={() => setTab('analysis')} className={`tab-btn ${tab === 'analysis' ? 'active' : ''}`}>
            {`Analysis jobs${jobs.length ? ` (${jobs.length})` : ''}`}
          </button>
          <button
            onClick={() => { setTab('members'); if (invites.length === 0) loadInvites() }}
            className={`tab-btn ${tab === 'members' ? 'active' : ''}`}
          >
            Members
          </button>
        </div>

        {loading && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {[1, 2, 3].map((i) => (
              <div key={i} className="skeleton" style={{ height: '60px' }} />
            ))}
          </div>
        )}

        {/* Datasets tab */}
        {!loading && tab === 'datasets' && (
          <div className="card anim-fade-up">
            {datasets.length === 0 ? (
              <div style={{ padding: '48px 32px', textAlign: 'center' }}>
                <p className="display" style={{ fontSize: '22px', color: 'var(--text-secondary)', marginBottom: '10px' }}>
                  No datasets yet
                </p>
                <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '20px' }}>
                  Upload a CSV or Excel file to get started with analysis.
                </p>
                <button className="btn btn-outline" onClick={() => setShowUpload(true)}>
                  Upload dataset
                </button>
              </div>
            ) : (
              datasets.map((ds, i) => (
                <div key={ds.id} className="dataset-row" style={{ animationDelay: `${i * 0.05}s` }}>
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <p style={{ fontSize: '13px', color: 'var(--text-primary)', marginBottom: '3px' }}>
                      {ds.filename}
                    </p>
                    <div style={{ display: 'flex', gap: '14px' }}>
                      <span className="mono-sm">{(ds.file_size / 1024).toFixed(1)} KB</span>
                      <span className="mono-sm">{ds.content_type}</span>
                      <span className="mono-sm">
                        {new Date(ds.created_at).toLocaleDateString('en-GB', {
                          day: 'numeric', month: 'short', year: 'numeric',
                        })}
                      </span>
                    </div>
                    {ds.description && (
                      <p style={{ fontSize: '11px', color: 'var(--text-secondary)', marginTop: '3px' }}>
                        {ds.description}
                      </p>
                    )}
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {/* Analysis tab */}
        {!loading && tab === 'analysis' && (
          <div className="card anim-fade-up">
            {jobs.length === 0 ? (
              <div style={{ padding: '48px 32px', textAlign: 'center' }}>
                <p className="display" style={{ fontSize: '22px', color: 'var(--text-secondary)', marginBottom: '10px' }}>
                  No analysis jobs yet
                </p>
                <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '20px' }}>
                  Select a dataset and run an analysis to see results here.
                </p>
                <button
                  className="btn btn-outline"
                  onClick={() => setShowAnalysis(true)}
                  disabled={datasets.length === 0}
                >
                  Run analysis
                </button>
              </div>
            ) : (
              jobs.map((job, i) => (
                <div key={job.id} style={{ animationDelay: `${i * 0.05}s` }}>
                  <div className="dataset-row">
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '4px' }}>
                        <p style={{ fontSize: '13px', color: 'var(--text-primary)' }}>
                          {JOB_TYPE_LABELS[job.job_type as JobType] ?? job.job_type}
                        </p>
                        <StatusBadge status={job.status} />
                      </div>
                      <div style={{ display: 'flex', gap: '14px' }}>
                        <span className="mono-sm">
                          {new Date(job.created_at).toLocaleString('en-GB', {
                            day: 'numeric', month: 'short', year: 'numeric',
                            hour: '2-digit', minute: '2-digit',
                          })}
                        </span>
                        {job.completed_at && (
                          <span className="mono-sm">
                            completed {new Date(job.completed_at).toLocaleTimeString('en-GB', {
                              hour: '2-digit', minute: '2-digit',
                            })}
                          </span>
                        )}
                      </div>
                      {job.error_message && (
                        <p style={{ fontSize: '11px', color: 'var(--status-failed-fg)', marginTop: '4px' }}>
                          {job.error_message}
                        </p>
                      )}
                    </div>

                    {job.status === 'completed' && job.result && (
                      <div style={{ display: 'flex', gap: '8px' }}>
                        <button
                          className="btn btn-outline btn-sm"
                          onClick={() => setExpandedJobId(expandedJobId === job.id ? null : job.id)}
                        >
                          {expandedJobId === job.id ? 'Hide results' : 'View results'}
                        </button>
                        <button
                          className="btn btn-outline btn-sm"
                          onClick={() => {
                            const blob = new Blob([JSON.stringify(job.result, null, 2)], { type: 'application/json' })
                            const url = URL.createObjectURL(blob)
                            const a = document.createElement('a')
                            a.href = url; a.download = `${job.id}.json`; a.click()
                            URL.revokeObjectURL(url)
                          }}
                        >
                          ↓
                        </button>
                      </div>
                    )}
                  </div>

                  {expandedJobId === job.id && job.result && (
                    <div style={{ padding: '20px 24px', borderTop: '1px solid var(--border)', background: 'rgba(255,255,255,0.01)' }}>
                      <ResultPanel job={job} />
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        )}

        {/* Members tab */}
        {!loading && tab === 'members' && (
          <div className="card anim-fade-up">
            <>
              {/* Members list — visible to all members */}
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
                  {/* Owner: remove button for non-self members */}
                  {workspace && currentUser?.id === workspace.owner_id && m.user_id !== currentUser.id && (
                    confirmRemove === m.id ? (
                      <span style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                        <span style={{ fontSize: '11px', color: 'var(--text-secondary)', marginRight: '4px' }}>Sure?</span>
                        <button
                          className="btn btn-outline btn-sm"
                          disabled={removing === m.id}
                          onClick={() => { setConfirmRemove(null); handleRemoveMember(m.id, m.user_id) }}
                        >
                          {removing === m.id ? 'Removing…' : 'Yes'}
                        </button>
                        <button className="btn btn-outline btn-sm" onClick={() => setConfirmRemove(null)}>No</button>
                      </span>
                    ) : (
                      <button
                        className="btn btn-outline btn-sm"
                        disabled={removing === m.id}
                        onClick={() => setConfirmRemove(m.id)}
                      >
                        Remove
                      </button>
                    )
                  )}
                  {/* Collaborator: leave button only on own row */}
                  {workspace && currentUser?.id !== workspace.owner_id && m.user_id === currentUser?.id && (
                    confirmLeave ? (
                      <span style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                        <span style={{ fontSize: '11px', color: 'var(--text-secondary)', marginRight: '4px' }}>Sure?</span>
                        <button
                          className="btn btn-outline btn-sm"
                          disabled={leaving}
                          onClick={() => { setConfirmLeave(false); handleLeave() }}
                        >
                          {leaving ? 'Leaving…' : 'Yes'}
                        </button>
                        <button className="btn btn-outline btn-sm" onClick={() => setConfirmLeave(false)}>No</button>
                      </span>
                    ) : (
                      <button className="btn btn-outline btn-sm" onClick={() => setConfirmLeave(true)}>
                        Leave
                      </button>
                    )
                  )}
                </div>
              ))}

              {/* Invite form — owner only */}
              {workspace && currentUser?.id === workspace.owner_id && (<>
                <div style={{ padding: '20px 24px', borderBottom: '1px solid var(--border)' }}>
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

                {/* Pending invites list */}
                {invitesLoading ? (
                  <div style={{ padding: '16px 24px' }}><div className="skeleton" style={{ height: '36px' }} /></div>
                ) : invites.filter(inv => inv.status === 'pending').length === 0 ? (
                  <div style={{ padding: '20px 24px' }}>
                    <p style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>No pending invites.</p>
                  </div>
                ) : (
                  invites.filter(inv => inv.status === 'pending').map((inv) => (
                    <div key={inv.id} className="dataset-row">
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <p style={{ fontSize: '13px', color: 'var(--text-primary)', marginBottom: '2px' }}>{inv.invited_email}</p>
                        <span className="mono-sm">expires {new Date(inv.expires_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}</span>
                      </div>
                      <button className="btn btn-outline btn-sm" disabled={revoking === inv.id} onClick={() => handleRevoke(inv.id)}>
                        {revoking === inv.id ? 'Revoking…' : 'Revoke'}
                      </button>
                    </div>
                  ))
                )}
              </>
            )}
            </>
          </div>
        )}
      </main>

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
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '10px',
                    background: 'var(--bg-raised)',
                    border: '1px solid var(--border-strong)',
                    borderRadius: 'var(--radius)',
                    padding: '8px 10px 8px 4px',
                  }}
                >
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
                <button type="button" className="btn btn-outline" onClick={() => setShowUpload(false)}>
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

      {/* Run analysis modal */}
      {showAnalysis && (
        <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && setShowAnalysis(false)}>
          <div className="modal">
            <p className="modal-title">Run analysis</p>
            <p style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
              Submitted jobs run asynchronously via Celery.
            </p>
            <hr className="modal-divider" />

            <form onSubmit={handleRunAnalysis} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div>
                <label className="field-label" htmlFor="job-dataset">Dataset</label>
                <select
                  id="job-dataset"
                  required
                  value={jobDatasetId}
                  onChange={(e) => setJobDatasetId(e.target.value)}
                  className="field-select"
                >
                  {datasets.map((ds) => (
                    <option key={ds.id} value={ds.id}>{ds.filename}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="field-label" htmlFor="job-type">Analysis type</label>
                <select
                  id="job-type"
                  required
                  value={jobType}
                  onChange={(e) => setJobType(e.target.value as JobType)}
                  className="field-select"
                >
                  {(Object.entries(JOB_TYPE_LABELS) as [JobType, string][]).map(([k, v]) => (
                    <option key={k} value={k}>{v}</option>
                  ))}
                </select>
              </div>

              <AnalysisParamFields
                jobType={jobType}
                params={jobParams}
                setParams={setJobParams}
              />

              {submitError && <div className="alert-error">{submitError}</div>}

              <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
                <button type="button" className="btn btn-outline" onClick={() => setShowAnalysis(false)}>
                  Cancel
                </button>
                <button type="submit" disabled={submitting} className="btn btn-primary">
                  {submitting ? <><span className="spinner" /> Submitting…</> : 'Run analysis'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
