/** Platform detection for the PWA install prompt. */

/**
 * iPadOS reports itself as a Mac, so touch points are the only reliable tell.
 * Matters because Safari never fires `beforeinstallprompt` - iOS users have to
 * be told to install manually or they get no prompt at all.
 */
export function isIos() {
  return (
    /iphone|ipad|ipod/i.test(navigator.userAgent) ||
    (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
  )
}

export function isStandalone() {
  return (
    window.matchMedia('(display-mode: standalone)').matches ||
    window.navigator.standalone === true
  )
}
