const CACHE_NAME = 'get-requests-cache-v3'
const CACHE_URLS = ['open-bus-stride-api']

// Install: אין precache — cache.addAll על 'open-bus-stride-api' (נתיב שאינו
// קיים) הכשיל את ההתקנה כולה באירוח סטטי, וכל המטמון מעולם לא נדלק.
self.addEventListener('install', () => {
  self.skipWaiting()
})

// Activate event: clear old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) =>
      Promise.all(
        cacheNames.map((cacheName) => {
          if (cacheName !== CACHE_NAME) {
            return caches.delete(cacheName)
          }
        }),
      ),
    ),
  )
  self.clients.claim()
})

// Fetch event: cache GET requests except when query includes today's date
self.addEventListener('fetch', (event) => {
  const today = new Date().toISOString().slice(0, 10) // e.g. "2025-10-28"

  // קבצי האפליקציה נושאים גיבוב-תוכן בשם — בטוחים למטמון-תחילה לצמיתות,
  // וחוסכים הורדה חוזרת של החבילה כשהאירוח מגביל את חיי המטמון (Pages: 10 דק')
  if (
    event.request.method === 'GET' &&
    new URL(event.request.url).origin === self.location.origin &&
    event.request.url.includes('/assets/')
  ) {
    event.respondWith(
      caches.match(event.request).then(
        (cached) =>
          cached ||
          fetch(event.request).then((response) => {
            if (response.ok) {
              const clone = response.clone()
              caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone))
            }
            return response
          }),
      ),
    )
    return
  }

  if (
    event.request.method === 'GET' &&
    !event.request.url.includes(today) &&
    CACHE_URLS.some((url) => event.request.url.includes(url))
  ) {
    event.respondWith(
      caches.match(event.request).then((cachedResponse) => {
        // Return cached response if available
        if (cachedResponse) return cachedResponse

        // Otherwise, fetch from network and cache the response
        return fetch(event.request).then((response) => {
          if (response.ok) {
            const responseClone = response.clone()
            caches.open(CACHE_NAME).then((cache) => {
              cache.put(event.request, responseClone)
            })
          }
          return response
        })
      }),
    )
  }
})
