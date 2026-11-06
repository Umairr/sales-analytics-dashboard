import { useEffect, useState } from 'react'
import { API_URL, get } from '../api'
import { Card } from '../components'
import { num } from '../format'

const PLATFORM = {
  shopify: { label: 'Shopify', color: '#5e8e3e' },
  woocommerce: { label: 'WooCommerce', color: '#7f54b3' },
  csv: { label: 'CSV upload', color: '#0ea5e9' },
  demo: { label: 'Demo data', color: '#94a3b8' },
}

function PlatformTag({ platform }) {
  const p = PLATFORM[platform] || { label: platform, color: '#64748b' }
  return <span className="platform" style={{ background: p.color }}>{p.label}</span>
}

function ago(iso) {
  if (!iso) return 'never'
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins} min ago`
  if (mins < 1440) return `${Math.round(mins / 60)} h ago`
  return `${Math.round(mins / 1440)} days ago`
}

async function send(method, path, body) {
  const res = await fetch(`${API_URL}${path}`, { method, body })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `${res.status} ${res.statusText}`)
  return data
}

export default function Sources({ onDataChanged }) {
  const [info, setInfo] = useState(null)
  const [busy, setBusy] = useState('')
  const [msg, setMsg] = useState(null)
  const [form, setForm] = useState({ name: '', currency: '', file: null, replaceDemo: true })

  const refresh = () => get('/api/sources').then(setInfo).catch((e) => setMsg({ tone: 'error', text: e.message }))
  useEffect(() => { refresh() }, [])

  async function run(label, fn) {
    setBusy(label)
    setMsg(null)
    try {
      const text = await fn()
      setMsg({ tone: 'ok', text })
      await refresh()
      onDataChanged()
    } catch (e) {
      setMsg({ tone: 'error', text: e.message })
    } finally {
      setBusy('')
    }
  }

  const syncNow = (full) => run(full ? 'full' : 'sync', async () => {
    const r = await send('POST', `/api/sync${full ? '?full=true' : ''}`)
    if (!r.stores.length) throw new Error('No stores in stores.json yet. See the setup steps below.')
    const ok = r.stores.filter((s) => s.ok)
    const failed = r.stores.filter((s) => !s.ok)
    return `Synced ${ok.length}/${r.stores.length} stores · ${num(r.etl.orders_loaded)} orders in the dashboard`
      + (failed.length ? ` · failed: ${failed.map((f) => `${f.name} (${f.error})`).join('; ')}` : '')
      + (r.demo_removed.length ? ' · demo data removed' : '')
  })

  const upload = (e) => {
    e.preventDefault()
    if (!form.file || !form.name.trim()) return
    run('upload', async () => {
      const fd = new FormData()
      fd.append('file', form.file)
      fd.append('name', form.name.trim())
      if (form.currency) fd.append('currency', form.currency)
      fd.append('replace_demo', String(form.replaceDemo))
      const r = await send('POST', '/api/sources/csv', fd)
      setForm({ name: '', currency: '', file: null, replaceDemo: form.replaceDemo })
      e.target.reset()
      return `Imported ${num(r.orders)} orders (${r.currency}) as "${r.code}"`
    })
  }

  const remove = (code, name) => {
    if (!window.confirm(`Remove "${name}" from the dashboard? You can sync or upload it again later.`)) return
    run(`del-${code}`, async () => { await send('DELETE', `/api/sources/${code}`); return `Removed ${name}` })
  }

  const loadDemo = () => run('demo', async () => { await send('POST', '/api/sources/demo'); return 'Demo stores loaded' })

  if (!info) return <Card title="Data sources"><p className="muted">Loading…</p></Card>

  return (
    <div>
      {msg && <div className={msg.tone === 'error' ? 'error' : 'notice'}>{msg.text}</div>}

      <div className="grid two-one">
        <Card
          title="Stores in the dashboard"
          subtitle="Every store below is merged into the same reports, converted to USD"
          action={(
            <div className="btn-row">
              <button className="ghost" disabled={!!busy} onClick={() => syncNow(true)}>{busy === 'full' ? 'Syncing…' : 'Full re-sync'}</button>
              <button className="primary" disabled={!!busy} onClick={() => syncNow(false)}>{busy === 'sync' ? 'Syncing…' : '↻ Sync now'}</button>
            </div>
          )}
        >
          <div className="table-scroll">
            <table className="nowrap">
              <thead><tr><th>Store</th><th>Source</th><th>Currency</th><th className="r">Orders</th><th className="r">Subscriptions</th><th>Updated</th><th /></tr></thead>
              <tbody>
                {info.sources.map((s) => (
                  <tr key={s.code}>
                    <td><strong>{s.name}</strong> <span className="muted mono small">{s.code}</span></td>
                    <td><PlatformTag platform={s.platform} /></td>
                    <td>{s.currency}</td>
                    <td className="r">{num(s.orders)}</td>
                    <td className="r">{num(s.subscriptions)}</td>
                    <td className="muted">{s.platform === 'demo' ? 'generated' : ago(s.synced_at)}</td>
                    <td className="r"><button className="link-btn" disabled={!!busy} onClick={() => remove(s.code, s.name)}>Remove</button></td>
                  </tr>
                ))}
                {!info.sources.length && (
                  <tr><td colSpan={7} className="empty-row">No data yet. Connect a store, upload a CSV or <button className="link-btn" onClick={loadDemo}>load demo data</button>.</td></tr>
                )}
              </tbody>
            </table>
          </div>
          {info.demo_active && (
            <p className="hint">You're looking at <strong>demo data</strong>. It's removed automatically the first time a real store syncs or a CSV is imported.</p>
          )}
          {!info.demo_active && info.sources.length > 0 && (
            <p className="hint"><button className="link-btn" disabled={!!busy} onClick={loadDemo}>Load demo stores</button> alongside your data.</p>
          )}
        </Card>

        <Card title="Upload a CSV" subtitle="Shopify order export, WooCommerce export or any spreadsheet">
          <form className="upload" onSubmit={upload}>
            <label>Store name<input required value={form.name} placeholder="e.g. My Amazon Store" onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
            <label>Currency <span className="muted">(optional)</span><input value={form.currency} maxLength={3} placeholder="USD" onChange={(e) => setForm({ ...form, currency: e.target.value.toUpperCase() })} /></label>
            <label>CSV file<input required type="file" accept=".csv,text/csv" onChange={(e) => setForm({ ...form, file: e.target.files[0] || null })} /></label>
            <label className="check"><input type="checkbox" checked={form.replaceDemo} onChange={(e) => setForm({ ...form, replaceDemo: e.target.checked })} /> Remove demo data</label>
            <button className="primary" disabled={!!busy || !form.file || !form.name.trim()}>{busy === 'upload' ? 'Importing…' : 'Import CSV'}</button>
            <p className="hint">Needs at least order ID, date and total columns. Shopify's own export works as-is; for other files columns like <span className="mono">order_id, created_at, customer_email, status, total, product, quantity, price</span> are recognised.</p>
          </form>
        </Card>
      </div>

      <Card title="Connected APIs" subtitle={info.config_found ? info.config_file : 'No stores.json yet'}>
        {info.config_error && <div className="error">stores.json problem: {info.config_error}</div>}
        {info.configured.length ? (
          <div className="table-scroll">
            <table className="nowrap">
              <thead><tr><th>Store</th><th>Platform</th><th>Last sync</th><th>Result</th></tr></thead>
              <tbody>
                {info.configured.map((s) => (
                  <tr key={s.code}>
                    <td><strong>{s.name}</strong> <span className="muted mono small">{s.code}</span></td>
                    <td><PlatformTag platform={s.platform === 'wordpress' ? 'woocommerce' : s.platform} /></td>
                    <td className="muted">{ago(s.last_result?.checked_at)}</td>
                    <td>
                      {!s.last_result && <span className="muted">not synced yet</span>}
                      {s.last_result?.ok && <span className="ok-text">✓ {num(s.last_result.orders)} orders ({s.last_result.mode})</span>}
                      {s.last_result && !s.last_result.ok && <span className="warn" style={{ whiteSpace: 'normal' }}>✗ {s.last_result.error}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="setup">
            <div>
              <h3><PlatformTag platform="shopify" /> Connect Shopify</h3>
              <ol>
                <li>Shopify admin → click your store name → <b>Dev Dashboard → Create app</b>.</li>
                <li>Admin API scopes: <span className="mono">read_orders</span>, <span className="mono">read_customers</span> (+ <span className="mono">read_all_orders</span> for history older than 60 days). Release a version and <b>install</b> it on the store.</li>
                <li>Copy the app's <b>Client ID</b> and <b>Client secret</b> from its Settings page.</li>
                <li>Add the store to <span className="mono">backend/stores.json</span> and both values to <span className="mono">backend/.env</span>. The connector swaps them for an access token on every sync.</li>
              </ol>
            </div>
            <div>
              <h3><PlatformTag platform="woocommerce" /> Connect WordPress / WooCommerce</h3>
              <ol>
                <li>WP admin → <b>WooCommerce → Settings → Advanced → REST API → Add key</b>.</li>
                <li>Permissions: <b>Read</b>. Copy the consumer key (<span className="mono">ck_…</span>) and secret (<span className="mono">cs_…</span>).</li>
                <li>Add the store URL to <span className="mono">backend/stores.json</span> and both keys to <span className="mono">backend/.env</span>.</li>
                <li>Restart the API and press <b>Sync now</b>.</li>
              </ol>
            </div>
            <p className="hint">Templates: <span className="mono">backend/stores.example.json</span> and <span className="mono">backend/.env.example</span>. Full guide in the README.</p>
          </div>
        )}
      </Card>
    </div>
  )
}
