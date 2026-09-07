import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import FilterBar from '../components/FilterBar.jsx'
import JobCard from '../components/JobCard.jsx'

/** Cursor pages can overlap; duplicate React keys would break rendering. */
function mergeJobs(existing, incoming) {
  const seen = new Set(existing.map((j) => j.id))
  return [...existing, ...incoming.filter((j) => !seen.has(j.id))]
}

export default function Jobs() {
  const [data, setData] = useState({ results: [], source: null, searched_for: null })
  const [busy, setBusy] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [lastParams, setLastParams] = useState({})
  const [error, setError] = useState('')

  const runSearch = useCallback(async (params) => {
    setBusy(true)
    setError('')
    setLastParams(params)
    try {
      setData(await api.searchJobs(params))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }, [])

  // The whole point: on load the feed populates from the resume, with no
  // keywords typed by the user.
  useEffect(() => {
    runSearch({})
  }, [runSearch])

  const loadMore = async () => {
    if (!data.next_cursor || loadingMore) return
    setLoadingMore(true)
    try {
      const next = await api.searchJobs({ ...lastParams, cursor: data.next_cursor })
      setData((d) => ({ ...next, results: mergeJobs(d.results, next.results) }))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoadingMore(false)
    }
  }

  const toggleSave = async (job) => {
    const next = !job.is_saved
    setData((d) => ({
      ...d,
      results: d.results.map((j) => (j.id === job.id ? { ...j, is_saved: next } : j)),
    }))
    try {
      await (next ? api.saveJob(job.id) : api.unsaveJob(job.id))
    } catch (err) {
      setData((d) => ({
        ...d,
        results: d.results.map((j) => (j.id === job.id ? { ...j, is_saved: !next } : j)),
      }))
      setError(err.message)
    }
  }

  const needsResume = !busy && data.source === 'none'

  return (
    <main className="page">
      <div className="page-header">
        <h1>Jobs for you</h1>
        {data.searched_for && (
          <span className="count-pill" title="Derived from your resume">
            {data.searched_for}
          </span>
        )}
      </div>

      {needsResume ? (
        <div className="empty">
          <h2>Upload your resume first</h2>
          <p>
            Everything here is built around it — we read your resume, work out your
            skillset, and search for matching roles automatically.
          </p>
          <Link className="btn primary" to="/profile">
            Go to Profile
          </Link>
        </div>
      ) : (
        <>
          <FilterBar busy={busy} onSearch={runSearch} />

          {data.source === 'sample' && (
            <div className="alert info">
              Showing sample listings. Add a <code>RAPIDAPI_KEY</code> to{' '}
              <code>backend/.env</code> for live results.
            </div>
          )}

          {error && <div className="alert error">{error}</div>}
          {busy && <div className="empty">Finding jobs that fit your resume…</div>}

          {!busy &&
            data.results.map((job) => (
              <JobCard key={job.id} job={job} onToggleSave={toggleSave} />
            ))}

          {!busy && data.next_cursor && data.results.length > 0 && (
            <button className="btn block" onClick={loadMore} disabled={loadingMore}>
              {loadingMore ? 'Loading…' : 'Load more jobs'}
            </button>
          )}

          {!busy && !error && data.results.length === 0 && (
            <div className="empty">
              <h2>No jobs found</h2>
              <p>
                Try widening the filters, or adjust your skill profile on the Profile
                page — that is what the search is built from.
              </p>
            </div>
          )}
        </>
      )}
    </main>
  )
}
