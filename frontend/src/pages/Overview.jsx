import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, ComposedChart, Legend, Line, ResponsiveContainer,
  Tooltip, XAxis, YAxis,
} from 'recharts'
import { BrandDot, Card, Insights, Kpi, Skeleton } from '../components'
import { compact, monthLabel, num, pct, usd } from '../format'
import { useApi } from '../useApi'

const axis = { tick: { fontSize: 11, fill: 'var(--muted)' }, stroke: 'var(--line)' }

export default function Overview({ ctx }) {
  const { params, prevParams, bucket, setBucket, brands, colorFor, visibleBrands } = ctx
  const { data, loading, error } = useApi({
    overview: ['/api/overview', params],
    insights: ['/api/insights', params],
    revenue: ['/api/revenue', { ...params, bucket }],
    previous: ['/api/revenue', { ...prevParams, bucket }],
    daily: ['/api/revenue', { ...params, bucket: 'day' }],
    forecast: ['/api/forecast', { brand: params.brand, horizon: 3 }],
    weekday: ['/api/weekday', params],
    products: ['/api/top-products', { ...params, limit: 8 }],
  }, [JSON.stringify(params), bucket])

  if (error) return <div className="error">Could not load data: {error}</div>
  if (!data) return <div className="grid"><Skeleton height={120} /><Skeleton height={320} /></div>

  const { overview, insights, revenue, previous, daily, forecast, weekday, products } = data
  const c = overview.current
  const d = overview.delta_pct
  const sparkRev = daily.map((p) => ({ v: p.total }))
  const sparkOrd = daily.map((p) => ({ v: p.orders }))
  const merged = revenue.map((p, i) => ({ ...p, previous: previous[i]?.total ?? null }))
  const fcData = [
    ...forecast.history.map((h) => ({ period: h.period, actual: h.actual, trend: h.trend })),
    ...forecast.forecast.map((f) => ({ period: f.period, forecast: f.forecast, band: [f.lower, f.upper] })),
  ]
  if (forecast.history.length && forecast.forecast.length) {
    const last = fcData[forecast.history.length - 1]
    last.forecast = last.actual
    last.band = [last.actual, last.actual]
  }
  const maxProduct = Math.max(...products.map((p) => p.revenue), 1)
  const tickFmt = bucket === 'month' ? monthLabel : (v) => v

  return (
    <div className={loading ? 'dim' : ''}>
      <div className="kpis">
        <Kpi label="Revenue" value={usd(c.revenue)} delta={d.revenue} spark={sparkRev} hint={`${usd(c.refunded)} refunded`} />
        <Kpi label="Paid orders" value={num(c.orders)} delta={d.orders} spark={sparkOrd} color="#64748b" />
        <Kpi label="Avg order value" value={usd(c.aov, 2)} delta={d.aov} />
        <Kpi label="Customers" value={num(c.customers)} delta={d.customers} hint={`${pct(c.repeat_rate)} repeat buyers`} />
        <Kpi label="Repeat rate" value={pct(c.repeat_rate)} delta={d.repeat_rate} unit="pp" />
        <Kpi label="Active subscriptions" value={num(c.active_subscriptions)} delta={d.active_subscriptions} />
        <Kpi label="MRR" value={usd(c.mrr)} delta={d.mrr} hint="monthly recurring" />
        <Kpi label="Churn (latest month)" value={pct(c.churn_rate, 2)} delta={d.churn_rate} unit="pp" invert />
      </div>

      <div className="grid two-one">
        <Card
          title="Revenue by brand"
          subtitle={overview.previous_range ? 'Dashed line = previous period total' : 'No earlier data to compare'}
          action={
            <div className="segmented small">
              {['day', 'week', 'month'].map((b) => (
                <button key={b} className={bucket === b ? 'on' : ''} onClick={() => setBucket(b)}>{b}</button>
              ))}
            </div>
          }
        >
          <ResponsiveContainer width="100%" height={320}>
            <ComposedChart data={merged} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="period" {...axis} tickMargin={6} minTickGap={24} tickFormatter={tickFmt} />
              <YAxis {...axis} tickFormatter={(v) => `$${compact(v)}`} width={56} />
              <Tooltip
                contentStyle={{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 8 }}
                labelFormatter={tickFmt}
                formatter={(v, n) => [usd(v), n === 'previous' ? 'Previous period' : brands.find((b) => b.code === n)?.name || n]}
              />
              <Legend wrapperStyle={{ fontSize: 12 }}
                formatter={(v) => (v === 'previous' ? 'Previous period' : brands.find((b) => b.code === v)?.name || v)} />
              {visibleBrands.map((b) => (
                <Area isAnimationActive={false} key={b.code} type="monotone" dataKey={b.code} stackId="1"
                  stroke={colorFor[b.code]} fill={colorFor[b.code]} fillOpacity={0.2} strokeWidth={2} />
              ))}
              {overview.previous_range && (
                <Line isAnimationActive={false} type="monotone" dataKey="previous" stroke="var(--muted)"
                  strokeDasharray="5 4" strokeWidth={1.5} dot={false} />
              )}
            </ComposedChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Automated insights" subtitle="Generated from the selected range">
          <Insights items={insights} />
        </Card>
      </div>

      <div className="grid three">
        <Card
          title="Revenue forecast"
          subtitle={`Holt's trend model · next 3 months · avg error ${forecast.mape}% · ${forecast.monthly_growth_pct >= 0 ? '+' : ''}${forecast.monthly_growth_pct}% / month`}
          className="span-2"
        >
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={fcData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="period" {...axis} tickFormatter={monthLabel} />
              <YAxis {...axis} tickFormatter={(v) => `$${compact(v)}`} width={56} />
              <Tooltip
                contentStyle={{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 8 }}
                labelFormatter={monthLabel}
                formatter={(v, n) => [Array.isArray(v) ? `${usd(v[0])} – ${usd(v[1])}` : usd(v),
                  { actual: 'Actual', trend: 'Model fit', forecast: 'Forecast', band: '95% range' }[n] || n]}
              />
              <Legend wrapperStyle={{ fontSize: 12 }}
                formatter={(v) => ({ actual: 'Actual', trend: 'Model fit', forecast: 'Forecast', band: '95% range' }[v] || v)} />
              <Area isAnimationActive={false} dataKey="band" stroke="none" fill="#8b5cf6" fillOpacity={0.15} />
              <Bar isAnimationActive={false} dataKey="actual" fill="#3b82f6" radius={[3, 3, 0, 0]} />
              <Line isAnimationActive={false} dataKey="trend" stroke="var(--muted)" strokeDasharray="4 4" dot={false} />
              <Line isAnimationActive={false} dataKey="forecast" stroke="#8b5cf6" strokeWidth={2.5} dot={{ r: 3 }} />
            </ComposedChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Sales by weekday" subtitle="Average revenue per day">
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={weekday} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="day" {...axis} />
              <YAxis {...axis} tickFormatter={(v) => `$${compact(v)}`} width={48} />
              <Tooltip contentStyle={{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 8 }}
                formatter={(v, n) => [n === 'avg_revenue' ? usd(v) : v, n === 'avg_revenue' ? 'Avg revenue' : 'Avg orders']} />
              <Bar isAnimationActive={false} dataKey="avg_revenue" fill="#10b981" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <div className="grid two">
        <Card title="Top products">
          <table>
            <thead><tr><th>Product</th><th>Brand</th><th className="r">Units</th><th>Revenue</th></tr></thead>
            <tbody>
              {products.map((p) => (
                <tr key={`${p.brand}-${p.product}`}>
                  <td>{p.product}</td>
                  <td><BrandDot color={colorFor[p.brand]} />{brands.find((b) => b.code === p.brand)?.name}</td>
                  <td className="r">{num(p.units)}</td>
                  <td className="bar-cell">
                    <div className="inline-bar"><span style={{ width: `${(p.revenue / maxProduct) * 100}%`, background: colorFor[p.brand] }} /></div>
                    <span className="r">{usd(p.revenue)}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <Card title="Orders per period">
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={merged} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="var(--grid)" vertical={false} />
              <XAxis dataKey="period" {...axis} tickMargin={6} minTickGap={24} tickFormatter={tickFmt} />
              <YAxis {...axis} width={44} />
              <Tooltip contentStyle={{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 8 }}
                labelFormatter={tickFmt} formatter={(v) => [num(v), 'Orders']} />
              <Area isAnimationActive={false} type="monotone" dataKey="orders" stroke="#64748b" fill="#64748b" fillOpacity={0.18} strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </Card>
      </div>
    </div>
  )
}
