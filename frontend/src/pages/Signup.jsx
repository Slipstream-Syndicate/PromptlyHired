import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext.jsx'

export default function Signup() {
  const { signup } = useAuth()
  const [form, setForm] = useState({ name: '', email: '', password: '' })
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await signup(form.name, form.email, form.password)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="auth">
      <form className="auth-card" onSubmit={submit}>
        <h1>Create account</h1>
        <p className="sub">Start tracking your job search.</p>

        {error && <div className="alert error">{error}</div>}

        <label className="field">
          <span>Name</span>
          <input value={form.name} onChange={set('name')} autoComplete="name" required />
        </label>

        <label className="field">
          <span>Email</span>
          <input
            type="email"
            value={form.email}
            onChange={set('email')}
            autoComplete="email"
            required
          />
        </label>

        <label className="field">
          <span>Password</span>
          <input
            type="password"
            value={form.password}
            onChange={set('password')}
            autoComplete="new-password"
            minLength={8}
            maxLength={72}
            required
          />
        </label>

        <button className="btn primary block" type="submit" disabled={busy}>
          {busy ? 'Creating…' : 'Create account'}
        </button>

        <p className="sub" style={{ marginTop: 16, marginBottom: 0 }}>
          Already have an account? <Link to="/login">Sign in</Link>
        </p>
      </form>
    </div>
  )
}
