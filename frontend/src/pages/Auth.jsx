import React, { useState } from 'react'
import { postApi, setToken } from '../lib.js'

/** Sign-in, forgot-password and reset-password screens (shown before the dashboard). */
export function readResetLink() {
  const h = window.location.hash
  if (!h.startsWith('#reset?')) return null
  const q = new URLSearchParams(h.slice('#reset?'.length))
  return q.get('token') ? { email: q.get('email') || '', token: q.get('token') } : null
}

function Shell({ title, sub, children }) {
  return (
    <div className="auth-wrap">
      <div className="auth-card">
        <div className="auth-brand">Damodara Oil Mill<span>KPI dashboard</span></div>
        <h2>{title}</h2>
        {sub && <p className="auth-sub">{sub}</p>}
        {children}
      </div>
    </div>
  )
}

function Field({ label, type = 'text', value, onChange, autoComplete, autoFocus }) {
  return (
    <label className="field">
      <span>{label}</span>
      <input type={type} value={value} onChange={(e) => onChange(e.target.value)} autoComplete={autoComplete}
        autoFocus={autoFocus} required />
    </label>
  )
}

export function Login({ onSignedIn }) {
  const [mode, setMode] = useState('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [done, setDone] = useState(null)

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true); setError(null)
    try {
      if (mode === 'login') {
        const r = await postApi('/auth/login', { email, password })
        setToken(r.token)
        onSignedIn(r.user)
      } else {
        const r = await postApi('/auth/forgot', { email })
        setDone(r.message)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (mode === 'forgot') {
    return (
      <Shell title="Forgot password" sub="Enter your email and we'll send you a link to set a new password.">
        {done ? <div className="info">{done}</div> : (
          <form onSubmit={submit}>
            <Field label="Email" type="email" value={email} onChange={setEmail} autoComplete="email" autoFocus />
            {error && <div className="error small-gap">{error}</div>}
            <button className="primary" disabled={busy}>{busy ? 'Sending…' : 'Send reset link'}</button>
          </form>
        )}
        <p className="auth-foot">
          <button className="link-btn" onClick={() => { setMode('login'); setDone(null); setError(null) }}>Back to sign in</button>
          <br />No email? Ask an admin for a reset link.
        </p>
      </Shell>
    )
  }
  return (
    <Shell title="Sign in">
      <form onSubmit={submit}>
        <Field label="Email" type="email" value={email} onChange={setEmail} autoComplete="username" autoFocus />
        <Field label="Password" type="password" value={password} onChange={setPassword} autoComplete="current-password" />
        {error && <div className="error small-gap">{error}</div>}
        <button className="primary" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
      </form>
      <p className="auth-foot">
        <button className="link-btn" onClick={() => { setMode('forgot'); setError(null) }}>Forgot password?</button>
      </p>
    </Shell>
  )
}

export function ResetPassword({ link, onSignedIn }) {
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  const submit = async (e) => {
    e.preventDefault()
    if (password !== confirm) { setError('The two passwords do not match.'); return }
    setBusy(true); setError(null)
    try {
      const r = await postApi('/auth/reset', { email: link.email, token: link.token, password })
      setToken(r.token)
      window.location.hash = ''
      onSignedIn(r.user)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Shell title="Set a new password" sub={`For ${link.email}. At least 8 characters.`}>
      <form onSubmit={submit}>
        <Field label="New password" type="password" value={password} onChange={setPassword} autoComplete="new-password" autoFocus />
        <Field label="Repeat new password" type="password" value={confirm} onChange={setConfirm} autoComplete="new-password" />
        {error && <div className="error small-gap">{error}</div>}
        <button className="primary" disabled={busy}>{busy ? 'Saving…' : 'Save password and sign in'}</button>
      </form>
      <p className="auth-foot">
        <button className="link-btn" onClick={() => { window.location.hash = '' }}>Back to sign in</button>
      </p>
    </Shell>
  )
}

export function ChangePasswordForm({ onChanged }) {
  const [current, setCurrent] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [msg, setMsg] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)
  const submit = async (e) => {
    e.preventDefault()
    if (password !== confirm) { setError('The two new passwords do not match.'); return }
    setBusy(true); setError(null); setMsg(null)
    try {
      const r = await postApi('/auth/change-password', { current, password })
      setToken(r.token)
      setCurrent(''); setPassword(''); setConfirm('')
      setMsg('Password changed. Other devices have been signed out.')
      onChanged && onChanged(r.user)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <form onSubmit={submit} className="narrow-form">
      <Field label="Current password" type="password" value={current} onChange={setCurrent} autoComplete="current-password" />
      <Field label="New password (min. 8 characters)" type="password" value={password} onChange={setPassword} autoComplete="new-password" />
      <Field label="Repeat new password" type="password" value={confirm} onChange={setConfirm} autoComplete="new-password" />
      {error && <div className="error small-gap">{error}</div>}
      {msg && <div className="info">{msg}</div>}
      <button className="primary" disabled={busy}>{busy ? 'Saving…' : 'Change password'}</button>
    </form>
  )
}
