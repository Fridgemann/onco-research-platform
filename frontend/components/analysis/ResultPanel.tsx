'use client'

import type { AnalysisJob } from '@/lib/types'
import KMCurveChart from './KMCurveChart'
import DescriptiveStatsTable from './DescriptiveStatsTable'
import RegressionResult from './RegressionResult'
import LogisticRegressionResult from './LogisticRegressionResult'

export default function ResultPanel({ job }: { job: AnalysisJob }) {
  if (!job.result) return null

  switch (job.job_type) {
    case 'kaplan_meier':
      return <KMCurveChart data={job.result as Parameters<typeof KMCurveChart>[0]['data']} />
    case 'descriptive_stats':
      return <DescriptiveStatsTable data={job.result as Parameters<typeof DescriptiveStatsTable>[0]['data']} />
    case 'regression':
      return <RegressionResult data={job.result as Parameters<typeof RegressionResult>[0]['data']} />
    case 'logistic_regression':
      return <LogisticRegressionResult data={job.result as Parameters<typeof LogisticRegressionResult>[0]['data']} />
    default:
      return (
        <pre style={{ fontSize: '11px', color: '#b8a99a', fontFamily: 'var(--font-mono)', overflowX: 'auto' }}>
          {JSON.stringify(job.result, null, 2)}
        </pre>
      )
  }
}
