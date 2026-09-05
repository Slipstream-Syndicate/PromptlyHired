import { useEffect, useState } from 'react'
import { api } from '../api/client'
import ApplyLink from '../components/ApplyLink.jsx'
import StatusBadge, { STATUS_LABELS, nextStatus } from '../components/StatusBadge.jsx'

const ALL_STATUSES = Object.keys(STATUS_LABELS)

function ApplicationRow({ row, onChange, onDelete }) {
  const [notes, setNotes] = useState(row.notes ?? '')
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)

  const advance = () => onChange(row.id, { status: nextStatus(row.status) })

  const saveNotes = async () => {
    setSaving(true)
    try {
      await onChange(row.id, { notes })
      setDirty(false)
    } finally {
      setSaving(false)
    }
  }

  return (
    <article className="card">
      <div className="row-between">
        <div className="job-main">
          <h3 className="job-title">
            {row.job.url ? (
              <a href={row.job.url} target="_blank" rel="noopener noreferrer">
                {row.job.title}
              </a>
            ) : (
              row.job.title
            )}
          </h3>
          <p className="job-company">
            {row.job.company.name}
            {row.job.location ? ` · ${row.job.location}` : ''}
          </p>
        </div>
        <StatusBadge status={row.status} onClick={advance} />
      </div>

      <div className="job-meta">
        <span className="chip">Applied {row.applied_date}</span>
        {row.needs_follow_up && (
          <span
            className="chip follow-up-flag"
            title={'No status change in ' + row.days_since_update + ' days'}
          >
            ⏰ Follow up — quiet {row.days_since_update} days
          </span>
        )}
        {row.job.salary_range && <span className="chip salary">{row.job.salary_range}</span>}
      </div>

      <div className="job-actions">
        <label className="field" style={{ margin: 0 }}>
          <select
            value={row.status}
            onChange={(e) => onChange(row.id, { status: e.target.value })}
            aria-label="Application status"
          >
            {ALL_STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABELS[s]}
              </option>
            ))}
          </select>
        </label>
        <ApplyLink job={row.job} variant="view" />
        <button className="btn danger" onClick={() => onDelete(row.id)}>
          Remove
        </button>
      </div>

      <textarea
        className="notes"
        placeholder="Notes — recruiter name, interview date, follow-ups…"
        value={notes}
        maxLength={10000}
        onChange={(e) => {
          setNotes(e.target.value)
          setDirty(true)
        }}
      />
      {dirty && (
        <button className="btn" onClick={saveNotes} disabled={saving}>
          {saving ? 'Saving…' : 'Save notes'}
        </button>
      )}
    </article>
  )
}

export default function Applications() {
  const [rows, setRows] = useState([])
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    ;(async () => {
      try {
        setRows(await api.listApplications())
      } catch (err) {
        setError(err.message)
      } finally {
        setBusy(false)
      }
    })()
  }, [])

  const change = async (id, payload) => {
    try {
      const updated = await api.updateApplication(id, payload)
      setRows((r) => r.map((row) => (row.id === id ? updated : row)))
    } catch (err) {
      setError(err.message)
    }
  }

  const remove = async (id) => {
    const previous = rows
    setRows((r) => r.filter((row) => row.id !== id))
    try {
      await api.deleteApplication(id)
    } catch (err) {
      setRows(previous)
      setError(err.message)
    }
  }

  return (
    <main className="page">
      <div className="page-header">
        <h1>Applications</h1>
        <span className="count-pill">
          {rows.length} tracked
          {rows.some((r) => r.needs_follow_up) &&
            ' · ' + rows.filter((r) => r.needs_follow_up).length + ' need follow-up'}
        </span>
      </div>

      {error && <div className="alert error">{error}</div>}
      {busy && <div className="empty">Loading…</div>}

      {!busy && rows.length === 0 && (
        <div className="empty">
          <h2>No applications yet</h2>
          <p>Hit “I applied” on a job and it will show up here.</p>
        </div>
      )}

      {rows.map((row) => (
        <ApplicationRow key={row.id} row={row} onChange={change} onDelete={remove} />
      ))}
    </main>
  )
}
