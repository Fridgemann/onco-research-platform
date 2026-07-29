'use client'

import {
  Line, XAxis, YAxis, CartesianGrid, Area, ComposedChart,
  Tooltip, Legend, ReferenceLine, ResponsiveContainer, Scatter,
} from 'recharts'
import type { KMGroup } from '@/lib/types'

// Displays backend-computed survival curves. Every value plotted here comes
// from the backend result — the step lookup below is plotting only (choosing
// which already-computed value applies at a given x), never recalculation.

const GROUP_COLORS = ['#c88828', '#4a8fc1', '#c15f4a', '#4ac17b', '#9b59b6']

type Series = {
  key: string
  color: string
  group: KMGroup
}

/** Value of a step function at time t: the last point with time <= t. */
function stepValueAt(times: number[], values: number[], t: number): number | null {
  let v: number | null = null
  for (let i = 0; i < times.length; i++) {
    if (times[i] <= t) v = values[i]
    else break
  }
  return v
}

export default function KMCurveChart({
  groups,
  showCI = true,
}: {
  groups: KMGroup[]
  showCI?: boolean
}) {
  const series: Series[] = groups.map((g, i) => ({
    key: String(g.label),
    color: GROUP_COLORS[i % GROUP_COLORS.length],
    group: g,
  }))

  const allTimes = Array.from(
    new Set(series.flatMap((s) => s.group.curve.timeline)),
  ).sort((a, b) => a - b)

  const chartData = allTimes.map((t) => {
    const point: Record<string, number | null> = { t }
    for (const s of series) {
      const c = s.group.curve
      point[s.key] = stepValueAt(c.timeline, c.survival_probability, t)
      if (showCI) {
        const lo = stepValueAt(c.timeline, c.ci_lower, t)
        const hi = stepValueAt(c.timeline, c.ci_upper, t)
        // Recharts renders a band from an [low, high] tuple; store as two keys.
        point[`${s.key}__ciLow`] = lo
        point[`${s.key}__ciRange`] = lo !== null && hi !== null ? hi - lo : null
      }
    }
    return point
  })

  // Censor marks come from the backend with their own survival coordinates.
  const censorPoints = series.flatMap((s) =>
    s.group.curve.censor_marks.map((m) => ({
      t: m.time,
      [`${s.key}__censor`]: m.survival_probability,
      count: m.count,
    })),
  )

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
      <ResponsiveContainer width="100%" height={340}>
        <ComposedChart data={chartData} margin={{ left: 0, right: 24, top: 8, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e2433" />
          <XAxis
            dataKey="t"
            type="number"
            domain={[0, 'dataMax']}
            tick={{ fill: '#7a8399', fontSize: 10, fontFamily: 'monospace' }}
            axisLine={{ stroke: '#1e2433' }}
            tickLine={false}
            label={{ value: 'Time', position: 'insideBottom', offset: -2, fill: '#7a8399', fontSize: 10 }}
          />
          <YAxis
            domain={[0, 1]}
            tickFormatter={(v: number) => `${(v * 100).toFixed(0)}%`}
            tick={{ fill: '#7a8399', fontSize: 10, fontFamily: 'monospace' }}
            axisLine={{ stroke: '#1e2433' }}
            tickLine={false}
          />
          <Tooltip
            contentStyle={{ background: '#0f1623', border: '1px solid #1e2433', borderRadius: '6px', fontSize: '11px', fontFamily: 'monospace' }}
            labelStyle={{ color: '#7a8399' }}
            itemStyle={{ color: '#b8a99a' }}
            formatter={(v, name) => {
              const label = String(name)
              if (label.includes('__ci')) return []
              return [typeof v === 'number' ? `${(v * 100).toFixed(1)}%` : '—', label]
            }}
            labelFormatter={(t) => `t = ${t}`}
          />
          {series.length > 1 && (
            <Legend wrapperStyle={{ fontSize: '11px', fontFamily: 'monospace', color: '#b8a99a' }} />
          )}

          {/* Pointwise 95% CI band (stacked low + range areas) */}
          {showCI && series.map((s) => (
            <Area
              key={`${s.key}-ci`}
              type="stepAfter"
              dataKey={`${s.key}__ciLow`}
              stackId={`ci-${s.key}`}
              stroke="none"
              fill="none"
              isAnimationActive={false}
              legendType="none"
            />
          ))}
          {showCI && series.map((s) => (
            <Area
              key={`${s.key}-ci-range`}
              type="stepAfter"
              dataKey={`${s.key}__ciRange`}
              stackId={`ci-${s.key}`}
              stroke="none"
              fill={s.color}
              fillOpacity={0.13}
              isAnimationActive={false}
              legendType="none"
            />
          ))}

          {series.map((s) => (
            <Line
              key={s.key}
              type="stepAfter"
              dataKey={s.key}
              stroke={s.color}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
              connectNulls
              isAnimationActive={false}
            />
          ))}

          {/* Censor ticks at backend-supplied coordinates */}
          {series.map((s) => (
            <Scatter
              key={`${s.key}-censor`}
              data={censorPoints.filter((p) => `${s.key}__censor` in p)}
              dataKey={`${s.key}__censor`}
              fill={s.color}
              shape="cross"
              legendType="none"
              isAnimationActive={false}
            />
          ))}

          <ReferenceLine y={0.5} stroke="#2a3042" strokeDasharray="4 4" label={{ value: '50%', position: 'right', fill: '#7a8399', fontSize: 10 }} />
        </ComposedChart>
      </ResponsiveContainer>

      <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap', alignItems: 'center' }}>
        {series.map((s) => {
          const m = s.group.curve.median_survival
          return (
            <div key={s.key} style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px', fontFamily: 'var(--font-mono)' }}>
              <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: s.color, flexShrink: 0 }} />
              <span style={{ color: '#7a8399' }}>{s.key}</span>
              <span style={{ color: '#e8ddd0' }}>
                median: {m === null ? 'not reached' : m.toFixed(1)}
              </span>
            </div>
          )
        })}
        <span style={{ fontSize: '10px', color: 'var(--text-secondary)', opacity: 0.8 }}>
          ✚ censored · shaded band = pointwise 95% CI
        </span>
      </div>
    </div>
  )
}
