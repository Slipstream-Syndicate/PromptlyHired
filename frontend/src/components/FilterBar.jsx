import { useState } from 'react'

const BLANK = { keywords: '', location: '', salary_min: '', job_type: '' }

/**
 * Narrows the resume-driven feed. These are transient query parameters, not
 * stored preferences - the skill profile on Profile is the persistent thing,
 * and keeping two sources of "what to search for" would let them drift.
 */
export default function FilterBar({ onSearch, busy }) {
  const [form, setForm] = useState(BLANK)
  const [open, setOpen] = useState(false)

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))

  const submit = (event) => {
    event.preventDefault()
    onSearch({
      keywords: form.keywords || undefined,
      location: form.location || undefined,
      salary_min: form.salary_min === '' ? undefined : form.salary_min,
      job_type: form.job_type || undefined,
    })
  }

  const clear = () => {
    setForm(BLANK)
    onSearch({})
  }

  return (
    <form className="filters" onSubmit={submit}>
      <button
        className="btn link filter-toggle"
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        {open ? '− Hide filters' : '+ Narrow these results'}
      </button>

      {open && (
        <>
          <div className="filter-grid">
            <label className="field full">
              <span>Override job title</span>
              <input
                value={form.keywords}
                onChange={set('keywords')}
                placeholder="Defaults to your skill profile"
                maxLength={255}
              />
            </label>
            <label className="field">
              <span>Location</span>
              <input value={form.location} onChange={set('location')} maxLength={255} />
            </label>
            <label className="field">
              <span>Job type</span>
              <select value={form.job_type} onChange={set('job_type')}>
                <option value="">Any</option>
                <option value="full_time">Full-time</option>
                <option value="part_time">Part-time</option>
                <option value="contract">Contract</option>
                <option value="remote">Remote</option>
              </select>
            </label>
            <label className="field">
              <span>Min salary</span>
              <input
                type="number"
                min="0"
                value={form.salary_min}
                onChange={set('salary_min')}
                placeholder="Any"
              />
            </label>
          </div>

          <div className="job-actions" style={{ marginTop: 0 }}>
            <button className="btn primary" type="submit" disabled={busy}>
              {busy ? 'Searching…' : 'Apply filters'}
            </button>
            <button className="btn" type="button" onClick={clear} disabled={busy}>
              Reset to my profile
            </button>
          </div>
        </>
      )}
    </form>
  )
}
