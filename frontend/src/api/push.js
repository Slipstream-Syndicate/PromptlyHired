import { api } from './client'

/** VAPID keys travel as base64url; PushManager wants raw bytes. */
function urlBase64ToUint8Array(base64String) {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(base64)
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)))
}

export function pushSupported() {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
}

/**
 * iOS only exposes push to an installed PWA (16.4+). In a normal Safari tab
 * PushManager is missing entirely, so telling the user to install is the only
 * useful advice we can give.
 */
export function isIos() {
  return (
    /iphone|ipad|ipod/i.test(navigator.userAgent) ||
    // iPadOS reports as Mac, so check for touch too.
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
  )
}

export function isStandalone() {
  return (
    window.matchMedia('(display-mode: standalone)').matches ||
    window.navigator.standalone === true
  )
}

export function permission() {
  return typeof Notification === 'undefined' ? 'unsupported' : Notification.permission
}

async function registration() {
  return navigator.serviceWorker.ready
}

export async function currentSubscription() {
  if (!pushSupported()) return null
  const reg = await registration()
  return reg.pushManager.getSubscription()
}

export async function enablePush() {
  if (!pushSupported()) throw new Error('This browser does not support push notifications.')

  const result = await Notification.requestPermission()
  if (result !== 'granted') {
    throw new Error(
      result === 'denied'
        ? 'Notifications are blocked. Enable them for this site in your browser settings.'
        : 'Notification permission was dismissed.',
    )
  }

  const config = await api.pushConfig()
  if (!config.enabled || !config.public_key) {
    throw new Error('Push is not configured on the server.')
  }

  const reg = await registration()
  let sub = await reg.pushManager.getSubscription()
  if (!sub) {
    sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(config.public_key),
    })
  }

  await api.pushSubscribe(sub.toJSON())
  return sub
}

export async function disablePush() {
  const sub = await currentSubscription()
  if (!sub) return
  // Tell the server first: if unsubscribing locally succeeds but the call
  // fails, the server would keep pushing to a dead endpoint.
  await api.pushUnsubscribe(sub.toJSON()).catch(() => null)
  await sub.unsubscribe()
}
