import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import JobCard from '../components/JobCard.jsx'

/**
 * The main page. There is no job feed: every job-board API is paid,
 * partner-only or retired, and bulk-scraping them is against their terms. So
 * jobs enter one at a time, by the user pasting a link to one they found.
 */
function AddJob({ onAdded }) {
  const [mode, setMode] = useState('url')
  const [url, setUrl] = useState('')
  const [text, setText] = useState('')
  const [title, setTitle] = useState('')
  const [company, setCompany] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      const job =
        mode === 'url'
          ? await api.addJobFromUrl(url)
          : await api.addJobFromText({ text, title, company, url: url || undefined })
      setUrl('')
      setText('')
      setTitle('')
      setCompany('')
      onAdded(job)
    } catch (err) {
      setError(err.message)
      // Sites that block server-side fetches are common enough that the
      // fallback should be offered rather than explained.
      if (mode === 'url' && /blocked|could not find|not be reached/i.test(err.message)) {
        setMode('text')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="card" onSubmit={submit}>
      <h2 className="section-title" style={{ marginTop: 0 }}>
        Add a job
      </h2>

      <div className="job-actions" style={{ marginTop: 0, marginBottom: 12 }}>
        <button
          type="button"
          className={mode === 'url' ? 'btn on' : 'btn'}
          onClick={() => setMode('url')}
        >
          Paste a link
        </button>
        <button
          type="button"
          className={mode === 'text' ? 'btn on' : 'btn'}
          onClick={() => setMode('text')}
        >
          Paste the text
        </button>
      </div>

      {error && <div className="alert error">{error}</div>}

      {mode === 'url' ? (
        <>
          <label className="field">
            <span>Job posting URL</span>
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://…"
              required
            />
          </label>
          <p className="fine-print">
            Works with most company careers pages and job boards. Some sites
            (LinkedIn and Indeed among them) block automated fetches — if that
            happens, switch to “Paste the text”.
          </p>
        </>
      ) : (
        <>
          <div className="filter-grid">
            <label className="field">
              <span>Job title</span>
              <input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} />
            </label>
            <label className="field">
              <span>Company</span>
              <input value={company} onChange={(e) => setCompany(e.target.value)} maxLength={200} />
            </label>
          </div>
          <label className="field">
            <span>Link to the posting (optional, for the Apply button)</span>
            <input type="url" value={url} onChange={(e) => setUrl(e.target.value)} />
          </label>
          <label className="field">
            <span>Job description</span>
            <textarea
              rows={10}
              value={text}
              onChange={(e) => setText(e.target.value)}
              placeholder="Copy the whole advert and paste it here…"
              required
              minLength={200}
            />
          </label>
        </>
      )}

      <button className="btn primary block" type="submit" disabled={busy}>
        {busy ? 'Reading the job…' : 'Add job'}
      </button>
    </form>
  )
}

export default function Jobs() {
  const navigate = useNavigate()
  const [jobs, setJobs] = useState([])
  const [resume, setResume] = useState(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([api.listJobs(), api.getActiveResume()])
      .then(([j, r]) => {
        setJobs(j)
        setResume(r)
      })
      .catch((err) => setError(err.message))
      .finally(() => setBusy(false))
  }, [])

  const onAdded = (job) => {
    setJobs((current) => [job, ...current.filter((j) => j.id !== job.id)])
    navigate(`/jobs/${job.id}`)
  }

  const toggleSave = async (job) => {
    const next = !job.is_saved
    setJobs((c) => c.map((j) => (j.id === job.id ? { ...j, is_saved: next } : j)))
    try {
      await (next ? api.saveJob(job.id) : api.unsaveJob(job.id))
    } catch (err) {
      setJobs((c) => c.map((j) => (j.id === job.id ? { ...j, is_saved: !next } : j)))
      setError(err.message)
    }
  }

  return (
    <main className="page">
      <div className="page-header">
        <h1>Jobs</h1>
      </div>

      {!busy && !resume && (
        <div className="alert info">
          <strong>Upload your resume first.</strong> Matching and document
          generation are both built on it. <Link to="/profile">Go to Profile →</Link>
        </div>
      )}

      <AddJob onAdded={onAdded} />

      {error && <div className="alert error">{error}</div>}
      {busy && <div className="empty">Loading…</div>}

      {!busy && jobs.length === 0 && (
        <div className="empty">
          <h2>No jobs yet</h2>
          <p>
            Found a role you like? Paste its link above and we’ll score it against
            your resume and write you a tailored application.
          </p>
        </div>
      )}

      {jobs.length > 0 && <h2 className="section-title">Your jobs</h2>}
      {jobs.map((job) => (
        <JobCard key={job.id} job={job} onToggleSave={toggleSave} />
      ))}
    </main>
  )
}
