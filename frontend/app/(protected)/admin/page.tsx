'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { apiFetch, ApiError } from '@/lib/api'
import { clearToken } from '@/lib/auth'
import { useUser } from '@/lib/user-context'

// ── Types ─────────────────────────────────────────────────────

interface ResearcherInvite {
  id: string
  invited_email: string
  status: 'pending' | 'accepted' | 'revoked'
  invited_by: string
  created_at: string
  expires_at: string
  accepted_at: string | null
}

interface CreateInviteResponse {
  invite_id: string
  token: string | null
  expires_at: string
  message: string
}

interface AdminUser {
  id: string
  email: string
  role: 'admin' | 'researcher' | 'collaborator'
  is_active: boolean
  is_verified: boolean
  failed_login_attempts: number
  locked_until: string | null
  created_at: string
  last_login: string | null
}

// ── Helpers ───────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { fg: string; bg: string }> = {
    pending:     { fg: 'var(--status-pending-fg)',   bg: 'var(--status-pending-bg)' },
    accepted:    { fg: 'var(--status-completed-fg)', bg: 'var(--status-completed-bg)' },
    revoked:     { fg: 'var(--status-failed-fg)',    bg: 'var(--status-failed-bg)' },
    researcher:  { fg: 'var(--status-running-fg)',   bg: 'var(--status-running-bg)' },
    collaborator:{ fg: 'var(--text-secondary)',       bg: 'var(--bg-raised)' },
    admin:       { fg: 'var(--status-pending-fg)',   bg: 'var(--status-pending-bg)' },
    active:      { fg: 'var(--status-completed-fg)', bg: 'var(--status-completed-bg)' },
    inactive:    { fg: 'var(--status-failed-fg)',    bg: 'var(--status-failed-bg)' },
  }
  const s = map[status] ?? { fg: 'var(--text-secondary)', bg: 'var(--bg-raised)' }
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 7px',
      borderRadius: '3px',
      fontSize: '10px',
      letterSpacing: '0.06em',
      textTransform: 'uppercase',
      color: s.fg,
      background: s.bg,
      fontFamily: 'var(--font-mono)',
    }}>
      {status}
    </span>
  )
}

function fmt(iso: string) {
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
}

// ── Section: Researcher Invites ───────────────────────────────

