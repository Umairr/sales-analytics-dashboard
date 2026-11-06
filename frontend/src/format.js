export const usd = (n, digits = 0) =>
  new Intl.NumberFormat('en-US', {
    style: 'currency', currency: 'USD', maximumFractionDigits: digits, minimumFractionDigits: digits,
  }).format(n || 0)

export const num = (n) => new Intl.NumberFormat('en-US').format(n || 0)

export const compact = (n) =>
  new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 }).format(n || 0)

export const pct = (n, digits = 1) => `${(n ?? 0).toFixed(digits)}%`

export function shiftDate(dateStr, days) {
  const d = new Date(`${dateStr}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return d.toISOString().slice(0, 10)
}

export function daysBetween(a, b) {
  return Math.round((new Date(`${b}T00:00:00Z`) - new Date(`${a}T00:00:00Z`)) / 86400000) + 1
}

export function monthLabel(period) {
  if (!period || !/^\d{4}-\d{2}$/.test(period)) return period
  const [y, m] = period.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, 1)).toLocaleString('en-US', { month: 'short', year: '2-digit', timeZone: 'UTC' })
}

export const BRAND_COLORS = ['#3b82f6', '#f59e0b', '#10b981', '#8b5cf6', '#ec4899']
