// Only public application files belong in Cache Storage. Account snapshots are
// stored by the page under a credential-specific namespace, never API responses.
const CACHE_NAME = 'schat-shell-world-import-v1';
const SHELL = '/s-chat';
const STATIC = [SHELL, '/assets/js/schat.js', '/assets/js/schat-library.js', '/s-chat/manifest.json',
  '/assets/brand/schat-pwa-192.png', '/assets/brand/schat-pwa-512.png'];
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC)));
  self.skipWaiting();
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys
    .filter(key => key.startsWith('schat-shell-') && key !== CACHE_NAME)
    .map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== self.location.origin
      || url.pathname.startsWith('/api/')) return;
  if (event.request.mode === 'navigate' && url.pathname === SHELL) {
    event.respondWith(fetch(event.request).then(response => {
      const clone = response.clone();
      if (response.ok) event.waitUntil(caches.open(CACHE_NAME)
        .then(cache => cache.put(SHELL, clone)));
      return response;
    }).catch(() => caches.match(SHELL)));
  } else if (STATIC.includes(url.pathname)) {
    event.respondWith(fetch(event.request).then(response => {
      const clone = response.clone();
      if (response.ok) event.waitUntil(caches.open(CACHE_NAME)
        .then(cache => cache.put(url.pathname, clone)));
      return response;
    }).catch(() => caches.match(url.pathname)));
  }
});
