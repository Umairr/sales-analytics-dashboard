import {
  Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'
import { BrandDot, Card, Delta, Skeleton } from '../components'
import { compact, monthLabel, num, pct, usd } from '../format'
import { useApi } from '../useApi'

const axis = { tick: { fontSize: 11, fill: 'var(--muted)' }, stroke: 'var(--line)' }
const tooltipStyle = { background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 8 }

export default function Brands({ ctx }) {
  const { params, colorFor } = ctx
  const { data, error } = useApi({
    rows: ['/api/brand-comparison', { start: params.start, end: params.end }],
    monthly: ['/api/revenue', { bucket: 'month' }],
  }, [params.start, params.end])

  if (error) return <div className="error">Could not load data: {error}</div>
  if (!data) return <div className="grid"><Skeleton height={300} /></div>
  const { rows, monthly } = data
  const maxRev = Math.max(...rows.map((r) => r.revenue), 1)

  return (
    <div>
      <div className="brand-cards">
        {rows.map((r) => (
          <div className="brand-card" key={r.code} style={{ borderTopColor: colorFor[r.code] }}>
            <div className="brand-card-head">
              <span><BrandDot color={colorFor[r.code]} />{r.name}</span>
              <span className="ccy-tag">{r.currency}</span>
            </div>
            <div className="brand-card-value">{usd(r.revenue)}</div>
            <Delta value={r.growth_pct} />
            <dl>
              <div><dt>Share</dt><dd>{pct(r.share)}</dd></div>
              <div><dt>AOV</dt><dd>{usd(r.aov, 2)}</dd></div>
              <div><dt>Repeat</dt><dd>{pct(r.repeat_rate)}</dd></div>
              <div><dt>MRR</dt><dd>{usd(r.mrr)}</dd></div>
            </dl>
          </div>
        ))}
      </div>

      <Card title="Brand benchmark" subtitle="Selected range, all amounts converted to USD">
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Brand</th><th>Revenue</th><th className="r">Growth</th><th className="r">Orders</th>
                <th className="r">AOV</th><th className="r">Customers</th><th className="r">Repeat</th>
                <th className="r">Refunds</th><th className="r">Active subs</th><th className="r">Churn</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.code}>
                  <td><BrandDot color={colorFor[r.code]} />{r.name}</td>
                  <td className="bar-cell">
                    <div className="inline-bar"><span style={{ width: `${(r.revenue / maxRev) * 100}%`, background: colorFor[r.code] }} /></div>
                    <span className="r">{usd(r.revenue)}</span>
                  </td>
                  <td className="r"><Delta value={r.growth_pct} /></td>
                  <td className="r">{num(r.orders)}</td>
                  <td className="r">{usd(r.aov, 2)}</td>
                  <td className="r">{num(r.customers)}</td>
                  <td className="r">{pct(r.repeat_rate)}</td>
                  <td className={`r ${r.refund_rate >= 6 ? 'warn' : ''}`}>{pct(r.refund_rate)}</td>
                  <td className="r">{num(r.active_subscriptions)}</td>
                  <td className="r">{pct(r.churn_rate, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="grid three">
        <Card title="Revenue share">
          <ResponsiveContainer width="100%" height={260}>
            <PieChart>
              <Pie isAnimationActive={false} data={rows} dataKey="revenue" nameKey="name" innerRadius={60} outerRadius={95} paddingAngle={2}>
                {rows.map((r) => <Cell key={r.code} fill={colorFor[r.code]} />)}
              </Pie>
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => usd(v)} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
            </PieChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Monthly revenue by brand" subtitle="Full history, independent of the date filter" className="span-2">
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={monthly} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="period" {...axis} tickFormatter={monthLabel} />
              <YAxis {...axis} tickFormatter={(v) => `$${compact(v)}`} width={56} />
              <Tooltip contentStyle={tooltipStyle} labelFormatter={monthLabel}
                formatter={(v, n) => [usd(v), rows.find((r) => r.code === n)?.name || n]} />
              <Legend wrapperStyle={{ fontSize: 12 }} formatter={(v) => rows.find((r) => r.code === v)?.name || v} />
              {rows.map((r) => (
                <Line isAnimationActive={false} key={r.code} type="monotone" dataKey={r.code} stroke={colorFor[r.code]} strokeWidth={2.5} dot={false} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <div className="grid two">
        <Card title="Average order value">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="name" {...axis} />
              <YAxis {...axis} tickFormatter={(v) => `$${v}`} width={48} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => [usd(v, 2), 'AOV']} />
              <Bar isAnimationActive={false} dataKey="aov" radius={[4, 4, 0, 0]}>
                {rows.map((r) => <Cell key={r.code} fill={colorFor[r.code]} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>
        <Card title="Refund rate">
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={rows} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="name" {...axis} />
              <YAxis {...axis} tickFormatter={(v) => `${v}%`} width={40} />
              <Tooltip contentStyle={tooltipStyle} formatter={(v) => [`${v}%`, 'Refund rate']} />
              <Bar isAnimationActive={false} dataKey="refund_rate" radius={[4, 4, 0, 0]}>
                {rows.map((r) => <Cell key={r.code} fill={r.refund_rate >= 6 ? '#ef4444' : colorFor[r.code]} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>
    </div>
  )
}
