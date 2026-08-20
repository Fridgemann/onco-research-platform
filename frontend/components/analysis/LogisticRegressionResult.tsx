'use client'

import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ReferenceLine, ResponsiveContainer, Cell,
} from 'recharts'
import { formatClassValue, sameClass } from '@/lib/analysis'
import type { AnalysisClassCount, AnalysisClassLabel, AnalysisTypedValue } from '@/lib/types'

type LogisticData = {
  type: 'logistic'
  target: string
  features: string[]
  intercept: number
  coefficients: Record<string, number>
  accuracy: number
  auc: number | null
  n: number
  classes: (string | number)[]
  // Recorded by the run since M4: the typed classes, the confirmed outcome,
  // and any names the researcher gave them. Optional so results stored before
  // M4 still render.
  target_classes?: AnalysisClassCount[]
  class_labels?: AnalysisClassLabel[]
  positive_class?: AnalysisTypedValue | null
  positive_class_confirmed?: boolean
}

/** The researcher's name for a class, matched on type AND value so numeric 1
 *  and string "1" are never treated as the same class. */
function labelFor(
  cls: AnalysisTypedValue,
  labels: AnalysisClassLabel[],
): string | null {
  return labels.find((l) => sameClass(l, cls))?.label ?? null
}

/** "0 — no recurrence" when a name was given, otherwise just the raw value.
 *  The raw value always stays visible so a result can be traced back to the
 *  data it came from. */
function describeClass(cls: AnalysisTypedValue, labels: AnalysisClassLabel[]): string {
  const raw = formatClassValue(cls.value, cls.value_type)
  const label = labelFor(cls, labels)
  return label ? `${raw} — ${label}` : raw
}

export default function LogisticRegressionResult({ data }: { data: LogisticData }) {
  const chartData = Object.entries(data.coefficients).map(([feature, value]) => ({ feature, value }))

  const labels = data.class_labels ?? []
  const typedClasses = data.target_classes ?? null
  // Typed classes keep 1 and "1" apart; the flat `classes` list is the
  // pre-M4 fallback and can only be shown as-is.
  const classesDisplay = typedClasses
    ? typedClasses.map((c) => describeClass(c, labels)).join(', ')
    : data.classes.join(', ')

  const outcome = data.positive_class && data.positive_class_confirmed
    ? (labelFor(data.positive_class, labels)
      ?? formatClassValue(data.positive_class.value, data.positive_class.value_type))
    : null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
        <Metric label="Accuracy" value={(data.accuracy * 100).toFixed(1) + '%'} />
        <Metric label="AUC" value={data.auc !== null ? data.auc.toFixed(3) : 'N/A'} highlight={data.auc !== null && data.auc >= 0.7} />
        <Metric label="N" value={String(data.n)} />
        <Metric label="Classes" value={classesDisplay} />
      </div>

      <div>
        <p style={{ fontSize: '10px', color: '#7a8399', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: '4px', fontFamily: 'var(--font-mono)' }}>
          Feature coefficients
        </p>
        {/* Name the outcome the directions refer to. "Raises probability" is
            meaningless without saying probability of what. */}
        <p style={{ fontSize: '11px', color: 'var(--text-secondary)', marginBottom: '12px', lineHeight: 1.6 }}>
          {outcome
            ? `Positive coefficients increase the estimated probability of ${outcome}; negative coefficients decrease it, holding other predictors constant.`
            : 'Positive coefficients increase the estimated probability of the modelled outcome; negative coefficients decrease it, holding other predictors constant.'}
          {' '}These are associations within the rows analysed, not evidence that changing a
          predictor would change the outcome.
        </p>
        <ResponsiveContainer width="100%" height={Math.min(Math.max(120, chartData.length * 40), 800)}>
          <BarChart data={chartData} layout="vertical" margin={{ left: 8, right: 24, top: 4, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e2433" horizontal={false} />
            <XAxis type="number" tick={{ fill: '#7a8399', fontSize: 10, fontFamily: 'monospace' }} axisLine={false} tickLine={false} />
            <YAxis type="category" dataKey="feature" width={120} tick={{ fill: '#c88828', fontSize: 11, fontFamily: 'monospace' }} axisLine={false} tickLine={false} />
            <Tooltip
              contentStyle={{ background: '#0f1623', border: '1px solid #1e2433', borderRadius: '6px', fontSize: '11px', fontFamily: 'monospace' }}
              labelStyle={{ color: '#c88828' }}
              itemStyle={{ color: '#b8a99a' }}
              formatter={(v) => [typeof v === 'number' ? v.toFixed(4) : v, 'coefficient']}
            />
            <ReferenceLine x={0} stroke="#2a3042" />
            <Bar dataKey="value" radius={[0, 3, 3, 0]}>
              {chartData.map((entry) => (
                <Cell key={entry.feature} fill={entry.value >= 0 ? '#98c379' : '#e06c75'} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

function Metric({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div style={{ padding: '12px 16px', background: 'rgba(255,255,255,0.03)', border: '1px solid #1e2433', borderRadius: '6px', minWidth: '100px' }}>
      <p style={{ fontSize: '10px', color: '#7a8399', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: '4px', fontFamily: 'var(--font-mono)' }}>{label}</p>
      <p style={{ fontSize: '18px', color: highlight ? '#c88828' : '#e8ddd0', fontFamily: 'var(--font-mono)' }}>{value}</p>
    </div>
  )
}
