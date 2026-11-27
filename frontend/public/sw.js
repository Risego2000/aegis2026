/* AEGIS · service worker
 *
 * Dos cometidos, nada más:
 *  1. Que la app abra aunque el túnel parpadee o no haya red: se guarda el
 *     armazón (HTML + CSS + JS con hash) y se sirve al instante, con la API
 *     aparte (si la API falla, la propia app ya muestra su aviso).
 *  2. Avisos del sistema con la ventana cerrada: la página manda
 *     `showNotification` cuando el motor de zonas detecta algo y aquí se
 *     muestra como notificación nativa.
 *
 * Nunca cachea /api/: los datos en vivo siempre vienen de la red.
 *
 * Ojo con el prefijo: en GitHub Pages el sitio vive en /<repo>/, así que el
 * armazón y los assets cuelgan de `self.registration.scope` y no de la raíz
 * del dominio (antes `/` era el README del repositorio, no la aplicación).
 */
const SCOPE = new URL(self.registration.scope);
const BASE = SCOPE.pathname.replace(/\/+$/, "");
const AT = (path) => `${BASE}${path}`;

const CACHE = "aegis-v1";
const SHELL = [AT("/"), AT("/icon.svg"), AT("/manifest.webmanifest")];

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL).catch(() => {})).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/") || url.pathname.startsWith("/ws/")) return;

  // Navegación: red primero (para tener la última versión), caché si falla.
  if (req.mode === "navigate") {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(AT("/"), copy)).catch(() => {});
          return res;
        })
        .catch(() => caches.match(AT("/")).then((hit) => hit || Response.error()))
    );
    return;
  }

  // Assets con hash: caché primero (son inmutables).
  event.respondWith(
    caches.match(req).then((hit) => {
      if (hit) return hit;
      return fetch(req).then((res) => {
        if (res.ok && (url.pathname.startsWith(AT("/_next/static/")) || url.pathname === AT("/icon.svg"))) {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put(req, copy)).catch(() => {});
        }
        return res;
      });
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
      for (const client of list) {
        if (client.url.includes(self.location.origin) && "focus" in client) return client.focus();
      }
      return self.clients.openWindow(AT("/"));
    })
  );
});
