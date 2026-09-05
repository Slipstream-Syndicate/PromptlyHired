/* Push handling, imported into the generated service worker.
   Kept as a plain script so the generateSW strategy still applies - no
   injectManifest machinery needed just to handle two events. */

self.addEventListener('push', (event) => {
  let payload = {}
  try {
    payload = event.data ? event.data.json() : {}
  } catch {
    payload = { title: 'JobTrail', body: event.data ? event.data.text() : '' }
  }

  const title = payload.title || 'JobTrail'
  event.waitUntil(
    self.registration.showNotification(title, {
      body: payload.body || '',
      icon: '/icon-192.png',
      badge: '/icon-192.png',
      // Collapses repeat digests into one notification instead of stacking.
      tag: payload.tag || 'jobtrail-digest',
      renotify: true,
      data: { url: payload.url || '/' },
    }),
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const target = new URL((event.notification.data && event.notification.data.url) || '/', self.location.origin)

  // Focus an existing tab if the app is already open, rather than piling up windows.
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clients) => {
      for (const client of clients) {
        if (new URL(client.url).origin === target.origin && 'focus' in client) {
          client.navigate(target.href)
          return client.focus()
        }
      }
      return self.clients.openWindow(target.href)
    }),
  )
})
