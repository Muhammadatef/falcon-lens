/*
 * Falcon Lens service worker: offline shell only.
 *
 * - Verdicts are NEVER cached: anything under /v1/ (and /share, /api/) is not touched
 *   by this worker at all, so it always goes to the network.
 * - Page HTML is never cached either (each response carries a one-time CSP nonce);
 *   when a navigation fails, the static /offline.html is shown instead.
 * - Cached: the offline page and immutable build assets (/_next/static, fonts, icons).
 */
const CACHE = "fl-shell-v1";
const PRECACHE = ["/offline.html", "/offline.css", "/icons/icon.svg", "/fonts/readex-pro-arabic-wght-normal.woff2", "/fonts/readex-pro-latin-wght-normal.woff2"];
const STATIC_PREFIXES = ["/_next/static/", "/fonts/", "/icons/"];
const NEVER = ["/v1/", "/share", "/api/", "/mcp"];

self.addEventListener("install", (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(PRECACHE)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) => Promise.all(keys.filter((key) => key !== CACHE).map((key) => caches.delete(key))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;
  if (NEVER.some((prefix) => url.pathname.startsWith(prefix))) return;

  if (request.mode === "navigate") {
    event.respondWith(fetch(request).catch(() => caches.match("/offline.html").then((hit) => hit || Response.error())));
    return;
  }

  if (STATIC_PREFIXES.some((prefix) => url.pathname.startsWith(prefix)) || url.pathname === "/offline.css") {
    event.respondWith(
      caches.match(request).then((hit) => {
        if (hit) return hit;
        return fetch(request).then((response) => {
          if (response.ok && response.type === "basic") {
            const copy = response.clone();
            caches.open(CACHE).then((cache) => cache.put(request, copy));
          }
          return response;
        });
      }),
    );
  }
});
