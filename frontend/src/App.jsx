import React, { useEffect, useState } from 'react'
import { useApi, fetchApi, clearClientCache, dt, getToken, setToken, num } from './lib.js'
import SalesPage from './pages/Sales.jsx'
import ReceivablesPage from './pages/Receivables.jsx'
import PayablesPage from './pages/Payables.jsx'
import CashPage from './pages/Cash.jsx'
import MarginPage from './pages/Margin.jsx'
import ProductionPage from './pages/Production.jsx'
import ControlPage from './pages/Control.jsx'
import { Login, ResetPassword, readResetLink } from './pages/Auth.jsx'
import { AdminPage, AccountPage } from './pages/Admin.jsx'
import { Loading } from './components/ui.jsx'

const PAGES = [
  { id: 'sales', label: 'Sales', items: 15, Comp: SalesPage },
  { id: 'receivables', label: 'Receivables', items: 8, Comp: ReceivablesPage },
  { id: 'payables', label: 'Payables', items: 4, Comp: PayablesPage },
  { id: 'cash', label: 'Cash', items: 1, Comp: CashPage },
  { id: 'margin', label: 'Margin', items: 4, Comp: MarginPage },
  { id: 'production', label: 'Production', items: 5, Comp: ProductionPage },
  { id: 'control', label: 'Control', items: 1, Comp: ControlPage },
]
const EXTRA = [
  { id: 'account', label: 'My account' },
  { id: 'admin', label: 'Users & Sheets', admin: true },
]

const fromHash = () => {
  const h = window.location.hash.replace('#', '')
  return PAGES.some((p) => p.id === h) || EXTRA.some((p) => p.id === h) ? h : 'sales'
}

/** Decides between the sign-in screens and the dashboard. */
export default function App() {
  const [user, setUser] = useState(null)
  const [checking, setChecking] = useState(!!getToken())
  const [resetLink, setResetLink] = useState(readResetLink())

  useEffect(() => {
    const onHash = () => setResetLink(readResetLink())
    const onExpired = () => setUser(null)
    window.addEventListener('hashchange', onHash)
    window.addEventListener('auth:expired', onExpired)
    if (getToken()) {
      fetchApi('/auth/me', { t: Date.now() })
        .then((r) => setUser(r.user))
        .catch(() => setToken(null))
        .finally(() => setChecking(false))
    }
    return () => {
      window.removeEventListener('hashchange', onHash)
      window.removeEventListener('auth:expired', onExpired)
    }
  }, [])

  const signedIn = (u) => {
    clearClientCache()
    setUser(u)
    if (!PAGES.some((p) => `#${p.id}` === window.location.hash)) window.location.hash = 'sales'
  }
  const signOut = () => {
    setToken(null)
    clearClientCache()
    setUser(null)
  }

  if (resetLink) return <ResetPassword link={resetLink} onSignedIn={(u) => { setResetLink(null); signedIn(u) }} />
  if (checking) return <div className="auth-wrap"><Loading /></div>
  if (!user) return <Login onSignedIn={signedIn} />
  return <Dashboard user={user} onSignOut={signOut} onUserChange={setUser} />
}

function refreshSummary(refresh) {
  const r = refresh && refresh.sales
  if (!r) return null
  return r.mode === 'delta' ? `${num(r.rows_fetched)} new/changed sales lines` : 'full reload'
}

function Dashboard({ user, onSignOut, onUserChange }) {
  const [page, setPage] = useState(fromHash())
  const [refreshKey, setRefreshKey] = useState(0)
  const [refreshing, setRefreshing] = useState(false)
  const meta = useApi('/meta', { r: refreshKey })
  useEffect(() => {
    const on = () => setPage(fromHash())
    window.addEventListener('hashchange', on)
    return () => window.removeEventListener('hashchange', on)
  }, [])
  const isAdmin = user.role === 'admin'
  const extras = EXTRA.filter((p) => !p.admin || isAdmin)
  const current = PAGES.find((p) => p.id === page) || extras.find((p) => p.id === page) || PAGES[0]

  const refresh = async (full) => {
    setRefreshing(true)
    try { await fetchApi('/cache/clear', { t: Date.now(), full: full ? 1 : undefined }) } catch (e) { /* ignore */ }
    clearClientCache()
    setRefreshKey((k) => k + 1)
    setRefreshing(false)
  }
  const updated = refreshSummary(meta.data && meta.data.refresh)

  let body
  if (current.id === 'admin') body = <AdminPage me={user} />
  else if (current.id === 'account') body = <AccountPage me={user} onChanged={onUserChange} />
  else body = <current.Comp />

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">Damodara Oil Mill<span>KPI dashboard</span></div>
        <nav>
          {PAGES.map((p) => (
            <a key={p.id} href={`#${p.id}`} className={p.id === current.id ? 'active' : ''}>
              {p.label}<em>{p.items}</em>
            </a>
          ))}
          <div className="nav-sep" />
          {extras.map((p) => (
            <a key={p.id} href={`#${p.id}`} className={p.id === current.id ? 'active' : ''}>{p.label}</a>
          ))}
        </nav>
        <div className="side-foot">
          {meta.data && (
            <>
              <div>{meta.data.current_company}</div>
              <div>Data as of <b>{dt(meta.data.as_of)}</b></div>
              {updated && <div className="muted-dark">Last refresh: {updated}</div>}
              {meta.data.demo_mode && <div className="demo">Demo mode: Excel extract</div>}
            </>
          )}
          {meta.error && <div className="error small">API not reachable: {meta.error}</div>}
          <button className="refresh" onClick={() => refresh(false)} disabled={refreshing}
            title="Reads only new and recently changed entries from Tally">
            {refreshing ? 'Refreshing…' : 'Refresh data'}
          </button>
          {isAdmin && (
            <button className="refresh subtle" onClick={() => refresh(true)} disabled={refreshing}
              title="Re-reads all history (slower). Use if an old entry was edited in Tally.">
              Full reload
            </button>
          )}
          <div className="who">
            <span title={user.email}>{user.name || user.email}</span>
            <button className="link-dark" onClick={onSignOut}>Sign out</button>
          </div>
        </div>
      </aside>
      <main key={refreshKey}>
        <h1>{current.label}</h1>
        {body}
      </main>
    </div>
  )
}
