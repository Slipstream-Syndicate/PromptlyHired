import { useEffect, useState } from 'react'

/**
 * The service worker serves the app shell offline, but every job list comes
 * from the API and will be empty. Saying so beats an unexplained empty page.
 */
export default function OfflineBanner() {
  const [online, setOnline] = useState(navigator.onLine)

  useEffect(() => {
    const goOnline = () => setOnline(true)
    const goOffline = () => setOnline(false)
    window.addEventListener('online', goOnline)
    window.addEventListener('offline', goOffline)
    return () => {
      window.removeEventListener('online', goOnline)
      window.removeEventListener('offline', goOffline)
    }
  }, [])

  if (online) return null

  return (
    <div className="offline-banner" role="status">
      You’re offline — job listings and updates will resync when you reconnect.
    </div>
  )
}