function ResearcherInvitesSection() {
  const [invites, setInvites] = useState<ResearcherInvite[]>([])
  const [loading, setLoading] = useState(true)
  const [email, setEmail] = useState('')
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState<string | null>(null)
  const [lastToken, setLastToken] = useState<string | null | undefined>(undefined)
  const [copied, setCopied] = useState(false)
  const [revoking, setRevoking] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await apiFetch<ResearcherInvite[]>('/api/admin/invites/researcher')
      setInvites(data)
    } catch { /* handled by layout */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  async function handleSend(e: React.FormEvent) {
    e.preventDefault()
    setSending(true)
    setSendError(null)
    setLastToken(null)
    try {
      const res = await apiFetch<CreateInviteResponse>('/api/admin/invites/researcher', {
        method: 'POST',
        body: JSON.stringify({ email }),
      })
      setLastToken(res.token)
      setEmail('')
      await load()
    } catch (err) {
      setSendError(err instanceof ApiError ? err.message : 'Failed to send invite')
    } finally {
      setSending(false)
    }
  }

  async function handleRevoke(id: string) {
    setRevoking(id)
    try {
      await apiFetch(`/api/admin/invites/researcher/${id}`, { method: 'DELETE' })
      setInvites((prev) => prev.map((inv) => inv.id === id ? { ...inv, status: 'revoked' } : inv))
    } catch { /* silently fail */ }
    finally { setRevoking(null) }
  }

  function copyToken(token: string) {
    const url = `${window.location.origin}/register?researcher_invite=${token}`
    navigator.clipboard.writeText(url)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="anim-fade-up-1">
      <div style={{ marginBottom: '20px' }}>
        <h2 className="display" style={{ fontSize: '16px', marginBottom: '4px' }}>Researcher Invites</h2>
        <p style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>
          Invited users register with researcher role. Without an invite, registration creates a collaborator account.
        </p>
      </div>

      {/* Create form */}
      <div className="card" style={{ padding: '20px', marginBottom: '16px' }}>
        <form onSubmit={handleSend} style={{ display: 'flex', gap: '10px', alignItems: 'flex-end', flexWrap: 'wrap' }}>
          <div style={{ flex: 1, minWidth: '220px' }}>
            <label className="field-label" htmlFor="invite-email">Email address</label>
            <input
              id="invite-email"
              type="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="field-input"
              placeholder="researcher@institution.org"
            />
          </div>
          <button type="submit" disabled={sending} className="btn btn-primary" style={{ flexShrink: 0 }}>
            {sending ? <><span className="spinner" /> Sending…</> : 'Send invite'}
          </button>
        </form>

        {sendError && <div className="alert-error" style={{ marginTop: '12px' }}>{sendError}</div>}

        {lastToken !== undefined && lastToken !== null && (
          <div style={{
            marginTop: '14px',
            padding: '10px 14px',
            background: 'var(--bg-raised)',
            border: '1px solid var(--border-accent)',
            borderRadius: 'var(--radius)',
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
            flexWrap: 'wrap',
          }}>
            <span style={{ fontSize: '11px', color: 'var(--text-secondary)', flex: 1 }}>
              Dev token (not shown in production)
            </span>
            <button
              className="btn btn-outline btn-sm"
              onClick={() => copyToken(lastToken)}
            >
              {copied ? '✓ Copied' : 'Copy link'}
            </button>
          </div>
        )}
        {lastToken === null && lastToken !== undefined && (
          <div style={{ marginTop: '12px', fontSize: '11px', color: 'var(--status-completed-fg)' }}>
            ✓ Invite email sent
          </div>
        )}
      </div>

      {/* Invite list */}
      {loading ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {[1, 2].map((i) => <div key={i} className="skeleton" style={{ height: '52px', animationDelay: `${i * 0.08}s` }} />)}
        </div>
      ) : invites.length === 0 ? (
        <p style={{ color: 'var(--text-secondary)', fontSize: '12px', padding: '20px 0' }}>No invites yet.</p>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {invites.map((inv) => (
            <div key={inv.id} className="card" style={{ padding: '12px 16px', display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
              <span style={{ flex: 1, fontSize: '12px', fontFamily: 'var(--font-mono)', minWidth: '180px' }}>
                {inv.invited_email}
              </span>
              <StatusBadge status={inv.status} />
              <span style={{ fontSize: '11px', color: 'var(--text-secondary)', minWidth: '90px' }}>
                {fmt(inv.created_at)}
              </span>
              {inv.status === 'pending' && (
                <button
                  className="btn btn-ghost btn-sm"
                  disabled={revoking === inv.id}
                  onClick={() => handleRevoke(inv.id)}
                  style={{ color: 'var(--status-failed-fg)' }}
                >
                  {revoking === inv.id ? 'Revoking…' : 'Revoke'}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Section: Users ────────────────────────────────────────────

function UsersSection({ currentUserId }: { currentUserId: string }) {
  const [users, setUsers] = useState<AdminUser[]>([])
  const [loading, setLoading] = useState(true)
  const [acting, setActing] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    apiFetch<AdminUser[]>('/api/admin/users')
      .then(setUsers)
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  async function handleDeactivate(id: string) {
    setActing(id)
    setError(null)
    try {
      await apiFetch(`/api/admin/users/${id}/deactivate`, { method: 'PATCH' })
      setUsers((prev) => prev.map((u) => u.id === id ? { ...u, is_active: false } : u))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to deactivate user.')
    } finally { setActing(null) }
  }

  async function handleReactivate(id: string) {
    setActing(id)
    setError(null)
    try {
      await apiFetch(`/api/admin/users/${id}/reactivate`, { method: 'PATCH' })
      setUsers((prev) => prev.map((u) => u.id === id ? { ...u, is_active: true } : u))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to reactivate user.')
    } finally { setActing(null) }
  }

  async function handleRoleChange(id: string, role: 'researcher' | 'collaborator') {
    setActing(id)
    setError(null)
    try {
      await apiFetch(`/api/admin/users/${id}/role`, {
        method: 'PATCH',
        body: JSON.stringify({ role }),
      })
      setUsers((prev) => prev.map((u) => u.id === id ? { ...u, role } : u))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to change role.')
    } finally { setActing(null) }
  }

  return (
    <div className="anim-fade-up-2">
      <div style={{ marginBottom: '20px' }}>
        <h2 className="display" style={{ fontSize: '16px', marginBottom: '4px' }}>Users</h2>
        <p style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>
          Manage platform roles and account status. Admin role cannot be assigned here.
        </p>
      </div>

      {error && <div className="alert-error" style={{ marginBottom: '12px' }}>{error}</div>}

      {loading ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
          {[1, 2, 3].map((i) => <div key={i} className="skeleton" style={{ height: '52px', animationDelay: `${i * 0.08}s` }} />)}
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {users.map((u) => {
            const isSelf = u.id === currentUserId
            return (
              <div key={u.id} className="card" style={{ padding: '12px 16px', display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                <div style={{ flex: 1, minWidth: '200px' }}>
                  <div style={{ fontSize: '12px' }}>{u.email}</div>
                  <div style={{ fontSize: '10px', color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', marginTop: '2px' }}>{u.id}</div>
                </div>
                <StatusBadge status={u.role} />
                <StatusBadge status={u.is_active ? 'active' : 'inactive'} />

                {!isSelf && u.role !== 'admin' && (
                  <div style={{ display: 'flex', gap: '6px' }}>
                    {u.is_active ? (
                      <button
                        className="btn btn-ghost btn-sm"
                        disabled={acting === u.id}
                        onClick={() => handleDeactivate(u.id)}
                        style={{ color: 'var(--status-failed-fg)' }}
                      >
                        Deactivate
                      </button>
                    ) : (
                      <button
                        className="btn btn-ghost btn-sm"
                        disabled={acting === u.id}
                        onClick={() => handleReactivate(u.id)}
                        style={{ color: 'var(--status-completed-fg)' }}
                      >
                        Reactivate
                      </button>
                    )}
                    {u.role === 'collaborator' ? (
                      <button
                        className="btn btn-ghost btn-sm"
                        disabled={acting === u.id}
                        onClick={() => handleRoleChange(u.id, 'researcher')}
                      >
                        → Researcher
                      </button>
                    ) : u.role === 'researcher' ? (
                      <button
                        className="btn btn-ghost btn-sm"
                        disabled={acting === u.id}
                        onClick={() => handleRoleChange(u.id, 'collaborator')}
                      >
                        → Collaborator
                      </button>
                    ) : null}
                  </div>
                )}
                {isSelf && (
                  <span style={{ fontSize: '10px', color: 'var(--text-secondary)', letterSpacing: '0.06em' }}>you</span>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────

export default function AdminPage() {
  const router = useRouter()
  const user = useUser()

  useEffect(() => {
    if (user.role !== 'admin') router.replace('/dashboard')
  }, [user.role, router])

  async function handleLogout() {
    try { await apiFetch('/api/auth/logout', { method: 'POST' }) } catch {}
    clearToken()
    router.replace('/login')
  }

  if (user.role !== 'admin') return null

  return (
    <div className="min-h-screen" style={{ background: 'var(--bg-base)' }}>
      <header className="app-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
          <div className="app-logo">
            <span className="app-logo-text">
              <span className="app-logo-accent">Onco</span>Research
            </span>
            <span className="app-logo-sub">Admin</span>
          </div>
          <Link
            href="/dashboard"
            style={{ fontSize: '11px', color: 'var(--text-secondary)', textDecoration: 'none', letterSpacing: '0.04em' }}
          >
            ← Dashboard
          </Link>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end' }}>
            <span style={{ fontSize: '12px', color: 'var(--text-primary)', lineHeight: 1.2 }}>{user.full_name}</span>
            <span className="label" style={{ lineHeight: 1.2 }}>{user.role}</span>
          </div>
          <button onClick={handleLogout} className="btn btn-ghost btn-sm">Sign out</button>
        </div>
      </header>

      <main style={{ maxWidth: '860px', margin: '0 auto', padding: '40px 28px', display: 'flex', flexDirection: 'column', gap: '48px' }}>
        <div className="anim-fade-up">
          <h1 className="display" style={{ fontSize: '32px', marginBottom: '4px' }}>Platform Admin</h1>
          <p style={{ color: 'var(--text-secondary)', fontSize: '12px' }}>
            Manage users, roles, and researcher access.
          </p>
        </div>

        <ResearcherInvitesSection />
        <UsersSection currentUserId={user.id} />
      </main>
    </div>
  )
}
