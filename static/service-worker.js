// static/service-worker.js
const CACHE_NAME = 'slt-static-v1';
const PRECACHE_URLS = [
  '/', 
  '/service-worker.js',
  '/static/js/app.js',
  '/static/js/admin.js',
  '/favicon.ico'
];

self.addEventListener('install', e => {
  e.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => cache.addAll(PRECACHE_URLS))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', e => {
  e.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME)
                      .map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  e.respondWith(
    caches.match(e.request).then(cached => {
      if (cached) return cached;
      return fetch(e.request).then(resp => {
        caches.open(CACHE_NAME).then(cache => cache.put(e.request, resp.clone()));
        return resp;
      });
    }).catch(() => {
      if (e.request.mode === 'navigate') return caches.match('/');
    })
  );
});