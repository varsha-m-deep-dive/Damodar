import React from 'react'
import { useApi } from '../lib.js'

export function Card({ title, item, priority, kind, note, children, actions, wide }) {
  return (
    <section className={`card${wide ? ' wide' : ''}`}>
      <header className="card-head">
        <div>
          <h3>{title}</h3>
          {item && (
            <div className="item-ref">
              {priority && <span className={`badge ${priority === 'Must-have' ? 'must' : 'imp'}`}>{priority}</span>}
              {kind && <span className="badge kind">{kind}</span>}
              <span className="item-text">{item}</span>
            </div>
          )}
        </div>
        {actions && <div className="card-actions">{actions}</div>}
      </header>
      <div className="card-body">{children}</div>
      {note && <p className="note">{note}</p>}
    </section>
  )
}

export function Kpi({ label, value, sub, delta, tone }) {
  const dTone = typeof delta === 'number' ? (delta >= 0 ? 'up' : 'down') : ''
  return (
    <div className={`kpi ${tone || ''}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {(sub || delta !== undefined) && (
        <div className="kpi-sub">
          {typeof delta === 'number' && <span className={`delta ${dTone}`}>{delta >= 0 ? '▲' : '▼'} {Math.abs(delta).toFixed(1)}%</span>}
          {sub && <span>{sub}</span>}
        </div>
      )}
    </div>
  )
}

export const KpiRow = ({ children }) => <div className="kpi-row">{children}</div>

export function Tabs({ tabs, value, onChange }) {
  return (
    <div className="tabs" role="tablist">
      {tabs.map((t) => (
        <button key={t.id} role="tab" aria-selected={value === t.id} className={value === t.id ? 'active' : ''}
          onClick={() => onChange(t.id)}>{t.label}</button>
      ))}
    </div>
  )
}

export function Select({ label, value, onChange, options }) {
  return (
    <label className="select">
      {label && <span>{label}</span>}
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => (
          <option key={o.value ?? o} value={o.value ?? o}>{o.label ?? o}</option>
        ))}
      </select>
    </label>
  )
}

export function NumberInput({ label, value, onChange, step = 100000 }) {
  return (
    <label className="select">
      {label && <span>{label}</span>}
      <input type="number" value={value} step={step} onChange={(e) => onChange(e.target.value)} />
    </label>
  )
}

export function Loading() {
  const [slow, setSlow] = React.useState(false)
  React.useEffect(() => {
    const t = setTimeout(() => setSlow(true), 15000)
    return () => clearTimeout(t)
  }, [])
  return (
    <div className="loading">
      <span className="spinner" /> Loading…
      {slow && <span className="muted">The first load after a server restart reads 5 years of data and can take 2–4 minutes. It is fast after that.</span>}
    </div>
  )
}

export function ErrorBox({ error }) {
  return <div className="error">Could not load: {error}</div>
}

/** Fetch an endpoint and render children(data) once it arrives. */
export function Async({ path, params, children }) {
  const { loading, data, error } = useApi(path, params)
  if (loading) return <Loading />
  if (error) return <ErrorBox error={error} />
  return children(data)
}

export const Note = ({ children }) => (children ? <p className="note">{children}</p> : null)
export const Empty = ({ children }) => <div className="empty">{children || 'No data for this period.'}</div>

export function Bullets({ items }) {
  if (!items || !items.length) return null
  return <ul className="bullets">{items.map((t, i) => <li key={i}>{t}</li>)}</ul>
}
