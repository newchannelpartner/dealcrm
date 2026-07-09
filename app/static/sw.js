// DealCRM Service Worker — enables PWA install and offline caching
const CACHE_NAME = 'dealcrm-v5';
const ASSETS = [
  '/',
  '/static/index.html',
  '/manifest.json',
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(ASSETS))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  // Only handle GET requests for static assets; skip API calls entirely.
  if (event.request.method !== 'GET' ||
      event.request.url.includes('/contacts') ||
      event.request.url.includes('/deals') ||
      event.request.url.includes('/notes') ||
      event.request.url.includes('/todos') ||
      event.request.url.includes('/inbound') ||
      event.request.url.includes('/dashboard') ||
      event.request.url.includes('/users') ||
      event.request.url.includes('/me') ||
      event.request.url.includes('/health')) {
    return;
  }

  // Network-first for the app shell (HTML navigations) so new deploys show up
  // immediately when online; fall back to cache only when offline.
  const isNavigation = event.request.mode === 'navigate' ||
    (event.request.headers.get('accept') || '').includes('text/html');

  if (isNavigation) {
    event.respondWith(
      fetch(event.request)
        .then((resp) => {
          const copy = resp.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
          return resp;
        })
        .catch(() => caches.match(event.request).then((c) => c || caches.match('/')))
    );
    return;
  }

  // Cache-first for other static assets.
  event.respondWith(
    caches.match(event.request).then((cached) => cached || fetch(event.request))
  );
});
