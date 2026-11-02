// Service worker: guarda la app y los mapas en el celular para que anden sin internet.
// Al cambiar cualquier archivo, subir VERSION: el celular baja todo de nuevo la proxima vez que
// abra la app con internet.
const VERSION = 'juando-2';
const ARCHIVOS = [
  './', './index.html', './manifest.json',
  './vendor/leaflet.min.css', './vendor/leaflet.min.js', './vendor/pmtiles.js', './vendor/protomaps-leaflet.js',
  './iconos/icono-192.png', './iconos/icono-512.png',
  './mapas/la_plata.pmtiles', './mapas/la_cumbre.pmtiles',
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(VERSION).then(c => c.addAll(ARCHIVOS.map(a => new Request(a, { cache: 'reload' })))).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== VERSION).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

// Primero lo guardado (anda offline y rapido); si no esta, la red.
self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  e.respondWith(caches.match(e.request, { ignoreSearch: true }).then(r => r || fetch(e.request)));
});

// Tocar una notificacion (aviso de bateria) abre la app
self.addEventListener('notificationclick', e => {
  e.notification.close();
  e.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(cs =>
    cs.length ? cs[0].focus() : self.clients.openWindow('./')));
});
