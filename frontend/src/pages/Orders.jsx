import { useEffect, useState } from 'react'
import { csvUrl } from '../api'
import { BrandDot, Card } from '../components'
import { num, usd } from '../format'
import { useApi } from '../useApi'

const PAGE = 25

export default function Orders({ ctx }) {
  const { params, colorFor } = ctx
  const [q, setQ] = useState('')
  const [debounced, setDebounced] = useState('')
  const [status, setStatus] = useState('')
  const [sort, setSort] = useState({ key: 'created_at', dir: 'desc' })
  const [page, setPage] = useState(0)

  useEffect(() => {
    const t = setTimeout(() => { setDebounced(q.trim()); setPage(0) }, 300)
    return () => clearTimeout(t)
  }, [q])
  useEffect(() => { setPage(0) }, [params.brand, params.start, params.end, status])

  const query = {
    ...params, q: debounced, status, sort: sort.key, direction: sort.dir, limit: PAGE, offset: page * PAGE,
  }
  const { data, loading, error } = useApi({ res: ['/api/orders/search', query] }, [JSON.stringify(query)])
  const res = data?.res
  const pages = res ? Math.max(1, Math.ceil(res.total / PAGE)) : 1

  function sortBy(key) {
    setSort((s) => ({ key, dir: s.key === key && s.dir === 'desc' ? 'asc' : 'desc' }))
    setPage(0)
  }
  const arrow = (key) => (sort.key === key ? (sort.dir === 'desc' ? ' ↓' : ' ↑') : '')

  return (
    <Card
      title="Orders"
      subtitle={res ? `${num(res.total)} orders match` : 'Loading…'}
      action={<a className="primary" href={csvUrl({ ...params, q: debounced, status })}>Export CSV</a>}
    >
      <div className="toolbar">
        <input className="search" placeholder="Search order ID or customer email…" value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="segmented small">
          {[['', 'All'], ['paid', 'Paid'], ['refunded', 'Refunded'], ['pending', 'Pending']].map(([v, l]) => (
            <button key={l} className={status === v ? 'on' : ''} onClick={() => setStatus(v)}>{l}</button>
          ))}
        </div>
      </div>
      {error && <div className="error">{error}</div>}
      <div className={`table-scroll ${loading ? 'dim' : ''}`}>
        <table>
          <thead>
            <tr>
              <th>Order</th><th>Brand</th>
              <th className="sortable" onClick={() => sortBy('created_at')}>Date{arrow('created_at')}</th>
              <th>Customer</th><th>Status</th>
              <th className="r sortable" onClick={() => sortBy('item_count')}>Items{arrow('item_count')}</th>
              <th className="r">Original</th>
              <th className="r sortable" onClick={() => sortBy('total_usd')}>USD{arrow('total_usd')}</th>
            </tr>
          </thead>
          <tbody>
            {(res?.rows || []).map((o) => (
              <tr key={o.order_id}>
                <td className="mono">{o.order_id}</td>
                <td><BrandDot color={colorFor[o.code]} />{o.brand}</td>
                <td>{o.created_at.replace('T', ' ').slice(0, 16)}</td>
                <td className="muted">{o.customer_email}</td>
                <td><span className={`status ${o.status}`}>{o.status}</span></td>
                <td className="r">{o.item_count}</td>
                <td className="r muted">{o.total_source.toFixed(2)} {o.currency}</td>
                <td className="r">{usd(o.total_usd, 2)}</td>
              </tr>
            ))}
            {res && !res.rows.length && <tr><td colSpan={8} className="empty-row">No orders match these filters.</td></tr>}
          </tbody>
        </table>
      </div>
      <div className="pager">
        <button className="ghost" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>← Prev</button>
        <span>Page {page + 1} of {num(pages)}</span>
        <button className="ghost" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>Next →</button>
      </div>
    </Card>
  )
}
