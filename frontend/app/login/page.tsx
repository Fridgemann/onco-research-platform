'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { apiFetch, ApiError } from '@/lib/api'
import { saveToken } from '@/lib/auth'

export default function LoginPage() {
  const router = useRouter()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e: React.SyntheticEvent<HTMLFormElement>) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      const data = await apiFetch<{ access_token: string }>('/api/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email, password }),
      })
      saveToken(data.access_token)
      router.push('/dashboard')
    } catch (err) {
      if (err instanceof ApiError) setError(err.message)
      else setError('Something went wrong')
    } finally {
      setLoading(false)
    }
  }

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
            Precision tools<br />for cancer research
          </h1>

          <p style={{ color: 'var(--text-secondary)', fontSize: '13px', lineHeight: 1.8, maxWidth: '340px' }}>
            Upload datasets, run statistical analyses, and collaborate
            with your team — all within a security-first environment
            built for clinical researchers.
          </p>
        </div>

        <div className="anim-fade-up-3">
          <div style={{ borderTop: '1px solid var(--border)', paddingTop: '28px' }}>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '1fr 1fr',
                gap: '16px',
              }}
            >
              {[
                { label: 'Kaplan–Meier', desc: 'Survival analysis' },
                { label: 'Regression', desc: 'Linear & logistic' },
                { label: 'Descriptive', desc: 'Summary statistics' },
                { label: 'Encrypted', desc: 'Field-level AES' },
              ].map((item) => (
                <div key={item.label}>
                  <div style={{ color: 'var(--accent)', fontSize: '11px', letterSpacing: '0.06em', marginBottom: '2px' }}>
                    {item.label}
                  </div>
                  <div style={{ color: 'var(--text-secondary)', fontSize: '11px' }}>
                    {item.desc}
                  </div>
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
            <h2
              className="display"
              style={{ fontSize: '28px', marginBottom: '6px' }}
            >
              Sign in
            </h2>
            <p style={{ color: 'var(--text-secondary)', fontSize: '12px' }}>
              Access your research workspaces
            </p>
          </div>

          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '18px' }}>
            <div className="anim-fade-up-2">
              <label className="field-label" htmlFor="email">Email address</label>
              <input
                id="email"
                type="email"
                required
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="field-input"
                placeholder="researcher@institution.org"
              />
            </div>

            <div className="anim-fade-up-3">
              <label className="field-label" htmlFor="password">Password</label>
              <input
                id="password"
                type="password"
                required
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="field-input"
              />
            </div>

            {error && (
              <div className="alert-error anim-fade-up">
                {error}
              </div>
            )}

            <div className="anim-fade-up-4">
              <button
                type="submit"
                disabled={loading}
                className="btn btn-primary"
                style={{ width: '100%' }}
              >
                {loading ? (
                  <>
                    <span className="spinner" />
                    Authenticating…
                  </>
                ) : (
                  'Sign in'
                )}
              </button>
            </div>
          </form>

          <div className="anim-fade-up-5" style={{ marginTop: '24px', textAlign: 'center' }}>
            <p style={{ fontSize: '12px', color: 'var(--text-secondary)' }}>
              No account?{' '}
              <Link
                href="/register"
                style={{ color: 'var(--accent)', textDecoration: 'none' }}
              >
                Request access
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
