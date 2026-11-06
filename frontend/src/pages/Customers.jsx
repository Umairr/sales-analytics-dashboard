import {
  Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { BrandDot, Card, Skeleton } from '../components'
import { monthLabel, num, usd } from '../format'
import { useApi } from '../useApi'

const axis = { tick: { fontSize: 11, fill: 'var(--muted)' }, stroke: 'var(--line)' }
const tooltipStyle = { background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 8 }

const SEGMENT_COLORS = {
  Champions: '#10b981', Loyal: '#3b82f6', 'Potential Loyalists': '#06b6d4', 'New Customers': '#8b5cf6',
  'Need Attention': '#f59e0b', 'At Risk': '#ef4444', Hibernating: '#94a3b8',
}

function heat(v) {
  // 0% -> very light, 50%+ -> strong blue. Month 0 is always 100%.
  const a = Math.min(1, v / 50)
  return `rgba(59, 130, 246, ${0.08 + a * 0.82})`
}

export default function Customers({ ctx }) {
  const { params, brands, colorFor } = ctx
  const { data, error } = useApi({
    cohorts: ['/api/cohorts', { brand: params.brand }],
    rfm: ['/api/rfm', { brand: params.brand, end: params.end }],
    churn: ['/api/churn', { brand: params.brand }],
  }, [params.brand, params.end])

  if (error) return <div className="error">Could not load data: {error}</div>
  if (!data) return <div className="grid"><Skeleton height={360} /></div>
  const { cohorts, rfm, churn } = data
  const width = Math.max(...cohorts.map((c) => c.retention.length), 0)

  return (
    <div>
      <Card
        title="Cohort retention"
        subtitle="Customers grouped by first-purchase month. Each cell = % of that cohort who bought again N months later."
      >
        <div className="table-scroll">
          <table className="cohort">
            <thead>
              <tr>
                <th>Cohort</th><th className="r">Customers</th><th className="r">Rev / customer</th>
                {Array.from({ length: width }, (_, i) => <th key={i} className="c">M{i}</th>)}
              </tr>
            </thead>
            <tbody>
              {cohorts.map((c) => (
                <tr key={c.cohort}>
                  <td>{monthLabel(c.cohort)}</td>
                  <td className="r">{num(c.customers)}</td>
                  <td className="r">{usd(c.revenue_per_customer)}</td>
                  {Array.from({ length: width }, (_, i) => {
                    const v = c.retention[i]
                    if (v === undefined) return <td key={i} className="c empty" />
                    return (
                      <td key={i} className="c heat" style={{ background: heat(v), color: v > 30 ? '#fff' : 'var(--ink)' }}>
                        {v.toFixed(0)}%
                      </td>
                    )
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid two">
        <Card title="RFM segments" subtitle="Recency, frequency and monetary scoring. Share of customers vs share of revenue.">
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={rfm.segments} layout="vertical" margin={{ top: 4, right: 16, left: 8, bottom: 0 }}>
              <CartesianGrid stroke="var(--grid)" horizontal={false} />
              <XAxis type="number" {...axis} tickFormatter={(v) => `${v}%`} />
              <YAxis type="category" dataKey="segment" {...axis} width={130} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v, n) => [`${v}%`, n === 'share_customers' ? 'Customers' : 'Revenue']} />
              <Legend wrapperStyle={{ fontSize: 12 }} formatter={(v) => (v === 'share_customers' ? '% of customers' : '% of revenue')} />
              <Bar isAnimationActive={false} dataKey="share_customers" fill="#94a3b8" radius={[0, 3, 3, 0]} />
              <Bar isAnimationActive={false} dataKey="share_revenue" fill="#3b82f6" radius={[0, 3, 3, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card title="What to do with each segment">
          <div className="table-scroll"><table className="nowrap-num">
            <thead><tr><th>Segment</th><th className="r">Customers</th><th className="r">Revenue</th><th className="r">Last order</th><th>Action</th></tr></thead>
            <tbody>
              {rfm.segments.map((s) => (
                <tr key={s.segment}>
                  <td style={{ whiteSpace: 'nowrap' }}><span className="seg" style={{ background: SEGMENT_COLORS[s.segment] }} />{s.segment}</td>
                  <td className="r">{num(s.customers)}</td>
                  <td className="r">{usd(s.revenue)}</td>
                  <td className="r" style={{ whiteSpace: 'nowrap' }}>{s.avg_recency_days}d ago</td>
                  <td className="muted small">{s.action}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        </Card>
      </div>

      <div className="grid two-one">
        <Card title="Top customers by lifetime value">
          <div className="table-scroll"><table className="nowrap">
            <thead><tr><th>Customer</th><th>Brand</th><th>Segment</th><th className="r">Orders</th><th className="r">LTV</th><th className="r" title="Recency · Frequency · Monetary scores, 1–5">RFM</th></tr></thead>
            <tbody>
              {rfm.top_customers.map((c) => (
                <tr key={c.email}>
                  <td className="mono ellipsis" title={c.email}>{c.email.replace('@example.com', '')}</td>
                  <td><BrandDot color={colorFor[c.brand]} />{brands.find((b) => b.code === c.brand)?.name}</td>
                  <td><span className="seg" style={{ background: SEGMENT_COLORS[c.segment] }} />{c.segment}</td>
                  <td className="r">{c.orders}</td>
                  <td className="r">{usd(c.revenue)}</td>
                  <td className="r mono">{c.rfm}</td>
                </tr>
              ))}
            </tbody>
          </table></div>
        </Card>

        <Card title="Subscription churn by month">
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={churn} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="period" {...axis} tickFormatter={monthLabel} />
              <YAxis yAxisId="rate" {...axis} tickFormatter={(v) => `${v}%`} width={44} />
              <YAxis yAxisId="count" orientation="right" {...axis} width={36} />
              <Tooltip contentStyle={tooltipStyle} labelFormatter={monthLabel} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line isAnimationActive={false} yAxisId="rate" type="monotone" dataKey="churn_rate" name="Churn %" stroke="#ef4444" strokeWidth={2} dot={false} />
              <Line isAnimationActive={false} yAxisId="count" type="monotone" dataKey="new" name="New subs" stroke="#10b981" strokeWidth={2} dot={false} />
              <Line isAnimationActive={false} yAxisId="count" type="monotone" dataKey="cancelled" name="Cancelled" stroke="#94a3b8" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </Card>
      </div>
    </div>
  )
}
