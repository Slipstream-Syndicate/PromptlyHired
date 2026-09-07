import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import JobCard from '../components/JobCard.jsx'

export default function SavedJobs() {
  const [rows, setRows] = useState([])
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .listSaved()
      .then(setRows)
      .catch((err) => setError(err.message))
      .finally(() => setBusy(false))
  }, [])

  const unsave = async (job) => {
    const previous = rows
    setRows((r) => r.filter((row) => row.job.id !== job.id))
    try {
      await api.unsaveJob(job.id)
    } catch (err) {
      setRows(previous)
      setError(err.message)
    }
  }

  return (
    <main className="page">
      <div className="page-header">
        <h1>Saved jobs</h1>
        <span className="count-pill">{rows.length} shortlisted</span>
      </div>

      {error && <div className="alert error">{error}</div>}
      {busy && <div className="empty">Loading…</div>}

      {!busy && rows.length === 0 && (
        <div className="empty">
          <h2>Nothing saved yet</h2>
          <p>Tap the heart on any listing to shortlist it here.</p>
          <Link className="btn primary" to="/">Browse jobs</Link>
        </div>
      )}

      {rows.map((row) => (
        <JobCard key={row.job.id} job={row.job} onToggleSave={unsave} />
      ))}
    </main>
  )
}
