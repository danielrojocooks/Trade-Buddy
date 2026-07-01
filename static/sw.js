// Minimal service worker — makes the app installable on the M9 and shells the
// static files. The /check call always hits the network.
const CACHE = "trade-buddy-v1";
const SHELL = [
  "/",
  "/styles.css",
  "/app.js",
  "/manifest.json",
  "/faces/fair.png",
  "/faces/uneven.png",
  "/faces/treasure.png",
  "/faces/confused.png",
  "/faces/error.png",
  "/faces/sleeping.png",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

// Network-first: always serve fresh content when online, fall back to cache
// offline. Prevents stale HTML/CSS/images after a deploy. The API is never cached.
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname === "/check") return;
  e.respondWith(
    fetch(e.request)
      .then((res) => {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(e.request, copy)).catch(() => {});
        return res;
      })
      .catch(() => caches.match(e.request))
  );
});
