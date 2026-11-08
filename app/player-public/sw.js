// Keeps the player usable offline once installed on the home screen.
// Installation stores the page and every file it references, because the very
// first visit loads them before this worker controls the page. Afterwards pages
// are fetched network-first so updates arrive, and hashed assets cache-first.
const CACHE = "stem-player-v2";
const STATIC_FILES = ["./manifest.webmanifest", "./apple-touch-icon.png", "./icon-192.png", "./icon-512.png"];

self.addEventListener("install", (event) => {
  // A failed download only delays offline use: the player still works online.
  event.waitUntil(precache().catch(() => {}).then(() => self.skipWaiting()));
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
  if (request.method !== "GET" || new URL(request.url).origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request)
        .then((response) => {
          if (response.ok && new URL(request.url).pathname.endsWith("/player.html")) {
            void pruneAssets(response.clone());
          }
          return store(request, response);
        })
        .catch(() => caches.match(request).then((cached) => cached ?? caches.match("./player.html"))),
    );
    return;
  }
  event.respondWith(caches.match(request).then((cached) => cached ?? fetch(request).then((response) => store(request, response))));
});

async function precache() {
  const cache = await caches.open(CACHE);
  const response = await fetch("./player.html", { cache: "no-cache" });
  if (!response.ok) throw new Error(`player.html: ${response.status}`);
  const assets = referencedAssets(await response.clone().text());
  await cache.put("./player.html", response);
  await cache.addAll([...STATIC_FILES, ...assets]);
}

/** Drops the hashed files of earlier releases once a newer page has loaded. */
async function pruneAssets(page) {
  const current = new Set(referencedAssets(await page.text()).map((path) => new URL(path, self.location.href).href));
  const cache = await caches.open(CACHE);
  for (const request of await cache.keys()) {
    if (new URL(request.url).pathname.includes("/assets/") && !current.has(request.url)) {
      // Lazily loaded files (such as workers) are fetched again when needed.
      await cache.delete(request);
    }
  }
}

function referencedAssets(html) {
  return [...new Set([...html.matchAll(/(?:src|href)="(\.\/assets\/[^"]+)"/g)].map((match) => match[1]))];
}

function store(request, response) {
  if (response.ok) {
    const copy = response.clone();
    caches.open(CACHE).then((cache) => cache.put(request, copy));
  }
  return response;
}
