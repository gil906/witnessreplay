const CACHE_VERSION = '20260224';
const CACHE_NAME = `wr-${CACHE_VERSION}`;
const STATIC_ASSETS = ['/', '/static/css/styles.css', '/static/js/app.js', '/static/js/audio.js', '/static/js/ui.js'];

self.addEventListener('install', (e) => {
    e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(STATIC_ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
    e.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))).then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
    if (e.request.method !== 'GET') return;
    e.respondWith(
        fetch(e.request).then(r => {
            const clone = r.clone();
            caches.open(CACHE_NAME).then(c => c.put(e.request, clone));
            return r;
        }).catch(() => {
            return caches.match(e.request).then(r => {
                if (r) return r;
                // Return offline fallback for navigation requests
                if (e.request.mode === 'navigate') {
                    return new Response(`<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Offline</title><style>body{font-family:system-ui;background:#0a0a0f;color:#e2e8f0;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}.c{max-width:400px}.icon{font-size:4rem;margin-bottom:1rem}h1{font-size:1.5rem;margin:0 0 .5rem}p{color:#94a3b8;font-size:.9rem}button{background:#3b82f6;color:#fff;border:none;padding:12px 24px;border-radius:8px;font-size:1rem;cursor:pointer;margin-top:1rem}button:hover{background:#2563eb}</style></head><body><div class="c"><div class="icon">📡</div><h1>You're Offline</h1><p>WitnessReplay needs an internet connection. Please check your connection and try again.</p><button onclick="location.reload()">Retry Connection</button></div></body></html>`,
                    { headers: { 'Content-Type': 'text/html' } });
                }
                return new Response('Offline', { status: 503 });
            });
        })
    );
});
