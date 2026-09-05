import { useRef, useState } from 'react'
import { api } from '../api/client'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000'

/** Local dev stores avatars on the API host, so relative URLs need its origin. */
export function avatarSrc(url) {
  if (!url) return null
  return url.startsWith('/') ? `${API_BASE}${url}` : url
}

export default function AvatarUpload({ user, onChange }) {
  const inputRef = useRef(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const pick = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return

    setBusy(true)
    setError('')
    try {
      onChange(await api.uploadProfilePicture(file))
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
      // Reset so re-picking the same file still fires onChange.
      if (inputRef.current) inputRef.current.value = ''
    }
  }

  const remove = async () => {
    setBusy(true)
    setError('')
    try {
      onChange(await api.removeProfilePicture())
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const src = avatarSrc(user?.profile_picture_url)

  return (
    <div className="avatar-row">
      {src ? (
        <img className="avatar" src={src} alt="" />
      ) : (
        <div className="avatar avatar-fallback" aria-hidden="true">
          {(user?.name || '?').slice(0, 1).toUpperCase()}
        </div>
      )}

      <div className="job-main">
        <div className="job-actions" style={{ marginTop: 0 }}>
          <button
            className="btn"
            type="button"
            disabled={busy}
            onClick={() => inputRef.current?.click()}
          >
            {busy ? 'Uploading…' : src ? 'Change photo' : 'Upload photo'}
          </button>
          {src && (
            <button className="btn danger" type="button" disabled={busy} onClick={remove}>
              Remove
            </button>
          )}
        </div>
        <p className="job-company" style={{ marginTop: 6 }}>
          JPEG, PNG or WebP, up to 5 MB. Resized and re-encoded on upload.
        </p>
        {error && <div className="alert error" style={{ marginTop: 8 }}>{error}</div>}
      </div>

      <input
        ref={inputRef}
        type="file"
        accept="image/jpeg,image/png,image/webp"
        onChange={pick}
        hidden
      />
    </div>
  )
}
