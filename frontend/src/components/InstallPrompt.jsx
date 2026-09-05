import { useEffect, useState } from 'react'
import { isIos, isStandalone } from '../api/push'

const DISMISSED_KEY = 'jobtrail.install_dismissed'

function dismissed() {
  try {
    return localStorage.getItem(DISMISSED_KEY) === '1'
  } catch {
    return false
  }
}

/**
 * Installing is not cosmetic: on iOS it is the only way push notifications ever
 * fire (16.4+, and only from the home screen). Chrome/Android give us a real
 * `beforeinstallprompt` event; iOS gives us nothing, so it gets instructions.
 */
export default function InstallPrompt() {
  const [deferred, setDeferred] = useState(null)
  const [showIosHint, setShowIosHint] = useState(false)
  const [hidden, setHidden] = useState(dismissed())

  useEffect(() => {
    if (isStandalone() || dismissed()) return

    const onBeforeInstall = (event) => {
      event.preventDefault()
      setDeferred(event)
    }
    window.addEventListener('beforeinstallprompt', onBeforeInstall)

    // Safari never fires that event, so surface the manual route instead.
    if (isIos()) setShowIosHint(true)

    return () => window.removeEventListener('beforeinstallprompt', onBeforeInstall)
  }, [])

  const close = () => {
    setHidden(true)
    try {
      localStorage.setItem(DISMISSED_KEY, '1')
    } catch {
      /* ignore */
    }
  }

  const install = async () => {
    if (!deferred) return
    deferred.prompt()
    await deferred.userChoice
    setDeferred(null)
    close()
  }

  if (hidden || isStandalone() || (!deferred && !showIosHint)) return null

  return (
    <div className="install-banner">
      <div className="job-main">
        <strong>Install JobTrail</strong>
        <p className="job-company" style={{ marginTop: 2 }}>
          {deferred
            ? 'Add it to your home screen for full-screen access and notifications.'
            : 'Tap Share, then “Add to Home Screen” — on iPhone that is the only way notifications can reach you.'}
        </p>
      </div>
      <div className="install-actions">
        {deferred && (
          <button className="btn primary" onClick={install}>
            Install
          </button>
        )}
        <button className="btn" onClick={close}>
          Not now
        </button>
      </div>
    </div>
  )
}
