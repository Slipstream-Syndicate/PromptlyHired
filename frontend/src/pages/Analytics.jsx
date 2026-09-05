import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import { STATUS_ICONS, STATUS_LABELS } from '../components/StatusBadge.jsx'

const FUNNEL_ORDER = ['applied', 'online_assessment', 'interview', 'offer']
const OUTCOME_ORDER = ['rejected', 'withdrawn']

/** A headline number is a stat tile, not a chart. */
function Stat({ label, value, suffix, hint }) {
  return (
    <div className="stat">
      <div className="stat-value">
        {value}
        {suffix && <span className="stat-suffix">{suffix}</span>}
      </div>
      <div className="stat-label">{label}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  )
}

/**
 * Horizontal bars. Every bar is directly labelled with its name and count, so
 * identity never depends on colour — which matters because offer/rejected are a
 * red/green pair.
 */
function StatusBars({ counts, total }) {
  const rows = [...FUNNEL_ORDER, ...OUTCOME_ORDER].filter((s) => counts[s] > 0)
  if (!rows.length) return null
  const max = Math.max(...rows.map((s) => counts[s]))

  return (
    <div className="bars">
      {rows.map((s) => (
        <div className="bar-row" key={s}>
          <div className="bar-label">
            <span aria-hidden="true">{STATUS_ICONS[s]}</span> {STATUS_LABELS[s]}
          </div>
          <div className="bar-track">
            <div
              className="bar-fill"
              data-s={s}
              style={{ width: `${Math.max(2, (counts[s] / max) * 100)}%` }}
              title={`${STATUS_LABELS[s]}: ${counts[s]} of ${total}`}
            />
          </div>
          <div className="bar-value">{counts[s]}</div>
        </div>
      ))}
    </div>
  )
}

/** Single series over time — the heading names it, so no legend box. */
function WeeklyBars({ data }) {
  const max = Math.max(1, ...data.map((d) => d.applications))
  return (
    <div className="spark">
      {data.map((d) => (
        <div className="spark-col" key={d.week} title={`Week of ${d.week}: ${d.applications}`}>
          <div
            className="spark-bar"
            style={{ height: `${(d.applications / max) * 100}%` }}
            data-empty={d.applications === 0 ? 'true' : 'false'}
          />
        </div>
      ))}
    </div>
  )
}

export default function Analytics() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .analyticsFunnel()
      .then(setData)
      .catch((err) => setError(err.message))
  }, [])

  if (error) {
    return (
      <main className="page">
        <div className="alert error">{error}</div>
      </main>
    )
  }
  if (!data) return <main className="page"><div className="empty">Loading…</div></main>

  const empty = data.total_applications === 0

  return (
    <main className="page">
      <div className="page-header">
        <h1>Your funnel</h1>
        <Link to="/profile" className="count-pill">
          ‹ Profile
        </Link>
      </div>

      {empty ? (
        <div className="empty">
          <h2>Nothing to analyse yet</h2>
          <p>Log a few applications and your response rates will show up here.</p>
        </div>
      ) : (
        <>
          <div className="stat-grid">
            <Stat label="Applications" value={data.total_applications} />
            <Stat
              label="Response rate"
              value={data.response_rate}
              suffix="%"
              hint={`${data.responded} heard back`}
            />
            <Stat
              label="Interview rate"
              value={data.interview_rate}
              suffix="%"
              hint={`${data.interviews} reached interview`}
            />
            <Stat
              label="Median reply time"
              value={data.median_days_to_response ?? '—'}
              suffix={data.median_days_to_response == null ? '' : ' days'}
              hint={data.median_days_to_response == null ? 'No replies logged yet' : null}
            />
          </div>

          <h2 className="section-title">Where your applications stand</h2>
          <div className="card">
            <StatusBars counts={data.by_status} total={data.total_applications} />
            <p className="job-company" style={{ marginTop: 12 }}>
              {data.awaiting_reply} still open · {data.offers} offer
              {data.offers === 1 ? '' : 's'} · {data.rejected} rejected
            </p>
          </div>

          <h2 className="section-title">Applications per week (last 12)</h2>
          <div className="card">
            <WeeklyBars data={data.applications_over_time} />
          </div>

          {data.needs_follow_up.length > 0 && (
            <>
              <h2 className="section-title">
                <span className="dot" />
                Worth a follow-up
              </h2>
              <div className="card">
                {data.needs_follow_up.map((row) => (
                  <div className="list-row" key={row.application_id}>
                    <div className="job-main">
                      <div className="job-title">{row.title}</div>
                      <p className="job-company">
                        {row.company} · {STATUS_LABELS[row.status]} · quiet for{' '}
                        {row.days_quiet} days
                      </p>
                    </div>
                  </div>
                ))}
                <p className="job-company" style={{ marginTop: 10 }}>
                  Flagged after {data.follow_up_after_days} days with no status change.
                </p>
              </div>
            </>
          )}

          {data.companies.length > 0 && (
            <>
              <h2 className="section-title">By company</h2>
              <div className="card table-wrap">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th>Company</th>
                      <th>Applied</th>
                      <th>Replied</th>
                      <th>Interviews</th>
                      <th>Response rate</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.companies.map((row) => (
                      <tr key={row.company}>
                        <td>{row.company}</td>
                        <td>{row.applications}</td>
                        <td>{row.responses}</td>
                        <td>{row.interviews}</td>
                        <td>{row.response_rate}%</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </>
          )}

          {data.tracked_events === 0 && (
            <div className="alert info">
              Status history starts from when this feature shipped, so rates for
              older applications are based on their current status alone.
            </div>
          )}
        </>
      )}
    </main>
  )
}
