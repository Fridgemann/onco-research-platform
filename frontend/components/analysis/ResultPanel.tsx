'use client'

import type { AnalysisJob } from '@/lib/types'
import ErrorBoundary from '@/components/ErrorBoundary'
import KMResult from './KMResult'
import DescriptiveStatsTable from './DescriptiveStatsTable'
import RegressionResult from './RegressionResult'
import LogisticRegressionResult from './LogisticRegressionResult'
import ProcessingReport, { type ColumnProcessing } from './ProcessingReport'

type Meta = { total_rows: number; used_rows: number; dropped_rows: number }
type DescriptiveColumnStats = { missing?: number; non_numeric?: number }

function DroppedRowsWarning({ meta }: { meta: Meta | null }) {
  if (!meta || meta.dropped_rows === 0) return null
  return (
    <p style={{ fontSize: '11px', color: '#c8a44a', marginBottom: '14px' }}>
      ⚠ {meta.dropped_rows} rows excluded due to missing values in selected columns
      ({meta.used_rows} of {meta.total_rows} used).
    </p>
  )
}

function DescriptiveStatsDroppedRowsWarning({
  meta,
  columns,
}: {
  meta: Meta | null
  columns: Record<string, DescriptiveColumnStats>
}) {
  if (!meta || meta.dropped_rows === 0) return null

  const colNames = Object.keys(columns)
  // Exact missing/non-numeric split is only well-defined for a single
  // selected column — with multiple columns a row can be excluded by more
  // than one column at once, so a per-column sum would double-count.
  const single = colNames.length === 1 ? columns[colNames[0]] : null

  return (
    <p style={{ fontSize: '11px', color: '#c8a44a', marginBottom: '14px' }}>
      ⚠ {meta.used_rows} of {meta.total_rows} rows used. {meta.dropped_rows} excluded
      {single
        ? `: ${single.missing ?? 0} missing, ${single.non_numeric ?? 0} non-numeric/coded.`
        : ' due to missing or non-numeric/coded values (see per-column breakdown below).'}
    </p>
  )
}

function stripInternalKeys(result: Record<string, unknown>): Record<string, unknown> {
  // Remove keys the analysis components should not treat as data. _meta and
  // processing are cross-cutting reporting fields; leaving `processing` in
  // would, for example, make KMCurveChart render it as a survival group.
  const rest = { ...result }
  delete rest._meta
  delete rest.processing
  return rest
}

function ResultPanelInner({ job }: { job: AnalysisJob }) {
  if (!job.result) return null

  const result = job.result as Record<string, unknown>
  const meta = (result._meta as Meta) ?? null
  const processing = (result.processing as Record<string, ColumnProcessing>) ?? null
  const clean = stripInternalKeys(result)
  const cleanJob = { ...job, result: clean }

  // descriptive_stats has its own richer per-column reporting inside its
  // table; the other three analyses share the Milestone 2 ProcessingReport.
  const preludeReport = job.job_type === 'descriptive_stats'
    ? <DescriptiveStatsDroppedRowsWarning meta={meta} columns={clean as Record<string, DescriptiveColumnStats>} />
    : processing
      ? <ProcessingReport meta={meta} processing={processing} />
      : <DroppedRowsWarning meta={meta} />

  return (
    <>
      {preludeReport}
      {(() => {
        switch (job.job_type) {
          case 'kaplan_meier':
            // KM returns a structured result (groups list + comparison +
            // reproducibility), so it renders from the full result rather
            // than the metadata-stripped dict.
            return <KMResult data={result as unknown as Parameters<typeof KMResult>[0]['data']} />
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
