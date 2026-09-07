import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import ApplyLink from '../components/ApplyLink.jsx'

/** The record of work done: every job documents were generated for. */
export default function History() {
  const [entries, setEntries] = useState([])
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .history()
      .then(setEntries)
      .catch((err) => setError(err.message))
      .finally(() => setBusy(false))
  }, [])

  return (
    <main className="page">
      <div className="page-header">
        <h1>History</h1>
        <span className="count-pill">{entries.length} prepared</span>
      </div>

      {error && <div className="alert error">{error}</div>}
      {busy && <div className="empty">Loading…</div>}

      {!busy && entries.length === 0 && (
        <div className="empty">
          <h2>Nothing prepared yet</h2>
          <p>
            Open a job, generate a resume or cover letter, and it will be kept here so
            you can come back to it.
          </p>
          <Link className="btn primary" to="/">Browse jobs</Link>
        </div>
      )}

      {entries.map((entry) => (
        <article className="card" key={entry.job.id}>
          <div className="job-top">
            <div className="job-main">
              <h3 className="job-title">
                <Link to={`/jobs/${entry.job.id}`}>{entry.job.title}</Link>
              </h3>
              <p className="job-company">
                {entry.job.company.name}
                {entry.job.location ? ` · ${entry.job.location}` : ''}
              </p>
            </div>
          </div>

          <div className="job-meta">
            <span className="chip">
              Prepared {new Date(entry.last_generated_at).toLocaleDateString()}
            </span>
            {entry.documents.map((doc) => (
              <Link className="chip analysed" key={doc.id} to={`/documents/${doc.id}`}>
                {doc.kind === 'resume' ? '📄 Resume' : '✉ Cover letter'}
                {doc.edited_content ? ' (edited)' : ''}
              </Link>
            ))}
          </div>

          {/* Still the only route to actually applying. */}
          <div className="job-actions">
            <ApplyLink job={entry.job} variant="view" />
          </div>
        </article>
      ))}
    </main>
  )
}
