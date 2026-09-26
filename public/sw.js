const CACHE_NAME = 'taskit-v4';

// App shell cached for offline start and fast launches from the home screen.
const SHELL_FILES = [
  '/',
  '/index.html',
  '/css/taskit.css',
  '/css/app.css',
  '/js/session-ui.js',
  '/js/camera.js',
  '/js/api.js',
  '/js/app.js',
  '/manifest.json',
  '/icons/icon.svg',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/apple-touch-icon.png',
];

// ── Install: pre-cache the app shell ──
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(SHELL_FILES)));
  self.skipWaiting();
});

// ── Activate: clean up old caches (including the old Memory Vault shell) ──
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  const { request } = event;
  const url = new URL(request.url);

  // Uploads, coach calls and other non-GET requests always go straight to the network.
  if (request.method !== 'GET') return;
  if (url.origin === self.location.origin &&
      (url.pathname.startsWith('/backend/') || url.pathname.startsWith('/api/') || url.pathname.startsWith('/uploads/'))) {
    return;
  }

  // Google Fonts: cache-first (they never change for a given URL).
  if (url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com') {
    event.respondWith(
      caches.match(request).then(cached => cached || fetch(request).then(response => {
        const clone = response.clone();
        caches.open(CACHE_NAME).then(cache => cache.put(request, clone));
        return response;
      }))
    );
    return;
  }

  if (url.origin !== self.location.origin) return;

  // App shell: network-first so updates show up right away, cache when offline.
  event.respondWith(
    fetch(request)
      .then(response => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(request, clone));
        }
        return response;
      })
      .catch(() => caches.match(request).then(cached =>
        cached || (request.mode === 'navigate' ? caches.match('/index.html') : Response.error())))
  );
});
