'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { getToken, saveToken, clearToken } from '@/lib/auth'
import { apiFetch } from '@/lib/api'
import { UserContext } from '@/lib/user-context'
import type { User } from '@/lib/types'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

type AuthStatus = 'loading' | 'ok' | 'out'

export default function ProtectedLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const router = useRouter()
  const [status, setStatus] = useState<AuthStatus>('loading')
  const [user, setUser] = useState<User | null>(null)

  useEffect(() => {
    async function init() {
      try {
        if (!getToken()) {
          const res = await fetch(`${API_BASE}/api/auth/refresh`, {
            method: 'POST',
            credentials: 'include',
          })
          if (!res.ok) { clearToken(); setStatus('out'); return }
          const { access_token } = await res.json()
          saveToken(access_token)
        }

        const me = await apiFetch<User>('/api/auth/me')
        if (!me.is_active) { clearToken(); setStatus('out'); return }
        setUser(me)
        setStatus('ok')
      } catch {
        clearToken()
        setStatus('out')
      }
    }
    init()
  }, [])

  useEffect(() => {
    if (status === 'out') router.replace('/login')
  }, [status, router])

  if (status !== 'ok' || !user) return null

  return (
    <UserContext.Provider value={{ user }}>
      {children}
    </UserContext.Provider>
  )
}
