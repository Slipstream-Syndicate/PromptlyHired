import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// The PWA foundation is here from the first commit rather than bolted on later:
// installing to a home screen is the only route to push notifications on
// mobile, and on iOS push requires the user to Add to Home Screen (16.4+).
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['apple-touch-icon.png', 'favicon-64.png'],
      manifest: {
        name: 'JobTrail - Job Search & Application Tracker',
        short_name: 'JobTrail',
        description:
          'Browse job listings, follow companies, and track every application you send.',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        orientation: 'portrait',
        background_color: '#0b1220',
        theme_color: '#0b1220',
        icons: [
          { src: '/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: '/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,png,svg,woff2}'],
        // Offline shell: any navigation falls back to the cached index.html, so
        // a deep link still boots the app with no network.
        navigateFallback: 'index.html',
        // Only the app shell is precached. API responses are per-user and
        // authenticated, so they are deliberately never cached by the service
        // worker - stale or cross-account data would be worse than a spinner.
        navigateFallbackDenylist: [/^\/api/, /^\/media/],
        runtimeCaching: [],
        // Push + notification-click handling, appended to the generated worker.
        importScripts: ['/push-sw.js'],
        cleanupOutdatedCaches: true,
      },
      devOptions: { enabled: false },
    }),
  ],
  server: { port: 5173 },
})
