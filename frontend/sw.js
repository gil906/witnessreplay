const CACHE_NAME = 'witnessreplay-v2';
const STATIC_ASSETS = [
    '/',
    '/css/styles.css',
    '/js/app.js',
    '/js/ui.js',
    '/js/audio.js',
    '/manifest.json',
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS))
    );
});

self.addEventListener('fetch', event => {
    // Network first for API calls and WebSocket, cache first for static assets
    if (event.request.url.includes('/api/') || event.request.url.includes('/ws/')) {
        event.respondWith(
            fetch(event.request).catch(() => caches.match(event.request))
        );
    } else {
        event.respondWith(
            caches.match(event.request).then(response => response || fetch(event.request))
        );
    }
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(names =>
            Promise.all(names.filter(n => n !== CACHE_NAME).map(n => caches.delete(n)))
        )
    );
});
