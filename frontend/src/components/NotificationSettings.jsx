import { useEffect, useState } from 'react'
import { api } from '../api/client'
import {
  currentSubscription,
  disablePush,
  enablePush,
  isIos,
  isStandalone,
  permission,
  pushSupported,
} from '../api/push'

/**
 * Push settings. Email is the channel that always works; this only ever adds a
 * second one, so every failure path here says so rather than looking broken.
 */
export default function NotificationSettings() {
  const [subscribed, setSubscribed] = useState(false)
  const [serverEnabled, setServerEnabled] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')

  useEffect(() => {
    ;(async () => {
      try {
        const config = await api.pushConfig()
        setServerEnabled(config.enabled)
      } catch {
        /* non-fatal - the toggle just stays available */
      }
      if (pushSupported()) setSubscribed(Boolean(await currentSubscription()))
    })()
  }, [])

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

  const supported = pushSupported()
  const blocked = permission() === 'denied'
  // iOS exposes PushManager only to an installed PWA, so an uninstalled iPhone
  // cannot subscribe at all - that needs explaining, not a dead button.
  const needsIosInstall = !supported && isIos() && !isStandalone()

  return (
    <div className="card">
      <h2 className="section-title" style={{ marginTop: 0 }}>
        Notifications
      </h2>
      <p className="job-company" style={{ marginBottom: 12 }}>
        New jobs from companies you follow always arrive by email. Push adds an
        instant alert on this device.
      </p>

      {error && <div className="alert error">{error}</div>}
      {message && <div className="alert info">{message}</div>}

      {needsIosInstall && (
        <div className="alert info">
          On iPhone and iPad, notifications only work once the app is installed:
          tap <strong>Share</strong> → <strong>Add to Home Screen</strong>, then open it
          from there. Requires iOS 16.4 or later.
        </div>
      )}

      {!supported && !needsIosInstall && (
        <div className="alert info">
          This browser does not support push notifications. You will still get the
          email digest.
        </div>
      )}

      {!serverEnabled && supported && (
        <div className="alert info">
          Push is not configured on the server (no VAPID keys). Email still works.
        </div>
      )}

      {blocked && (
        <div className="alert info">
          Notifications are blocked for this site. Re-enable them in your browser’s
          site settings, then reload.
        </div>
      )}

      {supported && serverEnabled && !blocked && (
        <div className="job-actions">
          {subscribed ? (
            <>
              <button
                className="btn on"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    await disablePush()
                    setSubscribed(false)
                  }, 'Push notifications turned off.')
                }
              >
                ✓ Push is on — turn off
              </button>
              <button
                className="btn"
                disabled={busy}
                onClick={() => run(() => api.pushTest(), 'Test notification sent.')}
              >
                Send test
              </button>
            </>
          ) : (
            <button
              className="btn primary"
              disabled={busy}
              onClick={() =>
                run(async () => {
                  await enablePush()
                  setSubscribed(true)
                }, 'Push notifications enabled on this device.')
              }
            >
              Enable push notifications
            </button>
          )}
        </div>
      )}
    </div>
  )
}
