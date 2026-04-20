'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiFetch, ApiError } from '@/lib/api'
import { clearToken } from '@/lib/auth'
import type { Workspace, User } from '@/lib/types'

type NewWsForm = { name: string; description: string }

export default function DashboardPage() {
  const router = useRouter()
  const [user, setUser] = useState<User | null>(null)
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [showModal, setShowModal] = useState(false)
  const [creating, setCreating] = useState(false)
  const [createError, setCreateError] = useState<string | null>(null)
  const [newWs, setNewWs] = useState<NewWsForm>({ name: '', description: '' })

  useEffect(() => {
    async function load() {
      try {
        const [me, wsList] = await Promise.all([
          apiFetch<User>('/api/auth/me'),
          apiFetch<Workspace[]>('/api/workspaces'),
        ])
        setUser(me)
        setWorkspaces(wsList)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Failed to load')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  function handleLogout() {
    clearToken()
    router.replace('/login')
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault()
    setCreating(true)
    setCreateError(null)
    try {
      const ws = await apiFetch<Workspace>('/api/workspaces', {
        method: 'POST',
        body: JSON.stringify({
          name: newWs.name,
          description: newWs.description || null,
        }),
      })
      setWorkspaces((prev) => [ws, ...prev])
      setShowModal(false)
      setNewWs({ name: '', description: '' })
    } catch (err) {
      setCreateError(err instanceof ApiError ? err.message : 'Failed to create workspace')
    } finally {
      setCreating(false)
    }
  }

  const initials = user?.full_name
    ? user.full_name
        .split(' ')
        .map((n) => n[0])
        .slice(0, 2)
        .join('')
        .toUpperCase()
    : '?'

  return (
    <div className="min-h-screen" style={{ background: 'var(--bg-base)' }}>
      {/* Header */}
      <header className="app-header">
        <div className="app-logo">
          <span className="app-logo-text">
            <span className="app-logo-accent">Onco</span>Research
          </span>
          <span className="app-logo-sub">Platform</span>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          {user && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <div
                style={{
                  width: '30px', height: '30px',
                  borderRadius: '50%',
                  background: 'var(--bg-raised)',
                  border: '1px solid var(--border-strong)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  fontSize: '10px',
                  color: 'var(--accent)',
                  letterSpacing: '0.04em',
                  flexShrink: 0,
                }}
              >
                {initials}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                <span style={{ fontSize: '12px', color: 'var(--text-primary)', lineHeight: 1.2 }}>
                  {user.full_name}
                </span>
                <span className="label" style={{ lineHeight: 1.2 }}>
                  {user.role}
                </span>
              </div>
            </div>
          )}
          <button
            onClick={handleLogout}
            className="btn btn-ghost btn-sm"
          >
            Sign out
          </button>
        </div>
      </header>

      {/* Main */}
      <main style={{ maxWidth: '860px', margin: '0 auto', padding: '40px 28px' }}>
        {/* Page title row */}
        <div
          className="anim-fade-up"
          style={{
            display: 'flex',
            alignItems: 'flex-end',
            justifyContent: 'space-between',
            marginBottom: '32px',
          }}
        >
          <div>
            <h1 className="display" style={{ fontSize: '32px', marginBottom: '4px' }}>
              Workspaces
            </h1>
            <p style={{ color: 'var(--text-secondary)', fontSize: '12px' }}>
              {loading
                ? 'Loading…'
                : `${workspaces.length} workspace${workspaces.length !== 1 ? 's' : ''}`}
            </p>
          </div>

          <button
            className="btn btn-primary anim-fade-up"
            onClick={() => setShowModal(true)}
          >
            + New workspace
          </button>
        </div>

        {/* Error */}
        {error && (
          <div className="alert-error anim-fade-up" style={{ marginBottom: '24px' }}>
            {error}
          </div>
        )}

        {/* Loading skeletons */}
        {loading && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            {[1, 2, 3].map((i) => (
              <div
                key={i}
                className="skeleton"
                style={{ height: '80px', animationDelay: `${i * 0.08}s` }}
              />
            ))}
          </div>
        )}

        {/* Empty state */}
        {!loading && !error && workspaces.length === 0 && (
          <div
            className="card anim-fade-up"
            style={{
              padding: '56px 32px',
              textAlign: 'center',
            }}
          >
            <p className="display" style={{ fontSize: '24px', marginBottom: '10px', color: 'var(--text-secondary)' }}>
              No workspaces yet
            </p>
            <p style={{ color: 'var(--text-secondary)', fontSize: '12px', marginBottom: '24px' }}>
              Create your first workspace to start uploading datasets and running analyses.
            </p>
            <button
              className="btn btn-outline"
              onClick={() => setShowModal(true)}
            >
              Create workspace
            </button>
          </div>
        )}

        {/* Workspace list */}
        {!loading && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {workspaces.map((ws, i) => (
              <button
                key={ws.id}
                onClick={() => router.push(`/workspaces/${ws.id}`)}
                className="ws-card"
                style={{ animationDelay: `${i * 0.06}s` }}
              >
                <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '16px' }}>
                  <div style={{ minWidth: 0 }}>
                    <p style={{ fontSize: '14px', color: 'var(--text-primary)', marginBottom: '4px', fontWeight: 400 }}>
                      {ws.name}
                    </p>
                    {ws.description && (
                      <p style={{ fontSize: '12px', color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {ws.description}
                      </p>
                    )}
                  </div>
                  <span className="label" style={{ flexShrink: 0, paddingTop: '2px' }}>
                    {new Date(ws.created_at).toLocaleDateString('en-GB', {
                      day: 'numeric',
                      month: 'short',
                      year: 'numeric',
                    })}
                  </span>
                </div>
              </button>
            ))}
          </div>
        )}
      </main>

      {/* New workspace modal */}
      {showModal && (
        <div className="modal-overlay" onClick={(e) => e.target === e.currentTarget && setShowModal(false)}>
          <div className="modal">
            <p className="modal-title">New workspace</p>
            <p style={{ fontSize: '12px', color: 'var(--text-secondary)', marginBottom: '4px' }}>
              A workspace groups datasets, collaborators, and analyses together.
            </p>
            <hr className="modal-divider" />

            <form onSubmit={handleCreate} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div>
                <label className="field-label" htmlFor="ws-name">Workspace name</label>
                <input
                  id="ws-name"
                  type="text"
                  required
                  autoFocus
                  value={newWs.name}
                  onChange={(e) => setNewWs((p) => ({ ...p, name: e.target.value }))}
                  className="field-input"
                  placeholder="e.g. Lung Cancer Cohort 2025"
                />
              </div>

              <div>
                <label className="field-label" htmlFor="ws-desc">Description <span style={{ opacity: 0.5 }}>(optional)</span></label>
                <input
                  id="ws-desc"
                  type="text"
                  value={newWs.description}
                  onChange={(e) => setNewWs((p) => ({ ...p, description: e.target.value }))}
                  className="field-input"
                  placeholder="Brief description of the study"
                />
              </div>

              {createError && (
                <div className="alert-error">{createError}</div>
              )}

              <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
                <button
                  type="button"
                  className="btn btn-outline"
                  onClick={() => { setShowModal(false); setCreateError(null) }}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="btn btn-primary"
                >
                  {creating ? (
                    <><span className="spinner" /> Creating…</>
                  ) : (
                    'Create workspace'
                  )}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
