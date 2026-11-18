import React, { useEffect, useState } from 'react'
import { useApi, fetchApi, clearClientCache, dt } from './lib.js'
import SalesPage from './pages/Sales.jsx'
import ReceivablesPage from './pages/Receivables.jsx'
import PayablesPage from './pages/Payables.jsx'
import CashPage from './pages/Cash.jsx'
import MarginPage from './pages/Margin.jsx'
import ProductionPage from './pages/Production.jsx'
import ControlPage from './pages/Control.jsx'

const PAGES = [
  { id: 'sales', label: 'Sales', items: 15, Comp: SalesPage },
  { id: 'receivables', label: 'Receivables', items: 8, Comp: ReceivablesPage },
  { id: 'payables', label: 'Payables', items: 4, Comp: PayablesPage },
  { id: 'cash', label: 'Cash', items: 1, Comp: CashPage },
  { id: 'margin', label: 'Margin', items: 4, Comp: MarginPage },
  { id: 'production', label: 'Production', items: 5, Comp: ProductionPage },
  { id: 'control', label: 'Control', items: 1, Comp: ControlPage },
]

const fromHash = () => {
  const h = window.location.hash.replace('#', '')
  return PAGES.some((p) => p.id === h) ? h : 'sales'
}

export default function App() {
  const [page, setPage] = useState(fromHash())
  const [refreshKey, setRefreshKey] = useState(0)
  const meta = useApi('/meta', { r: refreshKey })
  useEffect(() => {
    const on = () => setPage(fromHash())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  const current = PAGES.find((p) => p.id === page)
  const refresh = async () => {
    try { await fetchApi('/cache/clear', { t: Date.now() }) } catch (e) { /* ignore */ }
    clearClientCache()
    setRefreshKey((k) => k + 1)
  }
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">Damodara Oil Mill<span>KPI dashboard</span></div>
        <nav>
          {PAGES.map((p) => (
            <a key={p.id} href={`#${p.id}`} className={p.id === page ? 'active' : ''}>
              {p.label}<em>{p.items}</em>
            </a>
          ))}
        </nav>
        <div className="side-foot">
          {meta.data && (
            <>
              <div>{meta.data.current_company}</div>
              <div>Data as of <b>{dt(meta.data.as_of)}</b></div>
              {meta.data.demo_mode && <div className="demo">Demo mode: Excel extract</div>}
            </>
          )}
          {meta.error && <div className="error small">API not reachable: {meta.error}</div>}
          <button className="refresh" onClick={refresh}>Refresh data</button>
        </div>
      </aside>
      <main key={refreshKey}>
        <h1>{current.label}</h1>
        <current.Comp />
      </main>
    </div>
  )
}
