import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'

export default function FollowedCompanies() {
  const [rows, setRows] = useState([])
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    ;(async () => {
      try {
        setRows(await api.listFollows())
      } catch (err) {
        setError(err.message)
      } finally {
        setBusy(false)
      }
    })()
  }, [])

  const unfollow = async (companyId) => {
    const previous = rows
    setRows((r) => r.filter((row) => row.company.id !== companyId))
    try {
      await api.unfollowCompany(companyId)
    } catch (err) {
      setRows(previous)
      setError(err.message)
    }
  }

  return (
    <main className="page">
      <div className="page-header">
        <h1>Followed companies</h1>
        <Link to="/profile" className="count-pill">
          ‹ Profile
        </Link>
      </div>

      <div className="alert info">
        New listings from these companies get emailed to you and pinned to the top of
        your homepage feed. Saving a job does not follow its company.
      </div>

      {error && <div className="alert error">{error}</div>}
      {busy && <div className="empty">Loading…</div>}

      {!busy && rows.length === 0 && (
        <div className="empty">
          <h2>Not following anyone yet</h2>
          <p>Use “Follow company” on any listing to get notified about new roles.</p>
        </div>
      )}

      {rows.length > 0 && (
        <div className="card">
          {rows.map((row) => (
            <div className="list-row" key={row.company.id}>
              {row.company.logo_url ? (
                <img className="logo" src={row.company.logo_url} alt="" />
              ) : (
                <div className="logo logo-fallback" aria-hidden="true">
                  {row.company.name.slice(0, 1).toUpperCase()}
                </div>
              )}
              <div className="job-main">
                <div className="job-title">{row.company.name}</div>
              </div>
              <button className="btn danger" onClick={() => unfollow(row.company.id)}>
                Unfollow
              </button>
            </div>
          ))}
        </div>
      )}
    </main>
  )
}
