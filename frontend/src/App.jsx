import { useEffect, useMemo, useState } from 'react'
import { csvUrl, get, post } from './api'
import { BRAND_COLORS, daysBetween, num, shiftDate } from './format'
import Brands from './pages/Brands'
import Customers from './pages/Customers'
import Orders from './pages/Orders'
import Overview from './pages/Overview'

const TABS = [
  { id: 'overview', label: 'Overview', Page: Overview },
  { id: 'customers', label: 'Customers', Page: Customers },
  { id: 'brands', label: 'Brands', Page: Brands },
  { id: 'orders', label: 'Orders', Page: Orders },
]

const PRESETS = [
  { id: '30d', label: '30D', range: (max) => [shiftDate(max, -29), max], bucket: 'day' },
  { id: '90d', label: '90D', range: (max) => [shiftDate(max, -89), max], bucket: 'week' },
  { id: '6m', label: '6M', range: (max) => [shiftDate(max, -181), max], bucket: 'week' },
  { id: 'ytd', label: 'YTD', range: (max) => [`${max.slice(0, 4)}-01-01`, max], bucket: 'month' },
  { id: 'all', label: 'All', range: (max, min) => [min, max], bucket: 'month' },
]

function initialTheme() {
  const fromUrl = new URLSearchParams(window.location.search).get('theme')
  if (fromUrl === 'dark' || fromUrl === 'light') return fromUrl
  try {
    return localStorage.getItem('theme') || (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
  } catch {
    return 'light'
  }
}

function tabFromHash() {
  const h = window.location.hash.replace('#', '')
  return TABS.some((t) => t.id === h) ? h : 'overview'
}

export default function App() {
  const [meta, setMeta] = useState(null)
  const [brands, setBrands] = useState([])
  const [selected, setSelected] = useState([])
  const [preset, setPreset] = useState('90d')
  const [custom, setCustom] = useState(null)
  const [bucket, setBucket] = useState('week')
  const [tab, setTab] = useState(tabFromHash)
  const [theme, setTheme] = useState(initialTheme)
  const [etlMsg, setEtlMsg] = useState('')
  const [reload, setReload] = useState(0)
  const [error, setError] = useState('')

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try { localStorage.setItem('theme', theme) } catch { /* storage unavailable */ }
  }, [theme])

  useEffect(() => {
    const onHash = () => setTab(tabFromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  useEffect(() => {
    Promise.all([get('/api/meta'), get('/api/brands')])
      .then(([m, b]) => { setMeta(m); setBrands(b) })
      .catch((e) => setError(e.message))
  }, [reload])

  const colorFor = useMemo(() => {
    const map = {}
    brands.forEach((b, i) => { map[b.code] = BRAND_COLORS[i % BRAND_COLORS.length] })
    return map
  }, [brands])

  const [start, end] = useMemo(() => {
    if (!meta) return [null, null]
    if (preset === 'custom' && custom) return custom
    const p = PRESETS.find((x) => x.id === preset) || PRESETS[1]
    const [s, e] = p.range(meta.max_date, meta.min_date)
    return [s < meta.min_date ? meta.min_date : s, e]
  }, [meta, preset, custom])

  const params = useMemo(() => ({ brand: selected.join(','), start, end, _r: reload }), [selected, start, end, reload])
  const prevParams = useMemo(() => {
    if (!start) return params
    const len = daysBetween(start, end)
    const prevEnd = shiftDate(start, -1)
    return { ...params, start: shiftDate(prevEnd, -(len - 1)), end: prevEnd }
  }, [params, start, end])

  const visibleBrands = selected.length ? brands.filter((b) => selected.includes(b.code)) : brands

  function toggleBrand(code) {
    setSelected((s) => (s.includes(code) ? s.filter((c) => c !== code) : [...s, code]))
  }
  function choosePreset(id) {
    setPreset(id)
    setBucket(PRESETS.find((p) => p.id === id).bucket)
  }
  function setCustomDate(which, value) {
    if (!value) return
    const next = which === 'start' ? [value, end] : [start, value]
    if (next[0] > next[1]) return
    setCustom(next)
    setPreset('custom')
    const len = daysBetween(next[0], next[1])
    setBucket(len <= 45 ? 'day' : len <= 200 ? 'week' : 'month')
  }
  function openTab(id) {
    window.location.hash = id
    setTab(id)
  }
  async function rerunEtl() {
    setEtlMsg('Running ETL…')
    try {
      const r = await post('/api/etl/run')
      setEtlMsg(`ETL complete · ${num(r.orders_loaded)} orders loaded from ${r.brands} stores · ${r.orders_skipped} duplicates/test orders removed`)
      setReload((n) => n + 1)
      setTimeout(() => setEtlMsg(''), 6000)
    } catch (e) {
      setEtlMsg(`ETL failed: ${e.message}`)
    }
  }

  const { Page } = TABS.find((t) => t.id === tab)
  // Strip the cache-busting key before handing params to pages / URLs.
  const { _r, ...cleanParams } = params
  const { _r: _p, ...cleanPrev } = prevParams
  const ctx = {
    params: cleanParams, prevParams: cleanPrev, bucket, setBucket, brands, colorFor, visibleBrands, reload,
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="logo">
          <span className="logo-mark">◆</span>
          <div>
            <strong>Storefront</strong>
            <span>Analytics</span>
          </div>
        </div>
        <nav>
          {TABS.map((t) => (
            <button key={t.id} className={tab === t.id ? 'active' : ''} onClick={() => openTab(t.id)}>{t.label}</button>
          ))}
        </nav>
        <div className="side-foot">
          <button className="ghost full" onClick={rerunEtl}>↻ Re-run ETL</button>
          <button className="ghost full" onClick={() => setTheme((t) => (t === 'dark' ? 'light' : 'dark'))}>
            {theme === 'dark' ? '☀ Light mode' : '☾ Dark mode'}
          </button>
          {meta && <p className="tiny">Data {meta.min_date} → {meta.max_date}</p>}
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <h1>{TABS.find((t) => t.id === tab).label}</h1>
            <p className="sub">
              {visibleBrands.length} of {brands.length} brands · USD
              {start && <> · {start} → {end} ({daysBetween(start, end)} days)</>}
            </p>
          </div>
          {tab !== 'orders' && <a className="primary" href={csvUrl(cleanParams)}>Export CSV</a>}
        </header>

        {etlMsg && <div className="notice">{etlMsg}</div>}
        {error && <div className="error">Could not reach the API at {import.meta.env.VITE_API_URL || 'http://localhost:8000'}: {error}</div>}

        <div className="filters">
          <div className="chips" role="group" aria-label="Brands">
            <button className={`chip ${selected.length === 0 ? 'on' : ''}`} onClick={() => setSelected([])}>All brands</button>
            {brands.map((b) => (
              <button key={b.code} className={`chip ${selected.includes(b.code) ? 'on' : ''}`} onClick={() => toggleBrand(b.code)}>
                <span className="dot" style={{ background: colorFor[b.code] }} />
                {b.name}
                <span className="ccy">{b.source_currency}</span>
              </button>
            ))}
          </div>
          <div className="date-controls">
            <div className="segmented" role="group" aria-label="Date range">
              {PRESETS.map((p) => (
                <button key={p.id} className={preset === p.id ? 'on' : ''} onClick={() => choosePreset(p.id)}>{p.label}</button>
              ))}
            </div>
            {meta && (
              <div className="date-inputs">
                <input type="date" value={start || ''} min={meta.min_date} max={meta.max_date} onChange={(e) => setCustomDate('start', e.target.value)} />
                <span>→</span>
                <input type="date" value={end || ''} min={meta.min_date} max={meta.max_date} onChange={(e) => setCustomDate('end', e.target.value)} />
              </div>
            )}
          </div>
        </div>

        {start && <Page key={`${tab}-${reload}`} ctx={ctx} />}

        <footer className="foot">FastAPI · SQLAlchemy · React · Recharts · ETL across {brands.length} stores</footer>
      </main>
    </div>
  )
}
