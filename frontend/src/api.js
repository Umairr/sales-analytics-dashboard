export const API_URL = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')

export function buildQuery(params) {
  const q = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') q.set(k, v)
  })
  const s = q.toString()
  return s ? `?${s}` : ''
}

export async function get(path, params = {}) {
  const res = await fetch(`${API_URL}${path}${buildQuery(params)}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} on ${path}`)
  return res.json()
}

export async function post(path) {
  const res = await fetch(`${API_URL}${path}`, { method: 'POST' })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} on ${path}`)
  return res.json()
}

export function csvUrl(params) {
  return `${API_URL}/api/export/orders.csv${buildQuery(params)}`
}
