'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { getToken, saveToken, clearToken } from '@/lib/auth'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

type AuthStatus = 'loading' | 'ok' | 'out'

export default function ProtectedLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const router = useRouter()
  const [status, setStatus] = useState<AuthStatus>('loading')

  useEffect(() => {
    // TODO(human): implement the async auth initialization here.
    // If the token is already in memory, we're good — set status to 'ok'.
    // If not (e.g. page was refreshed, memory cleared), attempt a silent
    // token refresh using the httpOnly refresh cookie. On success, save
    // the new access_token and set status 'ok'. On failure, clear the
    // token and set status 'out'.
    if (getToken()) {
      setStatus('ok');
      return;
    }
    fetch(`${API_BASE}/api/auth/refresh`, { method: 'POST', credentials:'include' })
      .then(async (res) => {
        if (res.ok) {
          const { access_token } = await res.json();
          saveToken(access_token);
          setStatus('ok');
        } else {
          clearToken()
          setStatus('out');
        }
      })
      .catch(() => { clearToken(); setStatus('out'); })
  }, [])

  useEffect(() => {
    if (status === 'out') router.replace('/login')
  }, [status, router])

  if (status !== 'ok') return null

  return <>{children}</>
}
