import { Link } from 'react-router-dom'
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
 * A feed card. Deliberately shows no match percentage: scoring is one API call
 * per job, so it happens when the user opens a card, not across the whole feed.
 */
export default function JobCard({ job, onToggleSave, busy }) {
  return (
    <article className="card">
      <div className="job-top">
        <Logo company={job.company} />
        <div className="job-main">
          <h3 className="job-title">
            <Link to={`/jobs/${job.id}`}>{job.title}</Link>
          </h3>
          <p className="job-company">{job.company.name}</p>
          {job.company.short_description && (
            <p className="job-blurb">{job.company.short_description}</p>
          )}
        </div>
      </div>

      <div className="job-meta">
        {job.location && <span className="chip">{job.location}</span>}
        {job.job_type && <span className="chip">{JOB_TYPE_LABELS[job.job_type]}</span>}
        {job.salary_range && <span className="chip salary">{job.salary_range}</span>}
        {job.has_match && <span className="chip analysed">✓ Analysed</span>}
        {job.has_documents && <span className="chip analysed">📄 Documents</span>}
      </div>

      <div className="job-actions">
        <ApplyLink job={job} />

        <Link className="btn" to={`/jobs/${job.id}`}>
          View match
        </Link>

        {onToggleSave && (
          <button
            className={job.is_saved ? 'btn on' : 'btn'}
            disabled={busy}
            onClick={() => onToggleSave(job)}
            aria-pressed={job.is_saved}
          >
            {job.is_saved ? '♥ Saved' : '♡ Save'}
          </button>
        )}
      </div>
    </article>
  )
}
