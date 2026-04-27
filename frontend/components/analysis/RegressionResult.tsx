'use client'

type LinearResult = {
  type: 'linear'
  feature: string
  slope: number
  intercept: number
  r_squared: number
  p_value: number
  std_err: number
  n: number
}

type MultipleLinearResult = {
  type: 'multiple_linear'
  features: string[]
  intercept: number
  coefficients: Record<string, number>
  r_squared: number
  n: number
}

type RegressionData = LinearResult | MultipleLinearResult

export default function RegressionResult({ data }: { data: RegressionData }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
      <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
        <Metric label="R²" value={(data.r_squared * 100).toFixed(1) + '%'} />
        <Metric label="Intercept" value={data.intercept.toFixed(4)} />
        <Metric label="N" value={String(data.n)} />
        {data.type === 'linear' && (
          <>
            <Metric label="p-value" value={data.p_value < 0.001 ? '<0.001' : data.p_value.toFixed(4)} highlight={data.p_value < 0.05} />
            <Metric label="Std Err" value={data.std_err.toFixed(4)} />
          </>
        )}
      </div>

      <div>
        <p style={{ fontSize: '10px', color: '#7a8399', letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: '10px', fontFamily: 'var(--font-mono)' }}>
          Coefficients
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {data.type === 'linear' ? (
            <CoefficientRow feature={data.feature} value={data.slope} />
          ) : (
            Object.entries(data.coefficients).map(([f, v]) => (
              <CoefficientRow key={f} feature={f} value={v} />
            ))
          )}
        </div>
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

function CoefficientRow({ feature, value }: { feature: string; value: number }) {
  const positive = value >= 0
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '12px', fontSize: '12px' }}>
      <span style={{ width: '160px', color: '#c88828', fontFamily: 'var(--font-mono)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{feature}</span>
      <span style={{ color: positive ? '#98c379' : '#e06c75', fontFamily: 'var(--font-mono)', minWidth: '80px' }}>
        {positive ? '+' : ''}{value.toFixed(4)}
      </span>
    </div>
  )
}
