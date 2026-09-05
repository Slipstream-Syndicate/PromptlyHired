/**
 * Outbound link to the original job posting.
 *
 * The app tracks applications, it does not host them, so this is the only route
 * from browsing to actually applying. Required on every listing. Opens in a new
 * tab so the user does not lose their place in the feed, and names its
 * destination where the source board is known.
 */
export default function ApplyLink({ job, variant = 'apply' }) {
  // No usable link: render nothing rather than a dead button.
  if (!job.url) return null

  const isView = variant === 'view'
  const label = job.source_publisher
    ? `${isView ? 'View on' : 'Apply on'} ${job.source_publisher}`
    : isView
      ? 'View posting'
      : 'Apply'

  return (
    <a
      className={variant === 'view' ? 'btn' : 'btn primary'}
      href={job.url}
      target="_blank"
      rel="noopener noreferrer"
      title={`Opens ${job.source_publisher || 'the original posting'} in a new tab`}
    >
      {label}
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        <path d="M14 4h6v6M20 4l-8 8M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />
      </svg>
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  )
}
