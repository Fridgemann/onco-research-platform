'use client'

import type { AnalysisJob } from '@/lib/types'
import ErrorBoundary from '@/components/ErrorBoundary'
import KMCurveChart from './KMCurveChart'
import DescriptiveStatsTable from './DescriptiveStatsTable'
import RegressionResult from './RegressionResult'
import LogisticRegressionResult from './LogisticRegressionResult'

type Meta = { total_rows: number; used_rows: number; dropped_rows: number }

function DroppedRowsWarning({ meta }: { meta: Meta | null }) {
  if (!meta || meta.dropped_rows === 0) return null
  return (
    <p style={{ fontSize: '11px', color: '#c8a44a', marginBottom: '14px' }}>
      ⚠ {meta.dropped_rows} rows excluded due to missing values in selected columns
      ({meta.used_rows} of {meta.total_rows} used).
    </p>
  )
}

function stripMeta(result: Record<string, unknown>): Record<string, unknown> {
  const { _meta: _, ...rest } = result
  return rest
}

function ResultPanelInner({ job }: { job: AnalysisJob }) {
  if (!job.result) return null

  const result = job.result as Record<string, unknown>
  const meta = (result._meta as Meta) ?? null
  const clean = stripMeta(result)
  const cleanJob = { ...job, result: clean }

  return (
    <>
      <DroppedRowsWarning meta={meta} />
      {(() => {
        switch (job.job_type) {
          case 'kaplan_meier':
            return <KMCurveChart data={clean as Parameters<typeof KMCurveChart>[0]['data']} />
          case 'descriptive_stats':
            return <DescriptiveStatsTable data={clean as Parameters<typeof DescriptiveStatsTable>[0]['data']} />
          case 'regression':
            return <RegressionResult data={cleanJob.result as Parameters<typeof RegressionResult>[0]['data']} />
          case 'logistic_regression':
            return <LogisticRegressionResult data={cleanJob.result as Parameters<typeof LogisticRegressionResult>[0]['data']} />
          default:
            return (
              <pre style={{ fontSize: '11px', color: '#b8a99a', fontFamily: 'var(--font-mono)', overflowX: 'auto' }}>
                {JSON.stringify(clean, null, 2)}
              </pre>
            )
        }
      })()}
    </>
  )
}

export default function ResultPanel({ job }: { job: AnalysisJob }) {
  return (
    <ErrorBoundary>
      <ResultPanelInner job={job} />
    </ErrorBoundary>
  )
}
