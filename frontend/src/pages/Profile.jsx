import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import AvatarUpload from '../components/AvatarUpload.jsx'
import NotificationSettings from '../components/NotificationSettings.jsx'
import { useAuth } from '../context/AuthContext.jsx'

export default function Profile() {
  const { user, setUser, logout } = useAuth()
  const [name, setName] = useState(user?.name ?? '')
  const [prefs, setPrefs] = useState(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.getPreferences().then(setPrefs).catch((err) => setError(err.message))
  }, [])

  const setPref = (key) => (e) =>
    setPrefs((p) => ({ ...p, [key]: e.target.value === '' ? null : e.target.value }))

  const save = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const updated = await api.updateProfile({ name })
      setUser(updated)
      // The same fields back the homepage search filters - saving here is
      // saving the search defaults.
      setPrefs(
        await api.savePreferences({
          keywords: prefs?.keywords || null,
          location: prefs?.location || null,
          salary_min: prefs?.salary_min === '' ? null : prefs?.salary_min ?? null,
          salary_max: prefs?.salary_max === '' ? null : prefs?.salary_max ?? null,
          job_type: prefs?.job_type || null,
        }),
      )
      setMessage('Saved.')
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="page">
      <div className="page-header">
        <h1>Profile</h1>
      </div>

      {error && <div className="alert error">{error}</div>}
      {message && <div className="alert info">{message}</div>}

      <div className="card">
        <AvatarUpload user={user} onChange={setUser} />
      </div>

      <form className="card" onSubmit={save}>
        <label className="field">
          <span>Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} />
        </label>

        <label className="field">
          <span>Email</span>
          <input value={user?.email ?? ''} disabled />
        </label>

        <h2 className="section-title">Job preferences</h2>
        <p className="job-company" style={{ marginBottom: 12 }}>
          These are the defaults your homepage search runs with.
        </p>

        <label className="field">
          <span>Job title or keywords</span>
          <input
            value={prefs?.keywords ?? ''}
            onChange={setPref('keywords')}
            maxLength={255}
          />
        </label>

        <label className="field">
          <span>Location</span>
          <input
            value={prefs?.location ?? ''}
            onChange={setPref('location')}
            maxLength={255}
          />
        </label>

        <label className="field">
          <span>Job type</span>
          <select value={prefs?.job_type ?? ''} onChange={setPref('job_type')}>
            <option value="">Any</option>
            <option value="full_time">Full-time</option>
            <option value="part_time">Part-time</option>
            <option value="contract">Contract</option>
            <option value="remote">Remote</option>
          </select>
        </label>

        <label className="field">
          <span>Min salary</span>
          <input
            type="number"
            min="0"
            value={prefs?.salary_min ?? ''}
            onChange={setPref('salary_min')}
          />
        </label>

        <label className="field">
          <span>Max salary</span>
          <input
            type="number"
            min="0"
            value={prefs?.salary_max ?? ''}
            onChange={setPref('salary_max')}
          />
        </label>

        <button className="btn primary block" type="submit" disabled={busy}>
          {busy ? 'Saving…' : 'Save changes'}
        </button>
      </form>

      <NotificationSettings />

      <div className="card">
        <Link to="/profile/analytics" className="row-between" style={{ color: 'inherit' }}>
          <span>Your funnel &amp; follow-ups</span>
          <span className="count-pill">›</span>
        </Link>
      </div>

      <div className="card">
        <Link to="/profile/companies" className="row-between" style={{ color: 'inherit' }}>
          <span>Followed companies</span>
          <span className="count-pill">›</span>
        </Link>
      </div>

      <button className="btn danger block" onClick={logout}>
        Sign out
      </button>
    </main>
  )
}
