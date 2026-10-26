// Offline support is deliberately minimal: only the offline page and static assets are cached.
// Pages that contain personal data (plan, contacts, incidents, evidence) are NEVER cached.
const CACHE = "lesedi-static-v1";
const PRECACHE = ["/offline/", "/static/css/lesedi.css", "/static/js/app.js"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") { return; }
  const url = new URL(req.url);
  if (url.origin !== location.origin) { return; }
  if (req.mode === "navigate") {
    event.respondWith(fetch(req).catch(() => caches.match("/offline/")));
    return;
  }
  if (url.pathname.startsWith("/static/")) {
    event.respondWith(caches.match(req).then((hit) => hit || fetch(req)));
  }
});
