import { useEffect, useState } from 'react'
import { api } from '../api/client'
import AvatarUpload from '../components/AvatarUpload.jsx'
import ResumePanel from '../components/ResumePanel.jsx'
import { useAuth } from '../context/AuthContext.jsx'

export default function Profile() {
  const { user, setUser, logout } = useAuth()
  const [name, setName] = useState(user?.name ?? '')
  const [resume, setResume] = useState(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.getActiveResume().then(setResume).catch((err) => setError(err.message))
  }, [])

  const save = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    setMessage('')
    try {
      setUser(await api.updateProfile({ name }))
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

      {/* Resume first: it is the thing the whole product is built around. */}
      <ResumePanel resume={resume} onChange={setResume} />

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
        <button className="btn primary block" type="submit" disabled={busy}>
          {busy ? 'Saving…' : 'Save changes'}
        </button>
      </form>

      <button className="btn danger block" onClick={logout}>
        Sign out
      </button>
    </main>
  )
}
