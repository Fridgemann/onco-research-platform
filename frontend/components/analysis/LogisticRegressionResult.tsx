'use client'

import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
  Tooltip, ReferenceLine, ResponsiveContainer, Cell,
} from 'recharts'

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
}

export default function LogisticRegressionResult({ data }: { data: LogisticData }) {
  const chartData = Object.entries(data.coefficients).map(([feature, value]) => ({ feature, value }))

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
        <Metric label="Accuracy" value={(data.accuracy * 100).toFixed(1) + '%'} />
        <Metric label="AUC" value={data.auc !== null ? data.auc.toFixed(3) : 'N/A'} highlight={data.auc !== null && data.auc >= 0.7} />
        <Metric label="N" value={String(data.n)} />
        <Metric label="Classes" value={data.classes.join(', ')} />
      </div>

      <div>
        <p style={{ fontSize: '10px', color: '#7a8399', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: '12px', fontFamily: 'var(--font-mono)' }}>
          Feature coefficients — positive raises probability, negative lowers it
        </p>
        <ResponsiveContainer width="100%" height={Math.max(120, chartData.length * 40)}>
          <BarChart data={chartData} layout="vertical" margin={{ left: 8, right: 24, top: 4, bottom: 4 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e2433" horizontal={false} />
            <XAxis type="number" tick={{ fill: '#7a8399', fontSize: 10, fontFamily: 'monospace' }} axisLine={false} tickLine={false} />
            <YAxis type="category" dataKey="feature" width={120} tick={{ fill: '#c88828', fontSize: 11, fontFamily: 'monospace' }} axisLine={false} tickLine={false} />
            <Tooltip
              contentStyle={{ background: '#0f1623', border: '1px solid #1e2433', borderRadius: '6px', fontSize: '11px', fontFamily: 'monospace' }}
              labelStyle={{ color: '#c88828' }}
              itemStyle={{ color: '#b8a99a' }}
              formatter={(v: number) => [v.toFixed(4), 'coefficient']}
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
