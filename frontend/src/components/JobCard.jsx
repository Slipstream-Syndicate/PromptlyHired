import { useState } from 'react'
import ApplyLink from './ApplyLink.jsx'

const JOB_TYPE_LABELS = {
  full_time: 'Full-time',
  part_time: 'Part-time',
  contract: 'Contract',
  remote: 'Remote',
}

function Logo({ company }) {
  if (company.logo_url) {
    return <img className="logo" src={company.logo_url} alt="" loading="lazy" />
  }
  return (
    <div className="logo logo-fallback" aria-hidden="true">
      {company.name.slice(0, 1).toUpperCase()}
    </div>
  )
}

/**
 * Save and Follow are independent actions, never a combined toggle:
 * saving shortlists the job, following the company subscribes to notifications.
 */
export default function JobCard({ job, pinned, onToggleSave, onToggleFollow, onApplied }) {
  const [busy, setBusy] = useState(null)

  const run = async (key, fn) => {
    setBusy(key)
    try {
      await fn()
    } finally {
      setBusy(null)
    }
  }

  return (
    <article className={pinned ? 'card pinned' : 'card'}>
      <div className="job-top">
        <Logo company={job.company} />
        <div className="job-main">
          <h3 className="job-title">
            {job.url ? (
              <a href={job.url} target="_blank" rel="noopener noreferrer">
                {job.title}
              </a>
            ) : (
              job.title
            )}
          </h3>
          <p className="job-company">{job.company.name}</p>
        </div>
      </div>

      <div className="job-meta">
        {job.location && <span className="chip">{job.location}</span>}
        {job.job_type && <span className="chip">{JOB_TYPE_LABELS[job.job_type]}</span>}
        {job.salary_range && <span className="chip salary">{job.salary_range}</span>}
        {job.posted_date && <span className="chip">Posted {job.posted_date}</span>}
      </div>

      <div className="job-actions">
        <ApplyLink job={job} />

        {onToggleSave && (
          <button
            className={job.is_saved ? 'btn on' : 'btn'}
            disabled={busy === 'save'}
            onClick={() => run('save', () => onToggleSave(job))}
            aria-pressed={job.is_saved}
          >
            {job.is_saved ? '♥ Saved' : '♡ Save'}
          </button>
        )}

        {onToggleFollow && (
          <button
            className={job.is_company_followed ? 'btn on' : 'btn'}
            disabled={busy === 'follow'}
            onClick={() => run('follow', () => onToggleFollow(job))}
            aria-pressed={job.is_company_followed}
            title="Get notified about new jobs from this company"
          >
            {job.is_company_followed ? '✓ Following' : '+ Follow company'}
          </button>
        )}

        {onApplied && !job.application_status && (
          <button
            className="btn"
            disabled={busy === 'apply'}
            onClick={() => run('apply', () => onApplied(job))}
          >
            I applied
          </button>
        )}

        {job.application_status && (
          <span className="status" data-s={job.application_status}>
            Tracked
          </span>
        )}
      </div>
    </article>
  )
}
