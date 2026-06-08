'use client'

import { useState, Suspense } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { apiFetch, ApiError } from '@/lib/api'
import { saveToken } from '@/lib/auth'

function RegisterForm() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const inviteToken = searchParams.get('invite_token') ?? undefined
  const researcherInviteToken = searchParams.get('researcher_invite') ?? undefined

  const [form, setForm] = useState({ email: '', full_name: '', password: '' })
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  function set(field: keyof typeof form) {
    return (e: React.ChangeEvent<HTMLInputElement>) =>
      setForm((prev) => ({ ...prev, [field]: e.target.value }))
  }

  async function handleSubmit(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault()
    setLoading(true)
    try {
      const body: Record<string, string> = { ...form }
      if (inviteToken) body.invite_token = inviteToken
      if (researcherInviteToken) body.researcher_invite_token = researcherInviteToken

      const registerData = await apiFetch<{ workspace_id?: string | null }>('/api/auth/register', {
        method: 'POST',
        body: JSON.stringify(body),
        skipRefresh: true,
      })

      const loginData = await apiFetch<{ access_token: string }>('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email: form.email, password: form.password }),
        skipRefresh: true,
      })
      saveToken(loginData.access_token)

      if (registerData.workspace_id) {
        router.push(`/workspaces/${registerData.workspace_id}`)
      } else {
        router.push('/dashboard')
      }
    } catch (err) {
      if (err instanceof ApiError) setError(err.message)
      else setError('Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  const passwordRules = [
    { label: '12+ characters', ok: form.password.length >= 12 },
    { label: 'Uppercase letter', ok: /[A-Z]/.test(form.password) },
    { label: 'Number', ok: /[0-9]/.test(form.password) },
    { label: 'Special character', ok: /[!@#$%^&*(),.?":{}|<>]/.test(form.password) },
  ]

  return (
    <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      {(inviteToken || researcherInviteToken) && (
        <div
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border)',
            borderRadius: '6px',
            padding: '10px 14px',
            fontSize: '12px',
            color: 'var(--text-secondary)',
          }}
        >
          {researcherInviteToken
            ? 'You have been invited to join as a researcher. Registering will grant you full researcher access.'
            : 'You were invited to a workspace. Registering will automatically add you as a collaborator.'}
        </div>
      )}

      <div className="anim-fade-up-2">
        <label className="field-label" htmlFor="full_name">Full name</label>
        <input
          id="full_name"
          type="text"
          required
          autoComplete="name"
          value={form.full_name}
          onChange={set('full_name')}
          className="field-input"
          placeholder="Jane Smith"
        />
      </div>

      <div className="anim-fade-up-3">
        <label className="field-label" htmlFor="email">Email address</label>
        <input
          id="email"
          type="email"
          required
          autoComplete="email"
          value={form.email}
          onChange={set('email')}
          className="field-input"
          placeholder="you@institution.org"
        />
      </div>

      <div className="anim-fade-up-4">
        <label className="field-label" htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          required
          autoComplete="new-password"
          value={form.password}
          onChange={set('password')}
          className="field-input"
        />

        {form.password.length > 0 && (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '1fr 1fr',
              gap: '5px',
              marginTop: '10px',
            }}
          >
            {passwordRules.map((r) => (
              <div
                key={r.label}
                style={{
                  display: 'flex',
                  gap: '6px',
                  alignItems: 'center',
                  fontSize: '11px',
                  color: r.ok ? 'var(--status-completed-fg)' : 'var(--text-secondary)',
                  transition: 'color 0.2s',
                }}
              >
                <span>{r.ok ? '✓' : '○'}</span>
                {r.label}
              </div>
            ))}
          </div>
        )}
      </div>

      {error && (
        <div className="alert-error anim-fade-up">{error}</div>
      )}

      <div className="anim-fade-up-5">
        <button
          type="submit"
          disabled={loading}
          className="btn btn-primary"
          style={{ width: '100%' }}
        >
          {loading ? (
            <>
              <span className="spinner" />
              Creating account…
            </>
          ) : (
            'Create account'
          )}
        </button>
      </div>
    </form>
  )
}

export default function RegisterPage() {
  return (
    <div className="min-h-screen flex auth-texture" style={{ background: 'var(--bg-base)' }}>
      {/* Left — branding */}
      <div className="hidden lg:flex auth-brand-panel w-[42%] flex-col">
        <div className="anim-fade-up">
          <div className="app-logo mb-10">
            <span className="app-logo-text">
              <span className="app-logo-accent">Onco</span>Research
            </span>
          </div>

          <h1
            className="display mb-5"
            style={{ fontSize: '38px', lineHeight: 1.2 }}
          >
            Join the platform
          </h1>

          <p style={{ color: 'var(--text-secondary)', fontSize: '13px', lineHeight: 1.8, maxWidth: '340px' }}>
            Join workspaces, collaborate with your team, and contribute
            to research — all within a security-first environment built
            for clinical data.
          </p>
        </div>

        <div className="anim-fade-up-3">
          <div style={{ borderTop: '1px solid var(--border)', paddingTop: '28px' }}>
            <p className="label" style={{ marginBottom: '14px' }}>Security features</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {[
                'Field-level AES encryption for all PII',
                'JWT access tokens — 15 min expiry',
                'Append-only audit log',
                'Account lockout after 5 failed attempts',
              ].map((item) => (
                <div key={item} style={{ display: 'flex', gap: '10px', alignItems: 'flex-start' }}>
                  <span style={{ color: 'var(--accent)', fontSize: '11px', flexShrink: 0, marginTop: '1px' }}>▸</span>
                  <span style={{ color: 'var(--text-secondary)', fontSize: '12px' }}>{item}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Right — form */}
      <div
        className="flex-1 flex items-center justify-center px-8 py-12"
        style={{ minWidth: 0 }}
      >
        <div className="w-full" style={{ maxWidth: '380px' }}>
          {/* Mobile logo */}
          <div className="lg:hidden app-logo mb-8 anim-fade-up">
            <span className="app-logo-text">
              <span className="app-logo-accent">Onco</span>Research
            </span>
          </div>

          <div className="anim-fade-up-1" style={{ marginBottom: '32px' }}>
            <h2 className="display" style={{ fontSize: '28px', marginBottom: '6px' }}>
              Create account
            </h2>
            <p style={{ color: 'var(--text-secondary)', fontSize: '12px' }}>
              All fields required
            </p>
          </div>

          <Suspense fallback={null}>
            <RegisterForm />
          </Suspense>

          <div style={{ marginTop: '24px', textAlign: 'center' }}>
            <p style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
              Already have an account?{' '}
              <Link href="/login" style={{ color: 'var(--accent)', textDecoration: 'none' }}>
                Sign in
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
