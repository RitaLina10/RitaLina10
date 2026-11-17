// Service worker: mantém o app abrindo sem internet. Dados de API NÃO são cacheados aqui;
// o app guarda o necessário no IndexedDB (fila de operações + snapshot de referência).
"use strict";
const VERSION = "gc-v3";
const SHELL = ["/", "/static/app.js", "/static/db.js", "/static/styles.css", "/manifest.webmanifest", "/static/icon.svg"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== "GET" || url.origin !== self.location.origin) return;
  if (url.pathname.startsWith("/api/") || ["/health", "/ready", "/metrics"].includes(url.pathname)) return;

  if (req.mode === "navigate") {
    // Rede primeiro (pega versão nova); sem rede, usa o shell em cache.
    e.respondWith(fetch(req).then((res) => {
      const copy = res.clone();
      caches.open(VERSION).then((c) => c.put("/", copy));
      return res;
    }).catch(() => caches.match("/")));
    return;
  }
  // Estáticos: cache imediato + atualização em segundo plano.
  e.respondWith(caches.match(req).then((cached) => {
    const network = fetch(req).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(VERSION).then((c) => c.put(req, copy)); }
      return res;
    }).catch(() => cached);
    return cached || network;
  }));
});
