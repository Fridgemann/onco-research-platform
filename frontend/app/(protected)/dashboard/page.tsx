'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { apiFetch } from '@/lib/api'
import { clearToken } from '@/lib/auth'
import type { Workspace } from '@/lib/types'

export default function DashboardPage() {
  const router = useRouter()
  const [workspaces, setWorkspaces] = useState<Workspace[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    apiFetch<Workspace[]>('/api/workspaces')
      .then(setWorkspaces)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false))
  }, [])

  function handleLogout() {
    clearToken()
    router.replace('/login')
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-gray-900">Oncology Research Platform</h1>
        <button
          onClick={handleLogout}
          className="text-sm text-gray-500 hover:text-gray-900 transition-colors"
        >
          Sign out
        </button>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-10">
        <h2 className="text-xl font-semibold text-gray-900 mb-6">Your Workspaces</h2>

        {loading && (
          <p className="text-sm text-gray-500">Loading workspaces…</p>
        )}

        {error && (
          <p className="text-sm text-red-600 bg-red-50 rounded-lg px-4 py-3">{error}</p>
        )}

        {!loading && !error && workspaces.length === 0 && (
          <p className="text-sm text-gray-500">No workspaces yet.</p>
        )}

        <div className="grid gap-4">
          {workspaces.map((ws) => (
            <button
              key={ws.id}
              onClick={() => router.push(`/workspaces/${ws.id}`)}
              className="w-full text-left bg-white rounded-xl border border-gray-200 px-5 py-4 hover:border-blue-300 hover:shadow-sm transition-all"
            >
              <p className="font-medium text-gray-900">{ws.name}</p>
              {ws.description && (
                <p className="text-sm text-gray-500 mt-1">{ws.description}</p>
              )}
            </button>
          ))}
        </div>
      </main>
    </div>
  )
}
