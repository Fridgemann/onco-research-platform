'use client'

import { useEffect, useState, use } from 'react'
import { useRouter } from 'next/navigation'
import { apiFetch } from '@/lib/api'
import type { Dataset, AnalysisJob } from '@/lib/types'

type Tab = 'datasets' | 'analysis'

export default function WorkspacePage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = use(params)
  const router = useRouter()
  const [tab, setTab] = useState<Tab>('datasets')
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [jobs, setJobs] = useState<AnalysisJob[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    async function load() {
      try {
        const [ds, js] = await Promise.all([
          apiFetch<Dataset[]>(`/api/workspaces/${id}/datasets`),
          apiFetch<AnalysisJob[]>(`/api/analysis?workspace_id=${id}`),
        ])
        setDatasets(ds)
        setJobs(js)
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : 'Failed to load')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [id])

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 px-6 py-4 flex items-center gap-4">
        <button
          onClick={() => router.push('/dashboard')}
          className="text-sm text-gray-500 hover:text-gray-900 transition-colors"
        >
          ← Dashboard
        </button>
        <h1 className="text-lg font-semibold text-gray-900">Workspace</h1>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-8">
        {/* Tabs */}
        <div className="flex gap-1 border-b border-gray-200 mb-6">
          {(['datasets', 'analysis'] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={`px-4 py-2 text-sm font-medium capitalize transition-colors border-b-2 -mb-px ${
                tab === t
                  ? 'border-blue-600 text-blue-600'
                  : 'border-transparent text-gray-500 hover:text-gray-900'
              }`}
            >
              {t}
            </button>
          ))}
        </div>

        {loading && <p className="text-sm text-gray-500">Loading…</p>}
        {error && (
          <p className="text-sm text-red-600 bg-red-50 rounded-lg px-4 py-3">{error}</p>
        )}

        {/* Datasets tab */}
        {!loading && tab === 'datasets' && (
          <div className="flex flex-col gap-3">
            {datasets.length === 0 && (
              <p className="text-sm text-gray-500">No datasets uploaded yet.</p>
            )}
            {datasets.map((ds) => (
              <div
                key={ds.id}
                className="bg-white rounded-xl border border-gray-200 px-5 py-4"
              >
                <p className="font-medium text-gray-900 text-sm">{ds.filename}</p>
                <div className="flex gap-4 mt-1 text-xs text-gray-400">
                  <span>{(ds.file_size / 1024).toFixed(1)} KB</span>
                  <span>{ds.content_type}</span>
                  <span>{new Date(ds.created_at).toLocaleDateString()}</span>
                </div>
                {ds.description && (
                  <p className="text-xs text-gray-500 mt-1">{ds.description}</p>
                )}
              </div>
            ))}
          </div>
        )}

        {/* Analysis tab */}
        {!loading && tab === 'analysis' && (
          <div className="flex flex-col gap-3">
            {jobs.length === 0 && (
              <p className="text-sm text-gray-500">No analysis jobs yet.</p>
            )}
            {jobs.map((job) => (
              <div
                key={job.id}
                className="bg-white rounded-xl border border-gray-200 px-5 py-4"
              >
                <div className="flex items-center justify-between">
                  <p className="font-medium text-gray-900 text-sm capitalize">
                    {job.job_type.replace('_', ' ')}
                  </p>
                  <StatusBadge status={job.status} />
                </div>
                <p className="text-xs text-gray-400 mt-1">
                  {new Date(job.created_at).toLocaleString()}
                </p>
                {job.error_message && (
                  <p className="text-xs text-red-500 mt-2">{job.error_message}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </main>
    </div>
  )
}

function StatusBadge({ status }: { status: AnalysisJob['status'] }) {
  const styles: Record<AnalysisJob['status'], string> = {
    pending: 'bg-yellow-50 text-yellow-700',
    running: 'bg-blue-50 text-blue-700',
    completed: 'bg-green-50 text-green-700',
    failed: 'bg-red-50 text-red-700',
  }
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${styles[status]}`}>
      {status}
    </span>
  )
}
