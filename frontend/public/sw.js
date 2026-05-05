const CACHE_NAME = 'itgs-hr-v4'
const STATIC_PREFIX = '/static/dashboard/'
const PRECACHE_URLS = [
  '/static/dashboard/manifest.webmanifest',
  '/static/dashboard/icons/icon-192.svg',
  '/static/dashboard/icons/icon-512.svg'
]

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(PRECACHE_URLS)).then(() => self.skipWaiting())
  )
})

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)))
    ).then(() => self.clients.claim())
  )
})

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') {
    return
  }

  const url = new URL(event.request.url)
  const isStaticDashboardAsset = url.origin === self.location.origin && url.pathname.startsWith(STATIC_PREFIX)
  if (!isStaticDashboardAsset) {
    return
  }

  event.respondWith(
    caches.match(event.request).then((cached) => {
      if (cached) {
        return cached
      }
      return fetch(event.request).then((response) => {
        if (!response || response.status !== 200 || response.type !== 'basic') {
          return response
        }
        const copy = response.clone()
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy))
        return response
      })
    })
  )
})
