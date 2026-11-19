import React, { useCallback, useEffect, useState } from 'react'
import { fetchApi, postApi, clearClientCache, dt } from '../lib.js'
import { Card, Loading, ErrorBox, Note } from '../components/ui.jsx'
import { ChangePasswordForm } from './Auth.jsx'

function CopyBox({ link, note }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try { await navigator.clipboard.writeText(link); setCopied(true) } catch (e) { /* select manually */ }
  }
  return (
    <div className="copy-box">
      <div className="muted">{note}</div>
      <div className="copy-row">
        <input readOnly value={link} onFocus={(e) => e.target.select()} />
        <button className="secondary" onClick={copy}>{copied ? 'Copied' : 'Copy'}</button>
      </div>
    </div>
  )
}

function Users({ me }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [form, setForm] = useState({ email: '', name: '', role: 'viewer' })
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)

  const load = useCallback(() => {
    clearClientCache()
    fetchApi('/admin/users', { t: Date.now() }).then(setData).catch((e) => setError(e.message))
  }, [])
  useEffect(load, [load])

  const act = async (fn) => {
    setBusy(true); setError(null); setResult(null)
    try { const r = await fn(); setResult(r); load() } catch (e) { setError(e.message) } finally { setBusy(false) }
  }
  const add = (e) => {
    e.preventDefault()
    act(async () => {
      const r = await postApi('/admin/users', { ...form, send_invite: true })
      setForm({ email: '', name: '', role: 'viewer' })
      return { ...r, who: r.user.email, kind: 'invite' }
    })
  }

  if (!data && !error) return <Loading />
  return (
    <>
      <form className="inline-form" onSubmit={add}>
        <label className="field"><span>Email</span>
          <input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
        <label className="field"><span>Name</span>
          <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
        <label className="field"><span>Role</span>
          <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
            <option value="viewer">Viewer</option><option value="admin">Admin</option>
          </select></label>
        <button className="primary" disabled={busy}>Add user</button>
      </form>
      {error && <ErrorBox error={error} />}
      {result && result.link && (
        <CopyBox link={result.link}
          note={result.emailed
            ? `Email sent to ${result.who || ''}. You can also send this link yourself (valid ${result.kind === 'invite' ? '7 days' : '24 hours'}, works once):`
            : `${result.email_error ? `Email failed (${result.email_error}). ` : 'Email is not set up. '}Send this link to ${result.who || 'the user'} yourself (valid ${result.kind === 'invite' ? '7 days' : '24 hours'}, works once):`} />
      )}
      {data && (
        <div className="table-scroll">
          <table>
            <thead><tr><th>Email</th><th>Name</th><th>Role</th><th>Status</th><th>Last sign-in</th><th></th></tr></thead>
            <tbody>
              {data.users.map((u) => (
                <tr key={u.email}>
                  <td>{u.email}</td>
                  <td>{u.name}</td>
                  <td>
                    <select value={u.role} disabled={busy || u.email === me.email}
                      onChange={(e) => act(() => postApi('/admin/users/update', { email: u.email, role: e.target.value }))}>
                      <option value="viewer">Viewer</option><option value="admin">Admin</option>
                    </select>
                  </td>
                  <td>
                    {!u.active ? <span className="tag bad">Disabled</span>
                      : u.has_password ? <span className="tag good">Active</span> : <span className="tag warn">Invited</span>}
                  </td>
                  <td>{u.last_login ? dt(u.last_login) : '–'}</td>
                  <td className="row-actions">
                    <button className="link-btn" disabled={busy}
                      onClick={() => act(async () => ({ ...(await postApi('/admin/users/reset-link', { email: u.email, send_email: data.email_enabled })), who: u.email, kind: 'reset' }))}>
                      {data.email_enabled ? 'Send reset link' : 'Get reset link'}
                    </button>
                    {u.email !== me.email && (
                      <button className="link-btn" disabled={busy}
                        onClick={() => act(() => postApi('/admin/users/update', { email: u.email, active: !u.active }))}>
                        {u.active ? 'Disable' : 'Enable'}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <Note>
        Accounts are stored in {data?.store === 'google-sheet' ? 'the private users Google Sheet' : 'a local file (development only)'}.
        {' '}Email is {data?.email_enabled ? 'set up' : 'not set up, so copy reset links and send them yourself'}.
        {' '}Disabling a user signs them out within 30 seconds.
      </Note>
    </>
  )
}

function SheetsExport() {
  const [st, setSt] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const load = useCallback(() => {
    clearClientCache()
    fetchApi('/admin/sheets/status', { t: Date.now() }).then(setSt).catch((e) => setError(e.message))
  }, [])
  useEffect(load, [load])
  const run = async () => {
    setBusy(true); setError(null)
    try { await postApi('/admin/sheets/export') } catch (e) { setError(e.message) } finally { setBusy(false); load() }
  }
  if (!st && !error) return <Loading />
  return (
    <>
      {st && !st.configured && (
        <div className="warn">Google Sheets is not set up on the server (GOOGLE_SERVICE_ACCOUNT_JSON and KPI_SHEET_ID). See the README.</div>
      )}
      {st && (
        <div className="kpi-sub" style={{ marginBottom: 10 }}>
          <span>Last export: <b>{st.last_run || 'never'}</b>{st.seconds != null && ` (${st.seconds}s)`}</span>
          {st.tabs > 0 && <span>{st.tabs} tabs</span>}
          <span>Automatic: {st.interval_minutes > 0 ? `every ${st.interval_minutes} min` : 'off'}</span>
        </div>
      )}
      {st && st.service_account && <Note>Share the spreadsheet (Editor) with <code>{st.service_account}</code>.</Note>}
      {st && st.failed && st.failed.length > 0 && (
        <div className="warn">{st.failed.length} KPI(s) failed: {st.failed.map((f) => f.tab).join(', ')}</div>
      )}
      {error && <ErrorBox error={error} />}
      <div className="card-actions" style={{ marginTop: 10 }}>
        <button className="primary" disabled={busy || !st?.configured} onClick={run}>
          {busy ? 'Exporting… (1–3 min)' : 'Export all KPIs now'}
        </button>
        {st && st.url && <a className="secondary btn-link" href={st.url} target="_blank" rel="noreferrer">Open Google Sheet ↗</a>}
      </div>
    </>
  )
}

export function AdminPage({ me }) {
  return (
    <div className="grid">
      <Card title="Users" wide note="Add people by email. They get a link to set their own password.">
        <Users me={me} />
      </Card>
      <Card title="Google Sheets export" wide
        note="Writes every KPI to its own tab in the KPI spreadsheet, with an Index tab listing them.">
        <SheetsExport />
      </Card>
    </div>
  )
}

export function AccountPage({ me, onChanged }) {
  return (
    <div className="grid">
      <Card title="Your account">
        <p className="muted">{me.name ? `${me.name} · ` : ''}{me.email} · {me.role}</p>
        <h4>Change password</h4>
        <ChangePasswordForm onChanged={onChanged} />
      </Card>
    </div>
  )
}
