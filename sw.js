// Ping service worker: network-first shell, offline page, and push notifications.
const CACHE = 'ping-shell-v2';
self.addEventListener('install', e => { self.skipWaiting(); });
self.addEventListener('activate', e => { e.waitUntil(self.clients.claim()); });
self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET' || new URL(req.url).origin !== location.origin) return;
  e.respondWith(fetch(req).then(r => { const copy = r.clone(); caches.open(CACHE).then(c => c.put(req, copy)).catch(() => {}); return r; })
    .catch(() => caches.match(req).then(m => m || new Response('<!doctype html><meta charset=utf-8><body style="font-family:sans-serif;background:#313338;color:#fff;display:grid;place-items:center;height:100vh;margin:0"><div style="text-align:center"><h1>Ping</h1><p>You\'re offline. Ping needs a connection to reach your friends.</p></div>', { headers: { 'content-type': 'text/html' } }))));
});
self.addEventListener('push', e => {
  let d = {}; try { d = e.data ? e.data.json() : {}; } catch (err) { d = { body: e.data && e.data.text() }; }
  e.waitUntil(self.registration.showNotification(d.title || 'Ping', { body: d.body || '', tag: d.tag || 'ping', renotify: true, icon: 'icon-192.png', badge: 'icon-192.png', data: { url: d.url || './' } }));
});
self.addEventListener('notificationclick', e => {
  e.notification.close();
  const target = new URL(e.notification.data && e.notification.data.url || './', self.location.href).href;
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
    for (const c of list) { if ('focus' in c) { c.navigate ? c.navigate(target).catch(() => {}) : null; return c.focus(); } }
    return self.clients.openWindow(target);
  }));
});
