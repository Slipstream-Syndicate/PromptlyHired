import { useRef, useState } from 'react'
import { api } from '../api/client'

const ACCEPT = '.pdf,.docx,.txt'
const ACCEPT_TYPES = [
  'application/pdf',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  'text/plain',
].join(',')

function TagEditor({ label, items, onChange, placeholder }) {
  const [draft, setDraft] = useState('')

  const add = () => {
    const value = draft.trim()
    if (!value) return
    if (!items.some((i) => i.toLowerCase() === value.toLowerCase())) {
      onChange([...items, value])
    }
    setDraft('')
  }

  return (
    <div className="field">
      <span>{label}</span>
      <div className="tag-row">
        {items.map((item) => (
          <span className="tag" key={item}>
            {item}
            <button
              type="button"
              onClick={() => onChange(items.filter((i) => i !== item))}
              aria-label={`Remove ${item}`}
            >
              ×
            </button>
          </span>
        ))}
      </div>
      <div className="bullet-row">
        <input
          value={draft}
          placeholder={placeholder}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') {
              e.preventDefault()
              add()
            }
          }}
        />
        <button className="btn" type="button" onClick={add}>
          Add
        </button>
      </div>
    </div>
  )
}

/**
 * Resume upload plus the skill profile derived from it.
 *
 * The profile is editable because extraction is a starting point, not an
 * authority on someone's own career - and because it is what the job feed
 * searches with, so a wrong title means a wrong feed.
 */
export default function ResumePanel({ resume, onChange }) {
  const inputRef = useRef(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [profile, setProfile] = useState(resume?.skill_profile ?? null)
  const [dirty, setDirty] = useState(false)

  const run = async (fn, done) => {
    setBusy(true)
    setError('')
    setMessage('')
    try {
      await fn()
      if (done) setMessage(done)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const pick = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return
    await run(async () => {
      const uploaded = await api.uploadResume(file)
      setProfile(uploaded.skill_profile ?? null)
      setDirty(false)
      onChange(uploaded)
    }, 'Resume uploaded and analysed.')
    if (inputRef.current) inputRef.current.value = ''
  }

  const setField = (key, value) => {
    setProfile((p) => ({ ...p, [key]: value }))
    setDirty(true)
  }

  const saveProfile = () =>
    run(async () => {
      const updated = await api.updateSkillProfile(resume.id, {
        skills: profile.skills,
        job_titles: profile.job_titles,
        domains: profile.domains,
        locations: profile.locations,
        seniority: profile.seniority,
        years_experience: profile.years_experience,
        summary: profile.summary,
      })
      setProfile(updated)
      setDirty(false)
    }, 'Skill profile saved. Your job feed will use it.')

  const reanalyse = () =>
    run(async () => {
      setProfile(await api.reanalyzeResume(resume.id))
      setDirty(false)
    }, 'Re-analysed your resume.')

  return (
    <div className="card">
      <h2 className="section-title" style={{ marginTop: 0 }}>
        Your resume
      </h2>

      {error && <div className="alert error">{error}</div>}
      {message && <div className="alert info">{message}</div>}

      {resume ? (
        <p className="job-company">
          <strong>{resume.original_filename}</strong> · uploaded{' '}
          {new Date(resume.uploaded_at).toLocaleDateString()}
        </p>
      ) : (
        <p className="job-company">
          Everything starts here. We read your resume, work out your skillset, and
          search for matching jobs automatically.
        </p>
      )}

      <div className="job-actions">
        <button
          className={resume ? 'btn' : 'btn primary'}
          type="button"
          disabled={busy}
          onClick={() => inputRef.current?.click()}
        >
          {busy ? 'Working…' : resume ? 'Replace resume' : 'Upload resume'}
        </button>
        {resume && (
          <button className="btn" type="button" disabled={busy} onClick={reanalyse}>
            Re-analyse
          </button>
        )}
      </div>
      <p className="fine-print">PDF, DOCX or plain text, up to 10 MB.</p>

      <input
        ref={inputRef}
        type="file"
        accept={`${ACCEPT},${ACCEPT_TYPES}`}
        onChange={pick}
        hidden
      />

      {resume && profile && (
        <>
          <h2 className="section-title">Skill profile</h2>
          <p className="job-company" style={{ marginBottom: 12 }}>
            This is what your job feed searches with. We extracted it from your resume
            {profile.edited_by_user ? ' and you have since edited it' : ''} — correct
            anything that is wrong.
          </p>

          <TagEditor
            label="Job titles to search for"
            items={profile.job_titles || []}
            onChange={(v) => setField('job_titles', v)}
            placeholder="e.g. Backend Engineer"
          />
          <TagEditor
            label="Skills"
            items={profile.skills || []}
            onChange={(v) => setField('skills', v)}
            placeholder="e.g. Python"
          />
          <TagEditor
            label="Preferred locations"
            items={profile.locations || []}
            onChange={(v) => setField('locations', v)}
            placeholder="e.g. London"
          />

          <label className="field">
            <span>Seniority</span>
            <input
              value={profile.seniority ?? ''}
              onChange={(e) => setField('seniority', e.target.value)}
            />
          </label>

          <label className="field">
            <span>Years of experience</span>
            <input
              type="number"
              min="0"
              step="0.5"
              value={profile.years_experience ?? ''}
              onChange={(e) =>
                setField('years_experience', e.target.value === '' ? null : Number(e.target.value))
              }
            />
          </label>

          {dirty && (
            <button className="btn primary block" type="button" onClick={saveProfile} disabled={busy}>
              Save skill profile
            </button>
          )}
        </>
      )}

      {resume && !profile && (
        <div className="alert info">
          We couldn’t analyse this resume automatically. Try “Re-analyse”, or check the
          server has an <code>ANTHROPIC_API_KEY</code> configured.
        </div>
      )}
    </div>
  )
}
