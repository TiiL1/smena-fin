const CACHE_NAME = 'smena-fin-v1';
const ASSET_EXTENSIONS = ['.js', '.css', '.woff', '.woff2', '.ttf', '.eot', '.svg', '.png', '.jpg', '.webp'];

self.addEventListener('install', () => {
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
      );
    }).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Только GET и только same-origin или статику
  if (request.method !== 'GET') return;

  // API: network-first, fallback на кэш
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(request)
        .then((response) => {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          return response;
        })
        .catch(() => caches.match(request).then((c) => c ?? fetch(request)))
    );
    return;
  }

  // Статика: cache-first
  const isAsset = ASSET_EXTENSIONS.some((ext) => url.pathname.endsWith(ext));
  if (isAsset || url.pathname === '/' || url.pathname.endsWith('.html')) {
    event.respondWith(
      caches.match(request).then((cached) => {
        if (cached) return cached;
        return fetch(request).then((response) => {
          const clone = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put(request, clone));
          return response;
        });
      })
    );
    return;
  }

  // Остальное: network first
  event.respondWith(
    fetch(request).catch(() => caches.match(request).then((c) => c ?? Promise.reject('offline')))
  );
});
