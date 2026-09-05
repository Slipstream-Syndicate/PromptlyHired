import { useCallback, useEffect, useState } from 'react'
import { api } from '../api/client'
import FilterBar from '../components/FilterBar.jsx'
import JobCard from '../components/JobCard.jsx'

function toParams(form) {
  return {
    keywords: form.keywords || undefined,
    location: form.location || undefined,
    salary_min: form.salary_min === '' ? undefined : form.salary_min,
    salary_max: form.salary_max === '' ? undefined : form.salary_max,
    job_type: form.job_type || undefined,
  }
}

/** Cursor pages can overlap, and duplicate React keys would break rendering. */
function mergeJobs(existing, incoming) {
  const seen = new Set(existing.map((j) => j.id))
  return [...existing, ...incoming.filter((j) => !seen.has(j.id))]
}

export default function Home() {
  const [data, setData] = useState({ followed: [], results: [], preferences: null })
  const [busy, setBusy] = useState(true)
  const [loadingMore, setLoadingMore] = useState(false)
  const [lastParams, setLastParams] = useState({ use_saved_preferences: true })
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

  // Cursor pagination: append the next page instead of replacing the list.
  const loadMore = async () => {
    if (!data.next_cursor || loadingMore) return
    setLoadingMore(true)
    setError('')
    try {
      const next = await api.searchJobs({ ...lastParams, cursor: data.next_cursor })
      setData((d) => ({
        ...next,
        followed: mergeJobs(d.followed, next.followed),
        results: mergeJobs(d.results, next.results),
      }))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoadingMore(false)
    }
  }

  // On login the homepage auto-runs a search from the stored preferences.
  useEffect(() => {
    runSearch({ use_saved_preferences: true })
  }, [runSearch])

  // Patch one job in place so a Save/Follow toggle does not re-run the search.
  const patchJob = (jobId, changes) =>
    setData((d) => ({
      ...d,
      followed: d.followed.map((j) => (j.id === jobId ? { ...j, ...changes } : j)),
      results: d.results.map((j) => (j.id === jobId ? { ...j, ...changes } : j)),
    }))

  const patchCompany = (companyId, changes) =>
    setData((d) => ({
      ...d,
      followed: d.followed.map((j) =>
        j.company.id === companyId ? { ...j, ...changes } : j,
      ),
      results: d.results.map((j) =>
        j.company.id === companyId ? { ...j, ...changes } : j,
      ),
    }))

  const toggleSave = async (job) => {
    const next = !job.is_saved
    patchJob(job.id, { is_saved: next })
    try {
      await (next ? api.saveJob(job.id) : api.unsaveJob(job.id))
    } catch (err) {
      patchJob(job.id, { is_saved: !next })
      setError(err.message)
    }
  }

  const toggleFollow = async (job) => {
    const next = !job.is_company_followed
    patchCompany(job.company.id, { is_company_followed: next })
    try {
      await (next
        ? api.followCompany(job.company.id)
        : api.unfollowCompany(job.company.id))
    } catch (err) {
      patchCompany(job.company.id, { is_company_followed: !next })
      setError(err.message)
    }
  }

  const markApplied = async (job) => {
    try {
      await api.createApplication({ job_id: job.id })
      patchJob(job.id, { application_status: 'applied', is_saved: false })
    } catch (err) {
      setError(err.message)
    }
  }

  const cardProps = {
    onToggleSave: toggleSave,
    onToggleFollow: toggleFollow,
    onApplied: markApplied,
  }

  return (
    <main className="page">
      <div className="page-header">
        <h1>Find jobs</h1>
      </div>

      <FilterBar
        value={data.preferences}
        busy={busy}
        onSearch={(form) => runSearch(toParams(form))}
      />

      {data.source === 'sample' && (
        <div className="alert info">
          Showing sample listings. Add a <code>RAPIDAPI_KEY</code> to{' '}
          <code>backend/.env</code> for live JSearch results.
        </div>
      )}

      {error && <div className="alert error">{error}</div>}

      {busy && <div className="empty">Searching…</div>}

      {!busy && data.followed.length > 0 && (
        <>
          <h2 className="section-title">
            <span className="dot" />
            New from companies you follow
          </h2>
          {data.followed.map((job) => (
            <JobCard key={job.id} job={job} pinned {...cardProps} />
          ))}
        </>
      )}

      {!busy && data.results.length > 0 && (
        <>
          {data.followed.length > 0 && <h2 className="section-title">All results</h2>}
          {data.results.map((job) => (
            <JobCard key={job.id} job={job} {...cardProps} />
          ))}
        </>
      )}

      {!busy && data.next_cursor && (data.followed.length > 0 || data.results.length > 0) && (
        <button className="btn block" onClick={loadMore} disabled={loadingMore}>
          {loadingMore ? 'Loading…' : 'Load more jobs'}
        </button>
      )}

      {!busy && !error && data.followed.length === 0 && data.results.length === 0 && (
        <div className="empty">
          <h2>No jobs found</h2>
          <p>Try broadening your keywords or clearing the salary filters.</p>
        </div>
      )}
    </main>
  )
}
