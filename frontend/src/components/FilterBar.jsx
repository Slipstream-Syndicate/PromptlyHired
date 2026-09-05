import { useEffect, useState } from 'react'

const BLANK = {
  keywords: '',
  location: '',
  salary_min: '',
  salary_max: '',
  job_type: '',
}

/**
 * These are the same fields stored as the user's JobPreferences. Submitting
 * the form saves them as the new preferences, so the profile and the search
 * filters can never drift apart.
 */
export default function FilterBar({ value, onSearch, busy }) {
  const [form, setForm] = useState(BLANK)

  useEffect(() => {
    if (!value) return
    setForm({
      keywords: value.keywords ?? '',
      location: value.location ?? '',
      salary_min: value.salary_min ?? '',
      salary_max: value.salary_max ?? '',
      job_type: value.job_type ?? '',
    })
  }, [value])

  const set = (key) => (event) => setForm((f) => ({ ...f, [key]: event.target.value }))

  const submit = (event) => {
    event.preventDefault()
    onSearch(form)
  }

  return (
    <form className="filters" onSubmit={submit}>
      <div className="filter-grid">
        <label className="field full">
          <span>Job title or keywords</span>
          <input
            value={form.keywords}
            onChange={set('keywords')}
            placeholder="e.g. backend engineer"
            maxLength={255}
          />
        </label>

        <label className="field">
          <span>Location</span>
          <input
            value={form.location}
            onChange={set('location')}
            placeholder="e.g. London"
            maxLength={255}
          />
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

        <label className="field">
          <span>Max salary</span>
          <input
            type="number"
            min="0"
            value={form.salary_max}
            onChange={set('salary_max')}
            placeholder="Any"
          />
        </label>
      </div>

      <button className="btn primary block" type="submit" disabled={busy}>
        {busy ? 'Searching…' : 'Search jobs'}
      </button>
    </form>
  )
}
