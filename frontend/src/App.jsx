import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { csvUrl, get, post } from './api'

const BRAND_COLORS = ['#2563eb', '#d97706', '#059669', '#7c3aed', '#db2777']
const usd = (n, digits = 0) =>
  new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: digits }).format(n || 0)
const num = (n) => new Intl.NumberFormat('en-US').format(n || 0)
const compact = (n) => new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(n)

function shift(dateStr, days) {
  const d = new Date(`${dateStr}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

const PRESETS = [
  { id: '30d', label: 'Last 30 days', range: (max) => [shift(max, -29), max], bucket: 'day' },
  { id: '90d', label: 'Last 90 days', range: (max) => [shift(max, -89), max], bucket: 'week' },
  { id: 'ytd', label: 'Year to date', range: (max) => [`${max.slice(0, 4)}-01-01`, max], bucket: 'month' },
  { id: '12m', label: 'Last 12 months', range: (max, min) => [min, max], bucket: 'month' },
]

function Kpi({ label, value, hint }) {
  return (
    <div className="kpi">
      <span className="kpi-label">{label}</span>
      <span className="kpi-value">{value}</span>
      {hint && <span className="kpi-hint">{hint}</span>}
    </div>
  )
}

function Card({ title, children, action }) {
  return (
    <section className="card">
      <header className="card-head">
        <h2>{title}</h2>
        {action}
      </header>
      {children}
    </section>
  )
}

export default function App() {
  const [meta, setMeta] = useState(null)
  const [brands, setBrands] = useState([])
  const [selected, setSelected] = useState([])
  const [preset, setPreset] = useState('12m')
  const [bucket, setBucket] = useState('month')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [etlMsg, setEtlMsg] = useState('')

  useEffect(() => {
    Promise.all([get('/api/meta'), get('/api/brands')])
      .then(([m, b]) => { setMeta(m); setBrands(b) })
      .catch((e) => { setError(e.message); setLoading(false) })
  }, [])

  const colorFor = useMemo(() => {
    const map = {}
    brands.forEach((b, i) => { map[b.code] = BRAND_COLORS[i % BRAND_COLORS.length] })
    return map
  }, [brands])

  const [start, end] = useMemo(() => {
    if (!meta) return [null, null]
    const p = PRESETS.find((x) => x.id === preset)
    return p.range(meta.max_date, meta.min_date)
  }, [meta, preset])

  const params = useMemo(
    () => ({ brand: selected.join(','), start, end }),
    [selected, start, end],
  )

  const load = useCallback(async () => {
    if (!start) return
    setLoading(true)
    setError('')
    try {
      const [summary, revenue, churn, products, orders] = await Promise.all([
        get('/api/summary', params),
        get('/api/revenue', { ...params, bucket }),
        get('/api/churn', params),
        get('/api/top-products', { ...params, limit: 8 }),
        get('/api/orders', { ...params, limit: 8 }),
      ])
      setData({ summary, revenue, churn, products, orders })
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }, [params, bucket, start])

  useEffect(() => { load() }, [load])

  const visibleBrands = selected.length ? brands.filter((b) => selected.includes(b.code)) : brands

  function toggleBrand(code) {
    setSelected((s) => (s.includes(code) ? s.filter((c) => c !== code) : [...s, code]))
  }

  function choosePreset(id) {
    setPreset(id)
    setBucket(PRESETS.find((p) => p.id === id).bucket)
  }

  async function rerunEtl() {
    setEtlMsg('Running ETL…')
    try {
      const r = await post('/api/etl/run')
      setEtlMsg(`Loaded ${num(r.orders_loaded)} orders, skipped ${r.orders_skipped} duplicates/tests`)
      load()
    } catch (e) {
      setEtlMsg(`ETL failed: ${e.message}`)
    }
  }

  const s = data?.summary

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>Multi-Store Sales Analytics</h1>
          <p className="sub">
            {brands.length} brands · all amounts in USD
            {start && <> · {start} → {end}</>}
          </p>
        </div>
        <div className="top-actions">
          <button className="ghost" onClick={rerunEtl}>Re-run ETL</button>
          <a className="primary" href={csvUrl(params)}>Export CSV</a>
        </div>
      </header>
      {etlMsg && <div className="notice">{etlMsg}</div>}

      <div className="filters">
        <div className="chips" role="group" aria-label="Brands">
          <button className={`chip ${selected.length === 0 ? 'on' : ''}`} onClick={() => setSelected([])}>
            All brands
          </button>
          {brands.map((b) => (
            <button
              key={b.code}
              className={`chip ${selected.includes(b.code) ? 'on' : ''}`}
              onClick={() => toggleBrand(b.code)}
            >
              <span className="dot" style={{ background: colorFor[b.code] }} />
              {b.name}
              <span className="ccy">{b.source_currency}</span>
            </button>
          ))}
        </div>
        <div className="segmented" role="group" aria-label="Date range">
          {PRESETS.map((p) => (
            <button key={p.id} className={preset === p.id ? 'on' : ''} onClick={() => choosePreset(p.id)}>
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {error && <div className="error">Could not reach the API: {error}</div>}

      <div className={`kpis ${loading ? 'dim' : ''}`}>
        <Kpi label="Revenue" value={usd(s?.revenue)} hint={`${usd(s?.refunded)} refunded`} />
        <Kpi label="Paid orders" value={num(s?.orders)} />
        <Kpi label="Avg order value" value={usd(s?.aov, 2)} />
        <Kpi label="Customers" value={num(s?.customers)} />
        <Kpi label="Active subscriptions" value={num(s?.active_subscriptions)} hint={`${usd(s?.mrr)} MRR`} />
        <Kpi label="Churn (latest month)" value={`${s?.churn_rate ?? 0}%`} />
      </div>

      <div className="grid">
        <Card
          title="Revenue by brand"
          action={
            <div className="segmented small">
              {['day', 'week', 'month'].map((b) => (
                <button key={b} className={bucket === b ? 'on' : ''} onClick={() => setBucket(b)}>{b}</button>
              ))}
            </div>
          }
        >
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={data?.revenue || []} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="#eef0f3" vertical={false} />
              <XAxis dataKey="period" tick={{ fontSize: 11 }} tickMargin={6} minTickGap={24} />
              <YAxis tickFormatter={(v) => `$${compact(v)}`} tick={{ fontSize: 11 }} width={56} />
              <Tooltip formatter={(v, n) => [usd(v), brands.find((b) => b.code === n)?.name || n]} />
              <Legend wrapperStyle={{ fontSize: 12 }} formatter={(v) => brands.find((b) => b.code === v)?.name || v} />
              {visibleBrands.map((b) => (
                <Area isAnimationActive={false} key={b.code} type="monotone" dataKey={b.code} stackId="1"
                  stroke={colorFor[b.code]} fill={colorFor[b.code]} fillOpacity={0.18} strokeWidth={2} />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Orders per period">
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={data?.revenue || []} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="#eef0f3" vertical={false} />
              <XAxis dataKey="period" tick={{ fontSize: 11 }} tickMargin={6} minTickGap={24} />
              <YAxis tick={{ fontSize: 11 }} width={44} />
              <Tooltip formatter={(v) => [num(v), 'Orders']} />
              <Bar isAnimationActive={false} dataKey="orders" fill="#334155" radius={[3, 3, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Subscription churn by month">
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={data?.churn || []} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="#eef0f3" vertical={false} />
              <XAxis dataKey="period" tick={{ fontSize: 11 }} tickMargin={6} />
              <YAxis yAxisId="rate" tickFormatter={(v) => `${v}%`} tick={{ fontSize: 11 }} width={44} />
              <YAxis yAxisId="count" orientation="right" tick={{ fontSize: 11 }} width={36} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line isAnimationActive={false} yAxisId="rate" type="monotone" dataKey="churn_rate" name="Churn %" stroke="#dc2626" strokeWidth={2} dot={false} />
              <Line isAnimationActive={false} yAxisId="count" type="monotone" dataKey="new" name="New subs" stroke="#059669" strokeWidth={2} dot={false} />
              <Line isAnimationActive={false} yAxisId="count" type="monotone" dataKey="cancelled" name="Cancelled" stroke="#94a3b8" strokeWidth={2} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        <Card title="Top products">
          <table>
            <thead><tr><th>Product</th><th>Brand</th><th className="r">Units</th><th className="r">Revenue</th></tr></thead>
            <tbody>
              {(data?.products || []).map((p) => (
                <tr key={`${p.brand}-${p.product}`}>
                  <td>{p.product}</td>
                  <td><span className="dot" style={{ background: colorFor[p.brand] }} />{brands.find((b) => b.code === p.brand)?.name}</td>
                  <td className="r">{num(p.units)}</td>
                  <td className="r">{usd(p.revenue)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <Card title="Latest orders" action={<a className="link" href={csvUrl(params)}>Download all as CSV</a>}>
          <table>
            <thead><tr><th>Order</th><th>Brand</th><th>Date</th><th>Status</th><th className="r">Original</th><th className="r">USD</th></tr></thead>
            <tbody>
              {(data?.orders || []).map((o) => (
                <tr key={o.order_id}>
                  <td className="mono">{o.order_id}</td>
                  <td>{o.brand}</td>
                  <td>{o.created_at.slice(0, 10)}</td>
                  <td><span className={`status ${o.status}`}>{o.status}</span></td>
                  <td className="r muted">{o.total_source.toFixed(2)} {o.currency}</td>
                  <td className="r">{usd(o.total_usd, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>
      <footer className="foot">FastAPI · SQLAlchemy · React · Recharts — demo data generated by the ETL seed script</footer>
    </div>
  )
}
