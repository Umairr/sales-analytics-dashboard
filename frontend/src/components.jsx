import { Area, AreaChart, ResponsiveContainer } from 'recharts'

export function Card({ title, subtitle, action, children, className = '' }) {
  return (
    <section className={`card ${className}`}>
      {(title || action) && (
        <header className="card-head">
          <div>
            <h2>{title}</h2>
            {subtitle && <p className="card-sub">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  )
}

export function Delta({ value, unit = '%', invert = false }) {
  if (value === null || value === undefined) return <span className="delta flat">no prior data</span>
  const good = invert ? value < 0 : value > 0
  const cls = value === 0 ? 'flat' : good ? 'up' : 'down'
  const arrow = value > 0 ? '▲' : value < 0 ? '▼' : '•'
  const label = unit === 'pp' ? `${Math.abs(value).toFixed(1)} pts` : `${Math.abs(value).toFixed(1)}%`
  return <span className={`delta ${cls}`}>{arrow} {label}</span>
}

export function Kpi({ label, value, delta, unit, invert, hint, spark, color = '#3b82f6' }) {
  return (
    <div className="kpi">
      <div className="kpi-top">
        <span className="kpi-label">{label}</span>
        {delta !== undefined && <Delta value={delta} unit={unit} invert={invert} />}
      </div>
      <span className="kpi-value">{value}</span>
      <div className="kpi-bottom">
        {hint && <span className="kpi-hint">{hint}</span>}
        {spark && spark.length > 1 && (
          <div className="spark">
            <ResponsiveContainer width="100%" height={30}>
              <AreaChart data={spark} margin={{ top: 2, right: 0, left: 0, bottom: 0 }}>
                <Area isAnimationActive={false} type="monotone" dataKey="v" stroke={color} fill={color}
                  fillOpacity={0.15} strokeWidth={1.5} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  )
}

const TONE_ICON = { positive: '↗', negative: '↘', warning: '!', neutral: 'i' }

export function Insights({ items }) {
  if (!items?.length) return null
  return (
    <ul className="insights">
      {items.map((it) => (
        <li key={it.title} className={`insight ${it.tone}`}>
          <span className="insight-icon">{TONE_ICON[it.tone] || 'i'}</span>
          <div>
            <strong>{it.title}</strong>
            <p>{it.detail}</p>
          </div>
        </li>
      ))}
    </ul>
  )
}

export function Skeleton({ height = 240 }) {
  return <div className="skeleton" style={{ height }} />
}

export function BrandDot({ color }) {
  return <span className="dot" style={{ background: color }} />
}
