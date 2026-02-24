const CACHE_NAME = 'wr-v1';
const STATIC_ASSETS = ['/', '/static/css/styles.css', '/static/js/app.js', '/static/js/audio.js', '/static/js/ui.js'];

self.addEventListener('install', (e) => {
    e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(STATIC_ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
    e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
    // Network first, fallback to cache
    if (e.request.method !== 'GET') return;
    e.respondWith(fetch(e.request).then(r => {
        const clone = r.clone();
        caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
        return r;
    }).catch(() => caches.match(e.request)));
});
