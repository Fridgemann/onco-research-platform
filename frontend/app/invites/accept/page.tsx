'use client'

import { useEffect, useState, Suspense } from 'react'
import { useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { apiFetch, ApiError } from '@/lib/api'
import { getToken, saveToken } from '@/lib/auth'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

type PageState = 'checking' | 'unauthenticated' | 'ready' | 'submitting' | 'declining' | 'success' | 'declined' | 'error'

function AcceptInviteInner() {
  const searchParams = useSearchParams()
  const token = searchParams.get('token') ?? ''

  const [pageState, setPageState] = useState<PageState>('checking')
  const [error, setError] = useState<string | null>(null)
  const [workspaceId, setWorkspaceId] = useState<string | null>(null)

  // On mount: check auth via memory token or silent refresh
  useEffect(() => {
    if (!token) { setError('No invite token found in the URL.'); setPageState('error'); return }

    if (getToken()) { setPageState('ready'); return }

    fetch(`${API_BASE}/api/auth/refresh`, { method: 'POST', credentials: 'include' })
      .then(async (res) => {
        if (res.ok) {
          const { access_token } = await res.json()
          saveToken(access_token)
          setPageState('ready')
        } else {
          setPageState('unauthenticated')
        }
      })
      .catch(() => setPageState('unauthenticated'))
  }, [token])

  async function handleDecline() {
    setPageState('declining')
    setError(null)
    try {
      await apiFetch('/api/invites/decline', { method: 'POST', body: JSON.stringify({ token }) })
      setPageState('declined')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong.')
      setPageState('error')
    }
  }

  async function handleAccept() {
    setPageState('submitting')
    setError(null)
    try {
      const data = await apiFetch<{ message: string; workspace_id: string; role: string }>(
        '/api/invites/accept',
        { method: 'POST', body: JSON.stringify({ token }) },
      )
      setWorkspaceId(data.workspace_id);
      setPageState('success');
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Something went wrong.');
      setPageState('error');
    }
  }

  if (pageState === 'checking') {
    return (
      <div style={{ textAlign: 'center' }}>
        <div className="skeleton" style={{ height: '20px', width: '180px', margin: '0 auto 12px' }} />
        <div className="skeleton" style={{ height: '14px', width: '240px', margin: '0 auto' }} />
      </div>
    )
  }

  if (pageState === 'unauthenticated') {
    return (
      <>
        <h2 className="display" style={{ fontSize: '24px', marginBottom: '8px' }}>You have been invited</h2>
        <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '28px' }}>
          Sign in to accept your invitation, or create a new account — your invite will be applied automatically.
        </p>
        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
          <Link
            href={`/login?next=/invites/accept?token=${encodeURIComponent(token)}`}
            className="btn btn-primary"
            style={{ display: 'inline-block' }}
          >
            Sign in to accept
          </Link>
          <Link
            href={`/register?invite_token=${encodeURIComponent(token)}`}
            className="btn btn-outline"
            style={{ display: 'inline-block' }}
          >
            Create account
          </Link>
        </div>
      </>
    )
  }

  if (pageState === 'success') {
    return (
      <>
        <h2 className="display" style={{ fontSize: '24px', marginBottom: '8px' }}>You&apos;re in</h2>
        <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '28px' }}>
          You have joined the workspace as a collaborator.
        </p>
        <Link
          href={workspaceId ? `/workspaces/${workspaceId}` : '/dashboard'}
          className="btn btn-primary"
          style={{ display: 'inline-block' }}
        >
          Go to workspace
        </Link>
      </>
    )
  }

  if (pageState === 'declined') {
    return (
      <>
        <h2 className="display" style={{ fontSize: '24px', marginBottom: '8px' }}>Invitation declined</h2>
        <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '28px' }}>
          You have declined this workspace invitation.
        </p>
        <Link href="/dashboard" className="btn btn-outline" style={{ display: 'inline-block' }}>
          Go to dashboard
        </Link>
      </>
    )
  }

  if (pageState === 'error') {
    return (
      <>
        <h2 className="display" style={{ fontSize: '24px', marginBottom: '8px' }}>Invite unavailable</h2>
        <div className="alert-error" style={{ marginBottom: '24px' }}>{error}</div>
        <Link href="/dashboard" style={{ fontSize: '12px', color: 'var(--accent)', textDecoration: 'none' }}>
          Go to dashboard
        </Link>
      </>
    )
  }

  // ready | submitting
  return (
    <>
      <h2 className="display" style={{ fontSize: '24px', marginBottom: '8px' }}>Research workspace invite</h2>
      <p style={{ fontSize: '13px', color: 'var(--text-secondary)', marginBottom: '28px' }}>
        You have been invited to collaborate on a research workspace.
        Click below to accept and gain access.
      </p>
      {error && <div className="alert-error" style={{ marginBottom: '16px' }}>{error}</div>}
      <div style={{ display: 'flex', gap: '10px' }}>
        <button
          className="btn btn-primary"
          disabled={pageState === 'submitting' || pageState === 'declining'}
          onClick={handleAccept}
        >
          {pageState === 'submitting' ? <><span className="spinner" /> Accepting…</> : 'Accept invitation'}
        </button>
        <button
          className="btn btn-outline"
          disabled={pageState === 'submitting' || pageState === 'declining'}
          onClick={handleDecline}
        >
          {pageState === 'declining' ? <><span className="spinner" /> Declining…</> : 'Decline'}
        </button>
      </div>
    </>
  )
}

export default function AcceptInvitePage() {
  return (
    <div className="min-h-screen flex items-center justify-center" style={{ background: 'var(--bg-base)' }}>
      <div style={{ maxWidth: '420px', width: '100%', padding: '0 24px' }}>
        <div className="app-logo" style={{ marginBottom: '40px' }}>
          <span className="app-logo-text">
            <span className="app-logo-accent">Onco</span>Research
          </span>
        </div>
        <Suspense fallback={null}>
          <AcceptInviteInner />
        </Suspense>
      </div>
    </div>
  )
}
