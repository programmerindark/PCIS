// Service worker: makes PCIS work with no signal.
//
// Two caching strategies, deliberately different:
//
//  - App shell (this file's siblings): cache-first, versioned. Bump
//    CACHE_VERSION whenever index.html/app.js/pcis_core.zip change or
//    installed phones will keep running the old engineering core.
//
//  - Pyodide runtime (~7 MB from the CDN): cached opportunistically on
//    first successful fetch, then served from cache forever. It is
//    version-pinned in the URL, so a stale copy is never wrong -- and
//    without this, the app would need signal on every launch, which
//    defeats the point in a shed.

const CACHE_VERSION = "pcis-v2";  // bumped: dark-theme CSS
const SHELL = [
  "./",
  "./index.html",
  "./app.js",
  "./manifest.json",
  "./pcis_core.zip",
];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE_VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE_VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener("fetch", (e) => {
  const url = e.request.url;
  const isPyodide = url.includes("/pyodide/");

  e.respondWith(
    caches.match(e.request).then((hit) => {
      if (hit) return hit;
      return fetch(e.request).then((res) => {
        // Cache Pyodide's runtime pieces as they stream in. Opaque
        // cross-origin responses are cached too: we cannot inspect
        // them, but a version-pinned URL means the bytes are stable.
        if (isPyodide && (res.ok || res.type === "opaque")) {
          const copy = res.clone();
          caches.open(CACHE_VERSION).then((c) => c.put(e.request, copy));
        }
        return res;
      });
    })
  );
});
