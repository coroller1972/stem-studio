// Keeps the player usable at rehearsals, where the network is often there but
// too slow to answer. Once installed, every launch is served from the cache
// right away, whatever the network does: waiting for the network first would
// leave a blank screen until the request gives up, which takes minutes on a
// bad connection. Updates are downloaded in the background, assets first, and
// show up at the next launch.
const CACHE = "stem-player-v2";
const PAGE = "./player.html";
const DOWNLOAD_TIMEOUT_MS = 60_000;
const STATIC_FILES = ["./manifest.webmanifest", "./apple-touch-icon.png", "./icon-192.png", "./icon-512.png"];

self.addEventListener("install", (event) => {
  // If the download fails, the browser keeps the worker already installed (and
  // its cache) and tries again on a later visit.
  event.waitUntil(
    caches
      .open(CACHE)
      .then((cache) => cache.addAll(STATIC_FILES))
      .then(() => refreshPage())
      .then(() => self.skipWaiting()),
  );
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
    event.respondWith(caches.match(PAGE).then((cached) => cached ?? fetch(request)));
    event.waitUntil(refreshInBackground());
    return;
  }
  event.respondWith(
    caches.match(request).then(
      (cached) =>
        cached ??
        fetch(request).then((response) => {
          if (response.ok) {
            const copy = response.clone();
            event.waitUntil(caches.open(CACHE).then((cache) => cache.put(request, copy)));
          }
          return response;
        }),
    ),
  );
});

let refreshing = null;

/** One background update at a time; a failed one waits for the next launch. */
function refreshInBackground() {
  refreshing ??= refreshPage()
    .catch(() => {})
    .finally(() => {
      refreshing = null;
    });
  return refreshing;
}

/**
 * Stores the latest page only once every file it references is cached, so a
 * launch never shows a page whose script still has to come from the network.
 */
async function refreshPage() {
  const page = await download(PAGE);
  const assets = referencedAssets(await page.clone().text());
  const cache = await caches.open(CACHE);
  const downloaded = [];
  for (const path of assets) {
    if (!(await cache.match(path))) downloaded.push([path, await download(path)]);
  }
  for (const [path, response] of downloaded) await cache.put(path, response);
  await cache.put(PAGE, page);
  await pruneAssets(cache, assets);
}

/** Gives up on a stalled connection so the next launch can try again. */
async function download(path) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), DOWNLOAD_TIMEOUT_MS);
  try {
    const response = await fetch(path, { cache: "no-cache", signal: controller.signal });
    if (!response.ok) throw new Error(`${path}: ${response.status}`);
    // Read the whole body before the timer stops, so a stall mid-file aborts too.
    return new Response(await response.blob(), { headers: response.headers });
  } finally {
    clearTimeout(timer);
  }
}

/** Drops the hashed files of earlier releases once a newer page is stored. */
async function pruneAssets(cache, assets) {
  const current = new Set(assets.map((path) => new URL(path, self.location.href).href));
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
