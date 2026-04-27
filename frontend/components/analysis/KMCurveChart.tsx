'use client'

import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ReferenceLine, ResponsiveContainer,
} from 'recharts'

type GroupData = {
  timeline: number[]
  survival_probability: number[]
  median_survival: number
}

type KMData = Record<string, GroupData>

const GROUP_COLORS = ['#c88828', '#4a8fc1', '#c15f4a', '#4ac17b', '#9b59b6']

function survivalAt(group: GroupData, t: number): number {
  let prob = 1.0
  for (let i = 0; i < group.timeline.length; i++) {
    if (group.timeline[i] <= t) prob = group.survival_probability[i]
    else break;
  }
  return prob
}

function transformKMData(data: KMData): Record<string, number>[] {
  const allTimes = Array.from(
    new Set(Object.values(data).flatMap(g => g.timeline))
  ).sort((a, b) => a - b)

  return allTimes.map(t => {
    const point: Record<string, number> = { t }
    for (const [groupName, groupData] of Object.entries(data)) {
      point[groupName] = survivalAt(groupData, t)
    }
    return point
  })
}

export default function KMCurveChart({ data }: { data: KMData }) {
  const groups = Object.keys(data)
  const chartData = transformKMData(data)
  const medians = groups.map(g => ({ group: g, median: data[g].median_survival }))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
      <ResponsiveContainer width="100%" height={320}>
        <LineChart data={chartData} margin={{ left: 0, right: 24, top: 8, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e2433" />
          <XAxis
            dataKey="t"
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
            formatter={(v: number, name: string) => [`${(v * 100).toFixed(1)}%`, name]}
            labelFormatter={(t: number) => `t = ${t}`}
          />
          {groups.length > 1 && <Legend wrapperStyle={{ fontSize: '11px', fontFamily: 'monospace', color: '#b8a99a' }} />}
          {groups.map((g, i) => (
            <Line
              key={g}
              type="stepAfter"
              dataKey={g}
              stroke={GROUP_COLORS[i % GROUP_COLORS.length]}
              strokeWidth={2}
              dot={false}
              activeDot={{ r: 4 }}
            />
          ))}
          <ReferenceLine y={0.5} stroke="#2a3042" strokeDasharray="4 4" label={{ value: '50%', position: 'right', fill: '#7a8399', fontSize: 10 }} />
        </LineChart>
      </ResponsiveContainer>

      <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
        {medians.map(({ group, median }, i) => (
          <div key={group} style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px', fontFamily: 'var(--font-mono)' }}>
            <span style={{ width: '8px', height: '8px', borderRadius: '50%', background: GROUP_COLORS[i % GROUP_COLORS.length], flexShrink: 0 }} />
            <span style={{ color: '#7a8399' }}>{group}</span>
            <span style={{ color: '#e8ddd0' }}>median: {isFinite(median) ? median.toFixed(1) : '∞'}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
