// Sprint D6.23f — Self-destructing service worker.
//
// The previous workbox-generated SW was caching `/` HTML under a
// NetworkFirst "start-url" cache. Stale `/womenoffshore` content was
// being served at `/` even after a fresh deploy, breaking post-login
// for desktop, mobile, and PWA users alike. The runtime cache cleanup
// added in Providers.tsx never ran because the cached HTML referenced
// older JS bundles that didn't include the cleanup code.
//
// This file replaces /sw.js with a worker that, on activation:
//   1. Deletes EVERY cache the browser has stored for this origin
//      (covers any cache name workbox may have used historically).
//   2. Forces every connected client to navigate to its current URL
//      so they reload from network with no SW in front of them.
//   3. Unregisters itself from the registration set so no SW remains
//      controlling the page.
//
// The browser fetches /sw.js directly when checking for SW updates —
// that fetch bypasses the existing SW's fetch handler — so this kill
// worker WILL install on stuck PWAs the next time they're opened.
//
// next-pwa SW generation is disabled in next.config.ts so this file
// is the canonical /sw.js across future builds.

self.addEventListener('install', (event) => {
  // Skip waiting so the new (kill) SW activates immediately on install,
  // bypassing the standard "wait for old SW to release control" step.
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    // 1. Wipe all named caches. The previous SW used a "regknots-v12-*"
    //    prefix and a "start-url" cache; deleting all of them is the
    //    least error-prone way to ensure nothing stale remains.
    try {
      const names = await caches.keys();
      await Promise.all(names.map((n) => caches.delete(n)));
    } catch (e) {
      // Ignore — best effort.
    }

    // 2. Take control of all open pages so we can navigate them.
    try {
      await self.clients.claim();
    } catch (e) {
      // Ignore.
    }

    // 3. Force a navigation to the current URL on every open page so
    //    the user gets fresh HTML directly from the network. Using
    //    client.navigate() (rather than postMessage + reload) is
    //    important: it works in PWA standalone display mode where the
    //    user has no address bar to refresh from manually.
    try {
      const clients = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
      for (const client of clients) {
        try {
          client.navigate(client.url);
        } catch (e) {
          // Some PWAs disallow programmatic navigate; the user just
          // needs to reopen the app once. Best-effort.
        }
      }
    } catch (e) {
      // Ignore.
    }

    // 4. Unregister this SW so the next page load runs with NO SW
    //    intercepting any request. The next-pwa generator is disabled
    //    in next.config.ts so /sw.js will never come back unless we
    //    explicitly opt back in with a deliberate versioning strategy.
    try {
      await self.registration.unregister();
    } catch (e) {
      // Ignore.
    }
  })());
});

// Pass-through fetch handler. We intentionally do NOT cache or modify
// any request — every navigation goes straight to the network during
// the brief window between activate and unregister.
self.addEventListener('fetch', () => {
  // No-op — let the browser handle it normally.
});
