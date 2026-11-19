import { useEffect, useState } from 'react'

const API_BASE = (import.meta.env && import.meta.env.VITE_API_BASE) || ''
const cache = new Map()

export function apiUrl(path, params = {}) {
  const qs = new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== ''))
  return `${API_BASE}/api${path}${qs.toString() ? '?' + qs : ''}`
}

// ------------------------------------------------------------------ session
const TOKEN_KEY = 'dkpi_token'
let token = null
try { token = localStorage.getItem(TOKEN_KEY) } catch (e) { /* storage blocked */ }

export const getToken = () => token
export function setToken(t) {
  token = t || null
  try { t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY) } catch (e) { /* ignore */ }
}
/** Called when the API says the session is no longer valid. */
function sessionExpired() {
  setToken(null)
  cache.clear()
  window.dispatchEvent(new Event('auth:expired'))
}

const RETRY_STATUS = new Set([502, 503, 504])
const MAX_RETRIES = 8          // ~4 minutes: covers the first data load after a server restart
const RETRY_WAIT_MS = 30000
const wait = (ms) => new Promise((res) => setTimeout(res, ms))

async function request(url, opts = {}) {
  const headers = { ...(opts.headers || {}) }
  if (token) headers.Authorization = `Bearer ${token}`
  const isGet = !opts.method || opts.method === 'GET'
  let r
  for (let attempt = 0; ; attempt++) {
    try {
      r = await fetch(url, { ...opts, headers })
    } catch (e) {  // network error / gateway closed the connection
      if (!isGet || attempt >= MAX_RETRIES) throw e
      await wait(RETRY_WAIT_MS)
      continue
    }
    // The server keeps loading data after the platform's gateway gives up (504), so asking
    // again shortly afterwards gets the answer from memory.
    if (isGet && RETRY_STATUS.has(r.status) && attempt < MAX_RETRIES) {
      await wait(RETRY_WAIT_MS)
      continue
    }
    break
  }
  const body = await r.json().catch(() => ({ error: `HTTP ${r.status}` }))
  if (r.status === 401 && body.auth) sessionExpired()
  if (!r.ok || body.error) throw new Error(body.error || `HTTP ${r.status}`)
  return body
}

export async function fetchApi(path, params) {
  const url = apiUrl(path, params)
  if (cache.has(url)) return cache.get(url)
  const p = request(url)
  cache.set(url, p)
  p.catch(() => cache.delete(url))
  return p
}

/** POST JSON (never cached). */
export function postApi(path, data = {}) {
  return request(apiUrl(path), {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  })
}

export function clearClientCache() { cache.clear() }

/** Value that only updates after the input has been still for `ms`. */
export function useDebounced(value, ms = 600) {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms)
    return () => clearTimeout(t)
  }, [value, ms])
  return v
}

export function useApi(path, params = {}) {
  const key = apiUrl(path, params)
  const [state, setState] = useState({ loading: true, data: null, error: null })
  useEffect(() => {
    let alive = true
    setState((s) => ({ ...s, loading: true, error: null }))
    fetchApi(path, params)
      .then((data) => alive && setState({ loading: false, data, error: null }))
      .catch((e) => alive && setState({ loading: false, data: null, error: e.message }))
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])
  return state
}

// ------------------------------------------------------------------ formatting
const nf0 = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 })
const nf1 = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 1, minimumFractionDigits: 1 })
const nf2 = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 2, minimumFractionDigits: 2 })

export const isNum = (v) => typeof v === 'number' && isFinite(v)

/** ₹ in crore / lakh / plain, Indian style */
export function inr(v, digits) {
  digits = dg(digits, undefined)
  if (!isNum(v)) return '–'
  const a = Math.abs(v), sg = v < 0 ? '−' : ''
  if (a >= 1e7) return `${sg}₹${(digits === 0 ? nf0 : nf2).format(a / 1e7)} Cr`
  if (a >= 1e5) return `${sg}₹${(digits === 0 ? nf0 : nf1).format(a / 1e5)} L`
  return `${sg}₹${nf0.format(a)}`
}
export const inrFull = (v) => (isNum(v) ? `${v < 0 ? '−' : ''}₹${nf0.format(Math.abs(v))}` : '–')
export const rs2 = (v) => (isNum(v) ? `${v < 0 ? '−' : ''}₹${nf2.format(Math.abs(v))}` : '–')
const dg = (d, def) => (typeof d === 'number' ? d : def)  // formatters are also called as fmt(value, row)
export const num = (v, d) => { d = dg(d, 0); return (isNum(v) ? (d ? new Intl.NumberFormat('en-IN', { maximumFractionDigits: d, minimumFractionDigits: d }) : nf0).format(v) : '–') }
export const kg = (v) => {
  if (!isNum(v)) return '–'
  if (Math.abs(v) >= 1e5) return `${nf1.format(v / 1e5)} L kg`
  return `${nf0.format(v)} kg`
}
export const pct = (v, d) => (isNum(v) ? `${v.toFixed(dg(d, 1))}%` : '–')
export const spct = (v, d) => (isNum(v) ? `${v > 0 ? '+' : ''}${v.toFixed(dg(d, 1))}%` : '–')
export const days = (v) => (isNum(v) ? `${v.toFixed(0)} d` : '–')
const MON = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
export function dt(v) {
  if (!v) return '–'
  const [y, m, d] = String(v).slice(0, 10).split('-')
  return `${Number(d)} ${MON[Number(m) - 1]} ${y}`
}
export function mon(v) {
  if (!v) return '–'
  const [y, m] = String(v).slice(0, 7).split('-')
  return `${MON[Number(m) - 1]} ${y.slice(2)}`
}

export const FAMILY_COLORS = {
  Groundnut: '#2563eb',
  Sunflower: '#d97706',
  'Rice bran': '#059669',
  'Vegetable (blended)': '#7c3aed',
  'Pooja oil': '#db2777',
  'Groundnut seed': '#64748b',
  'All oils': '#111827',
}
export const familyColor = (f) => FAMILY_COLORS[f] || '#6b7280'

export function downloadCsv(filename, columns, rows) {
  const esc = (v) => {
    if (v === null || v === undefined) return ''
    const s = String(v)
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s
  }
  const lines = [columns.map((c) => esc(c.label)).join(',')]
  rows.forEach((r) => lines.push(columns.map((c) => esc(r[c.key])).join(',')))
  const blob = new Blob([lines.join('\n')], { type: 'text/csv' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = filename
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 1000)
}
