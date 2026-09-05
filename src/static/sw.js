const CACHE_NAME = 'shelfmark-v2';
// Cache only the small app shell needed to open the installed shortcut offline.
const APP_SHELL = [
  '/',
  '/static/style.css',
  '/static/app.js',
  '/static/manifest.json',
  '/static/icon.png',
];

self.addEventListener('install', (event) => {
  // A new cache name lets updated assets replace stale installed versions.
  event.waitUntil(caches.open(CACHE_NAME).then((cache) => cache.addAll(APP_SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  // Remove older shell caches after the new worker takes control.
  event.waitUntil(caches.keys().then((keys) => Promise.all(
    keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)),
  )));
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  // Navigation and static assets use cache-first behavior; form submissions stay online.
  if (event.request.method !== 'GET') return;
  event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request)));
});
